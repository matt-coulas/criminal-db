#!/bin/sh
set -e

# Initialise empty db/ on first run when using mounted volumes.
if [ ! -f /app/db/fulltext.db ] || [ ! -f /app/db/headnotes.db ]; then
  echo "entrypoint: running criminal-db init (missing database files)"
  criminal-db init
fi

exec "$@"
