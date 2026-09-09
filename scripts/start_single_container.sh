#!/usr/bin/env bash
set -euo pipefail

scripts/init_data_dirs.sh

export POSTGRES_DB="${POSTGRES_DB:-sora}"
export POSTGRES_USER="${POSTGRES_USER:-sora}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-sora_password}"
export PGDATA="${APP_PGDATA:-/data/postgres}"
if [ -z "${DATABASE_URL:-}" ] || [[ "${DATABASE_URL}" == *"@postgres:"* ]]; then
    export DATABASE_URL="postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:5432/${POSTGRES_DB}"
fi

case "${POSTGRES_DB}:${POSTGRES_USER}:${POSTGRES_PASSWORD}" in
    *"'"*|*\"*|*";"*|*" "*) echo "POSTGRES_DB, POSTGRES_USER, and POSTGRES_PASSWORD must not contain quotes, semicolons, or spaces." >&2; exit 1 ;;
esac

PG_BIN="$(dirname "$(command -v pg_ctl || true)")"
if [ -z "${PG_BIN}" ] || [ ! -x "${PG_BIN}/pg_ctl" ]; then
    PG_BIN="$(find /usr/lib/postgresql -type f -name pg_ctl -printf '%h\n' | sort -V | tail -n 1)"
fi
if [ -z "${PG_BIN}" ]; then
    echo "PostgreSQL binaries were not found." >&2
    exit 1
fi

mkdir -p /var/run/postgresql /data/postgres /data/logs /data/uploads /data/outputs /data/temp /data/secrets
touch /data/logs/postgres.log
chown -R postgres:postgres /data/postgres /data/logs /var/run/postgresql
chmod 700 /data/postgres /var/run/postgresql

if [ ! -s "${PGDATA}/PG_VERSION" ]; then
    su -s /bin/bash postgres -c "${PG_BIN}/initdb -D '${PGDATA}' --encoding=UTF8 --locale=C.UTF-8 --auth-local=trust --auth-host=scram-sha-256"
    {
        echo "listen_addresses = '127.0.0.1'"
        echo "port = 5432"
        echo "unix_socket_directories = '/var/run/postgresql'"
    } >> "${PGDATA}/postgresql.conf"
    echo "host all all 127.0.0.1/32 scram-sha-256" >> "${PGDATA}/pg_hba.conf"
fi

as_postgres() {
    su -s /bin/bash postgres -c "$1"
}

if ! as_postgres "${PG_BIN}/pg_ctl -D '${PGDATA}' -l /data/logs/postgres.log -w start"; then
    echo "PostgreSQL failed to start. Last log lines:" >&2
    tail -n 200 /data/logs/postgres.log >&2 || true
    exit 1
fi

cleanup() {
    if [ -n "${WORKER_PID:-}" ]; then
        kill "${WORKER_PID}" 2>/dev/null || true
    fi
    as_postgres "${PG_BIN}/pg_ctl -D '${PGDATA}' -m fast -w stop" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

role_exists="$(as_postgres "${PG_BIN}/psql -d postgres -tAc \"SELECT 1 FROM pg_roles WHERE rolname='${POSTGRES_USER}'\"")"
if [ "${role_exists}" != "1" ]; then
    as_postgres "${PG_BIN}/psql -d postgres -v ON_ERROR_STOP=1 -c \"CREATE ROLE ${POSTGRES_USER} LOGIN PASSWORD '${POSTGRES_PASSWORD}'\""
else
    as_postgres "${PG_BIN}/psql -d postgres -v ON_ERROR_STOP=1 -c \"ALTER ROLE ${POSTGRES_USER} WITH LOGIN PASSWORD '${POSTGRES_PASSWORD}'\""
fi

db_exists="$(as_postgres "${PG_BIN}/psql -d postgres -tAc \"SELECT 1 FROM pg_database WHERE datname='${POSTGRES_DB}'\"")"
if [ "${db_exists}" != "1" ]; then
    as_postgres "${PG_BIN}/createdb -O '${POSTGRES_USER}' '${POSTGRES_DB}'"
fi

/opt/venv/bin/alembic upgrade head

/opt/venv/bin/python -m app.workers.main &
WORKER_PID="$!"

/opt/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 &
WEB_PID="$!"
wait "${WEB_PID}"
