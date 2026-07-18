#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/workspace/erw_spatial_mrv}"
cd "${PROJECT_DIR}"

PRODUCTION_YEARS="${ERW_SCEPTER_PRODUCTION_YEARS:-5}"
RUN_LABEL="${ERW_SCEPTER_RUN_LABEL:-yr_${PRODUCTION_YEARS//./p}}"
export ERW_MRV_SCEPTER_OUTPUTS="${ERW_MRV_SCEPTER_OUTPUTS:-${PROJECT_DIR}/data/scepter_runs/outputs/${RUN_LABEL}}"
export ERW_MRV_SCEPTER_RUN_DIR="${ERW_MRV_SCEPTER_RUN_DIR:-${PROJECT_DIR}/data/scepter_runs/runs/${RUN_LABEL}}"
export ERW_MRV_OUTPUTS="${ERW_MRV_OUTPUTS:-${PROJECT_DIR}/data/outputs/${RUN_LABEL}}"

EXECUTED_NOTEBOOK_DIR="${ERW_MRV_OUTPUTS}/executed_notebooks"
mkdir -p \
  "${ERW_MRV_SCEPTER_OUTPUTS}" \
  "${ERW_MRV_SCEPTER_RUN_DIR}" \
  "${PROJECT_DIR}/data/scepter_runs/logs" \
  "${ERW_MRV_OUTPUTS}" \
  "${EXECUTED_NOTEBOOK_DIR}"

export_executed_notebooks() {
  mkdir -p "${EXECUTED_NOTEBOOK_DIR}"
  for notebook in \
    notebooks/05_run_scepter_scenarios.ipynb \
    notebooks/06_extract_scepter_outputs.ipynb \
    notebooks/07_spatial_mrv_maps_reports.ipynb
  do
    if [[ -f "${notebook}" ]]; then
      cp "${notebook}" "${EXECUTED_NOTEBOOK_DIR}/"
    fi
  done
}

trap export_executed_notebooks EXIT

JUPYTER_BIN="${JUPYTER_BIN:-/opt/conda/envs/erw_spatial_mrv/bin/jupyter}"

for required_path in \
  notebooks/05_run_scepter_scenarios.ipynb \
  notebooks/06_extract_scepter_outputs.ipynb \
  notebooks/07_spatial_mrv_maps_reports.ipynb \
  data/scepter_runs/inputs/scepter_runs.csv \
  external/SCEPTER/scepter
do
  if [[ ! -e "${required_path}" ]]; then
    echo "Required path is missing inside the container: ${PROJECT_DIR}/${required_path}" >&2
    echo "Re-sync the project files to EC2 and rebuild the image from /scepter/erw_spatial_mrv." >&2
    exit 2
  fi
done

echo "PROJECT_DIR=${PROJECT_DIR}"
echo "ERW_SCEPTER_RUN_MODE=${ERW_SCEPTER_RUN_MODE:-final}"
echo "ERW_RUN_EXTERNAL_SCEPTER=${ERW_RUN_EXTERNAL_SCEPTER:-true}"
echo "ERW_SCEPTER_PRODUCTION_YEARS=${PRODUCTION_YEARS}"
echo "ERW_SCEPTER_RUN_LABEL=${RUN_LABEL}"
echo "ERW_MRV_SCEPTER_OUTPUTS=${ERW_MRV_SCEPTER_OUTPUTS}"
echo "ERW_MRV_SCEPTER_RUN_DIR=${ERW_MRV_SCEPTER_RUN_DIR}"
echo "ERW_MRV_OUTPUTS=${ERW_MRV_OUTPUTS}"
echo "ERW_SCEPTER_TIMEOUT_SECONDS=${ERW_SCEPTER_TIMEOUT_SECONDS:-21600}"
echo "RUN_DOWNSTREAM_NOTEBOOKS=${RUN_DOWNSTREAM_NOTEBOOKS:-true}"
echo "JUPYTER_BIN=${JUPYTER_BIN}"
echo "EXECUTED_NOTEBOOK_DIR=${EXECUTED_NOTEBOOK_DIR}"
echo "SCEPTER executable:"
ls -lh external/SCEPTER/scepter

"${JUPYTER_BIN}" nbconvert \
  --to notebook \
  --execute \
  --inplace \
  notebooks/05_run_scepter_scenarios.ipynb \
  --ExecutePreprocessor.timeout="${NOTEBOOK05_TIMEOUT_SECONDS:-86400}"

if [[ "${RUN_DOWNSTREAM_NOTEBOOKS:-true}" == "true" ]]; then
  "${JUPYTER_BIN}" nbconvert \
    --to notebook \
    --execute \
    --inplace \
    notebooks/06_extract_scepter_outputs.ipynb \
    --ExecutePreprocessor.timeout="${NOTEBOOK06_TIMEOUT_SECONDS:-900}"

  "${JUPYTER_BIN}" nbconvert \
    --to notebook \
    --execute \
    --inplace \
    notebooks/07_spatial_mrv_maps_reports.ipynb \
    --ExecutePreprocessor.timeout="${NOTEBOOK07_TIMEOUT_SECONDS:-900}"
fi

echo "Completed SCEPTER summaries:"
find "${ERW_MRV_SCEPTER_OUTPUTS}" -mindepth 2 -maxdepth 2 -name '*_summary.csv' | wc -l
echo "Executed notebooks copied to:"
find "${EXECUTED_NOTEBOOK_DIR}" -maxdepth 1 -name '*.ipynb' -print
