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


## PostgreSQL restore smoke test

Run a full PostgreSQL backup and restore validation against an isolated Docker Compose project:

    RESTORE_TEST_CONFIRM=YES FRONTEND_PORT=18080 ./scripts/prod_restore_test.sh

The test creates marker data, creates a PostgreSQL backup, removes the test database volume, restores the backup into a clean database, and verifies that the marker ticket exists after restore.

This script uses a separate Compose project name and removes its own test volumes at the end.


## Uploaded media restore

Restore requires explicit confirmation:

    CONFIRM_RESTORE=YES ./scripts/restore_media.sh backups/media/media-YYYYMMDD-HHMMSS.tar.gz

The restore process clears `/app/media` inside the backend container before extracting the backup archive.

Do not run media restore against a production system unless you are certain the backup is correct.

## Uploaded media restore smoke test

Run a full media backup and restore validation against an isolated Docker Compose project:

    MEDIA_RESTORE_TEST_CONFIRM=YES FRONTEND_PORT=18081 ./scripts/prod_media_restore_test.sh

The test creates a marker file in the media volume, creates a media backup, wipes the media volume, restores the backup, and verifies that the marker file exists after restore.

## Important notes

- Do not commit files under `backups/`.
- Store production backups outside the server as well.
- Test restore on a clean environment before trusting the backup process.
- Back up both PostgreSQL and uploaded media; one without the other is incomplete.
