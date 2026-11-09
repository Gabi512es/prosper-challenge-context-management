"""Process-start identity, distinct from the editable agent JSON revision."""
import hashlib
from pathlib import Path
import subprocess

CODE_VERSION = "scheduling-slots-v7"
ROOT = Path(__file__).resolve().parents[1]
try:
    GIT_COMMIT = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
except (OSError, subprocess.CalledProcessError):
    GIT_COMMIT = None
_digest = hashlib.sha256()
for _path in sorted((ROOT / "backend").rglob("*.py")):
    if any(part.startswith(".") or part in {"tests", "logs", "__pycache__"} for part in _path.relative_to(ROOT).parts):
        continue
    _digest.update(str(_path.relative_to(ROOT)).encode())
    _digest.update(_path.read_bytes())
CODE_REVISION = _digest.hexdigest()
