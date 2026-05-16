# criminal-db — API container with embed + PDF + TUI extras preinstalled.
# Corpus HTML and SQLite files are NOT bundled; mount host data/ and db/.

FROM python:3.12-slim AS builder

WORKDIR /build
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY criminal_db ./criminal_db

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir ".[embed,pdf,tui]"

FROM python:3.12-slim AS runtime

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 appuser

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY pyproject.toml README.md ./
COPY criminal_db ./criminal_db
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN pip install --no-cache-dir --no-deps -e . \
    && chmod +x /usr/local/bin/docker-entrypoint.sh \
    && mkdir -p /app/data /app/db /app/models \
    && chown -R appuser:appuser /app

USER appuser

ENV PYTHONUNBUFFERED=1 \
    CRIMINAL_DB_API_HOST=0.0.0.0 \
    CRIMINAL_DB_API_PORT=8765

EXPOSE 8765

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["criminal-db", "serve"]
