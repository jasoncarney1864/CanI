FROM python:3.12-slim

# WeasyPrint's native deps (legal-draft PDF rendering, Sprint 4 Task 5). Package names
# verified against this exact base image — libgdk-pixbuf2.0-0 (the name in most WeasyPrint
# install docs) doesn't exist on Debian trixie; it's libgdk-pixbuf-2.0-0 here.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 libcairo2 \
    libffi-dev shared-mime-info fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 appuser

WORKDIR /build
COPY apps/shared-lib ./shared-lib
RUN pip install --no-cache-dir ./shared-lib

WORKDIR /app
COPY apps/docs-api/pyproject.toml ./pyproject.toml
COPY apps/docs-api/docs_api_app ./docs_api_app
RUN pip install --no-cache-dir .

RUN chown -R appuser:appuser /build /app
USER 10001

EXPOSE 8002
CMD ["uvicorn", "docs_api_app.main:app", "--host", "0.0.0.0", "--port", "8002"]
