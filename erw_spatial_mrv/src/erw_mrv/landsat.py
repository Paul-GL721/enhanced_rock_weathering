from __future__ import annotations

import json
import urllib.request
from urllib.parse import quote
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.mask import mask
from rasterio.merge import merge
from rasterio.vrt import WarpedVRT
from rasterio.warp import Resampling, reproject

from erw_mrv.paths import BOUNDARIES_PROCESSED, LANDSAT_PROCESSED, LANDSAT_RAW, ensure_dir


STAC_SEARCH_URL = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
PC_SIGN_URL = "https://planetarycomputer.microsoft.com/api/sas/v1/sign"
LANDSAT_COLLECTION = "landsat-c2-l2"
DEFAULT_AOI = BOUNDARIES_PROCESSED / "selected_districts_aoi.geojson"
DEFAULT_PATH_ROWS = (("172", "059"), ("172", "060"), ("173", "059"))
DEFAULT_BANDS = ("blue", "green", "red", "nir08", "swir16", "swir22", "qa_pixel")
DEFAULT_MOSAIC_BANDS = ("blue", "green", "red", "nir08", "swir16", "swir22")
AWS_BUCKET = "usgs-landsat"
_SIGNED_HREFS: dict[str, str] = {}
CLOUD_QA_BITS = (1, 2, 3, 4)


@dataclass(frozen=True)
class LandsatScene:
    item_id: str
    path: str
    row: str
    datetime: str
    cloud_cover: float
    assets: dict

    @property
    def path_row(self) -> tuple[str, str]:
        return self.path, self.row


def read_aoi_bounds(aoi_path: Path = DEFAULT_AOI) -> tuple[float, float, float, float]:
    aoi = gpd.read_file(aoi_path).to_crs("EPSG:4326")
    return tuple(aoi.total_bounds)


def search_landsat_scenes(
    bbox: tuple[float, float, float, float],
    start_date: str,
    end_date: str,
    max_cloud: float = 100,
    limit: int = 100,
) -> list[dict]:
    payload = {
        "collections": [LANDSAT_COLLECTION],
        "bbox": list(bbox),
        "datetime": f"{start_date}/{end_date}",
        "limit": limit,
        "query": {"eo:cloud_cover": {"lt": max_cloud}},
    }
    request = urllib.request.Request(
        STAC_SEARCH_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        data = json.loads(response.read().decode("utf-8"))
    return data.get("features", [])


def feature_to_scene(feature: dict) -> LandsatScene:
    props = feature["properties"]
    return LandsatScene(
        item_id=feature["id"],
        path=str(props["landsat:wrs_path"]).zfill(3),
        row=str(props["landsat:wrs_row"]).zfill(3),
        datetime=props["datetime"],
        cloud_cover=float(props.get("eo:cloud_cover", 100)),
        assets=feature["assets"],
    )


def select_best_scenes(
    features: Iterable[dict],
    path_rows: Iterable[tuple[str, str]] = DEFAULT_PATH_ROWS,
) -> list[LandsatScene]:
    wanted = {(str(path).zfill(3), str(row).zfill(3)) for path, row in path_rows}
    best: dict[tuple[str, str], LandsatScene] = {}

    for feature in features:
        scene = feature_to_scene(feature)
        if scene.path_row not in wanted:
            continue
        if scene.path_row not in best or scene.cloud_cover < best[scene.path_row].cloud_cover:
            best[scene.path_row] = scene

    missing = sorted(wanted.difference(best))
    if missing:
        missing_text = ", ".join(f"{path}/{row}" for path, row in missing)
        raise ValueError(f"No Landsat scenes found for path/row: {missing_text}")

    return [best[pair] for pair in sorted(best)]


def aws_asset_href(asset_href: str) -> str:
    marker = "/landsat-c2/"
    if marker not in asset_href:
        raise ValueError(f"Cannot convert non-Landsat C2 asset href to AWS: {asset_href}")
    suffix = asset_href.split(marker, 1)[1]
    return f"s3://{AWS_BUCKET}/collection02/{suffix}"


def signed_planetary_computer_href(asset_href: str) -> str:
    """Sign a Planetary Computer asset URL for direct Rasterio access."""
    if asset_href in _SIGNED_HREFS:
        return _SIGNED_HREFS[asset_href]

    sign_url = f"{PC_SIGN_URL}?href={quote(asset_href, safe='')}"
    with urllib.request.urlopen(sign_url, timeout=60) as response:
        data = json.loads(response.read().decode("utf-8"))

    signed_href = data["href"]
    _SIGNED_HREFS[asset_href] = signed_href
    return signed_href


def scene_manifest(scenes: Iterable[LandsatScene], bands: Iterable[str]) -> list[dict]:
    manifest = []
    for scene in scenes:
        band_assets = {}
        for band in bands:
            if band not in scene.assets:
                continue
            href = scene.assets[band]["href"]
            band_assets[band] = {
                "href": href,
                "aws_href": aws_asset_href(href),
            }

        manifest.append(
            {
                "item_id": scene.item_id,
                "path": scene.path,
                "row": scene.row,
                "datetime": scene.datetime,
                "cloud_cover": scene.cloud_cover,
                "bands": band_assets,
            }
        )
    return manifest


def clip_scene_bands(
    scene: LandsatScene,
    aoi_path: Path,
    output_dir: Path,
    bands: Iterable[str] = DEFAULT_BANDS,
    asset_source: str = "aws",
) -> list[Path]:
    output_dir = ensure_dir(output_dir / scene.item_id)
    aoi = gpd.read_file(aoi_path)
    written = []

    rasterio_env = {}
    if asset_source == "aws":
        rasterio_env = {
            "AWS_REQUEST_PAYER": "requester",
        }

    with rasterio.Env(**rasterio_env):
        for band in bands:
            if band not in scene.assets:
                continue

            href = scene.assets[band]["href"]
            if asset_source == "aws":
                source_href = aws_asset_href(href)
            elif asset_source == "azure":
                source_href = signed_planetary_computer_href(href)
            else:
                raise ValueError(f"Unsupported asset source: {asset_source}")
            output_path = output_dir / f"{scene.item_id}_{band}_aoi.tif"

            with rasterio.open(source_href) as src:
                shapes = aoi.to_crs(src.crs).geometry
                image, transform = mask(src, shapes, crop=True)
                profile = src.profile.copy()
                profile.update(
                    {
                        "driver": "GTiff",
                        "height": image.shape[1],
                        "width": image.shape[2],
                        "transform": transform,
                        "compress": "deflate",
                        "tiled": True,
                    }
                )

            with rasterio.open(output_path, "w", **profile) as dst:
                dst.write(image)

            written.append(output_path)

    return written


def download_april_2026_aoi(
    aoi_path: Path = DEFAULT_AOI,
    output_dir: Path = LANDSAT_RAW / "aoi_clips" / "2026-04",
    bands: Iterable[str] = DEFAULT_BANDS,
    path_rows: Iterable[tuple[str, str]] = DEFAULT_PATH_ROWS,
    asset_source: str = "aws",
    dry_run: bool = False,
) -> tuple[list[LandsatScene], list[Path]]:
    bbox = read_aoi_bounds(aoi_path)
    features = search_landsat_scenes(
        bbox=bbox,
        start_date="2026-04-01",
        end_date="2026-04-30",
    )
    scenes = select_best_scenes(features, path_rows=path_rows)
    output_dir = ensure_dir(output_dir)

    manifest_path = output_dir / "landsat_april_2026_manifest.json"
    manifest_path.write_text(json.dumps(scene_manifest(scenes, bands), indent=2) + "\n")

    if dry_run:
        return scenes, [manifest_path]

    written = [manifest_path]
    for scene in scenes:
        written.extend(
            clip_scene_bands(
                scene=scene,
                aoi_path=aoi_path,
                output_dir=output_dir,
                bands=bands,
                asset_source=asset_source,
            )
        )

    return scenes, written


def _scene_band_path(scene_dir: Path, band: str) -> Path | None:
    matches = sorted(scene_dir.glob(f"*_{band}_aoi.tif"))
    return matches[0] if matches else None


def _cloud_mask_from_qa(
    qa_path: Path,
    reference_profile: dict,
    reference_shape: tuple[int, int],
) -> np.ndarray:
    with rasterio.open(qa_path) as qa_src:
        qa = qa_src.read(1)
        if (
            qa_src.crs != reference_profile["crs"]
            or qa_src.transform != reference_profile["transform"]
            or qa.shape != reference_shape
        ):
            qa_aligned = np.zeros(reference_shape, dtype=qa.dtype)
            reproject(
                source=qa,
                destination=qa_aligned,
                src_transform=qa_src.transform,
                src_crs=qa_src.crs,
                dst_transform=reference_profile["transform"],
                dst_crs=reference_profile["crs"],
                resampling=Resampling.nearest,
            )
            qa = qa_aligned

    mask_bits = sum(1 << bit for bit in CLOUD_QA_BITS)
    return (qa & mask_bits) != 0


def write_cloud_masked_band(
    band_path: Path,
    qa_path: Path,
    output_path: Path,
    nodata: int = 0,
) -> Path:
    with rasterio.open(band_path) as src:
        data = src.read(1)
        profile = src.profile.copy()
        source_nodata = src.nodata

    cloud_mask = _cloud_mask_from_qa(qa_path, profile, data.shape)
    invalid = cloud_mask
    if source_nodata is not None:
        invalid = invalid | (data == source_nodata)

    data = data.copy()
    data[invalid] = nodata
    profile.update(nodata=nodata, compress="deflate", tiled=True)

    ensure_dir(output_path.parent)
    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(data, 1)

    return output_path


def mosaic_landsat_aoi_bands(
    clips_dir: Path = LANDSAT_RAW / "aoi_clips" / "2026-04",
    output_dir: Path = LANDSAT_PROCESSED / "mosaics" / "2026-04",
    bands: Iterable[str] = DEFAULT_MOSAIC_BANDS,
    apply_cloud_mask: bool = True,
    nodata: int = 0,
    target_crs: str = "EPSG:32636",
) -> list[Path]:
    """Merge path/row AOI clips into one AOI mosaic per band."""
    output_dir = ensure_dir(output_dir)
    scene_dirs = sorted(path for path in clips_dir.iterdir() if path.is_dir())
    if not scene_dirs:
        raise FileNotFoundError(f"No scene clip directories found in {clips_dir}")

    written = []
    temp_dir = ensure_dir(output_dir / "_cloud_masked_inputs")

    for band in bands:
        band_inputs = []
        for scene_dir in scene_dirs:
            band_path = _scene_band_path(scene_dir, band)
            if band_path is None:
                continue

            if apply_cloud_mask:
                qa_path = _scene_band_path(scene_dir, "qa_pixel")
                if qa_path is None:
                    raise FileNotFoundError(f"Missing qa_pixel clip in {scene_dir}")
                masked_path = temp_dir / f"{scene_dir.name}_{band}_cloudmasked.tif"
                band_inputs.append(write_cloud_masked_band(band_path, qa_path, masked_path, nodata=nodata))
            else:
                band_inputs.append(band_path)

        if not band_inputs:
            continue

        datasets = [rasterio.open(path) for path in band_inputs]
        vrt_datasets = []
        try:
            vrt_datasets = [
                WarpedVRT(
                    dataset,
                    crs=target_crs,
                    nodata=nodata,
                    resampling=Resampling.nearest,
                )
                for dataset in datasets
            ]
            mosaic, transform = merge(vrt_datasets, nodata=nodata, method="first")
            profile = vrt_datasets[0].profile.copy()
            profile.update(
                {
                    "driver": "GTiff",
                    "height": mosaic.shape[1],
                    "width": mosaic.shape[2],
                    "transform": transform,
                    "nodata": nodata,
                    "compress": "deflate",
                    "tiled": True,
                }
            )
        finally:
            for vrt_dataset in vrt_datasets:
                vrt_dataset.close()
            for dataset in datasets:
                dataset.close()

        output_path = output_dir / f"landsat_april_2026_aoi_{band}_mosaic.tif"
        with rasterio.open(output_path, "w", **profile) as dst:
            dst.write(mosaic)
        written.append(output_path)

    return written
