import pyscf
import pyscf.cc
import pyscf.mcscf
from qiskit import QuantumCircuit, QuantumRegister
import ffsim

def pre_ansatz(mol, active_space, scf):
    ccsd = pyscf.cc.CCSD(
    scf, frozen=[i for i in range(mol.nao_nr()) if i not in active_space]).run()
    t1 = ccsd.t1
    t2 = ccsd.t2

    return t1, t2

def create_ansatz(scf,num_orbitals,mol,active_space,num_elec_a,num_elec_b,n_reps=1):
    
    alpha_alpha_indices = [(p, p + 1) for p in range(num_orbitals - 1)]
    alpha_beta_indices = [(p, p) for p in range(0, num_orbitals, 4)]
    
    t1,t2 = pre_ansatz(mol,active_space,scf)
    ucj_op = ffsim.UCJOpSpinBalanced.from_t_amplitudes(
    t2=t2,
    t1=t1,
    n_reps=n_reps,
    interaction_pairs=(alpha_alpha_indices, alpha_beta_indices),
    )

    nelec = (num_elec_a, num_elec_b)
    qubits = QuantumRegister(2 * num_orbitals, name="q")
    circuit = QuantumCircuit(qubits)
    circuit.append(ffsim.qiskit.PrepareHartreeFockJW(num_orbitals, nelec), qubits)
    circuit.append(ffsim.qiskit.UCJOpSpinBalancedJW(ucj_op), qubits)
    circuit.measure_all()

    return circuit 
