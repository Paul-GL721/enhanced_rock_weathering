# ERW Spatial MRV

This project builds a notebook-first spatial MRV workflow for enhanced rock weathering in the maize belt of Uganda. It prepares an AOI, cropland mask, rainfall and soil inputs, stages SCEPTER model runs, executes/extracts model outputs, and creates spatial reporting products.

The workflow is designed to run locally or through the Google Colab extension. For Colab, keep the full project synced to google drive:

```text
/content/drive/MyDrive/erw_spatial_mrv
```

That Drive folder should include both the code and data:

```text
erw_spatial_mrv/
  notebooks/
  src/erw_mrv/
  data/
    raw/
    processed/
    scepter_runs/
    outputs/
```

`data/` is ignored by git, so it can be large and Drive-backed without being committed.

## Data Layout

Place or sync raw data under `data/raw`:

```text
data/raw/boundaries/uga_admin_boundaries.shp/uga_admin2.shp
data/raw/soilgrids/
```

The soil folder may contain HWSD2 zip files. Notebook `03b_prepare_hwsd_soil_inputs.ipynb` can extract the raster zip containing `HWSD2.bil` and the database zip containing `HWSD2.mdb`.

Generated products are written under:

```text
data/processed/
data/scepter_runs/
data/outputs/
```

## Running In Colab

Open notebooks from the synced Drive project. The setup cells mount Drive and point imports/data paths at:

```text
/content/drive/MyDrive/erw_spatial_mrv
```

If imports fail with `No module named 'erw_mrv'`, confirm this folder exists in Drive:

```text
/content/drive/MyDrive/erw_spatial_mrv/src/erw_mrv
```

If data files are missing, confirm the Drive copy contains the same `data/raw/...` structure as the local project.

## Notebook Order

Run the notebooks in this order.

| Notebook | Purpose | Main outputs |
| --- | --- | --- |
| `01_explore_boundaries.ipynb` | Select and dissolve the Uganda AOI districts. | `data/processed/boundaries/selected_districts_aoi.geojson`, `.gpkg` |
| `1.1_download_raster_img.ipynb` | Download Landsat/STAC imagery clips and mosaics. | Landsat rasters under `data/processed` |
| `02_explore_cropland_mask.ipynb` | Build the cropland mask. | `data/processed/landcover/cropland_pixels_jan_jun_2026_paper_adapted.tif` |
| `03_validate_cropland_outputs.ipynb` | Validate cropland outputs and QA summaries. | QA tables/plots |
| `03a_prepare_monthly_rainfall.ipynb` | Download and clip CHIRPS monthly rainfall from the DE Africa S3 bucket. | Monthly rainfall CSV and TIFFs |
| `03b_prepare_hwsd_soil_inputs.ipynb` | Extract HWSD2 soil raster and attributes for the AOI. | Soil GeoTIFF, GeoJSON/GPKG, SCEPTER soil defaults CSV |
| `04_test_scepter_inputs.ipynb` | Stage real SCEPTER input tables from cropland, rainfall, and soil data. | `data/scepter_runs/inputs/*` |
| `05_run_scepter_scenarios.ipynb` | Run SCEPTER scenarios when the SCEPTER executable is available. | `data/scepter_runs/outputs/*` |
| `06_extract_scepter_outputs.ipynb` | Extract model result summaries and additionality metrics. | Long results, summaries, additionality CSV |
| `07_spatial_mrv_maps_reports.ipynb` | Create spatial MRV maps, tables, and report text. | PNG maps, GPKG, CSV tables, markdown report |
| `08_uncertainty_sensitivity_analysis.ipynb` | Explore uncertainty and sensitivity once result metrics exist. | Uncertainty tables/figures |

## Key Results

Useful GeoTIFF outputs include:

```text
data/processed/landcover/cropland_pixels_jan_jun_2026_paper_adapted.tif
data/processed/climate/rainfall/rasters/chirps_rainfall_YYYY_MM.tif
data/processed/soil/hwsd2/hwsd2_aoi_mapping_units.tif
```

Spatial report outputs are written to:

```text
data/outputs/maps/spatial_mrv/
data/outputs/figures/spatial_mrv/
data/outputs/tables/spatial_mrv/
data/outputs/reports/spatial_mrv/
```

Notebook `07_spatial_mrv_maps_reports.ipynb` writes PNG maps where possible, including carbon-retained maps if SCEPTER output summaries contain a carbon-retention metric.

## SCEPTER Notes

Notebook `04_test_scepter_inputs.ipynb` stages inputs only. It does not run the model.

Notebook `05_run_scepter_scenarios.ipynb` is configured to run the external SCEPTER command:

```text
scepter --config {config_path} --output-dir {output_dir}
```

For real model execution, the Colab/runtime environment must have the SCEPTER executable installed and available on `PATH`, or the command template in notebook `05` must be updated to match the installed model command.

Notebook `06_extract_scepter_outputs.ipynb` can only compute CO2 removal or carbon-retention summaries if the SCEPTER result files include those metrics. If it reports no CO2/carbon metric, the extraction worked but the model summaries do not yet contain the expected result columns.

## Troubleshooting

- `ModuleNotFoundError: No module named 'erw_mrv'`: sync the full project to Drive, including `src/erw_mrv`.
- Missing shapefile: confirm `data/raw/boundaries/uga_admin_boundaries.shp/uga_admin2.shp` exists in Drive.
- Missing HWSD2 raster/database: put the HWSD2 zip files or extracted files in `data/raw/soilgrids`.
- Stale or corrupted SCEPTER results: delete `data/scepter_runs` and rerun notebooks `04`, `05`, and `06`.
- Empty additionality table: rerun after SCEPTER produces summaries with CO2 or carbon-retention metrics.
- Recent CHIRPS month missing: notebook `03a` allows partial months, so rerun later when the S3 bucket has the newest month.

## Local Setup

From the project folder:

```bash
cd erw_spatial_mrv
conda env create -f environment.yml
conda activate erw_spatial_mrv
python -m ipykernel install --user --name erw_spatial_mrv
```

Then open notebooks with the `erw_spatial_mrv` kernel.
