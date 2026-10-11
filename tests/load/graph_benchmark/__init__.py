"""G03 graph partition and traversal benchmark harness (PRP-02 item 3).

Public API (importable by scripts/gates/g03_live.py; add ``tests/load`` to ``sys.path`` and
``import graph_benchmark``)::

    run_benchmark(endpoint, credential_mode="emulator_key", *, workloads=WORKLOADS,
                  variants=("flat", "hier2", "hier3"), nodes=200, load_workers=16,
                  edges_per_node=3, domains=8,
                  skew_factor=0.8, hub_degree=200, iterations=20, warmup=2, budget=None,
                  seed=42, key=None, database_prefix="g03-bench", cleanup=True,
                  measure_request_charge=None, emulator=None, store=None) -> BenchmarkResult

    write_evidence(result, out_dir, label=EMULATOR_LABEL, *, when=None, slug=None)
        -> (json_path, md_path)      # <slug>-<YYYY-MM-DD>.json / .md

* ``credential_mode``: ``"emulator_key"`` (http emulator, any key, no RU) or
  ``"default_azure_credential"`` (live; needs azure-identity; RU captured per traversal).
* ``Budget(timeout_ms, limit, max_depth, max_nodes, max_edges)`` mirrors the Budget contract;
  ``limit`` is also the per-node fan-out cap.
* Every call creates a fresh database and fresh containers (flat ``/domain``, hierarchical
  ``/tenant,/domain`` and ``/tenant,/domain,/shard``); nothing is reused.
* Emulator evidence is labelled exactly ``EMULATOR_LABEL`` and contains no RU figure; RU, index
  policy, 429 throttling and cross-partition fan-out cost are stated UNMEASURED.
* Live evidence (``mode == "live"``) may carry measured request charge; pass your own label.
"""

from .evidence import EMULATOR_LABEL, build_payload, render_markdown, write_evidence
from .model import VARIANTS, Budget, PartitionVariant
from .runner import BenchmarkResult, CellResult, run_benchmark
from .store import CREDENTIAL_MODES, InMemoryGraphStore, SdkGraphStore
from .traversal import bounded_traverse, check_correctness
from .workloads import WORKLOADS, Dataset, generate

__all__ = [
    "CREDENTIAL_MODES",
    "EMULATOR_LABEL",
    "VARIANTS",
    "WORKLOADS",
    "BenchmarkResult",
    "Budget",
    "CellResult",
    "Dataset",
    "InMemoryGraphStore",
    "PartitionVariant",
    "SdkGraphStore",
    "bounded_traverse",
    "build_payload",
    "check_correctness",
    "generate",
    "render_markdown",
    "run_benchmark",
    "write_evidence",
]
