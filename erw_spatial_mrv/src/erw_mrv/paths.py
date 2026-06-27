from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_RAW = PROJECT_ROOT / "data_raw"
DATA_PROCESSED = PROJECT_ROOT / "data_processed"
BOUNDARIES_RAW = DATA_RAW / "boundaries"
BOUNDARIES_PROCESSED = DATA_PROCESSED / "boundaries"


def ensure_dir(path: Path) -> Path:
    """Create a directory when needed and return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path
