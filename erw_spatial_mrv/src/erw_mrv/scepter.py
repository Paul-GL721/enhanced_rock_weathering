from __future__ import annotations

import json
import shlex
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import geopandas as gpd
import pandas as pd

from erw_mrv.paths import SCEPTER_INPUTS, SCEPTER_OUTPUTS, SCEPTER_RUN_DIR, ensure_dir


PROJECTED_CRS = "EPSG:32636"
WEB_CRS = "EPSG:4326"


@dataclass(frozen=True)
class ScepterDefaults:
    """Interim assumptions used before measured soil and climate layers are ready."""

    soil_ph: float = 6.2
    cec_cmolc_kg: float = 14.0
    clay_pct: float = 28.0
    bulk_density_g_cm3: float = 1.30
    soil_depth_cm: float = 30.0
    temperature_c: float = 24.0
    precipitation_mm_yr: float = 1200.0
    runoff_mm_yr: float = 300.0
    basalt_application_t_ha: float = 20.0
    basalt_d50_um: float = 50.0
    simulation_years: int = 10


DEFAULT_SCENARIOS = pd.DataFrame(
    [
        {
            "scenario_id": "baseline_no_erw",
            "basalt_application_t_ha": 0.0,
            "basalt_d50_um": 50.0,
            "simulation_years": 10,
            "description": "No rock amendment baseline.",
        },
        {
            "scenario_id": "erw_10t_fine",
            "basalt_application_t_ha": 10.0,
            "basalt_d50_um": 50.0,
            "simulation_years": 10,
            "description": "Low application rate with fine basalt.",
        },
        {
            "scenario_id": "erw_20t_fine",
            "basalt_application_t_ha": 20.0,
            "basalt_d50_um": 50.0,
            "simulation_years": 10,
            "description": "Middle application rate with fine basalt.",
        },
        {
            "scenario_id": "erw_40t_medium",
            "basalt_application_t_ha": 40.0,
            "basalt_d50_um": 100.0,
            "simulation_years": 10,
            "description": "Higher application rate with medium basalt.",
        },
    ]
)


def load_cleaned_parcels(path: Path) -> gpd.GeoDataFrame:
    """Load cleaned cropland parcels and ensure area fields are present."""
    if not path.exists():
        raise FileNotFoundError(f"Cleaned parcel file not found: {path}")

    parcels = gpd.read_file(path)
    if parcels.empty:
        raise ValueError(f"Cleaned parcel file has no features: {path}")

    projected = parcels.to_crs(PROJECTED_CRS)
    if "area_m2" not in projected.columns:
        projected["area_m2"] = projected.geometry.area
    if "area_ha" not in projected.columns:
        projected["area_ha"] = projected["area_m2"] / 10_000

    return projected


def make_model_units(
    parcels: gpd.GeoDataFrame,
    defaults: ScepterDefaults | None = None,
    max_units: int | None = None,
) -> gpd.GeoDataFrame:
    """Convert cropland spatial units into SCEPTER model units with interim attributes."""
    defaults = defaults or ScepterDefaults()
    units = parcels.copy()
    units = units[~units.geometry.is_empty & units.geometry.notna()].copy()
    units = units.sort_values("area_ha", ascending=False).reset_index(drop=True)
    if max_units is not None:
        units = units.head(max_units).copy()

    units["model_unit_id"] = [f"mu_{index:05d}" for index in range(1, len(units) + 1)]
    units["area_m2"] = units.geometry.area
    units["area_ha"] = units["area_m2"] / 10_000

    centroids_projected = gpd.GeoSeries(units.geometry.centroid, crs=units.crs)
    centroids = centroids_projected.to_crs(WEB_CRS)
    units["centroid_lon"] = centroids.x
    units["centroid_lat"] = centroids.y

    for key, value in asdict(defaults).items():
        units[key] = value

    units["input_status"] = "assumption_pending_soil_climate_layers"
    return units


def model_units_table(units: gpd.GeoDataFrame) -> pd.DataFrame:
    """Return a flat, non-geometry table suitable for SCEPTER input prep."""
    columns = [
        "model_unit_id",
        "area_ha",
        "centroid_lon",
        "centroid_lat",
        "soil_ph",
        "cec_cmolc_kg",
        "clay_pct",
        "bulk_density_g_cm3",
        "soil_depth_cm",
        "temperature_c",
        "precipitation_mm_yr",
        "runoff_mm_yr",
        "input_status",
    ]
    optional_columns = [
        "soil_source",
        "soil_source_path",
        "soil_note",
        "rainfall_source",
        "rainfall_source_path",
        "rainfall_months_used",
        "missing_requested_months",
        "runoff_note",
    ]
    columns.extend(column for column in optional_columns if column in units.columns)
    return pd.DataFrame(units[columns]).copy()


def expand_scepter_runs(
    units_table: pd.DataFrame,
    scenarios: pd.DataFrame = DEFAULT_SCENARIOS,
) -> pd.DataFrame:
    """Create one run row for every model unit and scenario."""
    units = units_table.copy()
    scenarios = scenarios.copy()
    units["_join_key"] = 1
    scenarios["_join_key"] = 1
    runs = units.merge(scenarios, on="_join_key", how="inner").drop(columns="_join_key")
    runs["run_id"] = runs["model_unit_id"] + "__" + runs["scenario_id"]

    front = ["run_id", "model_unit_id", "scenario_id"]
    ordered = front + [column for column in runs.columns if column not in front]
    return runs[ordered]


def write_scepter_inputs(
    units: gpd.GeoDataFrame,
    output_dir: Path = SCEPTER_INPUTS,
    scenarios: pd.DataFrame = DEFAULT_SCENARIOS,
) -> dict[str, Path]:
    """Write model units, scenarios, and expanded run table."""
    output_dir = ensure_dir(output_dir)

    units_gpkg_path = output_dir / "scepter_model_units.gpkg"
    units_table_path = output_dir / "scepter_model_units.csv"
    scenarios_path = output_dir / "scepter_scenarios.csv"
    runs_path = output_dir / "scepter_runs.csv"
    readme_path = output_dir / "README_scepter_inputs.md"

    units.to_file(units_gpkg_path, layer="model_units", driver="GPKG")
    units_table = model_units_table(units)
    runs = expand_scepter_runs(units_table, scenarios)

    units_table.to_csv(units_table_path, index=False)
    scenarios.to_csv(scenarios_path, index=False)
    runs.to_csv(runs_path, index=False)
    readme_path.write_text(scepter_inputs_readme(), encoding="utf-8")

    return {
        "model_units_gpkg": units_gpkg_path,
        "model_units_csv": units_table_path,
        "scenarios_csv": scenarios_path,
        "runs_csv": runs_path,
        "readme": readme_path,
    }


def scepter_inputs_readme() -> str:
    """Describe the interim SCEPTER inputs for users outside the notebook."""
    return """# SCEPTER Input Tables

These files are the first-pass SCEPTER input staging tables for the ERW spatial MRV workflow.

- `scepter_model_units.gpkg`: spatial cropland model units derived from ESA cropland raster blocks.
- `scepter_model_units.csv`: non-spatial model unit attributes with cropland, soil, rainfall, and runoff provenance.
- `scepter_scenarios.csv`: ERW application scenarios.
- `scepter_runs.csv`: one row per model unit and scenario.

Soil and rainfall inputs should come from the processed HWSD2 and CHIRPS artifacts when available. Runoff remains an explicit first-pass estimate until a runoff layer is added.
"""


def load_scepter_runs(path: Path = SCEPTER_INPUTS / "scepter_runs.csv") -> pd.DataFrame:
    """Load the expanded SCEPTER run table produced by notebook 04."""
    if not path.exists():
        raise FileNotFoundError(f"SCEPTER run table not found: {path}")

    runs = pd.read_csv(path)
    required = {"run_id", "model_unit_id", "scenario_id"}
    missing = required.difference(runs.columns)
    if missing:
        raise ValueError(f"SCEPTER run table is missing columns: {', '.join(sorted(missing))}")

    return runs


def select_scepter_runs(
    runs: pd.DataFrame,
    max_runs: int | None = None,
    scenario_ids: list[str] | None = None,
) -> pd.DataFrame:
    """Select a small subset while testing, or return all rows for production."""
    selected = runs.copy()
    if scenario_ids:
        selected = selected[selected["scenario_id"].isin(scenario_ids)].copy()
    selected = selected.sort_values(["model_unit_id", "scenario_id"]).reset_index(drop=True)
    if max_runs is not None:
        selected = selected.head(max_runs).copy()
    return selected


def scepter_run_config(row: pd.Series | dict, output_dir: Path) -> dict:
    """Convert one run-table row into a simple model configuration dictionary."""
    record = dict(row)
    run_id = str(record["run_id"])
    config = {
        "run_id": run_id,
        "model_unit_id": record["model_unit_id"],
        "scenario_id": record["scenario_id"],
        "site": {
            "area_ha": float(record["area_ha"]),
            "centroid_lon": float(record["centroid_lon"]),
            "centroid_lat": float(record["centroid_lat"]),
        },
        "soil": {
            "ph": float(record["soil_ph"]),
            "cec_cmolc_kg": float(record["cec_cmolc_kg"]),
            "clay_pct": float(record["clay_pct"]),
            "bulk_density_g_cm3": float(record["bulk_density_g_cm3"]),
            "depth_cm": float(record["soil_depth_cm"]),
        },
        "climate": {
            "temperature_c": float(record["temperature_c"]),
            "precipitation_mm_yr": float(record["precipitation_mm_yr"]),
            "runoff_mm_yr": float(record["runoff_mm_yr"]),
        },
        "amendment": {
            "basalt_application_t_ha": float(record["basalt_application_t_ha"]),
            "basalt_d50_um": float(record["basalt_d50_um"]),
        },
        "simulation": {
            "years": int(record["simulation_years"]),
        },
        "outputs": {
            "output_dir": str(output_dir),
            "summary_csv": str(output_dir / f"{run_id}_summary.csv"),
        },
    }
    cropland_keys = [
        "cropland_source",
        "cropland_source_path",
        "cropland_pixels",
        "cropland_pixel_area_m2",
        "cropland_area_note",
    ]
    cropland = {
        key: record[key]
        for key in cropland_keys
        if key in record and pd.notna(record[key])
    }
    if cropland:
        config["cropland"] = cropland

    soil_map_keys = [
        "soil_map_hwsd2_unit_id",
        "soil_map_texture_group",
        "soil_map_wrb4",
        "soil_map_fao90",
        "soil_map_clay_pct",
        "soil_map_sand_pct",
        "soil_map_silt_pct",
        "soil_map_source_path",
        "soil_map_join",
    ]
    soil_map = {
        key: record[key]
        for key in soil_map_keys
        if key in record and pd.notna(record[key])
    }
    if soil_map:
        config["soil_map"] = soil_map

    source_keys = [
        "input_status",
        "cropland_source",
        "cropland_source_path",
        "cropland_area_note",
        "soil_map_hwsd2_unit_id",
        "soil_map_texture_group",
        "soil_map_wrb4",
        "soil_map_fao90",
        "soil_map_source_path",
        "soil_map_join",
        "soil_source",
        "soil_source_path",
        "soil_note",
        "rainfall_source",
        "rainfall_source_path",
        "rainfall_months_used",
        "missing_requested_months",
        "runoff_note",
    ]
    sources = {
        key: record[key]
        for key in source_keys
        if key in record and pd.notna(record[key])
    }
    if sources:
        config["input_sources"] = sources
    return config


def write_run_configs(
    runs: pd.DataFrame,
    run_root: Path = SCEPTER_RUN_DIR,
    output_root: Path = SCEPTER_OUTPUTS,
) -> pd.DataFrame:
    """Write one JSON config per SCEPTER run and return an execution table."""
    run_root = ensure_dir(run_root)
    output_root = ensure_dir(output_root)
    records = []

    for row in runs.to_dict(orient="records"):
        run_id = row["run_id"]
        run_dir = ensure_dir(run_root / run_id)
        output_dir = ensure_dir(output_root / run_id)
        config_path = run_dir / "scepter_config.json"
        config = scepter_run_config(row, output_dir)
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        source_fields = [
            "input_status",
            "cropland_source",
            "cropland_source_path",
            "cropland_pixels",
            "cropland_pixel_area_m2",
            "cropland_area_note",
            "soil_map_hwsd2_unit_id",
            "soil_map_texture_group",
            "soil_map_wrb4",
            "soil_map_fao90",
            "soil_map_clay_pct",
            "soil_map_sand_pct",
            "soil_map_silt_pct",
            "soil_map_source_path",
            "soil_map_join",
            "soil_source",
            "soil_source_path",
            "soil_note",
            "rainfall_source",
            "rainfall_source_path",
            "rainfall_months_used",
            "missing_requested_months",
            "runoff_note",
        ]
        source_record = {
            key: row[key]
            for key in source_fields
            if key in row and pd.notna(row[key])
        }
        records.append(
            {
                "run_id": run_id,
                "model_unit_id": row["model_unit_id"],
                "scenario_id": row["scenario_id"],
                "run_dir": run_dir,
                "output_dir": output_dir,
                "config_path": config_path,
                "status": "staged",
                **source_record,
            }
        )

    return pd.DataFrame(records)


def format_scepter_command(command_template: str, row: pd.Series | dict) -> list[str]:
    """Fill a command template and split it into subprocess arguments."""
    record = {key: str(value) for key, value in dict(row).items()}
    command = command_template.format(**record)
    return shlex.split(command)


def execute_scepter_runs(
    execution_table: pd.DataFrame,
    command_template: str,
    timeout_seconds: int | None = None,
) -> pd.DataFrame:
    """Run an external SCEPTER command for each staged config."""
    records = []
    for row in execution_table.to_dict(orient="records"):
        started = time.time()
        command = format_scepter_command(command_template, row)
        log_path = Path(row["run_dir"]) / "scepter_stdout.log"
        err_path = Path(row["run_dir"]) / "scepter_stderr.log"
        status = "failed"
        return_code = None

        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            return_code = completed.returncode
            log_path.write_text(completed.stdout, encoding="utf-8")
            err_path.write_text(completed.stderr, encoding="utf-8")
            status = "complete" if completed.returncode == 0 else "failed"
        except subprocess.TimeoutExpired as exc:
            log_path.write_text(exc.stdout or "", encoding="utf-8")
            err_path.write_text(exc.stderr or "SCEPTER run timed out.", encoding="utf-8")
            status = "timeout"
        except FileNotFoundError as exc:
            err_path.write_text(
                f"SCEPTER command was not found: {command[0]}\n"
                "Install SCEPTER in this runtime or update SCEPTER_COMMAND_TEMPLATE "
                "to the executable/script path that runs the model.\n"
                f"Original error: {exc}\n",
                encoding="utf-8",
            )
            log_path.write_text("", encoding="utf-8")
            status = "command_not_found"

        elapsed_seconds = time.time() - started
        records.append(
            {
                **row,
                "command": " ".join(command),
                "status": status,
                "return_code": return_code,
                "elapsed_seconds": elapsed_seconds,
                "stdout_log": log_path,
                "stderr_log": err_path,
            }
        )

    return pd.DataFrame(records)


def load_execution_manifest(
    path: Path = SCEPTER_OUTPUTS / "scepter_execution_manifest.csv",
) -> pd.DataFrame:
    """Load the notebook 05 execution manifest."""
    if not path.exists():
        raise FileNotFoundError(f"SCEPTER execution manifest not found: {path}")

    manifest = pd.read_csv(path)
    required = {"run_id", "model_unit_id", "scenario_id", "status", "output_dir"}
    missing = required.difference(manifest.columns)
    if missing:
        raise ValueError(f"SCEPTER execution manifest is missing columns: {', '.join(sorted(missing))}")

    return manifest


def expected_summary_path(row: pd.Series | dict) -> Path:
    """Return the standard per-run summary path used by notebook 05 configs."""
    record = dict(row)
    return Path(record["output_dir"]) / f"{record['run_id']}_summary.csv"


def read_run_summary(path: Path) -> dict:
    """Read one SCEPTER summary CSV into a flat dictionary.

    Supports either a one-row wide CSV, or a two-column `metric,value` CSV.
    """
    data = pd.read_csv(path)
    if data.empty:
        return {}

    lower_columns = {column.lower(): column for column in data.columns}
    if {"metric", "value"}.issubset(lower_columns):
        metric_col = lower_columns["metric"]
        value_col = lower_columns["value"]
        return dict(zip(data[metric_col], data[value_col]))

    return data.iloc[0].to_dict()


def extract_scepter_results(manifest: pd.DataFrame) -> pd.DataFrame:
    """Extract available per-run SCEPTER summary outputs."""
    records = []
    source_fields = [
        "input_status",
        "cropland_source",
        "cropland_source_path",
        "cropland_pixels",
        "cropland_pixel_area_m2",
        "cropland_area_note",
        "soil_map_hwsd2_unit_id",
        "soil_map_texture_group",
        "soil_map_wrb4",
        "soil_map_fao90",
        "soil_map_clay_pct",
        "soil_map_sand_pct",
        "soil_map_silt_pct",
        "soil_map_source_path",
        "soil_map_join",
        "soil_source",
        "soil_source_path",
        "soil_note",
        "rainfall_source",
        "rainfall_source_path",
        "rainfall_months_used",
        "missing_requested_months",
        "runoff_note",
    ]
    for row in manifest.to_dict(orient="records"):
        summary_path = expected_summary_path(row)
        base = {
            "run_id": row["run_id"],
            "model_unit_id": row["model_unit_id"],
            "scenario_id": row["scenario_id"],
            "execution_status": row["status"],
            "summary_path": summary_path,
        }
        base.update(
            {
                key: row[key]
                for key in source_fields
                if key in row and pd.notna(row[key])
            }
        )

        if summary_path.exists():
            metrics = read_run_summary(summary_path)
            records.append({**base, "result_status": "parsed", **metrics})
        else:
            records.append({**base, "result_status": "missing_summary"})

    return pd.DataFrame(records)


def join_results_to_units(
    results: pd.DataFrame,
    units_path: Path = SCEPTER_INPUTS / "scepter_model_units.gpkg",
) -> gpd.GeoDataFrame:
    """Join SCEPTER result rows back to spatial model units."""
    if not units_path.exists():
        raise FileNotFoundError(f"SCEPTER model unit geometry file not found: {units_path}")

    units = gpd.read_file(units_path)
    if "model_unit_id" not in units.columns:
        raise ValueError(f"Model unit file is missing `model_unit_id`: {units_path}")

    unit_columns = [
        "model_unit_id",
        *[column for column in units.columns if column not in results.columns and column != "model_unit_id"],
    ]
    return units[unit_columns].merge(results, on="model_unit_id", how="right")


def summarize_scepter_results(results: pd.DataFrame) -> pd.DataFrame:
    """Build scenario-level summaries for parsed numeric SCEPTER outputs."""
    numeric = results.select_dtypes(include="number").columns.tolist()
    metric_columns = [
        column
        for column in numeric
        if column not in {"return_code", "elapsed_seconds"}
    ]
    if not metric_columns:
        return pd.DataFrame(
            {
                "scenario_id": sorted(results["scenario_id"].dropna().unique()),
                "parsed_run_count": [
                    int((results["scenario_id"].eq(scenario) & results["result_status"].eq("parsed")).sum())
                    for scenario in sorted(results["scenario_id"].dropna().unique())
                ],
            }
        )

    grouped = results.groupby("scenario_id")[metric_columns].agg(["count", "mean", "sum"]).reset_index()
    grouped.columns = [
        "_".join([part for part in column if part]).strip("_")
        if isinstance(column, tuple)
        else column
        for column in grouped.columns
    ]
    return grouped
