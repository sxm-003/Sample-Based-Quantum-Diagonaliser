from datetime import datetime, timezone
from prefect import task, get_run_logger
from prefect_qiskit import QuantumRuntime
from prefect_qiskit.vendors.ibm_quantum import IBMQuantumCredentials
from qiskit_ibm_runtime import QiskitRuntimeService
from qiskit_aer import AerSimulator
import json
from pathlib import Path
from collections import defaultdict

def get_ibm_service_and_backend():
    """Get IBM service and backend using QuantumRuntime block"""
    try:
        # Load QuantumRuntime block
        runtime = QuantumRuntime.load("default-runtime") #this is redundant but in case if someone wants to tinker completely with prefect blocks they can use this
        resource_name = runtime.resource_name
        
        # Load credentials
        quantum_credentials = IBMQuantumCredentials.load("my-ibm-client")
        token = quantum_credentials.api_key.get_secret_value()
        instance = quantum_credentials.crn
        # Create service
        service = QiskitRuntimeService(
            channel="ibm_quantum_platform",
            token=token,
            instance=instance
        )
        
        # Get the specific backend
        backend = service.backend(resource_name)
        
        return service, backend, resource_name
        
    except Exception as e:
        raise RuntimeError(f"Failed to load QuantumRuntime block: {e}")

def estimate_molecular_complexity(file_path):
    """Estimate molecular complexity for backend selection"""
    try:
        with open(file_path, 'r') as f:
            content = f.read()
        
        atom_count = sum(content.count(atom) for atom in ['H', 'O', 'C', 'N', 'S', 'P', 'Li'])
        
        basis_complexity = 1
        if '6-31g' in content.lower():
            basis_complexity = 2
        elif 'cc-pvdz' in content.lower():
            basis_complexity = 3
        elif 'cc-pvtz' in content.lower():
            basis_complexity = 4
            
        complexity = atom_count * basis_complexity
        
        return {
            'atoms': atom_count,
            'basis_complexity': basis_complexity,
            'total_complexity': complexity,
            'recommend_real': True  # Always prefer real backends
        }
        
    except Exception as e:
        print(f"Failed to estimate complexity for {file_path}: {e}")
        return {'atoms': 0, 'basis_complexity': 1, 'total_complexity': 0, 'recommend_real': True}

def save_backend_details(backend, log_dir="backend_logs"):
    """Save comprehensive backend details"""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    full_log_dir = Path(log_dir) / timestamp
    full_log_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        backend_info = {
            "name": backend.name,
            "timestamp": timestamp,
            "num_qubits": backend.num_qubits,
            "basis_gates": backend.configuration().basis_gates,
        }
        
        # Handle properties safely
        try:
            backend_info["properties"] = backend.properties().to_dict()
            backend_info["status"] = backend.status().to_dict()
            backend_info["configuration"] = backend.configuration().to_dict()
        except:
            backend_info["properties"] = "unavailable"
            backend_info["status"] = "unavailable"
            backend_info["configuration"] = "unavailable"
            
        # Handle coupling map safely
        try:
            if hasattr(backend, 'coupling_map') and backend.coupling_map:
                if hasattr(backend.coupling_map, 'to_list'):
                    backend_info["coupling_map"] = backend.coupling_map.to_list()
                else:
                    backend_info["coupling_map"] = list(backend.coupling_map)
            else:
                backend_info["coupling_map"] = None
        except:
            backend_info["coupling_map"] = "unavailable"
            
        log_path = full_log_dir / f"{backend.name}_backend.json"
        with open(log_path, 'w') as f:
            json.dump(backend_info, f, indent=2, default=str)
            
        return str(log_path)
        
    except Exception as e:
        print(f"Failed to save backend details: {e}")
        return None

def score_real_backend(backend, need_qubits, depth_est):
    """Score real IBM backends only"""
    try:
        P, S = backend.properties(), backend.status()
        
        # Size penalty - critical for real backends
        if need_qubits > backend.num_qubits:
            return 1e9  # Cannot use this backend(very high penalty)
            
        # Depth penalty
        depth_penalty = 100 if depth_est > 400 else 0
        
        # Gate error (lower is better)
        try:
            gate_error = P.gate_error("cx", (0, 1)) * 1000
        except:
            gate_error = 10
            
        # Readout error
        max_qubits = min(need_qubits, backend.num_qubits)
        try:
            readout_error = sum(P.readout_error(q) for q in range(max_qubits)) * 10
        except:
            readout_error = 5
            
        # Queue length 
        queue_penalty = S.pending_jobs * 10
        
        # Calibration age
        try:
            last_update = P.last_update_date
            if last_update.tzinfo is None:
                last_update = last_update.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            age_hours = (now - last_update).total_seconds() / 3600
            age_penalty = age_hours / 6
        except:
            age_penalty = 2
            
        total_score = depth_penalty + gate_error + readout_error + queue_penalty + age_penalty
        
        return total_score
        
    except Exception as e:
        print(f"Error scoring backend: {e}")
        return 1e9

def load_balanced_backend_assignment(molecule_files, real_backends, service, log, load_factor=10):
    """
    Assign compounds to backends using load balancing algorithm
    
    """
    
    #Analyze all compounds and compute base scores
    compounds_info = []
    score_matrix = {}  # (mol_file, backend_name) -> score
    
    for mol_file in molecule_files:
        log.info(f"Analyzing {mol_file.name}")
        complexity = estimate_molecular_complexity(mol_file)
        
        log.info(f" Complexity: {complexity['total_complexity']} "
                f"({complexity['atoms']} atoms, basis level {complexity['basis_complexity']})")
                
        num_orbitals = max(4, complexity['atoms'] * 2)
        need_qubits = num_orbitals * 2
        depth_est = complexity['total_complexity'] * 20
        
        log.info(f" Resource needs: {need_qubits} qubits, depth ~{depth_est}")
        
        compounds_info.append({
            'mol_file': mol_file,
            'need_qubits': need_qubits,
            'depth_est': depth_est,
            'complexity': complexity
        })
        
        # Compute scores for all backends for this compound
        for backend_name, backend in real_backends.items():
            try:
                score = score_real_backend(backend, need_qubits, depth_est)
                score_matrix[(str(mol_file), backend_name)] = score
                log.info(f" {backend_name}: score {score:.2f}")
            except Exception as e:
                log.warning(f"Failed to score backend {backend_name}: {e}")
                score_matrix[(str(mol_file), backend_name)] = 1e9
    
    # Load-balanced assignment
    # Sort compounds by descending qubit need (largest first)
    compounds_info.sort(key=lambda x: x['need_qubits'], reverse=True)
    
    backend_loads = defaultdict(int)
    backend_assignments = {}
    
    for compound in compounds_info:
        mol_file = compound['mol_file']
        need_qubits = compound['need_qubits']
        
        log.info(f"Assigning {mol_file.name} (needs {need_qubits} qubits)")
        
        # Find best backend considering both quality and current load
        candidates = []
        for backend_name, backend in real_backends.items():
            base_score = score_matrix[(str(mol_file), backend_name)]
            
            if base_score >= 1e9:  # Backend cannot support this compound
                continue
                
            # Adjust score with load penalty
            adjusted_score = base_score + backend_loads[backend_name] * load_factor
            candidates.append((adjusted_score, backend_name, base_score))
        
        if not candidates:
            # Fallback: try to use default backend or any available
            log.error(f"No suitable backend found for {mol_file.name}")
            # Use first available backend as emergency fallback
            fallback_backend = next(iter(real_backends.keys()))
            final_choice = (fallback_backend, real_backends[fallback_backend], True)
            adjusted_score = 1000.0
        else:
            # Choose backend with lowest adjusted score
            adjusted_score, best_backend_name, base_score = min(candidates)
            final_choice = (best_backend_name, real_backends[best_backend_name], False)
        
        final_name, final_backend, is_fallback = final_choice
        
        # Record assignment
        backend_assignments[str(mol_file)] = {
            'name': final_name,
            'backend': final_backend,
            'is_simulator': False,
            'score': adjusted_score,
            'base_score': score_matrix.get((str(mol_file), final_name), adjusted_score),
            'load_when_assigned': backend_loads[final_name],
            'complexity': compound['complexity'],
            'decision_reason': f"load-balanced assignment (load: {backend_loads[final_name]}, score: {adjusted_score:.2f})"
        }
        
        # Update load
        backend_loads[final_name] += 1
        
        status = "FALLBACK" if is_fallback else "OPTIMAL"
        log.info(f" → Assigned to {final_name} ({status}) - "
                f"adjusted score: {adjusted_score:.2f}, current load: {backend_loads[final_name]}")
    
    #  Report load distribution
    log.info("=" * 60)
    log.info("LOAD BALANCING SUMMARY:")
    for backend_name in sorted(backend_loads.keys()):
        count = backend_loads[backend_name]
        log.info(f"  {backend_name}: {count} compounds assigned")
    log.info("=" * 60)
    
    return backend_assignments

@task
def analyze_compounds_and_select_backends(compounds_folder="compounds/", load_factor=10):
    """Analyze all compounds and select optimal REAL backends with load balancing"""
    log = get_run_logger()
    
    try:
        service, default_backend, default_name = get_ibm_service_and_backend()
        log.info(f"Connected to IBM Quantum via QuantumRuntime block. Default backend: {default_name}")
    except Exception as e:
        log.error(f"Failed to connect to IBM Quantum: {e}")
        raise RuntimeError("IBM Quantum connection required")
    
    # Get all available real backends
    try:
        all_backends = service.backends()
        real_backends = {}
        for backend in all_backends:
            if 'simulator' not in backend.name.lower() and 'fake' not in backend.name.lower():
                real_backends[backend.name] = backend
        
        log.info(f"Available real backends: {list(real_backends.keys())}")
        
        if not real_backends:
            raise RuntimeError("No real quantum backends available in your account")
            
    except Exception as e:
        log.error(f"Failed to get backends: {e}")
        raise RuntimeError("Failed to get available backends")
    
    compounds_path = Path(compounds_folder)
    molecule_files = list(compounds_path.glob("*.txt"))
    
    if not molecule_files:
        raise ValueError(f"No molecule files found in {compounds_folder}")
    
    log.info(f"Found {len(molecule_files)} molecules to analyze")
    log.info(f"Using load balancing with load_factor={load_factor}")
    
    # Use load balanced assignment
    backend_assignments = load_balanced_backend_assignment(
        molecule_files, real_backends, service, log, load_factor
    )
    
    return backend_assignments

@task(cache_policy=None)
def choose_backend_for_molecule(mol_file: str, backend_assignments: dict):
    """Get pre-assigned backend for specific molecule"""
    log = get_run_logger()
    
    if mol_file not in backend_assignments:
        raise ValueError(f"No backend assignment found for {mol_file}")
    
    assignment = backend_assignments[mol_file]
    
    log.info(f"Using pre-selected backend for {Path(mol_file).name}: "
             f"{assignment['name']} ({assignment['decision_reason']})")
    
    try:
        save_backend_details(assignment['backend'])
    except Exception as e:
        log.warning(f"Failed to save backend logs: {e}")
    
    return assignment['name'], assignment['backend']
