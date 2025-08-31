from prefect import task
from prefect_qiskit.vendors.ibm_quantum import IBMQuantumCredentials
from qiskit_ibm_runtime import QiskitRuntimeService, Sampler
from qiskit_aer import AerSimulator
from qiskit.compiler import transpile

@task(retries=3, retry_delay_seconds=30, cache_policy=None)
def run_sampler(circ, backend_obj, backend_name, options):
    
    from prefect import get_run_logger
    log = get_run_logger()
    
    log.info(f"Submitting to {backend_name}")
    log.info(f"Circuit: {circ.num_qubits} qubits, depth {circ.depth()}")
    
    try:
        log.info("Attempting real quantum execution...")
        credentials = IBMQuantumCredentials.load("my-ibm-client")
        service = QiskitRuntimeService(
            channel='ibm_quantum_platform',
            token=credentials.api_key.get_secret_value(),
            instance=credentials.crn )
        
        backend = service.backend(backend_name)
        sampler = Sampler(mode=backend)
        job = sampler.run([circ], shots=options.get("shots", 1024))
        
        # CAPTURE JOB ID
        job_id = job.job_id()
        log.info(f" JOB SUBMITTED: {job_id} on {backend_name}")
        print(f" IBM Quantum Job ID: {job_id}")
        
        job_result = job.result()
        pub_result = job_result[0]
        
        log.info("Real quantum execution successful")
        log.info(f"Total shots: {sum(pub_result.data.meas.get_counts().values())}")
        log.info(f" JOB COMPLETED: {job_id}")
        print(f"Job {job_id} completed successfully!")
        
        # Result class with job ID
        class QuantumResult:
            def __init__(self, pub_result, job_id, backend_name):
                self.data = pub_result.data
                self.job_id = job_id
                self.backend_name = backend_name
        
        return QuantumResult(pub_result, job_id, backend_name)
        
    except Exception as real_error:
        log.error(f"Real quantum execution failed: {real_error}")
        log.info("Falling back to Aer simulator...")
        return _aer_fallback_execution(circ, backend_obj, backend_name, options, log)

def _aer_fallback_execution(circuit, backend_obj, backend_name, options, log):
    """Aer fallback - also return simple structure"""
    try:
        log.info(f"Creating Aer simulator from {backend_name}")
        aer_simulator = AerSimulator.from_backend(backend_obj)
        
        try:
            aer_circuit = circuit
            log.info("Using original circuit for Aer")
        except Exception:
            aer_circuit = transpile(circuit, backend=aer_simulator, optimization_level=3)
            log.info("Re-transpiled circuit for Aer compatibility")
        
        job = aer_simulator.run(aer_circuit, shots=options.get("shots", 1024))
        result = job.result()
        
        # Generate pseudo job ID for Aer
        import uuid
        pseudo_job_id = f"aer_{str(uuid.uuid4())[:8]}"
        log.info(f" AER JOB ID: {pseudo_job_id}")
        print(f" Aer Simulation Job ID: {pseudo_job_id}")
        
        log.info("Aer simulation successful")
        
        #  Aer result classes with job ID
        class AerData:
            def __init__(self, qiskit_result):
                self.meas = qiskit_result
        
        class AerResult:
            def __init__(self, qiskit_result, job_id, backend_name):
                self.data = AerData(qiskit_result)
                self.job_id = job_id
                self.backend_name = backend_name
        
        return AerResult(result, pseudo_job_id, f"{backend_name}_aer")
        
    except Exception as aer_error:
        log.error(f"Aer simulation failed: {aer_error}")
        raise RuntimeError(f"Both quantum and Aer execution failed: {aer_error}")
