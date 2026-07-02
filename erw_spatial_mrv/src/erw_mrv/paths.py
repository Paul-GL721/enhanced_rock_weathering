import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = Path(os.environ.get("ERW_MRV_DATA_ROOT", PROJECT_ROOT / "data")).expanduser()
DATA_RAW = DATA_ROOT / "raw"
DATA_PROCESSED = DATA_ROOT / "processed"
BOUNDARIES_RAW = DATA_RAW / "boundaries"
BOUNDARIES_PROCESSED = DATA_PROCESSED / "boundaries"
LANDSAT_RAW = DATA_RAW / "landsat"
LANDSAT_PROCESSED = DATA_PROCESSED / "landsat"
SCEPTER_RUNS = DATA_ROOT / "scepter_runs"
SCEPTER_INPUTS = SCEPTER_RUNS / "inputs"
SCEPTER_RUN_DIR = SCEPTER_RUNS / "runs"
SCEPTER_OUTPUTS = SCEPTER_RUNS / "outputs"
OUTPUTS = DATA_ROOT / "outputs"
OUTPUT_FIGURES = OUTPUTS / "figures"
OUTPUT_MAPS = OUTPUTS / "maps"
OUTPUT_REPORTS = OUTPUTS / "reports"
OUTPUT_TABLES = OUTPUTS / "tables"


def ensure_dir(path: Path) -> Path:
    """Create a directory when needed and return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path
