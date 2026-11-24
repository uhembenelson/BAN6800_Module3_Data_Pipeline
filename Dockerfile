# BAN6800 Module 3 - reproducible pipeline image.
# Build:  docker build -t ban6800-module3-pipeline .
# Run:    docker run --rm -e PIPELINE_HASH_SALT=... -v "$PWD/artifacts:/app/artifacts" ban6800-module3-pipeline

FROM python:3.11-slim AS base

LABEL org.opencontainers.image.title="BAN6800 Module 3 - UK bank customer data pipeline" \
      org.opencontainers.image.description="Ingestion, anonymisation, cleaning, validation, bias audit and lineage for the UK bank customer profile dataset" \
      org.opencontainers.image.version="1.0.0" \
      org.opencontainers.image.authors="Okonkwo Jude Samson"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MPLCONFIGDIR=/tmp/matplotlib \
    PYTHONPATH=/app

WORKDIR /app

# Dependencies first so application changes do not invalidate the layer cache.
COPY requirements.txt ./
RUN python -m pip install --upgrade pip && \
    python -m pip install -r requirements.txt

# Application code, configuration, reference data and the raw extract.
COPY config ./config
COPY src ./src
COPY flows ./flows
COPY reference ./reference
COPY tests ./tests
COPY data/raw ./data/raw

RUN mkdir -p data/interim data/processed artifacts/figures && \
    useradd --create-home --uid 10001 pipeline && \
    chown -R pipeline:pipeline /app

USER pipeline

# Smoke test: the image must be able to import the DAG and the suite.
RUN python -c "import src.pipeline, src.validation_gx, src.bias_suite; print('imports ok')"

# A run is complete only when the gold dataset and the gate-B report exist.
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import pathlib,sys; sys.exit(0 if pathlib.Path('artifacts/run_manifest.json').exists() else 1)"

ENTRYPOINT ["python", "-m", "flows.local_runner"]
