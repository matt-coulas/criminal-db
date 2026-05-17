#!/bin/sh
set -e

# Initialise empty db/ on first run when using mounted volumes.
if [ ! -f /app/db/criminal.db ]; then
  echo "entrypoint: running criminal-db init (missing case database)"
  criminal-db init
fi

exec "$@"
