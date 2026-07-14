FROM python:3.12-slim

WORKDIR /build
COPY apps/shared-lib ./shared-lib
RUN pip install --no-cache-dir ./shared-lib

WORKDIR /app
COPY apps/retrieval-worker/pyproject.toml ./pyproject.toml
COPY apps/retrieval-worker/retrieval_worker_app ./retrieval_worker_app
RUN pip install --no-cache-dir .

EXPOSE 8003
CMD ["uvicorn", "retrieval_worker_app.main:app", "--host", "0.0.0.0", "--port", "8003"]
