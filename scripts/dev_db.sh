#!/usr/bin/env bash
# Start a throwaway PostgreSQL for local development and tests, without Docker.
#
# Docker Compose is the normal path (infra/compose.yaml); this exists for environments where a
# Docker daemon is unavailable. It does NOT install pgvector, so it is only good up to Phase 4.
set -euo pipefail

PGDATA="${PGDATA:-/var/lib/postgresql/vaanios-dev}"
PGPORT="${PGPORT:-55432}"
PGBIN="${PGBIN:-/usr/lib/postgresql/16/bin}"

case "${1:-start}" in
  start)
    if [ ! -d "$PGDATA/base" ]; then
      su postgres -c "mkdir -p $PGDATA"
      su postgres -c "$PGBIN/initdb -D $PGDATA -A trust" >/dev/null
    fi
    su postgres -c "$PGBIN/pg_ctl -D $PGDATA -o '-p $PGPORT -k /tmp' -l $PGDATA/log start" >/dev/null 2>&1 || true
    for _ in $(seq 1 30); do
      su postgres -c "$PGBIN/pg_isready -h /tmp -p $PGPORT" >/dev/null 2>&1 && break
      sleep 0.3
    done
    su postgres -c "psql -h /tmp -p $PGPORT -tc \"SELECT 1 FROM pg_roles WHERE rolname='vaanios'\"" \
      | grep -q 1 || su postgres -c "psql -h /tmp -p $PGPORT -qc \"CREATE ROLE vaanios LOGIN PASSWORD 'vaanios' SUPERUSER\""
    for db in vaanios vaanios_test; do
      su postgres -c "psql -h /tmp -p $PGPORT -tc \"SELECT 1 FROM pg_database WHERE datname='$db'\"" \
        | grep -q 1 || su postgres -c "psql -h /tmp -p $PGPORT -qc 'CREATE DATABASE $db OWNER vaanios'"
    done
    echo "postgres ready on port $PGPORT (databases: vaanios, vaanios_test)"
    ;;
  stop)
    su postgres -c "$PGBIN/pg_ctl -D $PGDATA stop" >/dev/null 2>&1 || true
    echo "stopped"
    ;;
  *)
    echo "usage: $0 {start|stop}" >&2
    exit 2
    ;;
esac
