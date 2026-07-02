from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from erw_mrv.landsat import (  # noqa: E402
    DEFAULT_AOI,
    DEFAULT_BANDS,
    DEFAULT_CLIP_DIR,
    DEFAULT_COVERAGE_TARGET_PCT,
    DEFAULT_DATE_RANGE,
    DEFAULT_MAX_CLOUD_COVER,
    DEFAULT_MOSAIC_DIR,
    DEFAULT_STAC_URL,
    LANDSAT_COLLECTION,
    coverage_is_complete,
    download_scene_bands,
    items_from_ids,
    load_aoi,
    mosaic_coverage_dataframe,
    mosaic_downloaded_bands,
    require_coverage,
    scenes_dataframe,
    search_landsat_items,
    select_all_scene_ids,
    write_manifest,
)
from erw_mrv.paths import ensure_dir  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download Landsat C2 L2 STAC AOI clips and build band mosaics."
    )
    parser.add_argument("--aoi", type=Path, default=DEFAULT_AOI)
    parser.add_argument("--date-range", default=DEFAULT_DATE_RANGE)
    parser.add_argument("--max-cloud-cover", type=float, default=DEFAULT_MAX_CLOUD_COVER)
    parser.add_argument("--clip-dir", type=Path, default=DEFAULT_CLIP_DIR)
    parser.add_argument("--mosaic-dir", type=Path, default=DEFAULT_MOSAIC_DIR)
    parser.add_argument("--stac-url", default=DEFAULT_STAC_URL)
    parser.add_argument("--collection", default=LANDSAT_COLLECTION)
    parser.add_argument("--bands", nargs="+", default=list(DEFAULT_BANDS))
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--mosaic", action="store_true")
    parser.add_argument("--no-cloud-mask", action="store_true")
    parser.add_argument("--download-retries", type=int, default=3)
    parser.add_argument("--download-retry-delay", type=float, default=5)
    parser.add_argument("--no-progress", action="store_true")
    parser.add_argument("--coverage-target", type=float, default=DEFAULT_COVERAGE_TARGET_PCT)
    parser.add_argument("--require-full-coverage", action="store_true")
    parser.add_argument("--max-items", type=int, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    clip_dir = ensure_dir(args.clip_dir)
    mosaic_dir = ensure_dir(args.mosaic_dir)

    aoi, aoi_geojson = load_aoi(args.aoi)
    items = search_landsat_items(
        aoi_geojson=aoi_geojson,
        date_range=args.date_range,
        max_cloud_cover=args.max_cloud_cover,
        stac_url=args.stac_url,
        collection=args.collection,
        max_items=args.max_items,
    )
    scenes = scenes_dataframe(items)
    selected_item_ids = select_all_scene_ids(scenes)
    selected_items = items_from_ids(items, selected_item_ids)

    print(f"Found {len(items)} scenes")
    print(f"Selected {len(selected_items)} scenes")
    if not scenes.empty:
        print(scenes[["item_id", "datetime", "cloud_cover", "path", "row"]].to_string(index=False))

    written = []
    if args.download:
        written = download_scene_bands(
            selected_items,
            args.bands,
            aoi,
            clip_dir,
            max_retries=args.download_retries,
            retry_delay=args.download_retry_delay,
            show_progress=not args.no_progress,
        )
    else:
        print("Download skipped. Add --download to write AOI clips.")

    mosaics = []
    if args.mosaic:
        mosaics = mosaic_downloaded_bands(
            clip_dir,
            aoi,
            args.bands,
            mosaic_dir,
            apply_cloud_mask=not args.no_cloud_mask,
        )
    else:
        print("Mosaic skipped. Add --mosaic after clips exist.")

    if mosaics:
        coverage = mosaic_coverage_dataframe(mosaics, aoi)
        print(coverage.to_string(index=False))
        if coverage_is_complete(coverage, args.coverage_target):
            print(f"Coverage gate passed: all checked bands meet >= {args.coverage_target}% AOI coverage.")
        elif args.require_full_coverage:
            require_coverage(coverage, args.coverage_target)
        else:
            print(
                f"Coverage gate failed: some bands are below {args.coverage_target}% AOI coverage. "
                "Use --require-full-coverage to fail the run."
            )

    manifest_path = write_manifest(
        clip_dir / "landsat_stac_manifest.json",
        stac_url=args.stac_url,
        collection=args.collection,
        date_range=args.date_range,
        max_cloud_cover=args.max_cloud_cover,
        aoi_path=args.aoi,
        bands=args.bands,
        selected_item_ids=selected_item_ids,
        written=written,
        mosaics=mosaics,
        apply_cloud_mask=not args.no_cloud_mask,
        coverage_target_pct=args.coverage_target,
        coverage=coverage if mosaics else None,
    )
    print(f"Wrote manifest: {manifest_path}")


if __name__ == "__main__":
    main()
