#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from erw_mrv.boundaries import make_district_aoi


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Process Uganda admin boundary shapefiles into selected district "
            "and dissolved AOI GeoPackages."
        )
    )
    parser.add_argument(
        "--districts",
        nargs="+",
        required=True,
        help="District names to extract from the Uganda admin-2 shapefile.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    outputs = make_district_aoi(args.districts)
    print("Boundary processing complete.")
    print(f"Selected districts: {outputs['districts']}")
    print(f"Dissolved AOI: {outputs['aoi']}")


if __name__ == "__main__":
    main()
