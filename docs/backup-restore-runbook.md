# Backup and restore runbook

> **Owner:** the operator running production.
> **Goal:** clear procedural steps for daily backups, retention,
> and the restore drill that gates pilot go-live. Updates / extends
> [docs/BACKUP_RESTORE.md](BACKUP_RESTORE.md), which already
> documents the script invocations.
>
> Wraps three pre-existing scripts (do NOT replace them):
>
> - [scripts/backup_postgres.sh](../scripts/backup_postgres.sh)
> - [scripts/restore_postgres.sh](../scripts/restore_postgres.sh)
> - [scripts/backup_media.sh](../scripts/backup_media.sh) /
>   [scripts/restore_media.sh](../scripts/restore_media.sh)
>
> The convenience wrappers under `scripts/ops/` (Sprint 6) call
> these scripts with the right env defaults; this runbook is the
> human-readable procedure.

---

## 1. Daily Postgres backup

### Command

```bash
./scripts/backup_postgres.sh
```

The script reads `COMPOSE_FILE` (default `docker-compose.prod.yml`)
and `BACKUP_DIR` (default `backups/postgres`). It runs
`pg_dump -Fc` inside the `db` container and writes the dump to
`backups/postgres/postgres-YYYYMMDD-HHMMSS.dump`.

### Cron / systemd timer

Pick one. Both run as the user that owns the docker socket on the
host.

#### crontab example

```cron
# Daily Postgres dump at 02:30 local time.
30 2 * * * cd /opt/cleaning-ticket-system && ./scripts/backup_postgres.sh >> backups/postgres.log 2>&1
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
ExecStart=/opt/cleaning-ticket-system/scripts/backup_postgres.sh
StandardOutput=append:/var/log/cleaning-ticket-pg-backup.log
StandardError=append:/var/log/cleaning-ticket-pg-backup.log
```

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
[pilot-launch-checklist.md §6](pilot-launch-checklist.md). It is
non-negotiable. A backup that has never been restored is a folder
of bytes, not a backup.

### Restore command

```bash
CONFIRM_RESTORE=YES \
  ./scripts/restore_postgres.sh \
  backups/postgres/postgres-YYYYMMDD-HHMMSS.dump
```

The `CONFIRM_RESTORE=YES` envelope is mandatory — the script
refuses to run otherwise. The restore uses
`pg_restore --clean --if-exists --no-owner` and runs against
whatever DB `docker-compose.prod.yml` is currently pointing at, so
**make sure you target the right stack**.

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
   COMPOSE_FILE=docker-compose.staging.yml \
   CONFIRM_RESTORE=YES \
     ./scripts/restore_postgres.sh \
     backups/postgres/postgres-<latest>.dump
   ```

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
./scripts/backup_media.sh
```

Archives the `cleaning-ticket-prod_backend_media_prod` docker
volume into `backups/media/media-YYYYMMDD-HHMMSS.tar.gz`.

Same retention discipline as Postgres applies — the media volume
holds every ticket attachment. **Schedule it on the same cron** as
the DB backup so the two are in lockstep.

```cron
# Daily media archive at 02:35 (5 minutes after the DB dump so the
# pg-backup log is closed).
35 2 * * * cd /opt/cleaning-ticket-system && ./scripts/backup_media.sh >> backups/media.log 2>&1
```

### Restore

```bash
./scripts/restore_media.sh backups/media/media-YYYYMMDD-HHMMSS.tar.gz
```

The script tar-extracts into the volume's mount path. Existing
files are overwritten where the archive contains a newer copy;
files that exist in the volume but not in the archive are left
alone (it's NOT a `--delete`-style sync). For a true point-in-time
restore, stop the worker first so no new uploads land while you
restore:

```bash
docker compose -f docker-compose.prod.yml stop backend worker beat
./scripts/restore_media.sh backups/media/media-<timestamp>.tar.gz
docker compose -f docker-compose.prod.yml start backend worker beat
```

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
