-- Create the non-superuser application role used by the backend at runtime.
--
-- The 'postgres' superuser is kept for Alembic migrations (DDL).
-- The app itself connects as 'albert_app' — no SUPERUSER, no BYPASSRLS —
-- so PostgreSQL enforces FORCE ROW LEVEL SECURITY on every query.
--
-- This script runs automatically on first container start via
-- /docker-entrypoint-initdb.d/. It is idempotent (DO $$ IF NOT EXISTS $$).
--
-- To apply to an already-running container without destroying the volume:
--   docker compose exec postgres psql -U postgres -d albert \
--     -f /docker-entrypoint-initdb.d/01_create_app_role.sql

\connect albert

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'albert_app') THEN
        CREATE ROLE albert_app WITH
            LOGIN
            PASSWORD 'albert_app'
            NOSUPERUSER
            INHERIT
            NOCREATEDB
            NOCREATEROLE
            NOBYPASSRLS;
    END IF;
END
$$;

GRANT CONNECT ON DATABASE albert TO albert_app;
GRANT USAGE ON SCHEMA public TO albert_app;

-- Default privileges cover tables/sequences/functions created by future migrations
-- (which run as the 'postgres' superuser).
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO albert_app;

ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO albert_app;

ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
    GRANT EXECUTE ON FUNCTIONS TO albert_app;
