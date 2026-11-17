#!/bin/bash
# The backup service (compose/base.yml): every database, dumped with pg_dumpall into the backups
# volume every BACKUP_EVERY seconds, keeping BACKUP_KEEP_DAYS days of them. With `once`, one dump
# now, which `make backup` runs. `make backup-pull` copies the newest off the host, encrypted;
# `make restore` puts one back. The dump has --clean, so restoring it replaces what's there.
set -euo pipefail
dump() {
	local f
	f=/backups/$(date -u +%Y%m%dT%H%M%SZ).sql.gz
	if pg_dumpall --clean --if-exists -h postgres -U t10 | gzip >"$f.part"; then
		mv "$f.part" "$f"
		echo "backup: $f"
	else
		rm -f "$f.part"
		echo "backup: pg_dumpall failed" >&2
		return 1
	fi
	find /backups -name '*.sql.gz' -mtime +"${BACKUP_KEEP_DAYS:-14}" -delete
}
if [ "${1:-}" = once ]; then
	dump
	exit
fi
while :; do
	dump || true
	sleep "${BACKUP_EVERY:-86400}"
done
