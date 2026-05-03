# Backup and Restore

## PostgreSQL backup

Start production database first:

```bash
docker compose -f docker-compose.prod.yml up -d db
```

Create a database backup:

```bash
./scripts/backup_postgres.sh
```

Backups are written to:

```text
backups/postgres/
```

The backup format is PostgreSQL custom format: `pg_dump -Fc`.

## PostgreSQL restore

Restore requires explicit confirmation:

```bash
CONFIRM_RESTORE=YES ./scripts/restore_postgres.sh backups/postgres/postgres-YYYYMMDD-HHMMSS.dump
```

The restore uses:

```text
pg_restore --clean --if-exists --no-owner
```

Do not run restore against a production database unless you are certain the backup is correct.

## Uploaded media backup

Start production backend first:

```bash
docker compose -f docker-compose.prod.yml up -d backend
```

Create a media backup:

```bash
./scripts/backup_media.sh
```

Backups are written to:

```text
backups/media/
```

## Important notes

- Do not commit files under `backups/`.
- Store production backups outside the server as well.
- Test restore on a clean environment before trusting the backup process.
- Back up both PostgreSQL and uploaded media; one without the other is incomplete.
