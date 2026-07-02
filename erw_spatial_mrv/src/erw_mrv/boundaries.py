from __future__ import annotations

from pathlib import Path

import geopandas as gpd

from erw_mrv.paths import BOUNDARIES_PROCESSED, BOUNDARIES_RAW, ensure_dir


UGANDA_ADMIN_DIR = BOUNDARIES_RAW / "uga_admin_boundaries.shp"
UGANDA_DISTRICTS = UGANDA_ADMIN_DIR / "uga_admin2.shp"
DISTRICT_NAME_FIELD = "adm2_name"
DISTRICT_CODE_FIELD = "adm2_pcode"
PROJECTED_CRS = "EPSG:32636"
WEB_CRS = "EPSG:4326"


def union_geometries(geometries: gpd.GeoSeries):
    """Return one geometry with shared district borders removed."""
    return geometries.union_all()


def load_uganda_districts(path: Path = UGANDA_DISTRICTS) -> gpd.GeoDataFrame:
    """Load Uganda admin-2 district boundaries."""
    if not path.exists():
        raise FileNotFoundError(
            f"District shapefile not found at {path}. "
            "Expected Uganda admin boundaries under data/raw/boundaries."
        )

    districts = gpd.read_file(path)
    required_columns = {DISTRICT_NAME_FIELD, DISTRICT_CODE_FIELD, "geometry"}
    missing = required_columns.difference(districts.columns)
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise ValueError(f"District shapefile is missing required columns: {missing_list}")

    return districts


def filter_districts(
    districts: gpd.GeoDataFrame,
    district_names: list[str],
    name_field: str = DISTRICT_NAME_FIELD,
) -> gpd.GeoDataFrame:
    """Return district features whose names match the requested list."""
    if not district_names:
        raise ValueError("Provide at least one district name.")

    lookup = {name.casefold(): name for name in district_names}
    matched = districts[districts[name_field].str.casefold().isin(lookup)].copy()
    found = set(matched[name_field].str.casefold())
    missing = [name for key, name in lookup.items() if key not in found]
    if missing:
        available = ", ".join(sorted(districts[name_field].dropna().unique())[:25])
        missing_list = ", ".join(missing)
        raise ValueError(
            f"District(s) not found: {missing_list}. "
            f"Check spelling against {name_field}. First available values: {available}"
        )

    order = {name.casefold(): index for index, name in enumerate(district_names)}
    matched["_request_order"] = matched[name_field].str.casefold().map(order)
    return matched.sort_values("_request_order").drop(columns="_request_order")


def make_district_aoi(
    district_names: list[str],
    source_path: Path = UGANDA_DISTRICTS,
    output_dir: Path = BOUNDARIES_PROCESSED,
    projected_crs: str = PROJECTED_CRS,
) -> dict[str, Path]:
    """Clip selected districts and create a dissolved AOI boundary."""
    output_dir = ensure_dir(output_dir)
    districts = load_uganda_districts(source_path)
    selected = filter_districts(districts, district_names)

    selected = selected.to_crs(projected_crs)
    selected["area_km2_calc"] = selected.geometry.area / 1_000_000

    districts_path = output_dir / "selected_districts.gpkg"
    aoi_path = output_dir / "selected_districts_aoi.gpkg"
    aoi_geojson_path = output_dir / "selected_districts_aoi.geojson"

    selected.to_file(districts_path, layer="districts", driver="GPKG")

    aoi_geometry = union_geometries(selected.geometry)
    aoi = gpd.GeoDataFrame(
        {
            DISTRICT_NAME_FIELD: [", ".join(selected[DISTRICT_NAME_FIELD].tolist())],
            "district_count": [len(selected)],
            "area_km2_calc": [aoi_geometry.area / 1_000_000],
        },
        geometry=[aoi_geometry],
        crs=selected.crs,
    )
    aoi.to_file(aoi_path, layer="aoi", driver="GPKG")
    aoi.to_crs(WEB_CRS).to_file(aoi_geojson_path, driver="GeoJSON")

    return {
        "districts": districts_path,
        "aoi": aoi_path,
        "aoi_geojson": aoi_geojson_path,
    }
