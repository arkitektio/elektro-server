"""Read-only analytic computations over a stored NeuronModel config.

These operate on the deserialized ``ModelConfigModel`` (from ``NeuronModel.json_model``)
and never run NEURON — they estimate electrophysiological quantities from the stored
geometry + biophysics using classical cable theory.
"""

from .dominance import SectionDominance, compute_dominance

__all__ = ["SectionDominance", "compute_dominance"]
