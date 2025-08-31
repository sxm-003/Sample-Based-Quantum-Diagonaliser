from functools import partial
from typing import List
import numpy as np

from qiskit_addon_sqd.fermion import (
    SCIResult,
    diagonalize_fermionic_hamiltonian,
    solve_sci_batch,
)


def set_sqd_options() -> dict:
    """Set and return SQD options as a dictionary."""
    # SQD options
    energy_tol = 1e-3
    occupancies_tol = 1e-3
    max_iterations = 5

    # Eigenstate solver options
    num_batches = 3
    samples_per_batch = 300
    symmetrize_spin = True
    carryover_threshold = 1e-4
    max_cycle = 200

    # Partial sci_solver with custom options
    sci_solver = partial(solve_sci_batch, spin_sq=0.0, max_cycle=max_cycle)

    return {
        "energy_tol": energy_tol,
        "occupancies_tol": occupancies_tol,
        "max_iterations": max_iterations,
        "num_batches": num_batches,
        "samples_per_batch": samples_per_batch,
        "symmetrize_spin": symmetrize_spin,
        "carryover_threshold": carryover_threshold,
        "sci_solver": sci_solver,
    }


def define_sqd_callback(nuclear_repulsion_energy: float):
    """Define and return the SQD callback function."""

    result_history = []

    def callback(results: List[SCIResult]):
        result_history.append(results)
        iteration = len(result_history)
        print(f"Iteration {iteration}")
        for i, result in enumerate(results):
            print(f"\tSubsample {i}")
            print(f"\t\tEnergy: {result.energy + nuclear_repulsion_energy}")
            print(
                f"\t\tSubspace dimension: {np.prod(result.sci_state.amplitudes.shape)}"
            )

    return callback


def compute_sqd_result(
    hcore,
    eri,
    meas_data,
    num_orbitals: int,
    nelec: tuple[int, int],
    options: dict,
    callback
):
    """Compute and return the SQD result using diagonalize_fermionic_hamiltonian."""
    result = diagonalize_fermionic_hamiltonian(
        hcore,
        eri,
        meas_data,
        samples_per_batch=options["samples_per_batch"],
        norb=num_orbitals,
        nelec=nelec,
        num_batches=options["num_batches"],
        energy_tol=options["energy_tol"],
        occupancies_tol=options["occupancies_tol"],
        max_iterations=options["max_iterations"],
        sci_solver=options["sci_solver"],
        symmetrize_spin=options["symmetrize_spin"],
        carryover_threshold=options["carryover_threshold"],
        callback=callback,
        seed=12345,
    )
    return result
