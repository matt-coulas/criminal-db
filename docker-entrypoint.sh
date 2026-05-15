#!/bin/sh
set -e
# First-run layout when volumes are empty
if [ ! -f "${CRIMINAL_DB_DB_DIR:-/db}/fulltext.db" ]; then
  echo "criminal-db: initializing databases under ${CRIMINAL_DB_DB_DIR:-/db} ..."
  criminal-db init
fi
exec "$@"
