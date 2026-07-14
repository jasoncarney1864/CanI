FROM python:3.12-slim

WORKDIR /build
COPY apps/shared-lib ./shared-lib
RUN pip install --no-cache-dir ./shared-lib

WORKDIR /app
COPY apps/hub-api/pyproject.toml ./pyproject.toml
COPY apps/hub-api/hub_api_app ./hub_api_app
RUN pip install --no-cache-dir .

EXPOSE 8001
CMD ["uvicorn", "hub_api_app.main:app", "--host", "0.0.0.0", "--port", "8001"]
