import pyscf
import pyscf.cc
import pyscf.mcscf

def mol_prop(atom,
             basis = '6-31g',
             symmetry = False,
             spin_sq=0,
             charge=0 ):

    mol = pyscf.gto.Mole()
    mol.atom = atom
    mol.basis = basis
    mol.spin = spin_sq
    if charge:
        mol.charge = charge
    if symmetry:
        mol.symmetry = symmetry
    mol.build()

    return mol

def mol_integrals(atom,basis,symmetry,spin_sq,charge,n_frozen = 1):
    
    mol = mol_prop(atom,basis,symmetry,spin_sq,charge)
    active_space = range(n_frozen,mol.nao_nr())
    scf = pyscf.scf.RHF(mol).run()
    num_orbitals = len(active_space)
    n_electrons = int(sum(scf.mo_occ[active_space]))
    num_elec_a = (n_electrons + mol.spin) // 2
    num_elec_b = (n_electrons - mol.spin) // 2
    cas = pyscf.mcscf.CASCI(scf, num_orbitals, (num_elec_a, num_elec_b))
    mo = cas.sort_mo(active_space, base=0)
    hcore, nuclear_repulsion_energy = cas.get_h1cas(mo)
    eri = pyscf.ao2mo.restore(1, cas.get_h2cas(mo), num_orbitals)
    
    return mol, mo, hcore, nuclear_repulsion_energy, num_orbitals, active_space, eri , scf, num_elec_a,num_elec_b
