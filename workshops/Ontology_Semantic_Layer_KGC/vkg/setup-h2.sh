#!/bin/bash
# Initialize the H2 database from SQL into a separate dir (not the mounted volume)
DB_DIR="/opt/ontop/db"
DB_FILE="${DB_DIR}/insurance.mv.db"
SQL_FILE="/opt/ontop/input/insurance.sql"

mkdir -p "$DB_DIR"

if [ ! -f "$DB_FILE" ]; then
  echo "Initializing H2 database from $SQL_FILE ..."
  java -cp "/opt/ontop/jdbc/*:/opt/ontop/lib/*" org.h2.tools.RunScript \
    -url "jdbc:h2:${DB_DIR}/insurance" \
    -user sa -password "" \
    -script "$SQL_FILE"
  echo "H2 database initialized at ${DB_FILE}"
else
  echo "H2 database already exists, skipping init."
fi

# Run Ontop with all remaining arguments
exec /opt/ontop/ontop "$@"
