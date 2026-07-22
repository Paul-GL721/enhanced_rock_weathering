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

Notebook `05_run_scepter_scenarios.ipynb` is configured to run an external SCEPTER executable:

```text
python scripts/run_scepter_adapter.py --config {config_path} --output-dir {output_dir}
```

The upstream model source is available from [cdr-laboratory/SCEPTER](https://github.com/cdr-laboratory/SCEPTER). Build and test it locally first. Notebook `05` calls `scripts/run_scepter_adapter.py`, which converts the staged JSON config into native SCEPTER input files, runs the compiled binary, and writes a one-row summary CSV for notebooks `06` and `07`.

Suggested local flow:

```bash
cd erw_spatial_mrv
mkdir -p external
git clone https://github.com/cdr-laboratory/SCEPTER.git external/SCEPTER
cd external/SCEPTER
```

When using the Conda environment on macOS, `gfortran_osx-64` usually installs the compiler as a prefixed executable rather than plain `gfortran`. Check it with:

```bash
ls "$CONDA_PREFIX/bin/"*gfortran*
```

Then build SCEPTER by overriding the makefile compiler and stale makefile variables. The default upstream makefile enables AMD benchmark flags that can force hard-coded `/storage/...` paths, so the command below also overrides `CPFLAGS`.

```bash
export CONDA_ENV="$CONDA_PREFIX"
export PATH="$CONDA_ENV/bin:$PATH"

make --file=makefile clean \
  FC="$CONDA_ENV/bin/x86_64-apple-darwin13.4.0-gfortran" \
  PROGRAM=scepter \
  OBJS=scepter.o \
  SRC=scepter.f90

make --file=makefile \
  FC="$CONDA_ENV/bin/x86_64-apple-darwin13.4.0-gfortran" \
  PROGRAM=scepter \
  OBJS=scepter.o \
  SRC=scepter.f90 \
  CPFLAGS="-Dksld_chk -Dmod_basalt_cmp -Dnrec_prof_in=200" \
  INC="-I$(pwd)/data" \
  LDFLAGS="-L$CONDA_ENV/lib" \
  LIBS="-lopenblas"
```

If `make` fails with a missing source file such as `scepter_PREV_STRCT_DEV_H_part_SAVE_ATTEMPT_IS_CLEAN.f90`, the local makefile is pointing at a stale development filename. The upstream repository source file is `scepter.f90`. Check the makefile:

```bash
grep -n "SRC\\|OBJS\\|PROGRAM" makefile
```

It should point to:

```make
OBJS = scepter.o
SRC = scepter.f90
PROGRAM = scepter
```

If it does not, either edit those three lines or reclone a clean copy of the repository.

You can also override the stale makefile variables without editing the upstream file. Keep the `CPFLAGS` override to avoid the AMD benchmark build:

```bash
export CONDA_ENV="$CONDA_PREFIX"
export PATH="$CONDA_ENV/bin:$PATH"

make --file=makefile clean \
  FC="$CONDA_ENV/bin/x86_64-apple-darwin13.4.0-gfortran" \
  PROGRAM=scepter \
  OBJS=scepter.o \
  SRC=scepter.f90

make --file=makefile \
  FC="$CONDA_ENV/bin/x86_64-apple-darwin13.4.0-gfortran" \
  PROGRAM=scepter \
  OBJS=scepter.o \
  SRC=scepter.f90 \
  CPFLAGS="-Dksld_chk -Dmod_basalt_cmp -Dnrec_prof_in=200" \
  INC="-I$(pwd)/data" \
  LDFLAGS="-L$CONDA_ENV/lib" \
  LIBS="-lopenblas"
```

After that, confirm the expected executable exists:

```bash
ls -lh scepter
```

If your local build creates a binary somewhere else, set the path before running notebook `05`:

```bash
export SCEPTER_EXECUTABLE=/absolute/path/to/SCEPTER/scepter
```

Copy or sync the staged inputs from Drive into the local ignored `data/` folder before local testing:

```text
data/scepter_runs/inputs/
data/processed/soil/hwsd2/
data/processed/climate/rainfall/
data/processed/landcover/
```

For local smoke testing, notebook `05` defaults to one staged run (`MAX_TEST_RUNS = 1`) and the adapter defaults to a very short SCEPTER horizon. For production-scale execution, pass `--production-years` through the adapter command template or run the adapter directly with a longer timeout.

Notebook `06_extract_scepter_outputs.ipynb` can only compute CO2 removal or carbon-retention summaries if the SCEPTER result files include those metrics. If it reports no CO2/carbon metric, the extraction worked but the model summaries do not yet contain the expected result columns.

## Running SCEPTER In Docker

Use Docker for long production runs on EC2. The image builds a Linux Conda environment, compiles SCEPTER inside the image, and can run the full sequence from model-unit preparation through notebooks `05`, `06`, and `07`.

The Docker build expects the required notebooks, source code, processed inputs, and staged SCEPTER run configs to be present in the build context. It does not need raw ESA/HWSD2/HWSD downloads once the processed cropland, rainfall, and soil inputs have already been created.

### Sync Required Files To EC2

The examples below assume an EC2 instance with the EBS/NVMe volume mounted at:

```text
/scepter
```

From the parent folder that contains `erw_spatial_mrv`, create the destination:

```bash
ssh -i ~/.ssh/gls_ash_system.pem \
  ubuntu@ec2-54-228-60-184.eu-west-1.compute.amazonaws.com \
  "mkdir -p /scepter/erw_spatial_mrv"
```

Sync only the required project files:

```bash
rsync -avz --progress \
  -e "ssh -i ~/.ssh/gls_ash_system.pem" \
  --include="Dockerfile" \
  --include=".dockerignore" \
  --include="environment.yml" \
  --include="README.md" \
  --include="config/***" \
  --include="src/***" \
  --include="scripts/***" \
  --include="notebooks/***" \
  --include="external/***" \
  --include="data/" \
  --include="data/processed/***" \
  --include="data/scepter_runs/" \
  --include="data/scepter_runs/inputs/***" \
  --include="data/scepter_runs/runs/***" \
  --exclude="data/raw/***" \
  --exclude="data/outputs/***" \
  --exclude="data/scepter_runs/outputs/***" \
  --exclude="data/scepter_runs/logs/***" \
  --exclude="**/.DS_Store" \
  --exclude="**/.ipynb_checkpoints/***" \
  --exclude="**/__pycache__/***" \
  --exclude="*" \
  erw_spatial_mrv/ \
  ubuntu@ec2-54-228-60-184.eu-west-1.compute.amazonaws.com:/scepter/erw_spatial_mrv/
```

### Build The Image

On EC2:

```bash
cd /scepter/erw_spatial_mrv
docker build -t paulgl721/erw:scepter-production .
```

The Dockerfile removes the macOS-only `gfortran_osx-64` dependency from `environment.yml`, uses `mamba` for faster environment solving, installs Linux BLAS/LAPACK packages, and compiles `external/SCEPTER/scepter` with:

```bash
gfortran ... -llapack -lblas
```

If you want to publish the image to Docker Hub:

```bash
docker login -u paulgl721
docker push paulgl721/erw:scepter-production
```

### Build Model Units

Before running SCEPTER, rebuild the model-unit inputs from notebook `04`. This step uses the ESA cropland mask, rainfall rasters, and soil map to create:

```text
data/scepter_runs/inputs/scepter_model_units.csv
data/scepter_runs/inputs/scepter_scenarios.csv
data/scepter_runs/inputs/scepter_runs.csv
```

Create the mounted input/output folders:

```bash
mkdir -p \
  /scepter/erw_spatial_mrv/data/processed \
  /scepter/erw_spatial_mrv/data/scepter_runs/inputs \
  /scepter/erw_spatial_mrv/data/scepter_runs/outputs \
  /scepter/erw_spatial_mrv/data/scepter_runs/logs \
  /scepter/erw_spatial_mrv/data/outputs
```

Run notebook `04` inside the container. By default `ERW_MAX_MODEL_UNITS=all` builds every available cropland model unit. Set it to a number such as `100` or `500` only when you want a smaller test run.

```bash
docker run --rm \
  --name erw-prepare-scepter-inputs \
  -e ERW_MAX_MODEL_UNITS=all \
  -v /scepter/erw_spatial_mrv/data/processed:/workspace/erw_spatial_mrv/data/processed \
  -v /scepter/erw_spatial_mrv/data/scepter_runs/inputs:/workspace/erw_spatial_mrv/data/scepter_runs/inputs \
  paulgl721/erw:scepter-production \
  /opt/conda/envs/erw_spatial_mrv/bin/jupyter nbconvert \
    --to notebook \
    --execute \
    --inplace \
    notebooks/04_test_scepter_inputs.ipynb \
    --ExecutePreprocessor.timeout=7200
```

Check the run count before launching the batch:

```bash
wc -l /scepter/erw_spatial_mrv/data/scepter_runs/inputs/scepter_model_units.csv
wc -l /scepter/erw_spatial_mrv/data/scepter_runs/inputs/scepter_runs.csv
```

The expected number of completed summary files is the number of rows in `scepter_runs.csv` minus the header row.

### Run A Year-Specific SCEPTER Batch

Create persistent output folders on the mounted volume:

```bash
mkdir -p \
  /scepter/erw_spatial_mrv/data/scepter_runs/outputs \
  /scepter/erw_spatial_mrv/data/scepter_runs/logs \
  /scepter/erw_spatial_mrv/data/outputs
```

Each production run should use a year-specific label. The runner writes SCEPTER summaries to `data/scepter_runs/outputs/<label>/`, spatial outputs to `data/outputs/<label>/`, and executed notebooks to `data/outputs/<label>/executed_notebooks/`.

For a 1-year run:

```bash
docker rm -f erw-scepter-1yr 2>/dev/null || true

docker run -d \
  --name erw-scepter-1yr \
  -e ERW_SCEPTER_PRODUCTION_YEARS=1 \
  -e ERW_SCEPTER_RUN_LABEL=yr_1 \
  -v /scepter/erw_spatial_mrv/data/scepter_runs/inputs:/workspace/erw_spatial_mrv/data/scepter_runs/inputs \
  -v /scepter/erw_spatial_mrv/data/scepter_runs/runs:/workspace/erw_spatial_mrv/data/scepter_runs/runs \
  -v /scepter/erw_spatial_mrv/data/scepter_runs/outputs:/workspace/erw_spatial_mrv/data/scepter_runs/outputs \
  -v /scepter/erw_spatial_mrv/data/scepter_runs/logs:/workspace/erw_spatial_mrv/data/scepter_runs/logs \
  -v /scepter/erw_spatial_mrv/data/outputs:/workspace/erw_spatial_mrv/data/outputs \
  paulgl721/erw:scepter-production
```

For a 10-year run:

```bash
docker rm -f erw-scepter-10yr 2>/dev/null || true

docker run -d \
  --name erw-scepter-10yr \
  -e ERW_SCEPTER_PRODUCTION_YEARS=10 \
  -e ERW_SCEPTER_RUN_LABEL=yr_10 \
  -v /scepter/erw_spatial_mrv/data/scepter_runs/inputs:/workspace/erw_spatial_mrv/data/scepter_runs/inputs \
  -v /scepter/erw_spatial_mrv/data/scepter_runs/runs:/workspace/erw_spatial_mrv/data/scepter_runs/runs \
  -v /scepter/erw_spatial_mrv/data/scepter_runs/outputs:/workspace/erw_spatial_mrv/data/scepter_runs/outputs \
  -v /scepter/erw_spatial_mrv/data/scepter_runs/logs:/workspace/erw_spatial_mrv/data/scepter_runs/logs \
  -v /scepter/erw_spatial_mrv/data/outputs:/workspace/erw_spatial_mrv/data/outputs \
  paulgl721/erw:scepter-production
```

To run another horizon, change only the container name, `ERW_SCEPTER_PRODUCTION_YEARS`, and `ERW_SCEPTER_RUN_LABEL`. For example, a 5-year run uses `erw-scepter-5yr`, `ERW_SCEPTER_PRODUCTION_YEARS=5`, and `ERW_SCEPTER_RUN_LABEL=yr_5`.

The default container environment is:

```text
ERW_SCEPTER_RUN_MODE=final
ERW_RUN_EXTERNAL_SCEPTER=true
ERW_SCEPTER_PRODUCTION_YEARS=5
ERW_SCEPTER_RUN_LABEL=yr_5
ERW_SCEPTER_TIMEOUT_SECONDS=21600
RUN_DOWNSTREAM_NOTEBOOKS=true
```

After the run finishes, pull year-specific outputs and executed notebooks back to the local project from your Mac:

```bash
rsync -avz --progress \
  -e "ssh -i ~/.ssh/gls_ash_system.pem" \
  ubuntu@ec2-54-228-60-184.eu-west-1.compute.amazonaws.com:/scepter/erw_spatial_mrv/data/scepter_runs/outputs/yr_1/ \
  erw_spatial_mrv/data/scepter_runs/outputs/yr_1/

rsync -avz --progress \
  -e "ssh -i ~/.ssh/gls_ash_system.pem" \
  ubuntu@ec2-54-228-60-184.eu-west-1.compute.amazonaws.com:/scepter/erw_spatial_mrv/data/outputs/yr_1/ \
  erw_spatial_mrv/data/outputs/yr_1/
```

Replace `yr_1` with `yr_5`, `yr_10`, or the label you used. Then open the copied notebooks locally from:

```text
erw_spatial_mrv/data/outputs/yr_1/executed_notebooks/
```

### Monitor Progress

Check whether the container is running:

```bash
docker ps
```

If it is not listed, inspect exited containers and logs:

```bash
docker ps -a | grep erw
docker logs erw-scepter-1yr
```

Follow logs:

```bash
docker logs -f erw-scepter-1yr
```

Count completed SCEPTER summaries:

```bash
find /scepter/erw_spatial_mrv/data/scepter_runs/outputs/yr_1 \
  -mindepth 2 -maxdepth 2 \
  -name '*_summary.csv' | wc -l
```

Compare that count to `wc -l data/scepter_runs/inputs/scepter_runs.csv` minus one header row.

Check disk use:

```bash
df -h /scepter
du -sh /scepter/erw_spatial_mrv/data/scepter_runs/outputs/yr_1
```

Stop or resume:

```bash
docker stop erw-scepter-1yr
docker start erw-scepter-1yr
docker logs -f erw-scepter-1yr
```

To rerun one label from a clean state:

```bash
docker rm -f erw-scepter-1yr
rm -rf /scepter/erw_spatial_mrv/data/scepter_runs/outputs/yr_1
rm -rf /scepter/erw_spatial_mrv/data/outputs/yr_1
```

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
