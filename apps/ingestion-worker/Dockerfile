FROM python:3.12-slim

WORKDIR /build
COPY apps/shared-lib ./shared-lib
RUN pip install --no-cache-dir ./shared-lib

WORKDIR /app
COPY apps/ingestion-worker/pyproject.toml ./pyproject.toml
COPY apps/ingestion-worker/ingestion_worker_app ./ingestion_worker_app
RUN pip install --no-cache-dir .

CMD ["python", "-m", "ingestion_worker_app.worker"]
