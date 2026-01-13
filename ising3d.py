import numpy as np
import matplotlib.pyplot as plt
from scipy.optimize import brentq, curve_fit
from numba import jit
import multiprocessing
import time

# --- CONFIGURATION ---
# 1. Blind Scout (Wide net to find the neighborhood)
L_scout_A = 16
L_scout_B = 32
T_range_scout = np.linspace(4.45, 4.55, 11) 
n_meas_scout = 8000

# 2. Parallel Production (Heavy Lifting)
# We go up to L=128. Crossing of 96/128 is extremely close to T_inf.
L_prod = [32, 48, 64, 96, 128]
n_therm = 10000          # Deep thermalization
n_meas = 200000          # 200k samples for smooth histograms

# --- JIT KERNEL (WOLFF ALGORITHM) ---
@jit(nopython=True)
def wolff_step(spins, L, beta):
    N = L**3
    p_add = 1.0 - np.exp(-2.0 * beta)
    
    rx, ry, rz = np.random.randint(0, L), np.random.randint(0, L), np.random.randint(0, L)
    seed_spin = spins[rx, ry, rz]
    spins[rx, ry, rz] = -seed_spin
    
    stack_x = np.zeros(N, dtype=np.int32)
    stack_y = np.zeros(N, dtype=np.int32)
    stack_z = np.zeros(N, dtype=np.int32)
    stack_ptr = 0
    
    stack_x[0], stack_y[0], stack_z[0] = rx, ry, rz
    stack_ptr += 1
    
    while stack_ptr > 0:
        stack_ptr -= 1
        cx, cy, cz = stack_x[stack_ptr], stack_y[stack_ptr], stack_z[stack_ptr]
        
        # Periodic Neighbors (Unrolled)
        nx_list = np.array([(cx + 1) % L, (cx - 1 + L) % L, cx, cx, cx, cx])
        ny_list = np.array([cy, cy, (cy + 1) % L, (cy - 1 + L) % L, cy, cy])
        nz_list = np.array([cz, cz, cz, cz, (cz + 1) % L, (cz - 1 + L) % L])
        
        for i in range(6):
            nx, ny, nz = nx_list[i], ny_list[i], nz_list[i]
            if spins[nx, ny, nz] == seed_spin:
                if np.random.random() < p_add:
                    spins[nx, ny, nz] = -seed_spin
                    stack_x[stack_ptr] = nx
                    stack_y[stack_ptr] = ny
                    stack_z[stack_ptr] = nz
                    stack_ptr += 1
    return 1

@jit(nopython=True)
def calc_obs(spins, L):
    M = np.sum(spins)
    E = 0.0
    for x in range(L):
        for y in range(L):
            for z in range(L):
                s = spins[x, y, z]
                # Forward neighbors only for Energy sum
                E -= s * spins[(x+1)%L, y, z]
                E -= s * spins[x, (y+1)%L, z]
                E -= s * spins[x, y, (z+1)%L]
    return float(M), float(E)

# --- WORKER PROCESS ---
def run_simulation_task(args):
    """Independent worker for multiprocessing"""
    L, T_sim, n_th, n_me, seed = args
    np.random.seed(seed) 
    
    beta_sim = 1.0 / T_sim
    spins = np.ones((L, L, L), dtype=np.int8)
    
    # Thermalize
    for _ in range(n_th):
        wolff_step(spins, L, beta_sim)
        
    E_hist = np.zeros(n_me, dtype=np.float64)
    M2_hist = np.zeros(n_me, dtype=np.float64)
    M4_hist = np.zeros(n_me, dtype=np.float64)
    
    # Measure
    for i in range(n_me):
        wolff_step(spins, L, beta_sim)
        m, e = calc_obs(spins, L)
        E_hist[i] = e
        M2_hist[i] = m**2
        M4_hist[i] = m**4
        
    return L, E_hist, M2_hist, M4_hist

# --- ANALYSIS HELPERS ---
def reweight_U4(beta_tgt, beta_sim, E, M2, M4):
    d_beta = beta_tgt - beta_sim
    log_w = -d_beta * E
    log_w -= np.max(log_w)
    w = np.exp(log_w)
    m2_avg = np.sum(M2*w)/np.sum(w)
    m4_avg = np.sum(M4*w)/np.sum(w)
    return 1.0 - m4_avg/(3.0*m2_avg**2)

def reweight_Chi(beta_tgt, beta_sim, E, M2, Vol):
    d_beta = beta_tgt - beta_sim
    log_w = -d_beta * E
    log_w -= np.max(log_w)
    w = np.exp(log_w)
    m2_avg = np.sum(M2*w)/np.sum(w)
    return beta_tgt * m2_avg / Vol

# --- PHASE 1: SERIAL SCOUT ---
def run_scout():
    print(f"--- Phase 1: Blind Scout ({T_range_scout[0]}-{T_range_scout[-1]}) ---")
    res = {}
    for L in [L_scout_A, L_scout_B]:
        print(f"  Scouting L={L}...", end="", flush=True)
        spins = np.ones((L, L, L), dtype=np.int8)
        u4s = []
        for T in T_range_scout:
            beta = 1.0/T
            for _ in range(1000): wolff_step(spins, L, beta)
            m2_s, m4_s = 0.0, 0.0
            for _ in range(n_meas_scout):
                wolff_step(spins, L, beta)
                M, _ = calc_obs(spins, L)
                m2_s += M**2; m4_s += M**4
            u4s.append(1.0 - (m4_s/n_meas_scout)/(3.0*(m2_s/n_meas_scout)**2))
        res[L] = u4s
        print(" Done.")
    
    # Linear Intersection
    diff = np.array(res[L_scout_A]) - np.array(res[L_scout_B])
    for i in range(len(diff)-1):
        if np.sign(diff[i]) != np.sign(diff[i+1]):
            T1, T2 = T_range_scout[i], T_range_scout[i+1]
            D1, D2 = diff[i], diff[i+1]
            Tc = T1 + (0 - D1) * (T2 - T1) / (D2 - D1)
            print(f"  >> Scouted Tc = {Tc:.5f}")
            return Tc
            
    # Fallback to midpoint (should not happen with wide scan)
    return np.mean(T_range_scout)

# --- MAIN EXECUTION ---
if __name__ == "__main__":
    # Force compile before forking
    print("Compiling JIT kernels...")
    wolff_step(np.ones((4,4,4), dtype=np.int32), 4, 0.2)
    calc_obs(np.ones((4,4,4), dtype=np.int32), 4)
    
    # 1. Scout
    T_sim = run_scout()
    
    # 2. Parallel Production
    print(f"\n--- Phase 2: Parallel Production at T={T_sim:.5f} ---")
    print(f"  Lattices: {L_prod}")
    print(f"  Measurements: {n_meas} per lattice")
    print(f"  CPUs: {multiprocessing.cpu_count()}")
    
    tasks = []
    for i, L in enumerate(L_prod):
        seed = int(time.time()) + i*999
        tasks.append((L, T_sim, n_therm, n_meas, seed))
        
    t_start = time.time()
    
    # Run Parallel
    with multiprocessing.Pool() as pool:
        results_list = pool.map(run_simulation_task, tasks)
        
    print(f"  >> Simulations Complete. Total time: {time.time()-t_start:.1f}s")
    
    # Organize Data
    data_store = {}
    for res in results_list:
        L, E, M2, M4 = res
        data_store[L] = {'E': E, 'M2': M2, 'M4': M4}

    # 3. Reweighted Analysis
    print(f"\n--- Phase 3: High-Precision Analysis ---")
    beta_sim = 1.0 / T_sim
    
    # A. Find Intersection of two LARGEST lattices (Self-Contained Tc)
    L_A = L_prod[-2] # 96
    L_B = L_prod[-1] # 128
    print(f"  Determining Tc from intersection of L={L_A} and L={L_B}...")
    
    def crossing_func(T):
        b = 1.0/T
        u4_a = reweight_U4(b, beta_sim, data_store[L_A]['E'], data_store[L_A]['M2'], data_store[L_A]['M4'])
        u4_b = reweight_U4(b, beta_sim, data_store[L_B]['E'], data_store[L_B]['M2'], data_store[L_B]['M4'])
        return u4_a - u4_b
        
    try:
        # Search window +/- 0.005 around simulation point
        Tc_final = brentq(crossing_func, T_sim - 0.005, T_sim + 0.005)
        print(f"  >> PRECISION Tc = {Tc_final:.6f}")
    except:
        print("  !! Intersection reweighting failed. Using T_sim.")
        Tc_final = T_sim
        
    # B. Scaling
    print(f"  Measuring Scaling at Tc={Tc_final:.6f}...")
    beta_c = 1.0 / Tc_final
    
    log_L = []
    log_Chi = []
    log_Chi_err = []
    
    for L in L_prod:
        d = data_store[L]
        chi = reweight_Chi(beta_c, beta_sim, d['E'], d['M2'], L**3)
        
        # Bootstrap Error Estimate
        n_blocks = 20
        block_size = n_meas // n_blocks
        block_chis = []
        for k in range(n_blocks):
            sl = slice(k*block_size, (k+1)*block_size)
            chi_k = reweight_Chi(beta_c, beta_sim, d['E'][sl], d['M2'][sl], L**3)
            block_chis.append(chi_k)
        
        chi_err = np.std(block_chis) / np.sqrt(n_blocks)
        
        log_L.append(np.log(L))
        log_Chi.append(np.log(chi))
        log_Chi_err.append(chi_err / chi)
        print(f"    L={L:3d}: Chi={chi:.2f} +/- {chi_err:.2f}")
        
    # Weighted Fit
    def scaling(x, s, i): return s*x + i
    popt, pcov = curve_fit(scaling, log_L, log_Chi, sigma=log_Chi_err, absolute_sigma=True)
    slope = popt[0]
    slope_err = np.sqrt(pcov[0,0])
    eta = 2.0 - slope
    
    print(f"\n>>> FINAL SELF-CONTAINED RESULT")
    print(f"Tc:  {Tc_final:.6f}")
    print(f"Eta: {eta:.5f} +/- {slope_err:.5f}")
    
    # Plot
    plt.figure(figsize=(12, 5))
    
    plt.subplot(1, 2, 1)
    t_plot = np.linspace(Tc_final-0.0005, Tc_final+0.0005, 50)
    u4_a = [reweight_U4(1.0/t, beta_sim, data_store[L_A]['E'], data_store[L_A]['M2'], data_store[L_A]['M4']) for t in t_plot]
    u4_b = [reweight_U4(1.0/t, beta_sim, data_store[L_B]['E'], data_store[L_B]['M2'], data_store[L_B]['M4']) for t in t_plot]
    plt.plot(t_plot, u4_a, label=f'L={L_A}')
    plt.plot(t_plot, u4_b, label=f'L={L_B}')
    plt.axvline(Tc_final, color='k', ls=':', label='Tc')
    plt.title(f"Intersection (Finding Tc)")
    plt.legend(); plt.grid(True)
    
    plt.subplot(1, 2, 2)
    plt.errorbar(log_L, log_Chi, yerr=log_Chi_err, fmt='bo', capsize=4, label='Data')
    plt.plot(log_L, scaling(np.array(log_L), *popt), 'r--', label=fr'$\eta={eta:.4f}$')
    plt.title(f"Scaling (Finding Eta)")
    plt.xlabel(r"$\ln L$"); plt.ylabel(r"$\ln \chi$"); plt.legend(); plt.grid(True)
    
    plt.tight_layout()
    plt.show()