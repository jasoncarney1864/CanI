FROM python:3.12-slim

WORKDIR /app
RUN pip install --no-cache-dir "psycopg[binary]>=3.1"

COPY db/migrate.py ./migrate.py
COPY db/migrations ./migrations

CMD ["python", "migrate.py"]
