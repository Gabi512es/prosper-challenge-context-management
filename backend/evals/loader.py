"""Load the development scenarios only when their pinned catalog matches."""

import hashlib
import json
from pathlib import Path


BACKEND_DIR = Path(__file__).parents[1]
DEFAULT_SCENARIOS_PATH = Path(__file__).with_name("dev_scenarios.json")
DEFAULT_CATALOG_PATH = BACKEND_DIR / "data" / "catalog.json"


class CatalogBlobMismatchError(ValueError):
    pass


def git_blob_sha(path: Path) -> str:
    """Return Git's SHA-1 object ID for the file bytes without invoking Git."""
    content = path.read_bytes()
    header = f"blob {len(content)}\0".encode()
    return hashlib.sha1(header + content).hexdigest()


def load_dev_scenarios(
    path: Path = DEFAULT_SCENARIOS_PATH,
    catalog_path: Path = DEFAULT_CATALOG_PATH,
) -> dict:
    """Load the source-of-truth development JSON and enforce its catalog pin."""
    data = json.loads(path.read_text())
    expected_sha = data.get("catalog", {}).get("blob_sha")
    actual_sha = git_blob_sha(catalog_path)
    if expected_sha != actual_sha:
        raise CatalogBlobMismatchError(
            "Development scenarios require catalog blob "
            f"{expected_sha}, but {catalog_path} is {actual_sha}."
        )
    if data.get("dataset_role") != "development_only":
        raise ValueError("Scenario file must declare dataset_role=development_only.")
    if any(item.get("split") != "development" for item in data.get("scenarios", [])):
        raise ValueError("Development scenario file contains a non-development case.")
    return data
