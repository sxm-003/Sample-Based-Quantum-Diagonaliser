from chemistry import loader, molecule_build as mb
from flows.tasks_reliability import cached, retryable
from dataclasses import dataclass

@dataclass
class MoleculeData:
    mo: any
    hcore: any
    nuclear_repulsion_energy: float
    num_orbitals: int
    active_space: any
    eri: any
    scf: any
    num_elec_a: int
    num_elec_b: int

@cached
def load_mol(path):
    return loader.load_molecule(path)

@cached
@retryable()
def integrals(mi):
    # mol_integrals returns: (mol, mo, hcore, enuc, n_orb, active_space, eri, scf, num_elec_a, num_elec_b)
    mol, mo, hcore, enuc, n_orb, active_space, eri, scf, num_elec_a, num_elec_b = mb.mol_integrals(*mi)
    
    # Create structured data object
    md = MoleculeData(mo, hcore, enuc, n_orb, active_space, eri, scf, num_elec_a, num_elec_b)
    
    # Return both for compatibility with your flow
    return md, mol


