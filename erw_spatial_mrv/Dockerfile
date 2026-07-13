FROM continuumio/miniconda3:24.5.0-0

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ENV DEBIAN_FRONTEND=noninteractive
ENV PROJECT_DIR=/workspace/erw_spatial_mrv

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    gfortran \
    make \
    screen \
    && rm -rf /var/lib/apt/lists/*

WORKDIR ${PROJECT_DIR}

COPY environment.yml /tmp/environment.yml
RUN grep -v "gfortran_osx-64" /tmp/environment.yml > /tmp/environment-linux.yml \
    && conda env create -f /tmp/environment-linux.yml \
    && conda clean -afy

COPY . ${PROJECT_DIR}

ARG BASALT_DEFINES=basalt_defines_BLACK.h
RUN test -f "external/SCEPTER/data/${BASALT_DEFINES}" \
    && cp "external/SCEPTER/data/${BASALT_DEFINES}" external/SCEPTER/basalt_defines.h \
    && gfortran -cpp -O2 -ffree-line-length-none -Iexternal/SCEPTER -Iexternal/SCEPTER/data \
        -o external/SCEPTER/scepter external/SCEPTER/scepter.f90 \
    && chmod +x external/SCEPTER/scepter \
    && mkdir -p data/scepter_runs/outputs data/scepter_runs/logs data/outputs

ENV ERW_SCEPTER_RUN_MODE=final
ENV ERW_RUN_EXTERNAL_SCEPTER=true
ENV ERW_SCEPTER_PRODUCTION_YEARS=10
ENV ERW_SCEPTER_TIMEOUT_SECONDS=21600
ENV RUN_DOWNSTREAM_NOTEBOOKS=true

CMD ["bash", "scripts/run_scepter_10yr.sh"]
