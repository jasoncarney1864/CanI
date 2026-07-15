FROM python:3.12-slim

RUN useradd --create-home --uid 10001 appuser

WORKDIR /build
COPY apps/shared-lib ./shared-lib
RUN pip install --no-cache-dir ./shared-lib

WORKDIR /app
COPY apps/ingestion-worker/pyproject.toml ./pyproject.toml
COPY apps/ingestion-worker/ingestion_worker_app ./ingestion_worker_app
RUN pip install --no-cache-dir .

RUN chown -R appuser:appuser /build /app
USER 10001

CMD ["python", "-m", "ingestion_worker_app.worker"]
