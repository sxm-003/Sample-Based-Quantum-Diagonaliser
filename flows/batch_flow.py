from pathlib import Path
import shutil
import psutil
import re
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from prefect import flow, task
from prefect.cache_policies import NONE
from prefect.task_runners import ThreadPoolTaskRunner
from chemistry import create_ansatz as ca, ansatz_optimiser as ao, recovery_solver as rs
from flows.tasks_scheduling import analyze_compounds_and_select_backends
from flows.tasks_reliability import retryable, checkpointed
from flows.sampler_task import run_sampler
from flows.tasks_core import load_mol, integrals

# System resource monitoring
LOAD_THRESHOLD = 90
MAX_CONCURRENT_PREPARATIONS = 3  # Limit concurrent preparations

def get_timestamp():
    """Get current timestamp for filenames"""
    return datetime.now().strftime('%Y%m%d_%H%M%S')

def clear_old_cache():
    """Clear all old cache files at the start of a fresh workflow run"""
    cache_dir = Path(".prefect_cache")
    if cache_dir.exists():
        for item in cache_dir.iterdir():
            if item.is_file():
                item.unlink()
                print(f"Cleared cache file: {item.name}")
            elif item.is_dir():
                shutil.rmtree(item)
                print(f"Cleared cache directory: {item.name}")
    print("Old cache cleared - starting fresh run")

def check_system_load():
    """Check if system is overloaded"""
    cpu_percent = psutil.cpu_percent(interval=1)
    memory_percent = psutil.virtual_memory().percent
    print(f"System load: CPU {cpu_percent:.1f}%, Memory {memory_percent:.1f}%")
    return cpu_percent > LOAD_THRESHOLD or memory_percent > LOAD_THRESHOLD

def wait_for_system_capacity():
    """Wait until system has capacity"""
    while check_system_load():
        print("System overloaded, waiting 30 seconds...")
        time.sleep(30)

def create_fallback_molecule_file(original_file):
    """Create a fallback molecule file with sto-3g basis"""
    with open(original_file, 'r') as f:
        content = f.read()
    
    # Replace basis with sto-3g
    fallback_content = re.sub(
        r'basis\s*=\s*["\'][^"\']*["\']',
        'basis = "sto-3g"',
        content
    )
    
    # Create fallback file
    fallback_file = original_file.replace('.txt', '_fallback_sto3g.txt')
    with open(fallback_file, 'w') as f:
        f.write(fallback_content)
    
    return fallback_file

def move_fallback_compound_to_folder(fallback_file_path, original_mol_file):
    """Move fallback compound file to compounds_fallback folder with proper naming"""
    # Create compounds_fallback folder if it doesn't exist
    fallback_folder = Path('compounds_fallback')
    fallback_folder.mkdir(exist_ok=True)
    
    # Get compound name from original molecule file
    compound_name = Path(original_mol_file).stem
    fallback_compound_filename = f'{compound_name}_fallback.txt'
    fallback_compound_path = fallback_folder / fallback_compound_filename
    
    # Move the fallback file to the fallback folder
    shutil.move(fallback_file_path, fallback_compound_path)
    print(f"Moved fallback compound to: {fallback_compound_path}")
    
    return fallback_compound_path

def save_result_file(mol_file, backend_name, energy_total, job_id="unknown", fallback_used=False, energy_obj_str=None):
    """Save result file with timestamp naming convention"""
    compound_name = Path(mol_file).stem
    timestamp = get_timestamp()
    
    # Create filename based on fallback status
    if fallback_used:
        result_filename = f'result_{compound_name}_{timestamp}_fallback.txt'
    else:
        result_filename = f'result_{compound_name}_{timestamp}.txt'
    
    # Save result file
    with open(result_filename, 'w') as f:
        f.write(f"Molecule: {Path(mol_file).name}\n")
        f.write(f"Backend: {backend_name}\n")
        f.write(f"Quantum Job ID: {job_id}\n")
        f.write(f"SQD Energy: {energy_total:.6f}\n")
        f.write(f"Fallback Used: {fallback_used}\n")
        f.write(f"Timestamp: {timestamp}\n")
        if energy_obj_str:
            f.write(f"Full Result: {energy_obj_str}\n")
    
    print(f"Result saved to: {result_filename}")
    return result_filename

@retryable(max_tries=3, delay_s=30)
def build_isa(be, reps, norb, opt, mol, act, scf, na, nb):
    """Build ISA - preserves backend object for consistency"""
    from prefect import get_run_logger
    log = get_run_logger()
    log.info(f"Transpiling for {be.name}")
    circ = ca.create_ansatz(scf, norb, mol, act, na, nb, reps)
    optimized_circ = ao.optimiser(circ, norb, be, opt)
    log.info(f"Circuit ready: {optimized_circ.num_qubits} qubits, depth {optimized_circ.depth()}")
    return optimized_circ

@checkpointed
def run_sqd(hcore, eri, meas_data, num_orbitals, nelec, options, callback, ckpt_key: str, init_state=None):
    if init_state is not None:
        return init_state
    return rs.compute_sqd_result(hcore, eri, meas_data, num_orbitals, nelec, options, callback)

@task(cache_policy=NONE, tags=["preparation"])
def prepare_compound_for_sqd_with_load_check(mol_file: str, backend_name: str, reps: int = 1, opt: int = 3):
    """Prepare molecule with system load check - for parallel execution"""
    from prefect import get_run_logger
    log = get_run_logger()
    
    # Wait for system capacity before starting
    wait_for_system_capacity()
    
    print(f"Preparing compound: {Path(mol_file).name}")
    
    # Load molecule and compute integrals
    mi = load_mol(mol_file)
    (md, mol) = integrals(mi)
    
    # RECONSTRUCT BACKEND INSIDE TASK
    from flows.tasks_scheduling import get_ibm_service_and_backend
    service, default_backend, default_name = get_ibm_service_and_backend()
    backend = service.backend(backend_name)
    
    log.info(f"Using backend: {backend_name}")
    if hasattr(backend, 'properties'):
        try:
            last_update = backend.properties().last_update_date
            log.info(f"Backend calibration: {last_update}")
        except:
            log.info("Backend calibration info unavailable")

    # Build ISA and get quantum samples
    isa = build_isa(backend, reps, md.num_orbitals, opt, mol,
                    md.active_space, md.scf, md.num_elec_a, md.num_elec_b)
    samp = run_sampler(isa, backend, backend_name, {"shots": 1024})
    
    # Get job ID from sampler result
    job_id = getattr(samp, 'job_id', 'unknown')
    
    # Return all data needed for SQD (but don't run SQD yet)
    return {
        'mol_file': mol_file,
        'backend_name': backend_name,
        'job_id': job_id,
        'md': md,
        'samp_data': samp,  # Pass the full samp object (includes job_id)
        'nelec': (md.num_elec_a, md.num_elec_b)
    }

def rerun_compound_with_sto3g_fallback(original_mol_file: str, backend_assignments: dict):
    """Rerun a specific compound with sto-3g fallback"""
    print(f"\n*** FALLBACK: Rerunning {Path(original_mol_file).name} with sto-3g basis ***")
    
    try:
        # Create fallback molecule file with sto-3g
        fallback_file = create_fallback_molecule_file(original_mol_file)
        backend_name = backend_assignments[original_mol_file]['name']
        
        print(f"Created fallback file: {Path(fallback_file).name}")
        
        # Prepare compound with fallback file (using the load-checking version)
        compound_data = prepare_compound_for_sqd_with_load_check(fallback_file, backend_name)
        compound_data['mol_file'] = original_mol_file  # Keep original filename for result
        compound_data['fallback_used'] = True
        
        # Move fallback compound to compounds_fallback folder
        move_fallback_compound_to_folder(fallback_file, original_mol_file)
        
        # Run SQD with fallback data
        result = run_sqd_for_compound_with_fallback_info(compound_data)
        
        return result
        
    except Exception as e:
        print(f"FALLBACK ALSO FAILED for {Path(original_mol_file).name}: {e}")
        return (Path(original_mol_file).name, None, True)

def run_sqd_for_compound(compound_data):
    """Run SQD computation for a single compound with AER fallback handling"""
    mol_file = compound_data['mol_file']
    backend_name = compound_data['backend_name']
    md = compound_data['md']
    samp_data = compound_data['samp_data']
    nelec = compound_data['nelec']
    job_id = compound_data.get('job_id', 'unknown')
    
    print(f"\n{'='*60}")
    print(f"STARTING SQD COMPUTATION FOR {Path(mol_file).name}")
    print(f"Backend: {backend_name}")
    if job_id != 'unknown':
        print(f" Quantum Job ID: {job_id}")
    print(f"{'='*60}")
    
    try:
        # Extract measurement data properly
        if hasattr(samp_data, 'data'):
            meas_data = samp_data.data.meas
        else:
            meas_data = samp_data
        
        # SQD COMPUTATION 
        energy_obj = run_sqd(
            hcore=md.hcore,
            eri=md.eri,
            meas_data=meas_data,
            num_orbitals=md.num_orbitals,
            nelec=nelec,
            options=rs.set_sqd_options(),
            callback=rs.define_sqd_callback(md.nuclear_repulsion_energy),
            ckpt_key=Path(mol_file).stem
        )
        
        energy_total = energy_obj.energy + md.nuclear_repulsion_energy
        
        print(f"{'='*60}")
        print(f"COMPLETED SQD FOR {Path(mol_file).name}: {energy_total:.6f}")
        if job_id != 'unknown':
            print(f"★ Used Quantum Job: {job_id}")
        print(f"{'='*60}\n")
        
        # Results
        save_result_file(mol_file, backend_name, energy_total, job_id, False, str(energy_obj))
        
        return (Path(mol_file).name, energy_total, False)
        
    except Exception as e:
        if "tuple index out of range" in str(e) or isinstance(e, IndexError):
            print(f"\n*** IndexError detected during SQD for {Path(mol_file).name} ***")
            print(f"Error: {e}")
            print("This compound will be rerun with sto-3g basis fallback...")
            return None
        else:
            print(f"ERROR during SQD for {Path(mol_file).name}: {e}")
            return (Path(mol_file).name, None, False)

def run_sqd_for_compound_with_fallback_info(compound_data):
    """Run SQD for compound with fallback info"""
    result = run_sqd_for_compound(compound_data)
    if result is None:
        return None
    
    # Add fallback info if it exists
    fallback_used = compound_data.get('fallback_used', False)
    if fallback_used:
        mol_file = compound_data['mol_file']
        backend_name = compound_data['backend_name']
        job_id = compound_data.get('job_id', 'unknown')
        
        print(f"{'='*60}")
        print(f"COMPLETED SQD FOR {Path(mol_file).name}: {result[1]:.6f} (FALLBACK sto-3g)")
        print(f"{'='*60}\n")
        
        # Fallback result
        save_result_file(mol_file, backend_name, result[1], job_id, True, "Fallback successful")
        
        return (result[0], result[1], True)
    
    return result

@flow(log_prints=True, task_runner=ThreadPoolTaskRunner(max_workers=MAX_CONCURRENT_PREPARATIONS))
def sqd_batch_quantum_runtime(compounds_folder="compounds/"):
    """Parallel Phase 1 (preparation) then Sequential Phase 2 (SQD) with system load monitoring"""
    
    clear_old_cache()
    
    print("Starting batch SQD workflow")
    print("Initialising parallel pre-computation for compounds")
    print("SQD computations will run STRICTLY SEQUENTIAL per molecule")
    print(f"Max concurrent preparations: {MAX_CONCURRENT_PREPARATIONS}")
    
    # Analyze compounds and select backends
    backend_assignments = analyze_compounds_and_select_backends(compounds_folder, load_factor=20000) # self adjusted this after many trials
    if not backend_assignments:
        print("No suitable backends found!")
        return []

    molecule_files = list(backend_assignments.keys())
    print(f"Found {len(molecule_files)} compounds to process")
    
    # PHASE 1: Prepare compounds IN PARALLEL with system load checks
    print(f"\nPHASE 1: Preparing compounds in parallel (max {MAX_CONCURRENT_PREPARATIONS} concurrent)...")
    
    # Submit all preparation tasks concurrently
    preparation_futures = []
    for mol_file in molecule_files:
        backend_name = backend_assignments[mol_file]['name']
        mol_name = Path(mol_file).name
        
        print(f"Submitting for preparation: {mol_name}")
        # Submit task for concurrent execution with load checking
        future = prepare_compound_for_sqd_with_load_check.submit(mol_file, backend_name)
        preparation_futures.append((mol_file, mol_name, future))
    
    # Collect results as they complete
    prepared_compounds = []
    completed_count = 0
    
    for mol_file, mol_name, future in preparation_futures:
        try:
            print(f"Waiting for completion: {mol_name}")
            compound_data = future.result()  # This blocks until the task completes
            prepared_compounds.append(compound_data)
            completed_count += 1
            print(f"Prepared ({completed_count}/{len(preparation_futures)}): {mol_name}")
        except Exception as e:
            print(f"FAILED to prepare {mol_name}: {e}")
    
    print(f"\nPHASE 1 COMPLETED: {len(prepared_compounds)} compounds prepared successfully")
    
    # PHASE 2: Run SQD computations with changed basis fallback also with AER fallback if the real quantum backend execution fails 
    print(f"\nPHASE 2: Running SQD computations sequentially with fallback...")
    results = []
    
    for i, compound_data in enumerate(prepared_compounds, 1):
        mol_file = compound_data['mol_file']
        mol_name = Path(mol_file).name
        
        print(f"\nSQD COMPUTATION {i}/{len(prepared_compounds)}: {mol_name}")
        
        try:
            result = run_sqd_for_compound(compound_data)
            
            if result is None:
                # IndexError occurred - try fallback
                print(f"Running fallback for {mol_name}...")
                result = rerun_compound_with_sto3g_fallback(mol_file, backend_assignments)
            
            results.append(result)
            
            if result[1] is not None:
                fallback_info = " (FALLBACK)" if result[2] else ""
                print(f"SUCCESS: {result[0]} = {result[1]:.6f}{fallback_info}")
            else:
                print(f"FAILED: {result[0]}")
                
        except Exception as e:
            print(f"FAILED SQD for {mol_name}: {e}")
            results.append((mol_name, None, False))
    
    # Summary
    print(f"\nBatch Results Summary:")
    print("=" * 60)
    successful = 0
    fallback_count = 0
    
    for name, energy, fallback in results:
        if energy is not None:
            status = f"{energy:.6f}"
            if fallback:
                status += " (FALLBACK)"
                fallback_count += 1
            successful += 1
        else:
            status = "FAILED"
        print(f"{name:30} {status}")
    
    print(f"\nFinal Result: {successful}/{len(results)} successful calculations")
    print(f"Fallback used: {fallback_count}/{len(results)} molecules")
    print(f"Fallback compounds stored in: compounds_fallback/ folder")
    
    return results

if __name__ == "__main__":
    results = sqd_batch_quantum_runtime("compounds/")
    successful = len([r for r in results if r[1] is not None])
    total = len(results)
    print(f"\nCompleted: {successful}/{total} successful calculations")
