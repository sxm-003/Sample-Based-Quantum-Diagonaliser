
# **Prefect Orchestrated Sample-Based Quantum Diagonaliser Workflow**

A quantum chemistry computational pipeline that leverages **IBM Quantum hardware through Qiskit** and is orchestrated using **Prefect** for robust, fault-tolerant execution.  
The system performs **Sample-based Quantum Diagonalization (SQD)** calculations on molecular systems with intelligent backend selection, load balancing, and multi-level error recovery.

## **Features**

- **Quantum-Centric Supercomputing**: Orchestrated pipeline with Prefect workflow management  

- **Multi-Backend Support**: Automatic load balancing across IBM Quantum backends  

- **Fault-Tolerant Execution**: Multi-level fallback strategies (hardware → simulator → basis set)  

- **Parallel Processing**: Concurrent molecular preparation with sequential SQD computation  

- **Interactive Recovery**: Manual retry capabilities for development and debugging  

- **Comprehensive Monitoring**: Real-time execution tracking and detailed logging  

## **Architecture**
```
SQD_pipeline/

├── chemistry/             # Core quantum chemistry logic

│ ├── create_ansatz.py       # Quantum circuit ansatz construction

│ ├── molecule_build.py      # Structure & integral computation

│ ├── ansatz_optimiser.py    # Circuit optimization for backends

│ ├── zigzag_layout.py       # Qubit layout optimization

│ ├── recovery_solver.py     # SQD solver implementation

│ └── loader.py              # Molecule file parser

├── flows/                # Prefect workflow orchestration

│ ├── batch_flow.py          # Main workflow orchestrator

│ ├── sampler_task.py        # Quantum circuit execution engine

│ ├── tasks_scheduling.py    # Backend selection & load balancing

│ ├── tasks_reliability.py   # Custom decorators & utilities

│ └── tasks_core.py          # Molecules & integrals computation

├── compounds/            # Input compounds data

├── compounds_fallback/   # Fallback basis set data (sto-3g)

├── backend_logs/         # IBM Quantum backend logs

└── .prefect_cache/       # Prefect task caches directory
```
## **Usage Instructions**

### **1\. Install Dependencies**

It is recommended to use a virtual environment for clean dependency management.


```
# Create and activate virtual environment

python -m venv sqd_env
source sqd_env/bin/activate 
```



```
# Install required packages

pip install prefect qiskit qiskit-ibm-runtime pyscf ffsim
```

### **2\. Submitting Molecule or Compound Data**

Add molecules to the compounds/ folder in the following format:

**Example: compounds/methane.txt**
```
atom = [

["C", (0.000000, 0.000000, 0.000000)],

["H", (0.629118, 0.629118, 0.629118)],

["H", (-0.629118, -0.629118, 0.629118)],

["H", (0.629118, -0.629118, -0.629118)],

["H", (-0.629118, 0.629118, -0.629118)]

]

basis = "6-31g"

charge = 0

spin_sq = 0

symmetry = False

n_frozen = 1
```
### **3\. Configure Prefect Blocks**

Set up Prefect blocks for credentials and storage:

- **IBM Quantum Credentials Block**  
    **Name**: ```my-ibm-client```  
    Type: Store IBM Quantum API key and CRN  

- **Quantum Runtime Block**  
    **Name**: ```default-runtime```  
    Type: Configure default quantum backend  

- **Local File System Block**  
    **Name**: ```sqd-local-cache```  
    Basepath: .prefect_cache  

### **4\. Start Prefect Server**

\# Create and configure Prefect profile
```
prefect profile create qiskit

prefect profile use qiskit

prefect config set PREFECT_API_URL='<http://127.0.0.1:4200/api>'
```
\# Start Prefect server
```
prefect server start --host 127.0.0.1 --background
```
\# Register Qiskit blocks
```
prefect block register -m prefect_qiskit

prefect block register -m prefect_qiskit.vendors
```
### **5\. Run Workflow**

Execute the main workflow:

python -m flows.batch_flow

### **6\. Monitor Execution**

- **Prefect UI**: <http://127.0.0.1:4200>
  - Task monitoring, retries, and visualization  

- **Console Logs**: Track job IDs and execution progress  

- **Backend Logs**: Detailed hardware logs in backend_logs/  

## **Result Storage**

**File Naming Convention:**

```result_molecule1_20250831_141530.txt # Normal execution```

```result_molecule2_20250831_141545_fallback.txt # Fallback execution```

**Result File Example:**
```
Molecule: water.txt

Backend: ibm_brisbane

Quantum Job ID: ct9k2b4560bg008hvt8g

SQD Energy: -75.123456

Fallback Used: False

Timestamp: 20250831_141530

Full Result: SCIResult(energy=-76.234, ...)
```
## **Error Recovery Strategy**

- **Prefect Native Retries**: 3 automatic retries with 30s delays  

- **Interactive Retries**: Manual retry for development/debugging  

- **Hardware Fallbacks**: IBM Quantum → Aer Simulator  

- **Algorithmic Fallbacks**: Complex basis sets → sto-3g basis  

- **Checkpointing**: Resume long-running SQD computations from disk  

## **Key Configuration Parameters**

\# System Resource Management
```
#location: flows/batch_flow.py

LOAD_THRESHOLD = 90

MAX_CONCURRENT_PREPARATIONS = 3
```
\# Backend Load Balancing
```
#location: flows/batch_flow.py

load_factor = 20000
```
\# Prefect Task Settings
```
#location: flows/sampler_task.py

retries = 3
retry_delay_seconds = 30

#location: flows/tasks_reliability.py

cache_expiration = 24
```
\# SQD Algorithm Parameters
```
#location: chemistry/recovery_solver.py

energy_tol = 1e-3

max_iterations = 5

samples_per_batch = 300
```
## **Workflow Phases**

### **Phase 1: Parallel Preparation**

- Molecular complexity analysis  

- Intelligent backend assignment  

- Quantum circuit construction and optimization  

- Parallel execution with Aer fallback  

- System load monitoring  

### **Phase 2: Sequential SQD Computation**

- Sequential SQD algorithm execution  

- Checkpoint recovery for interruptions  

- Automatic fallback to simpler basis sets  

- Result storage with metadata and timestamps  

## **License**

This project is licensed under the MIT License.

## **Contributing**

Contributions are welcome. Please submit a Pull Request.

## **Contact**

For questions or support, please open an issue on GitHub.



