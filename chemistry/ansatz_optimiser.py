from . import zigzag_layout as zz 
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
import ffsim


def optimiser(circuit,num_orbitals,backend,
              optimisation_level = 1):
    initial_layout, _ = zz.get_zigzag_physical_layout(num_orbitals, backend=backend)
    pass_manager = generate_preset_pass_manager( optimization_level=optimisation_level, backend=backend, initial_layout=initial_layout)
    pass_manager.pre_init = ffsim.qiskit.PRE_INIT
    return pass_manager.run(circuit)
