"""The ``detections`` worker role: configuration findings and shadow-AI discovery (PRP-61).

The role builder (``role.build_detections``) is imported by ``runtime.factories`` for its
``BUILDERS`` table, so this package must not import ``runtime.factories`` at import time.
"""

from neurosphere_workers.detections.settings import DetectionSettings

__all__ = ["DetectionSettings"]
