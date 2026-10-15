#!/usr/bin/env bash
# Run a command against the production (Neon) database.
# The connection string lives outside the repo in ~/.sales_neon_url
# (chmod 600) and is only passed to the child process as DATABASE_URL.
#
# Usage: scripts/with_prod_db.sh poetry run python scripts/optimize_listings.py
set -euo pipefail

url_file="${HOME}/.sales_neon_url"
if [[ ! -s "$url_file" ]]; then
  echo "Missing $url_file — save the Neon connection string there first." >&2
  exit 1
fi
if grep -q '\.\.\.' "$url_file"; then
  echo "$url_file still holds placeholder text — paste the real Neon connection string." >&2
  exit 1
fi

DATABASE_URL="$(cat "$url_file")" exec "$@"
