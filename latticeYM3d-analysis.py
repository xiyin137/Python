import numpy as np
import matplotlib.pyplot as plt
from scipy.optimize import curve_fit
import scipy.linalg as la

# --- LOAD DATA ---
data = np.load('lattice_data_3d.npz')
ops_history = data['ops_history']
wilson_avg = data['wilson_avg']
L = int(data['L'])
beta = float(data['beta'])

print(f"Loaded Data: Beta={beta}, L={L}, Configs={ops_history.shape[0]}")

# --- GEVP PROCESSING ---
n_meas, n_ops, Nt = ops_history.shape

# 1. Build C matrix
vevs = np.mean(ops_history, axis=0)
vev_per_op = np.mean(vevs, axis=1)
ops_sub = np.zeros_like(ops_history)
for k in range(n_ops):
    ops_sub[:, k, :] = ops_history[:, k, :] - vev_per_op[k]

C_matrix = np.zeros((Nt, n_ops, n_ops))
for t in range(Nt):
    for i_op in range(n_ops):
        for j_op in range(n_ops):
            prod = ops_sub[:, i_op, :] * np.roll(ops_sub[:, j_op, :], -t, axis=1)
            C_matrix[t, i_op, j_op] = np.mean(prod)

# Symmetrize and Fold
C_matrix = 0.5 * (C_matrix + np.transpose(C_matrix, (0, 2, 1)))
for t in range(1, Nt//2 + 1):
    C_matrix[t] = 0.5 * (C_matrix[t] + C_matrix[Nt-t])

# Solve Eigenvalues
eig_vals = np.zeros((Nt//2, n_ops))
t0_gevp = 0
for t in range(Nt//2):
    try:
        evals = la.eigh(C_matrix[t], C_matrix[t0_gevp], eigvals_only=True)
        eig_vals[t, :] = np.sort(evals)[::-1]
    except:
        eig_vals[t, :] = np.nan

lambda_0 = eig_vals[:, 0]

# --- INTERACTIVE FITTING ---

# Improve Model: Cosh + Constant (to handle noise floor)
def cosh_noise_model(t, A, m, C):
    return A * np.cosh(m * (t - Nt/2.0)) + C

# Fit Range: Adjust this if the plot looks bad!
t_start = 1
t_end = 5  # Cut off before noise completely dominates

t_data = np.arange(Nt//2)
y_data = lambda_0

try:
    # Bounds: Mass must be positive, C must be small positive
    popt, pcov = curve_fit(cosh_noise_model, 
                           t_data[t_start:t_end], 
                           y_data[t_start:t_end], 
                           p0=[y_data[1], 1.0, 0.01],
                           bounds=([0, 0, 0], [np.inf, 5.0, 1.0]))
    mass_est = popt[1]
    mass_err = np.sqrt(pcov[1,1])
    print(f"\nGLUEBALL MASS: {mass_est:.4f} +/- {mass_err:.4f}")
except Exception as e:
    print(f"Fit failed: {e}")
    mass_est = 0.0

# --- STRING TENSION ---
R_max = wilson_avg.shape[0]
V_R = np.zeros(R_max)
V_R[:] = np.nan
for r in range(R_max):
    if wilson_avg[r, 3] > 0 and wilson_avg[r, 4] > 0:
        V_R[r] = np.log(wilson_avg[r, 3] / wilson_avg[r, 4])

r_vals = np.arange(1, R_max+1)
mask = np.isfinite(V_R) & (r_vals >= 2)
sigma_a2 = np.nan
if np.sum(mask) >= 2:
    popt_s, _ = curve_fit(lambda r,s,c: s*r+c, r_vals[mask], V_R[mask])
    sigma_a2 = popt_s[0]
    print(f"STRING TENSION: {sigma_a2:.4f}")

if not np.isnan(sigma_a2) and mass_est > 0:
    print(f"RATIO: {mass_est/np.sqrt(sigma_a2):.4f}")

# --- PLOTTING ---
plt.figure(figsize=(10, 5))

# Plot Correlator
plt.subplot(1, 2, 1)
plt.plot(t_data, y_data, 'bo', label='Data')
# Plot Fit
fit_x = np.linspace(0, Nt//2, 100)
plt.plot(fit_x, cosh_noise_model(fit_x, *popt), 'r-', label=f'Fit m={mass_est:.3f}')
plt.yscale('log')
plt.ylim(1e-3, 2.0) # Zoom in to ignore extreme noise tails
plt.title(f'Fit Range: t=[{t_start}, {t_end}]')
plt.xlabel('t')
plt.ylabel('C(t)')
plt.legend()
plt.grid(True, which="both")

# Plot Potential
plt.subplot(1, 2, 2)
plt.plot(r_vals, V_R, 'bo', label='V(R)')
if not np.isnan(sigma_a2):
    plt.plot(r_vals, r_vals*sigma_a2 + popt_s[1], 'r--', label=f'$\sigma$={sigma_a2:.3f}')
plt.title('Static Potential')
plt.legend()
plt.grid(True)

plt.tight_layout()
plt.show()