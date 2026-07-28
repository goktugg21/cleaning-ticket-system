# Off-site encrypted backups (restic)

> **Owner:** the operator running production.
> **Status:** the tooling below is BUILT but NOT RUN. Nothing has been
> deployed, no restic repository exists yet, and no credentials have been
> generated — the owner had not yet bought off-site storage when this was
> written (Sprint 134). This doc plus `scripts/backup_restic.sh` and
> `scripts/systemd/osius-backup-restic.{service,timer}` are ready to
> deploy the moment storage is provisioned.

Complements, does not replace,
[engineering/backup-restore.md](../engineering/backup-restore.md) — that
runbook's `scripts/archive/backup_postgres.sh` / `backup_media.sh` still
work for a quick, local, unencrypted dump (e.g. before a risky migration).
**This doc is specifically the OFF-SITE, ENCRYPTED copy** that closes the
`## NEXT` item in
[planning/sprint-checklist.md](../planning/sprint-checklist.md): *"today
NEITHER [the media volume] NOR Postgres is backed up, so a disk loss is
unrecoverable."*

---

## 1. What gets backed up, and why it matters more than "ticket attachments"

`scripts/backup_restic.sh` backs up:

1. A full Postgres dump (`pg_dump -Fc`) of the application database.
2. A tar archive of the ENTIRE `backend_media_prod` docker volume
   (mounted at `/app/media` in the `backend` and `worker` containers).

**The media volume is not just ticket attachments.** As of Sprint 134 it
holds, all mixed together under one `MEDIA_ROOT`:

| What | Model field |
|---|---|
| Ticket attachments | `tickets.Attachment.file` |
| Customer documents (the Documents tab) | `documents.Document.file` |
| Customer contract PDFs | `customers.Customer.contract_pdf` |
| Customer logos | `customers.Customer.logo` |
| Company logos | `companies.Company.logo` |
| User profile photos | `accounts.User.profile_photo` |
| Staff credential documents | `accounts.StaffCredential.document` |
| Custom profile-property documents | `accounts.CustomProfileProperty.document` |

A disk loss without a backup does not just lose attachments — it loses
every customer contract, every staff credential on file, and every
uploaded document across every tenant. Size the urgency of actually
provisioning storage and running this accordingly.

---

## 2. Provision a Hetzner Storage Box sub-account

(Any restic-supported backend works — S3, Backblaze B2, a second VPS over
SFTP. This section documents Hetzner Storage Box specifically since it's
the owner's stated preference; swap the `RESTIC_REPOSITORY` URL scheme
for your actual backend if different — see
[restic's repository docs](https://restic.readthedocs.io/en/stable/030_preparing_a_new_repo.html).)

1. In the Hetzner Robot panel, order a Storage Box (the smallest tier is
   enough to start — a Postgres dump + media tarball for a pilot-scale
   tenant set is well under 10 GB; resize later, Storage Boxes support
   that without re-provisioning).
2. Create a **sub-account** scoped to a single subdirectory (Storage Box
   → your box → "Sub-accounts" → new). Do NOT use the main account
   credentials for the backup script — a sub-account limits blast radius
   if the credential ever leaks, and can be revoked independently.
3. Enable SSH key authentication for the sub-account (Storage Box →
   "SSH Keys"). **Do not rely on password auth** — the nightly systemd
   timer runs unattended with no one to type a password.
   ```bash
   # On the production host, as the user the systemd service runs as
   # (User= in scripts/systemd/osius-backup-restic.service):
   ssh-keygen -t ed25519 -f ~/.ssh/osius-backup-restic -N ""
   # Paste the .pub key's contents into the Storage Box sub-account's
   # "SSH Keys" panel.
   ```
   Add a matching entry to that user's `~/.ssh/config` so restic's
   `sftp:` URL doesn't need the key path repeated:
   ```
   Host uXXXXXX.your-storagebox.de
     User uXXXXXX-subN
     IdentityFile ~/.ssh/osius-backup-restic
   ```
4. Confirm SFTP connectivity BEFORE wiring up the timer:
   ```bash
   sftp uXXXXXX-subN@uXXXXXX.your-storagebox.de
   ```
   A successful connection with no password prompt confirms the key is
   accepted.

---

## 3. Fill in the env file and initialize the repository

1. Copy the template and fill in real values:
   ```bash
   sudo cp scripts/osius-backup.env.example /etc/osius-backup.env
   sudo chown root:root /etc/osius-backup.env
   sudo chmod 600 /etc/osius-backup.env
   sudo nano /etc/osius-backup.env   # fill in RESTIC_REPOSITORY / RESTIC_PASSWORD
   ```
   Generate `RESTIC_PASSWORD` with `openssl rand -base64 32` — this is
   restic's own encryption password, NOT the Storage Box account
   password. **Store a copy of it somewhere other than this server** (a
   password manager). Losing it makes every existing snapshot
   permanently unrecoverable, even with full storage access.

2. Install `restic` on the host (not bundled with the app containers —
   this script runs on the DOCKER HOST, not inside a container, the same
   way `scripts/archive/backup_postgres.sh` does):
   ```bash
   # Debian/Ubuntu:
   sudo apt-get install restic
   # or the static binary from https://github.com/restic/restic/releases
   ```

3. Initialize the repository — **one-time, before the first backup run**:
   ```bash
   set -a; source /etc/osius-backup.env; set +a
   restic init
   ```
   This creates the encrypted repository structure at
   `RESTIC_REPOSITORY`. Running it twice against an already-initialized
   repository is a harmless no-op error ("repository master key and
   config already initialized").

4. Run the backup once by hand to confirm it works end to end before
   trusting the timer with it:
   ```bash
   ./scripts/backup_restic.sh
   ```
   It refuses to run (loud, immediate, non-zero exit) if
   `/etc/osius-backup.env` is missing or incomplete — see the script's
   own header comment for the exact checks.

5. Install the systemd units:
   ```bash
   sudo cp scripts/systemd/osius-backup-restic.service /etc/systemd/system/
   sudo cp scripts/systemd/osius-backup-restic.timer /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now osius-backup-restic.timer
   ```
   Verify it's scheduled: `systemctl list-timers osius-backup-restic.timer`.

---

## 4. Retention

`scripts/backup_restic.sh` prunes on every successful run:

```bash
restic forget --keep-within 30d --prune --tag cleaning-ticket
```

Every snapshot from the last 30 days is kept; older ones are removed and
their now-unreferenced data chunks are reclaimed. This is deliberately
simpler than the daily/weekly split
[engineering/backup-restore.md §2](../engineering/backup-restore.md#2-retention-policy)
documents for the local unencrypted dumps — restic's content-addressed
storage deduplicates unchanged data across snapshots automatically, so a
flat 30-day window doesn't cost extra storage the way 30 independent
`pg_dump` files would.

To change the window, edit the `--keep-within` value in
`scripts/backup_restic.sh` directly (there is deliberately no env-var
override for this — it's a retention POLICY decision, not a per-host
credential, and belongs in the reviewed script, not an unreviewed env
file).

---

## 5. The restore drill (perform this before you trust the backup)

**A backup nobody has restored from is not a backup.** This mirrors
[engineering/backup-restore.md §3](../engineering/backup-restore.md#3-postgres-restore)'s
existing restore-drill discipline, adapted for a restic snapshot instead
of a local dump file. Run this against a **scratch database on a
throwaway compose stack** — never against production.

### 5.1 List available snapshots

```bash
set -a; source /etc/osius-backup.env; set +a
restic snapshots --tag cleaning-ticket
```

Note the snapshot ID (or short ID, e.g. `a1b2c3d4`) you want to restore.

### 5.2 Restore the snapshot's files to a scratch directory

```bash
mkdir -p /tmp/restic-restore-drill
restic restore <snapshot-id> --target /tmp/restic-restore-drill
```

This produces `/tmp/restic-restore-drill/var/backups/cleaning-ticket/restic-staging/postgres.dump`
and `.../media.tar.gz` (restic preserves the original absolute path the
files were backed up from — see `STAGING_DIR` in `backup_restic.sh`).

### 5.3 Spin up an isolated scratch stack

Same pattern as the existing Postgres restore drill — a throwaway compose
project so production is never touched:

```bash
cp docker-compose.prod.yml docker-compose.restore-drill.yml
sed -i 's/cleaning-ticket-prod/cleaning-ticket-restore-drill/g' \
  docker-compose.restore-drill.yml
sed -i 's/_prod:/_restoredrill:/g' docker-compose.restore-drill.yml
docker compose -f docker-compose.restore-drill.yml up -d db
```

### 5.4 Restore the Postgres dump into the scratch database

```bash
DUMP=/tmp/restic-restore-drill/var/backups/cleaning-ticket/restic-staging/postgres.dump
cat "$DUMP" | docker compose -f docker-compose.restore-drill.yml exec -T db sh -c \
  'pg_restore --clean --if-exists --no-owner -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

### 5.5 Restore the media archive into the scratch stack's volume

```bash
docker compose -f docker-compose.restore-drill.yml up -d backend
MEDIA=/tmp/restic-restore-drill/var/backups/cleaning-ticket/restic-staging/media.tar.gz
cat "$MEDIA" | docker compose -f docker-compose.restore-drill.yml exec -T backend sh -c '
  mkdir -p /app/media
  tar -xzf - -C /app
'
```

### 5.6 Bring up the scratch app and spot-check

```bash
docker compose -f docker-compose.restore-drill.yml up -d
```
Open the scratch frontend (different port — check
`docker compose -f docker-compose.restore-drill.yml ps`) and verify:
- Super admin login works with a real seeded account.
- User count / ticket count / customer count roughly match production
  (exact match if the snapshot is recent and no writes have landed since).
- Open one customer's Documents tab and confirm a known file downloads
  and its content is intact (not just that the row exists).
- Open one customer's contract PDF and confirm it renders.

### 5.7 Tear down

```bash
docker compose -f docker-compose.restore-drill.yml down -v
rm docker-compose.restore-drill.yml
rm -rf /tmp/restic-restore-drill
```

### 5.8 Record it

Note the date and the restore time in whatever the team uses for
operational records. **Repeat at least quarterly** — same cadence as
[engineering/backup-restore.md §3](../engineering/backup-restore.md#3-postgres-restore)
already recommends for the local-dump drill.

---

## 6. Operator's "is the off-site backup working" checklist

Run weekly, alongside the existing
[engineering/backup-restore.md §6](../engineering/backup-restore.md#6-operators-is-the-backup-working-checklist)
checklist:

- [ ] `restic snapshots --tag cleaning-ticket` shows a snapshot within
      the last 36 hours.
- [ ] `journalctl -u osius-backup-restic.service -p err --since -7d`
      shows no failures in the last week.
- [ ] `systemctl status osius-backup-restic.timer` shows it active and
      the next scheduled run in the future.
- [ ] `restic check` (an integrity check of the repository itself — run
      monthly, not weekly, it reads the whole repository) reports no
      errors.
- [ ] At least one restore drill (§5 above) on file in the last 90 days.
