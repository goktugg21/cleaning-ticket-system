# Media Storage Strategy

## Current production strategy

Uploaded ticket attachments are stored in the Docker volume mounted at:

    backend_media_prod:/app/media

This is the selected strategy for the first production deployment.

## Why local Docker volume is acceptable for the first release

- The app currently runs as a single-server Docker Compose deployment.
- Attachment size is limited.
- Attachment MIME types are restricted.
- Attachment file names are randomized in storage.
- Attachment downloads are protected by authenticated API endpoints.
- A media backup script exists.

## Backup requirement

Media files must be backed up together with PostgreSQL.

Create a media backup:

    ./scripts/backup_media.sh

Create a PostgreSQL backup:

    ./scripts/backup_postgres.sh

A PostgreSQL backup without the matching media backup is incomplete, because ticket records may reference uploaded files.

## Restore requirement

When restoring production data, restore both:

- PostgreSQL database backup
- Uploaded media backup

## Future migration option

If the system grows beyond a single server or needs stronger durability, move uploaded media to object storage such as S3, MinIO, or another S3-compatible service.

Recommended future object storage requirements:

- Private bucket by default
- Signed URLs or backend-proxied downloads
- Server-side encryption
- Lifecycle policy for old files if needed
- Separate backup/replication policy
