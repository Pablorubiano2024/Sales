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

# Optional: MercadoLibre app credentials (ML_CLIENT_ID=..., ML_CLIENT_SECRET=...,
# ML_REDIRECT_URI=... one per line), so an expired access token can be
# refreshed locally instead of waiting for the next GitHub Actions run.
ml_file="${HOME}/.sales_ml_env"
if [[ -s "$ml_file" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ml_file"
  set +a
fi

DATABASE_URL="$(cat "$url_file")" exec "$@"
