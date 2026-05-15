# criminal-db — API + TUI image (embed + PDF + sqlite-vec)
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    CRIMINAL_DB_DATA_DIR=/data \
    CRIMINAL_DB_DB_DIR=/db \
    CRIMINAL_DB_MODELS_DIR=/models \
    CRIMINAL_DB_API_HOST=0.0.0.0 \
    CRIMINAL_DB_API_PORT=8765

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE ./
COPY criminal_db ./criminal_db

RUN pip install --upgrade pip \
    && pip install -e ".[embed,pdf,tui]"

RUN mkdir -p /data /db /models

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

VOLUME ["/data", "/db", "/models"]

EXPOSE 8765 8080

ENTRYPOINT ["docker-entrypoint.sh"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD curl -sf "http://127.0.0.1:8765/health" || exit 1

CMD ["criminal-db", "serve", "--host", "0.0.0.0", "--port", "8765"]
