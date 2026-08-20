# Backup and restore runbook

> **Owner:** the operator running production.
> **Goal:** clear procedural steps for daily backups, retention,
> and the restore drill that gates pilot go-live. Updates / extends
> [docs/archive/2026-05-pilot/BACKUP_RESTORE.md](../archive/2026-05-pilot/BACKUP_RESTORE.md), which already
> documents the script invocations.
>
> **This runbook is LOCAL, unencrypted dumps under `backups/`** — good for
> a quick pre-migration snapshot, not sufficient on its own ("the pilot's
> first incident must NOT be 'the host died and so did the only copy of
> the backups'" — §2 below). For the actual OFF-SITE, ENCRYPTED copy, see
> [docs/operations/backups.md](../operations/backups.md) (Sprint 134).
>
> **THE HELPER SCRIPTS THIS RUNBOOK USED TO WRAP ARE DEAD. Every
> command below is now the real one, written out in full.**
>
> `backup_postgres.sh`, `restore_postgres.sh`, `backup_media.sh` and
> `restore_media.sh` were moved to
> [scripts/archive/](../../scripts/archive/) and each carries the header
> *"ARCHIVED — pilot-era one-off (2026-05-03). Not maintained. Do not run
> against any live environment without reading it first."* They are **not**
> on the `scripts/` paths this runbook used to print, so
> `./scripts/backup_postgres.sh` fails with "No such file or directory".
>
> That is not a cosmetic drift. Two consecutive deploys got a database
> backup only because the operator noticed the failure and typed
> `pg_dump` by hand. A backup procedure that does not run is worse than
> no procedure at all, because people believe it. So this runbook no
> longer delegates: the `docker compose exec` commands below are what you
> run, and they are the same commands the archived scripts contained.
>
> Do not resurrect the archived scripts to make the old text true. If a
> wrapper is wanted again it is a deliberate piece of work with an owner,
> not a `git mv`.
>
> `scripts/ops/` holds one live script (`frontend_nginx_validate.sh`) and
> no backup wrappers. For the OFF-SITE, ENCRYPTED copy — which is a
> different thing from the local dumps here — see
> [scripts/backup_restic.sh](../../scripts/backup_restic.sh) and
> [docs/operations/backups.md](../operations/backups.md) (Sprint 134).

---

## 1. Daily Postgres backup

### Command

```bash
mkdir -p backups/postgres
docker compose -f docker-compose.prod.yml exec -T db sh -c \
  'pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  > "backups/postgres/postgres-$(date +%Y%m%d-%H%M%S).dump"
```

`-Fc` is the custom format, which is what `pg_restore` in §3 expects —
a plain-SQL dump will not restore with those flags. `$POSTGRES_USER` and
`$POSTGRES_DB` are read INSIDE the container from its own environment, so
the command carries no credentials and stays correct if they change.

**On a host where docker needs a group wrapper** (crmtest is one), wrap
the whole thing rather than the inner part:

```bash
sg docker -c "docker compose -f docker-compose.prod.yml exec -T db sh -c 'pg_dump -Fc -U \"\$POSTGRES_USER\" \"\$POSTGRES_DB\"'" \
  > "backups/postgres/postgres-$(date +%Y%m%d-%H%M%S).dump"
```

**Check the redirect, not the pipeline.** The `>` is on the HOST side, so
a failure inside the container still leaves a file behind — an empty or
truncated one. Always confirm the size is plausible and verify it reads
back (next section) before trusting it.

### Verify the dump before you rely on it

A dump nobody has opened is a folder of bytes. This takes seconds:

```bash
DUMP=backups/postgres/postgres-<timestamp>.dump
ls -l "$DUMP"
docker compose -f docker-compose.prod.yml exec -T db sh -c 'cat > /tmp/verify.dump' < "$DUMP"
docker compose -f docker-compose.prod.yml exec -T db sh -c \
  'pg_restore --list /tmp/verify.dump | head -20; rm -f /tmp/verify.dump'
```

A healthy dump prints its archive header (`Archive created at ...`,
`dbname:`, `TOC Entries:`) and a table of contents.

**Why the file is copied in first:** `pg_restore --list` on a custom-format
archive needs a SEEKABLE file. Piping the dump to `pg_restore --list
/dev/stdin` fails with `did not find magic string in file header` even
when the dump is perfectly good — that error means "not seekable", not
"corrupt". Copy it to a real path inside the container, or run
`pg_restore` on the host if the client is installed there.

### Cron / systemd timer

Pick one. Both run as the user that owns the docker socket on the
host.

#### crontab example

```cron
# Daily Postgres dump at 02:30 local time.
30 2 * * * cd /opt/cleaning-ticket-system && mkdir -p backups/postgres && docker compose -f docker-compose.prod.yml exec -T db sh -c 'pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB"' > "backups/postgres/postgres-$(date +\%Y\%m\%d-\%H\%M\%S).dump" 2>> backups/postgres.log
```

#### systemd timer example

`/etc/systemd/system/cleaning-ticket-pg-backup.service`:

```ini
[Unit]
Description=Cleaning Ticket — daily Postgres dump
After=docker.service

[Service]
Type=oneshot
User=cleaning-ops
WorkingDirectory=/opt/cleaning-ticket-system
ExecStart=/opt/cleaning-ticket-system/ops/backup-postgres.sh
StandardOutput=append:/var/log/cleaning-ticket-pg-backup.log
StandardError=append:/var/log/cleaning-ticket-pg-backup.log
```

**Do NOT inline the dump command in `ExecStart`.** systemd performs its own
`$VAR` expansion on that line, and `POSTGRES_USER` / `POSTGRES_DB` are not
in systemd's environment — they live inside the `db` container. Inlined,
they expand to empty strings and `pg_dump` runs with no user and no
database. The unit therefore calls a one-line file that the operator owns:

```bash
# /opt/cleaning-ticket-system/ops/backup-postgres.sh   (chmod +x)
#!/usr/bin/env bash
set -euo pipefail
cd /opt/cleaning-ticket-system
mkdir -p backups/postgres
docker compose -f docker-compose.prod.yml exec -T db sh -c \
  'pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  > "backups/postgres/postgres-$(date +%Y%m%d-%H%M%S).dump"
```

This is a file YOU create on the host, deliberately, not a repo script
that can be archived out from under you — which is the exact failure this
runbook is recovering from. Keep it next to the deployment, not in git.
The same applies to the cron line above: `%` is special in crontab and
must be escaped as `\%`, which the example does.

`/etc/systemd/system/cleaning-ticket-pg-backup.timer`:

```ini
[Unit]
Description=Cleaning Ticket — daily Postgres dump (02:30)

[Timer]
OnCalendar=*-*-* 02:30:00
Persistent=true

[Install]
WantedBy=timers.target
```

Enable: `systemctl enable --now cleaning-ticket-pg-backup.timer`.

---

## 2. Retention policy

**Default recommendation: keep 14 daily + 4 weekly.** The 14 dailies
catch yesterday-was-fine-this-morning-isn't scenarios; the 4
weeklies catch slower-burn corruption that wasn't noticed for a
fortnight.

### Pruning (append after the dump command in cron)

```bash
# Keep the last 14 daily dumps.
find backups/postgres -maxdepth 1 -name 'postgres-*.dump' -mtime +14 -delete
```

If you want a separate weekly bucket:

```bash
# Promote every Sunday's dump to backups/postgres/weekly/, then
# keep the last 4 weeklies.
DOW=$(date +%u)  # Mon=1 .. Sun=7
if [ "$DOW" = "7" ]; then
  cp backups/postgres/postgres-$(date +%Y%m%d)-*.dump backups/postgres/weekly/
  find backups/postgres/weekly -maxdepth 1 -name 'postgres-*.dump' -mtime +28 -delete
fi
```

### Off-host copies

Local-only backups are not enough. Pick one:

- **rsync to a backup server** in the same datacenter:
  ```bash
  rsync -az --delete backups/postgres/ backup-server:/var/backups/cleaning-ticket/postgres/
  ```
- **Object storage** (S3 / DigitalOcean Spaces / Backblaze B2):
  ```bash
  aws s3 sync backups/postgres/ s3://your-bucket/cleaning-ticket/postgres/ \
    --storage-class STANDARD_IA --delete
  ```
- **Managed-Postgres native snapshots** if you're using RDS /
  Cloud SQL / DigitalOcean Managed Postgres. In that case you
  can drop the in-compose `db` service entirely and point
  `POSTGRES_HOST` at the managed endpoint.

The pilot's first incident must NOT be "the host died and so did
the only copy of the backups."

---

## 3. Postgres restore

### Restore drill (perform BEFORE pilot go-live)

The drill is documented in
[pilot-launch-checklist.md §6](../archive/2026-05-pilot/pilot-launch-checklist.md). It is
non-negotiable. A backup that has never been restored is a folder
of bytes, not a backup.

### Restore command

```bash
docker compose -f docker-compose.prod.yml exec -T db sh -c \
  'pg_restore --clean --if-exists --no-owner -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  < backups/postgres/postgres-YYYYMMDD-HHMMSS.dump
```

THIS COMMAND IS DESTRUCTIVE AND HAS NO CONFIRMATION PROMPT. The archived
script wrapped it in a mandatory `CONFIRM_RESTORE=YES` envelope; running
`pg_restore` directly, as you now do, has no such guard. `--clean
--if-exists` DROPS the existing objects before recreating them, and it
runs against whatever database the compose file in `-f` currently points
at. **Read the `-f` flag out loud before you press return.** If you want
the old safety net back, put it in your own shell:

```bash
[ "${CONFIRM_RESTORE:-}" = "YES" ] || { echo "set CONFIRM_RESTORE=YES" >&2; exit 1; }
```

### Restore drill steps

1. **Spin up an isolated stack** so the production DB stays
   untouched:
   ```bash
   cp docker-compose.prod.yml docker-compose.staging.yml
   sed -i 's/cleaning-ticket-prod/cleaning-ticket-staging/g' \
     docker-compose.staging.yml
   sed -i 's/_prod:/_staging:/g' docker-compose.staging.yml
   docker compose -f docker-compose.staging.yml up -d db
   ```
   (Adjust the destination ports if the staging stack must avoid
   colliding with production on the same host.)

2. **Pipe the latest dump in**:
   ```bash
   docker compose -f docker-compose.staging.yml exec -T db sh -c \
     'pg_restore --clean --if-exists --no-owner -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
     < backups/postgres/postgres-<latest>.dump
   ```
   (Note the `-f docker-compose.staging.yml`. That flag is the only thing
   standing between a restore drill and a production wipe.)

3. **Bring up the staging app and spot-check**:
   ```bash
   docker compose -f docker-compose.staging.yml up -d
   ```
   Open the staging frontend (different port) and verify counts
   match production (super admin → users count, tickets count).

4. **Tear down**:
   ```bash
   docker compose -f docker-compose.staging.yml down -v
   rm docker-compose.staging.yml
   ```

5. **Record** the restore time and the disk-space watermark.
   Repeat at least quarterly.

### Restore time expectations

| DB size | Approx. restore time on a small VPS |
|---|---|
| < 100 MB | < 30 s |
| 100 MB – 1 GB | 1–5 min |
| 1–10 GB | 5–30 min, plan a maintenance window |

---

## 4. Media volume backup and restore

### Backup

```bash
mkdir -p backups/media
OUT="backups/media/media-$(date +%Y%m%d-%H%M%S).tar.gz"
docker compose -f docker-compose.prod.yml exec -T backend sh -c \
  'mkdir -p /app/media && tar -czf - -C /app media' > "$OUT"
tar -tzf "$OUT" >/dev/null && echo "media archive OK: $OUT"
```

Archives the backend's `/app/media` (the
`cleaning-ticket-prod_backend_media_prod` docker volume) into
`backups/media/media-YYYYMMDD-HHMMSS.tar.gz`. The `tar -tzf` line is the
same integrity check the archived script ran and is not optional — as
with the DB dump, the `>` redirect is on the host, so a failure inside
the container still leaves a file.

Same retention discipline as Postgres applies — the media volume
holds every ticket attachment. **Schedule it on the same cron** as
the DB backup so the two are in lockstep.

```cron
# Daily media archive at 02:35 (5 minutes after the DB dump so the
# pg-backup log is closed).
35 2 * * * cd /opt/cleaning-ticket-system && mkdir -p backups/media && docker compose -f docker-compose.prod.yml exec -T backend sh -c 'mkdir -p /app/media && tar -czf - -C /app media' > "backups/media/media-$(date +\%Y\%m\%d-\%H\%M\%S).tar.gz" 2>> backups/media.log
```

### Restore

```bash
ARCHIVE=backups/media/media-YYYYMMDD-HHMMSS.tar.gz
tar -tzf "$ARCHIVE" >/dev/null   # validate BEFORE deleting anything
docker compose -f docker-compose.prod.yml exec -T backend sh -c '
  set -e
  mkdir -p /app/media
  find /app/media -mindepth 1 -delete
  tar -xzf - -C /app
' < "$ARCHIVE"
```

Note what this does: it **empties `/app/media` first**, so the result is
the archive's contents exactly — anything uploaded since the archive was
taken is gone. (The archived script did the same; the old wording here,
"files that exist in the volume but not in the archive are left alone",
was wrong about its own script.) Validate the tarball before the delete,
as above, or a corrupt archive costs you the media volume.

Stop the app first so no upload lands mid-restore:

```bash
docker compose -f docker-compose.prod.yml stop backend worker beat
# ... run the restore above, but against a stopped backend you will need
# a one-off container instead of `exec`; simplest is to restore, then:
docker compose -f docker-compose.prod.yml start backend worker beat
```

Because `exec` needs a RUNNING container, the practical order on a live
box is: stop `worker` and `beat` (the writers), leave `backend` up for
the `exec`, restore, then start the two back up.

---

## 5. Redis is NOT a source of truth

Redis holds Celery's broker queue and the result backend (DBs 1
and 2 in the default config — see `CELERY_BROKER_URL` /
`CELERY_RESULT_BACKEND` in `.env.production.example`).

- Redis backups are **not required** for the pilot.
- Losing Redis = losing in-flight Celery tasks (currently used for
  outgoing email). Email sends will be retried by Celery's retry
  policy when Redis comes back; some emails may be lost.
- Redis persistence is left ON via the volume mount
  (`redis_data_prod`) so a docker host reboot doesn't drop the
  queue. That is the only durability requirement.

If you ever extend the app to use Redis as a cache for non-
ephemeral data (per-tenant quota counters, distributed locks for
ticket-number generation, etc.), revisit this section and add
Redis to the backup plan.

---

## 6. Operator's "is the backup working" checklist

Run this **weekly** during the pilot. Five minutes; catches the
silent-failure modes.

- [ ] `ls -lh backups/postgres/ | tail -5` shows a dump within the
      last 36 hours.
- [ ] `ls -lh backups/media/ | tail -5` shows a media archive
      within the last 36 hours.
- [ ] The backup destination (rsync target / S3 prefix) shows a
      copy of the latest dump.
- [ ] The cron / timer log (`backups/postgres.log`,
      `backups/media.log`, or `journalctl -u
      cleaning-ticket-pg-backup.timer`) has no errors in the last
      week.
- [ ] Disk usage on the backup host is below 80% (`df -h
      backups/`). Bump retention down if it climbs.
- [ ] At least one restore drill on file in the last 90 days.
