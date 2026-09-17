#!/usr/bin/env bash
# Regenerate db/schema.current.sql from a migrated database, so the committed schema cannot
# drift from what the migrations actually build.
set -euo pipefail
: "${PGPORT:=55432}"
: "${PGDATABASE:=vaanios}"
OUT="$(git rev-parse --show-toplevel)/db/schema.current.sql"
{
  cat <<'HDR'
-- GENERATED FILE — do not edit.
--
-- Dumped from a database built by `alembic upgrade head`, so this is the schema that actually
-- exists today. Regenerate with: scripts/dump_schema.sh
--
-- For the full *designed* schema, including the RAG, memory, quiz and evaluation tables that
-- later phases will add, see db/schema.sql.

HDR
  su postgres -c "pg_dump -h /tmp -p $PGPORT -d $PGDATABASE --schema-only --no-owner --no-privileges --no-comments" \
    | grep -v '^--' | grep -v '^SET ' | grep -v '^SELECT pg_catalog' \
    | grep -v '^\\restrict' | grep -v '^\\unrestrict' | cat -s
} > "$OUT"
echo "wrote $OUT"
