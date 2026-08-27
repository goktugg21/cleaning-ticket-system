#!/usr/bin/env bash
#
# W-VIEWER §17 — install the ONE front door onto crmtest's captured mail.
#
# Run this ON THE HOST, with sudo. It is the only step of §17 that needs
# root, which is why it is a script and not a paragraph in a report:
#
#   sudo scripts/ops/install_mailhog_front_door.sh <username>
#
# It does three things, each of which it checks first:
#
#   1. Creates /etc/nginx/.htpasswd-mailhog if it is missing, prompting
#      for the password. The file is NEVER in this repo — it is a
#      credential, and a credential in git is a credential published.
#   2. Copies scripts/host-nginx-osius.conf over
#      /etc/nginx/sites-available/osius.conf, keeping a timestamped
#      backup of whatever was there.
#   3. `nginx -t`, then reloads. A config that does not parse is NOT
#      loaded — the site stays up on the old one.
#
# WHY IT IS NEEDED AT ALL. MailHog has no authentication. Anything that
# can reach its UI reads every message the system has ever sent, which on
# crmtest includes password-reset and invitation links. The compose file
# now publishes that UI on 127.0.0.1 only, so this basic-auth proxy is
# the only route to it from anywhere else.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SRC="$REPO_ROOT/scripts/host-nginx-osius.conf"
DEST="/etc/nginx/sites-available/osius.conf"
LINK="/etc/nginx/sites-enabled/osius.conf"
HTPASSWD="/etc/nginx/.htpasswd-mailhog"
USERNAME="${1:-}"

if [[ $EUID -ne 0 ]]; then
  echo "This must run as root: sudo $0 <username>" >&2
  exit 1
fi
if [[ ! -f "$SRC" ]]; then
  echo "Missing $SRC" >&2
  exit 1
fi

if [[ ! -f "$HTPASSWD" ]]; then
  if [[ -z "$USERNAME" ]]; then
    echo "No $HTPASSWD yet — pass the username to create it:" >&2
    echo "  sudo $0 <username>" >&2
    exit 1
  fi
  if ! command -v htpasswd >/dev/null 2>&1; then
    echo "htpasswd is missing. Install it first:" >&2
    echo "  sudo apt-get install -y apache2-utils" >&2
    exit 1
  fi
  echo "Creating $HTPASSWD for user '$USERNAME' — you will be asked for a password."
  htpasswd -c "$HTPASSWD" "$USERNAME"
  chown root:www-data "$HTPASSWD"
  chmod 640 "$HTPASSWD"
else
  echo "$HTPASSWD already exists — left alone."
  echo "  (add another user: sudo htpasswd $HTPASSWD <username>)"
fi

if [[ -f "$DEST" ]]; then
  BACKUP="$DEST.bak.$(date +%Y%m%d%H%M%S)"
  cp -a "$DEST" "$BACKUP"
  echo "Backed up the existing config to $BACKUP"
fi
install -o root -g root -m 644 "$SRC" "$DEST"
ln -sfn "$DEST" "$LINK"

echo "Testing the nginx configuration..."
nginx -t
systemctl reload nginx
echo
echo "Done. The mailbox is at  https://crmtest.osius.nl/mailhog/"
echo "It will ask for the username and password held in $HTPASSWD."
