import numpy as np
import scipy.linalg as la
import time

# --- CONFIGURATION ---
L = 32             
beta = 6.0         
n_therm = 1000     
n_meas = 3000      
n_skip = 5         
epsilon_met = 0.3  

# --- CORE FUNCTIONS ---
def get_cold_start(shape):
    Id = np.zeros(shape + (2, 2), dtype=np.complex128)
    Id[..., 0, 0] = 1.0; Id[..., 1, 1] = 1.0
    return Id

def project_SU2(m):
    det = np.linalg.det(m)
    scale = 1.0 / np.sqrt(det)[..., None, None]
    return m * scale

def random_SU2_updates(shape, epsilon):
    r = np.random.uniform(-0.5, 0.5, shape + (4,))
    r[..., 0] = np.sign(r[..., 0]) * np.sqrt(1 - epsilon**2)
    r[..., 1:] *= epsilon
    norm = np.linalg.norm(r, axis=-1, keepdims=True)
    r = r / norm
    a0, a1, a2, a3 = r[..., 0], r[..., 1], r[..., 2], r[..., 3]
    U = np.zeros(shape + (2, 2), dtype=np.complex128)
    U[..., 0, 0] = a0 + 1j*a3; U[..., 0, 1] = a2 + 1j*a1
    U[..., 1, 0] = -a2 + 1j*a1; U[..., 1, 1] = a0 - 1j*a3
    return U

def compute_staples_3d(U, mu):
    staple_sum = np.zeros_like(U[..., 0, :, :])
    for nu in range(3): 
        if nu == mu: continue
        U_nu = U[..., nu, :, :]
        U_mu_s = np.roll(U[..., mu, :, :], -1, axis=nu)
        U_nu_dag_s = np.swapaxes(np.roll(U[..., nu, :, :], -1, axis=mu).conj(), -1, -2)
        staple_sum += U_nu @ U_mu_s @ U_nu_dag_s
        U_nu_dag_b = np.swapaxes(np.roll(U[..., nu, :, :], 1, axis=nu).conj(), -1, -2)
        U_mu_b = np.roll(U[..., mu, :, :], 1, axis=nu)
        U_nu_b_s = np.roll(np.roll(U[..., nu, :, :], 1, axis=nu), -1, axis=mu)
        staple_sum += U_nu_dag_b @ U_mu_b @ U_nu_b_s
    return staple_sum

def update_metropolis(U):
    R = random_SU2_updates((L, L, L, 3), epsilon=epsilon_met)
    U_prime = R @ U
    for mu in range(3): 
        Staples = compute_staples_3d(U, mu)
        Staples_dag = np.swapaxes(Staples.conj(), -1, -2)
        old_link = U[..., mu, :, :]
        new_link = U_prime[..., mu, :, :]
        dS = -(beta/2.0) * np.real(np.trace((new_link - old_link) @ Staples_dag, axis1=-1, axis2=-2))
        accept_prob = np.exp(-dS)
        r = np.random.uniform(0, 1, dS.shape)
        accept = r < accept_prob
        U[..., mu, :, :][accept] = new_link[accept]
    return U

def spatial_ape_smear(U_in, alpha=0.5, n_steps=1):
    U_sm = U_in.copy()
    for _ in range(n_steps):
        U_curr = U_sm.copy()
        for mu in range(2): # Spatial only
            staple_sum = np.zeros_like(U_curr[..., mu, :, :])
            for nu in range(2):
                if mu == nu: continue
                U_nu = U_curr[..., nu, :, :]
                U_mu_s = np.roll(U_curr[..., mu, :, :], -1, axis=nu)
                U_nu_dag_s = np.swapaxes(np.roll(U_curr[..., nu, :, :], -1, axis=mu).conj(), -1, -2)
                staple_sum += U_nu @ U_mu_s @ U_nu_dag_s
                U_nu_dag_b = np.swapaxes(np.roll(U_curr[..., nu, :, :], 1, axis=nu).conj(), -1, -2)
                U_mu_b = np.roll(U_curr[..., mu, :, :], 1, axis=nu)
                U_nu_b_s = np.roll(np.roll(U_curr[..., nu, :, :], 1, axis=nu), -1, axis=mu)
                staple_sum += U_nu_dag_b @ U_mu_b @ U_nu_b_s
            U_temp = (1.0 - alpha) * U_curr[..., mu, :, :] + (alpha / 2.0) * staple_sum
            U_sm[..., mu, :, :] = project_SU2(U_temp)
    return U_sm

def measure_glueball_3d(U):
    U_0 = U[..., 0, :, :]
    U_1 = U[..., 1, :, :]
    P01 = (U_0 @ np.roll(U_1, -1, axis=0)) @ (np.swapaxes(np.roll(U_0, -1, axis=1).conj(),-1,-2) @ np.swapaxes(U_1.conj(),-1,-2))
    trP = np.real(np.trace(P01, axis1=-2, axis2=-1))
    return np.sum(trP, axis=(0, 1))

def measure_wilson_loops_3d(U, R_max, T_max):
    W_RT = np.zeros((R_max, T_max))
    mu, nu = 0, 2 
    U_R_line = U[..., mu, :, :]
    for r in range(1, R_max + 1):
        spatial_line = U_R_line.copy()
        U_shift = np.roll(U[..., mu, :, :], -r, axis=mu)
        U_R_line = U_R_line @ U_shift
        U_T_line = U[..., nu, :, :]
        for t in range(1, T_max + 1):
            V_0 = U_T_line.copy()
            V_R = np.roll(V_0, -r, axis=mu)
            top = np.roll(spatial_line, -t, axis=nu)
            top_dag = np.swapaxes(top.conj(), -1, -2)
            V_0_dag = np.swapaxes(V_0.conj(), -1, -2)
            Loop = spatial_line @ V_R @ top_dag @ V_0_dag
            val = np.real(np.mean(np.trace(Loop, axis1=-2, axis2=-1)))
            W_RT[r-1, t-1] += val
            U_time_shift = np.roll(U[..., nu, :, :], -t, axis=nu)
            U_T_line = U_T_line @ U_time_shift
    return W_RT

# --- MAIN ---
print(f"--- 3D SU(2) Data Collection Run ---")
U = get_cold_start((L, L, L, 3))

print(f"Thermalizing ({n_therm} steps)...")
for i in range(n_therm):
    U = update_metropolis(U)

# GEVP Setup
smear_levels = [10, 20, 30]
n_ops = len(smear_levels)
ops_history = np.zeros((n_meas, n_ops, L))

# Wilson loops
R_max, T_max = 6, 6
wilson_avg = np.zeros((R_max, T_max))

print(f"Measuring ({n_meas} configs)...")
t0 = time.time()

for i in range(n_meas):
    for _ in range(n_skip):
        U = update_metropolis(U)
    
    # GEVP Meas
    U_curr = U.copy()
    U_curr = spatial_ape_smear(U_curr, alpha=0.5, n_steps=smear_levels[0])
    ops_history[i, 0, :] = measure_glueball_3d(U_curr)
    
    U_curr = spatial_ape_smear(U_curr, alpha=0.5, n_steps=smear_levels[1]-smear_levels[0])
    ops_history[i, 1, :] = measure_glueball_3d(U_curr)

    U_curr = spatial_ape_smear(U_curr, alpha=0.5, n_steps=smear_levels[2]-smear_levels[1])
    ops_history[i, 2, :] = measure_glueball_3d(U_curr)
    
    # Wilson Loops
    U_space_smeared = spatial_ape_smear(U, alpha=0.5, n_steps=10)
    U_hybrid = U.copy()
    U_hybrid[..., 0, :, :] = U_space_smeared[..., 0, :, :]
    U_hybrid[..., 1, :, :] = U_space_smeared[..., 1, :, :]
    wilson_avg += measure_wilson_loops_3d(U_hybrid, R_max, T_max)
    
    if i % 500 == 0 and i > 0:
         elapsed = time.time() - t0
         print(f"  Meas {i}/{n_meas} ({(n_meas-i)/(i/elapsed)/60:.1f}m left)")

wilson_avg /= n_meas

# --- SAVE DATA ---
print("Saving raw data to 'lattice_data_3d.npz'...")
np.savez('lattice_data_3d.npz', 
         ops_history=ops_history, 
         wilson_avg=wilson_avg,
         beta=beta, L=L)
print("Done. Use the analysis script to fit.")