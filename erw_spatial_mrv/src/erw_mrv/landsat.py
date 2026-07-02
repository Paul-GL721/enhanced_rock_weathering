from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from typing import Iterable

import geopandas as gpd
import numpy as np
import pandas as pd
import planetary_computer
import rasterio
from rasterio.errors import RasterioIOError
from pystac_client import Client
from rasterio.features import geometry_mask
from rasterio.mask import mask
from rasterio.merge import merge
from rasterio.vrt import WarpedVRT
from rasterio.warp import Resampling, reproject

from erw_mrv.paths import BOUNDARIES_PROCESSED, LANDSAT_PROCESSED, LANDSAT_RAW, ensure_dir


DEFAULT_AOI = BOUNDARIES_PROCESSED / "selected_districts_aoi.geojson"
DEFAULT_STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
LANDSAT_COLLECTION = "landsat-c2-l2"
DEFAULT_BANDS = ("blue", "green", "red", "nir08", "swir16", "swir22", "qa_pixel")
SPECTRAL_BANDS = ("blue", "green", "red", "nir08", "swir16", "swir22")
DEFAULT_DATE_RANGE = "2026-01-01/2026-06-29"
DEFAULT_MAX_CLOUD_COVER = 10
DEFAULT_COVERAGE_TARGET_PCT = 99.9
DEFAULT_CLIP_DIR = LANDSAT_RAW / "stac_aoi_clips" / "202601_202606"
DEFAULT_MOSAIC_DIR = LANDSAT_PROCESSED / "mosaics" / "202601_202606"
QA_PIXEL_CLEAR_BITS = (0, 1, 2, 3, 4)


def load_aoi(aoi_path: Path = DEFAULT_AOI) -> tuple[gpd.GeoDataFrame, dict]:
    """Load the dissolved AOI and return it with a GeoJSON geometry for STAC search."""
    aoi = gpd.read_file(aoi_path).to_crs("EPSG:4326")
    aoi_geometry = aoi.geometry.union_all()
    return aoi, aoi_geometry.__geo_interface__


def search_landsat_items(
    aoi_geojson: dict,
    date_range: str = DEFAULT_DATE_RANGE,
    max_cloud_cover: int | float = DEFAULT_MAX_CLOUD_COVER,
    stac_url: str = DEFAULT_STAC_URL,
    collection: str = LANDSAT_COLLECTION,
    max_items: int | None = None,
) -> list:
    """Search Planetary Computer STAC for Landsat scenes intersecting the AOI."""
    catalog = Client.open(stac_url)
    search = catalog.search(
        collections=[collection],
        intersects=aoi_geojson,
        datetime=date_range,
        query={"eo:cloud_cover": {"lt": max_cloud_cover}},
        max_items=max_items,
    )
    return list(search.items())


def scenes_dataframe(items: Iterable) -> pd.DataFrame:
    """Convert STAC items to a compact scene table."""
    rows = []
    for item in items:
        props = item.properties
        rows.append(
            {
                "item_id": item.id,
                "datetime": props.get("datetime"),
                "platform": props.get("platform"),
                "cloud_cover": props.get("eo:cloud_cover"),
                "path": props.get("landsat:wrs_path"),
                "row": props.get("landsat:wrs_row"),
                "asset_count": len(item.assets),
            }
        )

    if not rows:
        return pd.DataFrame(
            columns=[
                "item_id",
                "datetime",
                "platform",
                "cloud_cover",
                "path",
                "row",
                "asset_count",
            ]
        )

    return pd.DataFrame(rows).sort_values(["datetime", "cloud_cover"]).reset_index(drop=True)


def select_all_scene_ids(scenes: pd.DataFrame) -> list[str]:
    """Select every scene returned by the filtered STAC search."""
    if scenes.empty:
        return []
    return scenes.sort_values(["datetime", "cloud_cover"])["item_id"].tolist()


def items_from_ids(items: Iterable, item_ids: Iterable[str]) -> list:
    """Return STAC items in the same order as item_ids."""
    items_by_id = {item.id: item for item in items}
    return [items_by_id[item_id] for item_id in item_ids]


def clip_asset_to_aoi(
    item,
    band: str,
    aoi: gpd.GeoDataFrame,
    output_dir: Path,
    max_retries: int = 3,
    retry_delay: int | float = 5,
) -> Path | None:
    """Read a signed STAC raster asset, clip it to the AOI, and write a GeoTIFF."""
    if band not in item.assets:
        print(f"Skipping {item.id} {band}: asset missing")
        return None

    output_dir = ensure_dir(output_dir)
    output_path = output_dir / f"{item.id}_{band}_aoi.tif"
    if output_path.exists():
        print(f"Exists: {output_path.name}")
        return output_path

    temp_path = output_path.with_suffix(output_path.suffix + ".part")
    for attempt in range(1, max_retries + 1):
        temp_path.unlink(missing_ok=True)
        try:
            signed_asset = planetary_computer.sign(item.assets[band])
            with rasterio.Env(
                GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
                GDAL_HTTP_MAX_RETRY="4",
                GDAL_HTTP_RETRY_DELAY="2",
                CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".TIF,.tif",
                VSI_CACHE="TRUE",
            ):
                with rasterio.open(signed_asset.href) as src:
                    shapes = aoi.to_crs(src.crs).geometry
                    image, transform = mask(src, shapes, crop=True)
                    profile = src.profile.copy()

            profile.update(
                driver="GTiff",
                height=image.shape[1],
                width=image.shape[2],
                transform=transform,
                compress="deflate",
                tiled=True,
                BIGTIFF="IF_SAFER",
            )

            with rasterio.open(temp_path, "w", **profile) as dst:
                dst.write(image)

            temp_path.replace(output_path)
            print(f"Wrote: {output_path.name}")
            return output_path
        except (RasterioIOError, OSError, RuntimeError) as exc:
            temp_path.unlink(missing_ok=True)
            print(
                f"Attempt {attempt}/{max_retries} failed for {item.id} {band}: {exc}"
            )
            if attempt < max_retries:
                time.sleep(retry_delay)

    print(f"Failed after {max_retries} attempts: {item.id} {band}")
    return None


def download_scene_bands(
    items: Iterable,
    bands: Iterable[str],
    aoi: gpd.GeoDataFrame,
    output_dir: Path = DEFAULT_CLIP_DIR,
    max_retries: int = 3,
    retry_delay: int | float = 5,
    show_progress: bool = True,
) -> list[Path]:
    """Download AOI clips for all selected scene/band combinations."""
    items = list(items)
    bands = list(bands)
    total = len(items) * len(bands)
    written = []
    completed = 0
    existing = 0
    failed = 0

    progress = None
    if show_progress:
        try:
            from tqdm import tqdm

            progress = tqdm(total=total, desc="Landsat band clips", unit="clip")
        except ImportError:
            progress = None
            print(f"Downloading {total} Landsat band clips")

    for item_index, item in enumerate(items, start=1):
        for band_index, band in enumerate(bands, start=1):
            output_path = Path(output_dir) / f"{item.id}_{band}_aoi.tif"
            existed_before = output_path.exists()
            path = clip_asset_to_aoi(
                item,
                band,
                aoi,
                output_dir,
                max_retries=max_retries,
                retry_delay=retry_delay,
            )
            if path is not None:
                written.append(path)
                if existed_before:
                    existing += 1
                else:
                    completed += 1
            else:
                failed += 1

            done = (item_index - 1) * len(bands) + band_index
            remaining = total - done
            if progress is not None:
                progress.set_postfix(
                    new=completed,
                    existing=existing,
                    failed=failed,
                    left=remaining,
                    refresh=False,
                )
                progress.update(1)
            elif show_progress:
                print(
                    f"Progress {done}/{total}; left={remaining}; "
                    f"new={completed}; existing={existing}; failed={failed}"
                )

    if progress is not None:
        progress.close()

    if show_progress:
        print(
            f"Download summary: total={total}, new={completed}, "
            f"existing={existing}, failed={failed}"
        )
    return written


def band_clip_paths(clip_dir: Path, band: str) -> list[Path]:
    """Return downloaded AOI clips for one band."""
    return sorted(Path(clip_dir).glob(f"*_{band}_aoi.tif"))


def qa_path_for_band_clip(clip_path: Path, band: str) -> Path:
    """Return the matching qa_pixel clip path for a downloaded band clip."""
    clip_path = Path(clip_path)
    suffix = f"_{band}_aoi.tif"
    if not clip_path.name.endswith(suffix):
        raise ValueError(f"Expected {clip_path.name} to end with {suffix}")
    return clip_path.with_name(clip_path.name.removesuffix(suffix) + "_qa_pixel_aoi.tif")


def clear_mask_from_qa(
    qa_array: np.ndarray,
    clear_bits: Iterable[int] = QA_PIXEL_CLEAR_BITS,
) -> np.ndarray:
    """Return True where Landsat QA_PIXEL has no fill/cloud/shadow flags."""
    mask_array = np.ones(qa_array.shape, dtype=bool)
    for bit in clear_bits:
        mask_array &= (qa_array & (1 << bit)) == 0
    return mask_array


def _read_qa_matching_band(band_dataset, qa_path: Path) -> np.ndarray:
    """Read qa_pixel, reprojecting only if its grid differs from the band grid."""
    with rasterio.open(qa_path) as qa_src:
        if (
            qa_src.crs == band_dataset.crs
            and qa_src.transform == band_dataset.transform
            and qa_src.width == band_dataset.width
            and qa_src.height == band_dataset.height
        ):
            return qa_src.read(1)

        qa = np.zeros((band_dataset.height, band_dataset.width), dtype=qa_src.dtypes[0])
        reproject(
            source=rasterio.band(qa_src, 1),
            destination=qa,
            src_transform=qa_src.transform,
            src_crs=qa_src.crs,
            dst_transform=band_dataset.transform,
            dst_crs=band_dataset.crs,
            resampling=Resampling.nearest,
        )
        return qa


def write_cloud_masked_clip(
    band_path: Path,
    qa_path: Path,
    output_path: Path,
    clear_bits: Iterable[int] = QA_PIXEL_CLEAR_BITS,
) -> Path:
    """Write a temporary spectral clip with cloudy QA pixels set to nodata."""
    with rasterio.open(band_path) as src:
        data = src.read()
        qa = _read_qa_matching_band(src, qa_path)
        clear = clear_mask_from_qa(qa, clear_bits)
        profile = src.profile.copy()

    nodata = profile.get("nodata")
    if nodata is None:
        nodata = 0
        profile["nodata"] = nodata

    data[:, ~clear] = nodata
    profile.update(
        compress="deflate",
        tiled=True,
        BIGTIFF="IF_SAFER",
        SPARSE_OK="TRUE",
    )

    output_path = Path(output_path)
    ensure_dir(output_path.parent)
    temp_path = output_path.with_suffix(output_path.suffix + ".part")
    temp_path.unlink(missing_ok=True)
    with rasterio.open(temp_path, "w", **profile) as dst:
        dst.write(data)

    temp_path.replace(output_path)
    return output_path


def cloud_masked_band_clip_paths(
    clip_paths: Iterable[Path],
    band: str,
    temp_dir: Path,
    clear_bits: Iterable[int] = QA_PIXEL_CLEAR_BITS,
) -> list[Path]:
    """Create QA-masked temporary clips for one spectral band."""
    masked_paths = []
    for clip_path in clip_paths:
        qa_path = qa_path_for_band_clip(clip_path, band)
        if not qa_path.exists():
            print(f"Skipping cloud mask for {clip_path.name}: missing {qa_path.name}")
            continue
        masked_path = Path(temp_dir) / clip_path.name.replace("_aoi.tif", "_clear_aoi.tif")
        masked_paths.append(write_cloud_masked_clip(clip_path, qa_path, masked_path, clear_bits))
    return masked_paths


def mosaic_band_clips(
    clip_paths: Iterable[Path],
    aoi: gpd.GeoDataFrame,
    output_path: Path,
    method: str = "first",
    resampling: Resampling = Resampling.nearest,
) -> Path | None:
    """Mosaic downloaded clips for one band, then clip the mosaic to the AOI.

    Landsat path/row scenes over the AOI can arrive in different projected CRS
    zones. Rasterio merge requires a common CRS, so mismatched inputs are read
    through WarpedVRTs using the first clip as the target grid family.
    """
    clip_paths = [Path(path) for path in clip_paths]
    if not clip_paths:
        print(f"No clips found for {output_path.name}")
        return None

    output_path = Path(output_path)
    ensure_dir(output_path.parent)
    if output_path.exists():
        try:
            with rasterio.open(output_path) as src:
                src.profile
            print(f"Exists: {output_path.name}")
            return output_path
        except RasterioIOError:
            print(f"Replacing unreadable mosaic: {output_path.name}")
            output_path.unlink(missing_ok=True)

    datasets = [rasterio.open(path) for path in clip_paths]
    vrts = []
    try:
        target_crs = datasets[0].crs
        merge_sources = []
        for dataset in datasets:
            if dataset.crs == target_crs:
                merge_sources.append(dataset)
                continue

            vrt = WarpedVRT(
                dataset,
                crs=target_crs,
                resampling=resampling,
                src_nodata=dataset.nodata,
                nodata=dataset.nodata,
            )
            vrts.append(vrt)
            merge_sources.append(vrt)

        mosaic, transform = merge(merge_sources, method=method)
        profile = merge_sources[0].profile.copy()
        profile.update(
            driver="GTiff",
            height=mosaic.shape[1],
            width=mosaic.shape[2],
            transform=transform,
            crs=target_crs,
            compress="deflate",
            tiled=True,
            BIGTIFF="IF_SAFER",
            SPARSE_OK="TRUE",
        )

        temp_path = output_path.with_suffix(output_path.suffix + ".part")
        temp_path.unlink(missing_ok=True)
        with rasterio.open(temp_path, "w", **profile) as dst:
            dst.write(mosaic)

        with rasterio.open(temp_path) as src:
            shapes = aoi.to_crs(src.crs).geometry
            clipped, clipped_transform = mask(src, shapes, crop=True)
            clipped_profile = src.profile.copy()

        clipped_profile.update(
            height=clipped.shape[1],
            width=clipped.shape[2],
            transform=clipped_transform,
            compress="deflate",
            tiled=True,
            BIGTIFF="IF_SAFER",
            SPARSE_OK="TRUE",
        )
        final_temp_path = output_path.with_suffix(output_path.suffix + ".final.part")
        final_temp_path.unlink(missing_ok=True)
        with rasterio.open(final_temp_path, "w", **clipped_profile) as dst:
            dst.write(clipped)

        temp_path.unlink(missing_ok=True)
        final_temp_path.replace(output_path)
    finally:
        for vrt in vrts:
            vrt.close()
        for dataset in datasets:
            dataset.close()

    print(f"Wrote mosaic: {output_path.name}")
    return output_path


def mosaic_downloaded_bands(
    clip_dir: Path,
    aoi: gpd.GeoDataFrame,
    bands: Iterable[str] = DEFAULT_BANDS,
    output_dir: Path = DEFAULT_MOSAIC_DIR,
    method: str = "first",
    apply_cloud_mask: bool = True,
    clear_bits: Iterable[int] = QA_PIXEL_CLEAR_BITS,
) -> list[Path]:
    """Create one AOI-clipped mosaic per band from downloaded scene clips."""
    output_dir = ensure_dir(output_dir)
    mosaics = []
    temp_parent = ensure_dir(output_dir / "_tmp_cloud_masked")
    with tempfile.TemporaryDirectory(dir=temp_parent) as temp_dir:
        for band in bands:
            paths = band_clip_paths(clip_dir, band)
            if apply_cloud_mask and band != "qa_pixel":
                paths = cloud_masked_band_clip_paths(paths, band, Path(temp_dir), clear_bits)
            output_path = output_dir / f"landsat_{band}_mosaic_aoi.tif"
            mosaic_path = mosaic_band_clips(paths, aoi, output_path, method=method)
            if mosaic_path is not None:
                mosaics.append(mosaic_path)
    return mosaics


def mosaic_coverage_dataframe(
    mosaic_paths: Iterable[Path],
    aoi: gpd.GeoDataFrame,
) -> pd.DataFrame:
    """Report valid-data coverage inside the AOI for each mosaic."""
    rows = []
    for path in mosaic_paths:
        path = Path(path)
        with rasterio.open(path) as src:
            inside_aoi = geometry_mask(
                aoi.to_crs(src.crs).geometry,
                out_shape=(src.height, src.width),
                transform=src.transform,
                invert=True,
            )
            valid_data = src.dataset_mask() > 0
            inside_pixels = int(inside_aoi.sum())
            valid_inside_pixels = int((inside_aoi & valid_data).sum())
            coverage = (
                valid_inside_pixels / inside_pixels * 100 if inside_pixels else 0
            )
        rows.append(
            {
                "path": str(path),
                "band": path.name.removeprefix("landsat_").removesuffix("_mosaic_aoi.tif"),
                "inside_aoi_pixels": inside_pixels,
                "valid_inside_aoi_pixels": valid_inside_pixels,
                "valid_aoi_coverage_pct": coverage,
            }
        )
    return pd.DataFrame(rows)


def coverage_gaps(
    coverage: pd.DataFrame,
    target_pct: float = DEFAULT_COVERAGE_TARGET_PCT,
    exclude_bands: Iterable[str] = ("qa_pixel",),
) -> pd.DataFrame:
    """Return mosaic coverage rows that fall below the target."""
    if coverage.empty:
        return coverage
    exclude_bands = set(exclude_bands)
    checked = coverage[~coverage["band"].isin(exclude_bands)].copy()
    return checked[checked["valid_aoi_coverage_pct"] < target_pct]


def coverage_is_complete(
    coverage: pd.DataFrame,
    target_pct: float = DEFAULT_COVERAGE_TARGET_PCT,
    exclude_bands: Iterable[str] = ("qa_pixel",),
) -> bool:
    """Return True when all checked bands meet the AOI coverage target."""
    if coverage.empty:
        return False
    return coverage_gaps(coverage, target_pct, exclude_bands).empty


def require_coverage(
    coverage: pd.DataFrame,
    target_pct: float = DEFAULT_COVERAGE_TARGET_PCT,
    exclude_bands: Iterable[str] = ("qa_pixel",),
) -> None:
    """Raise when cloud-masked mosaics do not meet the AOI coverage target."""
    gaps = coverage_gaps(coverage, target_pct, exclude_bands)
    if gaps.empty:
        return

    gap_text = gaps[["band", "valid_aoi_coverage_pct"]].to_string(index=False)
    raise ValueError(
        f"Mosaic AOI coverage is below {target_pct:.2f}% for one or more bands.\n"
        f"{gap_text}\n"
        "Widen DATE_RANGE, relax MAX_CLOUD_COVER, or download more scenes and rerun "
        "the cloud-masked mosaic."
    )


def write_manifest(
    manifest_path: Path,
    *,
    stac_url: str,
    collection: str,
    date_range: str,
    max_cloud_cover: int | float,
    aoi_path: Path,
    bands: Iterable[str],
    selected_item_ids: Iterable[str],
    written: Iterable[Path],
    mosaics: Iterable[Path] | None = None,
    apply_cloud_mask: bool = True,
    coverage_target_pct: float = DEFAULT_COVERAGE_TARGET_PCT,
    coverage: pd.DataFrame | None = None,
) -> Path:
    """Write a JSON manifest for downloaded clips and mosaics."""
    manifest = {
        "stac_url": stac_url,
        "collection": collection,
        "date_range": date_range,
        "max_cloud_cover": max_cloud_cover,
        "aoi_path": str(aoi_path),
        "bands": list(bands),
        "selected_item_ids": list(selected_item_ids),
        "written": [str(path) for path in written],
        "mosaics": [str(path) for path in mosaics or []],
        "apply_cloud_mask": apply_cloud_mask,
        "qa_pixel_clear_bits": list(QA_PIXEL_CLEAR_BITS),
        "coverage_target_pct": coverage_target_pct,
        "coverage": coverage.to_dict(orient="records") if coverage is not None else [],
    }
    manifest_path = Path(manifest_path)
    ensure_dir(manifest_path.parent)
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return manifest_path
