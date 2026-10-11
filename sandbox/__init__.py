"""NeuroSphere synthetic sandbox generator (PRP-03 item 3).

Produces deterministic, seeded, AI-governance-only synthetic data as newline-delimited JSON.
Records are built from the generated ``neurosphere_contracts`` models. Nothing here imports
from ``services/*`` and nothing here touches the network.
"""

__all__ = ["__version__"]

__version__ = "1.0.0"
