"""One evaluator identity for both comparison arms."""
import hashlib
from pathlib import Path

EVALUATOR_VERSION = "dev-eval-v5-recovery"


def evaluator_sha256():
    root = Path(__file__).parent
    digest = hashlib.sha256()
    # Behavior identity excludes operational checkpoint/budget code. That has
    # its own execution hash, so resuming unattempted cases does not relabel
    # unchanged patient/scoring behavior.
    for name in ("scorer.py", "text_integration.py"):
        digest.update(name.encode() + b"\0" + (root / name).read_bytes())
    return digest.hexdigest()
