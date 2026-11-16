#!/bin/sh
# Every module's <id>-db one-shot runs this on every start (scripts/wiring.py): the module's own
# login, which owns only its own database, made if missing. Setting the password each time makes
# rotating it a restart. MODULE_DB names both; MODULE_DB_PASSWORD is its password.
set -eu
psql -v ON_ERROR_STOP=1 -d auth <<SQL
SELECT 'CREATE ROLE $MODULE_DB LOGIN' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$MODULE_DB')\gexec
ALTER ROLE $MODULE_DB PASSWORD '$MODULE_DB_PASSWORD';
SELECT 'CREATE DATABASE $MODULE_DB OWNER $MODULE_DB' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$MODULE_DB')\gexec
REVOKE ALL ON DATABASE $MODULE_DB FROM PUBLIC;
SQL
