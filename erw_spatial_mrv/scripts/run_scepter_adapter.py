#!/usr/bin/env python3
"""Run upstream SCEPTER from an ERW MRV JSON config.

The compiled SCEPTER binary does not expose a JSON/CLI interface. This adapter
translates the JSON written by notebook 05 into SCEPTER's native input files,
executes the binary inside the run output folder, and writes a compact summary
CSV that downstream notebooks can parse.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--scepter-root", type=Path)
    parser.add_argument("--executable", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=None)
    parser.add_argument(
        "--production-years",
        type=float,
        default=None,
        help="Override simulation years. Omit to use config simulation.years.",
    )
    parser.add_argument(
        "--smoke-test-years",
        type=float,
        default=0.000001,
        help="Short run length used unless --production-years is supplied.",
    )
    parser.add_argument(
        "--nstep",
        type=int,
        default=1,
        help="SCEPTER time-step growth iterations; keep small for smoke tests.",
    )
    parser.add_argument(
        "--keep-native-outputs",
        action="store_true",
        help="Keep bulky native SCEPTER output folders. By default only summary/log files are retained.",
    )
    return parser.parse_args()


def project_root_from_script() -> Path:
    return Path(__file__).resolve().parents[1]


def default_scepter_root() -> Path:
    return project_root_from_script() / "external" / "SCEPTER"


def load_config(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def reset_output_dir(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for child in output_dir.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def add_scepter_python_path(scepter_root: Path) -> None:
    if not scepter_root.exists():
        raise FileNotFoundError(f"SCEPTER source folder not found: {scepter_root}")
    if str(scepter_root) not in sys.path:
        sys.path.insert(0, str(scepter_root))


def as_float(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def as_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def build_native_inputs(config: dict, output_dir: Path, scepter_root: Path, years: float, nstep: int) -> dict:
    import make_inputs  # type: ignore

    run_id = str(config["run_id"])
    parent = output_dir.parent
    runname = output_dir.name
    outdir = str(parent) + os.sep

    soil = config.get("soil", {})
    climate = config.get("climate", {})
    amendment = config.get("amendment", {})
    simulation = config.get("simulation", {})

    depth_m = max(as_float(soil.get("depth_cm"), 30.0) / 100.0, 0.05)
    temperature_c = as_float(climate.get("temperature_c"), 24.0)
    runoff_m_yr = max(as_float(climate.get("runoff_mm_yr"), 300.0) / 1000.0, 1.0e-6)
    bulk_density = as_float(soil.get("bulk_density_g_cm3"), 1.3)
    porosity = min(max(1.0 - (bulk_density / 2.65), 0.25), 0.70)
    cec = max(as_float(soil.get("cec_cmolc_kg"), 14.0), 0.01)

    basalt_t_ha = max(as_float(amendment.get("basalt_application_t_ha"), 0.0), 0.0)
    basalt_g_m2 = basalt_t_ha * 100.0
    dust_duration_yr = 1.0 if basalt_g_m2 > 0 else 0.0
    fdust_g_m2_yr = basalt_g_m2 / dust_duration_yr if dust_duration_yr else 0.0
    particle_radius_m = max(as_float(amendment.get("basalt_d50_um"), 50.0) * 1.0e-6 / 2.0, 1.0e-7)

    # Keep the first adapter run short unless explicitly overridden; full
    # production runs can take much longer than notebook users expect.
    config_years = as_float(simulation.get("years"), 10.0)
    ttot = years if years is not None else config_years

    output_dir.mkdir(parents=True, exist_ok=True)
    scepter_data = scepter_root / "data"
    dust_file = scepter_data / "dust_basalt.in"
    secondaries_file = scepter_data / "2ndslds_def.in"

    sld_list = ["inrt", "g2"]
    srcfile_dust = None
    if fdust_g_m2_yr > 0:
        # dust_basalt.in defines the basalt composition; include common oxide
        # phase labels used by SCEPTER's basalt helper scripts.
        sld_list.extend(["cao", "mgo", "na2o", "k2o"])
        srcfile_dust = str(dust_file) if dust_file.exists() else None

    make_inputs.get_input_frame(
        outdir=outdir,
        runname=runname,
        ztot=depth_m,
        nz=30,
        ttot=ttot,
        temp=temperature_c,
        fdust=fdust_g_m2_yr,
        fdust2=0,
        taudust=dust_duration_yr,
        omrain=900,
        zom=min(0.25, depth_m),
        poro=porosity,
        moistsrf=0.5,
        zwater=1000,
        zdust=min(0.25, depth_m),
        w=1.0e-5,
        q=runoff_m_yr,
        p=particle_radius_m,
        nstep=nstep,
        rstrt="self",
        runid=run_id,
    )
    make_inputs.get_input_switches(
        outdir=outdir,
        runname=runname,
        w_scheme=0,
        mix_scheme=0,
        poro_iter="true",
        sldmin_lim="true",
        display=1,
        report=0,
        restart="false",
        rough="true",
        act_ON="true",
        dt_fix="false",
        cec_on="true",
        dz_fix="true",
        close_aq="false",
        poro_evol="true",
        sa_evol_1="true",
        sa_evol_2="false",
        psd_bulk="true",
        psd_full="true",
        season="false",
    )
    make_inputs.get_input_tracers(
        outdir=outdir,
        runname=runname,
        sld_list=sld_list,
        aq_list=["ca", "k", "mg", "na"],
        gas_list=["pco2"],
        exrxn_list=[],
    )
    make_inputs.get_input_tracer_bounds(
        outdir=outdir,
        runname=runname,
        pr_list=[("inrt", 1.0)],
        rain_list=[("ca", 5.0e-6)],
        atm_list=[("pco2", 4.2e-4), ("po2", 0.21), ("pnh3", 1.0e-50), ("pn2o", 1.0e-50)],
    )

    cec_params = ("inrt", cec, 5.9, 4.8, 10.47, 10.786, 16.47, 3.4)
    make_inputs.get_input_sld_properties(outdir=outdir, runname=runname, filename="psdpr.in", sld_varlist=[])
    make_inputs.get_input_sld_properties(
        outdir=outdir,
        runname=runname,
        filename="dust.in",
        srcfile=srcfile_dust,
        sld_varlist=[] if srcfile_dust else [],
    )
    make_inputs.get_input_sld_properties(outdir=outdir, runname=runname, filename="cec.in", sld_varlist=[cec_params])
    make_inputs.get_input_sld_properties(outdir=outdir, runname=runname, filename="OM_rain.in", sld_varlist=[("g2", 1.0)])
    make_inputs.get_input_sld_properties(outdir=outdir, runname=runname, filename="kinspc.in", sld_varlist=[])
    make_inputs.get_input_sld_properties(outdir=outdir, runname=runname, filename="keqspc.in", sld_varlist=[])
    make_inputs.get_input_sld_properties(outdir=outdir, runname=runname, filename="sa.in", sld_varlist=[])
    make_inputs.get_input_sld_properties(outdir=outdir, runname=runname, filename="nopsd.in", sld_varlist=[])
    make_inputs.get_input_sld_properties(
        outdir=outdir,
        runname=runname,
        filename="2ndslds.in",
        srcfile=str(secondaries_file) if secondaries_file.exists() else None,
        sld_varlist=[],
    )

    return {
        "run_id": run_id,
        "ttot_years": ttot,
        "fdust_g_m2_yr": fdust_g_m2_yr,
        "taudust_years": dust_duration_yr,
        "q_m_yr": runoff_m_yr,
        "porosity": porosity,
        "particle_radius_m": particle_radius_m,
        "adapter_note": "short smoke-test run" if years != config_years else "configured simulation years",
    }


def run_scepter(executable: Path, output_dir: Path, timeout_seconds: int | None) -> subprocess.CompletedProcess[str]:
    run_exe = output_dir / "scepter"
    shutil.copy2(executable, run_exe)
    run_exe.chmod(0o755)
    return subprocess.run(
        ["./scepter"],
        cwd=output_dir,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )


def final_flux_row(path: Path) -> dict[str, float]:
    if not path.exists():
        return {}

    header: list[str] | None = None
    last_values: list[float] | None = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split()
        if not parts:
            continue
        try:
            values = [float(part) for part in parts]
        except ValueError:
            header = parts
            continue
        last_values = values

    if not header or not last_values:
        return {}
    return {name: value for name, value in zip(header, last_values)}


def extract_flux_metrics(output_dir: Path, config: dict) -> dict[str, float]:
    metrics: dict[str, float] = {}
    flx_dir = output_dir / "flx"
    for species in ["DIC", "ALK", "hco3", "co3", "co2aq", "co2g"]:
        row = final_flux_row(flx_dir / f"int_flx_co2sp-{species}.txt")
        for column, value in row.items():
            metrics[f"scepter_final_int_{species}_{column}"] = value

    # SCEPTER's integrated flux files are area-normalized. Keep the raw model
    # values above, and provide a clearly named CO2-equivalent helper for MRV QA.
    dic_tflx = metrics.get("scepter_final_int_DIC_tflx")
    area_ha = as_float(config.get("site", {}).get("area_ha"), 0.0)
    if dic_tflx is not None and area_ha > 0:
        area_m2 = area_ha * 10_000.0
        metrics["dic_flux_co2_equivalent_t"] = dic_tflx * 44.0095 * area_m2 / 1_000_000.0
        metrics["dic_flux_carbon_equivalent_t"] = dic_tflx * 12.011 * area_m2 / 1_000_000.0

    return metrics


def write_summary(output_dir: Path, config: dict, native: dict, completed: subprocess.CompletedProcess[str], elapsed: float) -> Path:
    run_id = str(config["run_id"])
    summary_path = output_dir / f"{run_id}_summary.csv"
    stdout_path = output_dir / "scepter_stdout.log"
    stderr_path = output_dir / "scepter_stderr.log"
    stdout_path.write_text(completed.stdout or "", encoding="utf-8")
    stderr_path.write_text(completed.stderr or "", encoding="utf-8")

    if completed.returncode == 0:
        adapter_status = "complete"
    elif completed.returncode == 124:
        adapter_status = "timeout"
    else:
        adapter_status = "failed"

    rows = {
        "run_id": run_id,
        "model_unit_id": config.get("model_unit_id", ""),
        "scenario_id": config.get("scenario_id", ""),
        "adapter_status": adapter_status,
        "return_code": completed.returncode,
        "elapsed_seconds": elapsed,
        "stdout_log": str(stdout_path),
        "stderr_log": str(stderr_path),
        **native,
        **extract_flux_metrics(output_dir, config),
    }
    header = ",".join(rows.keys())
    values = ",".join(json.dumps(value) if isinstance(value, str) else str(value) for value in rows.values())
    summary_path.write_text(header + "\n" + values + "\n", encoding="utf-8")
    return summary_path


def remove_native_outputs(output_dir: Path) -> None:
    """Drop bulky SCEPTER-native outputs after summary metrics are extracted."""
    keep_names = {
        "scepter_stdout.log",
        "scepter_stderr.log",
        f"{output_dir.name}_summary.csv",
    }
    for child in output_dir.iterdir():
        if child.name in keep_names:
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    scepter_root = (args.scepter_root or default_scepter_root()).resolve()
    executable = (args.executable or scepter_root / "scepter").resolve()
    if not executable.exists():
        raise FileNotFoundError(f"Compiled SCEPTER executable not found: {executable}")

    add_scepter_python_path(scepter_root)
    reset_output_dir(args.output_dir)

    years = args.production_years if args.production_years is not None else args.smoke_test_years
    native = build_native_inputs(config, args.output_dir, scepter_root, years=years, nstep=args.nstep)

    started = time.time()
    try:
        completed = run_scepter(executable, args.output_dir, args.timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        completed = subprocess.CompletedProcess(
            args=exc.cmd,
            returncode=124,
            stdout=as_text(exc.stdout),
            stderr=(as_text(exc.stderr) + "\nSCEPTER adapter timed out.").strip(),
        )
        summary_path = write_summary(args.output_dir, config, native, completed, time.time() - started)
        if not args.keep_native_outputs:
            remove_native_outputs(args.output_dir)
        print(f"Wrote SCEPTER adapter timeout summary: {summary_path}")
        return 124

    summary_path = write_summary(args.output_dir, config, native, completed, time.time() - started)
    if not args.keep_native_outputs:
        remove_native_outputs(args.output_dir)
    print(f"Wrote SCEPTER adapter summary: {summary_path}")
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
