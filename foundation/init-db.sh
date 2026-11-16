#!/bin/sh
# Runs once, when the Postgres volume is new: one database per foundation service, all on the
# t10 login, as in t10-quickstart. Modules add their own script beside this one.
set -eu
psql -v ON_ERROR_STOP=1 -U t10 -d auth <<SQL
CREATE DATABASE workbench;
CREATE DATABASE collab;
CREATE DATABASE knowledge;
CREATE DATABASE agent_control;
CREATE DATABASE console;
CREATE DATABASE automations;
SQL
