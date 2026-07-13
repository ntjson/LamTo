-- The application/migration role owns the Django tables.  Write procedures
-- run as this separate NOLOGIN role so ordinary SQL cannot forge their trigger
-- identity by setting a custom GUC.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'lamto_service') THEN
        CREATE ROLE lamto_service
            NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
    END IF;
END
$$;

GRANT lamto_service TO lamto WITH ADMIN OPTION;
