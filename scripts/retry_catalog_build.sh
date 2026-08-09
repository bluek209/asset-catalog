#!/usr/bin/env bash

set -euo pipefail

if [[ $# -ne 2 || ! "$1" =~ ^[0-9]+$ || ! "$2" =~ ^[0-9]+$ ]]; then
  echo "usage: $0 <first-delay-seconds> <second-delay-seconds>" >&2
  exit 64
fi

retry_delays=("$1" "$2")

for attempt in 1 2 3; do
  if catalog_output="$(asset-catalog \
    --site-root site \
    --history-output catalog.json \
    --history-manifest-output manifest.json \
    --crypto-history-output crypto/catalog.json \
    --crypto-history-manifest-output crypto/manifest.json \
    --hydrate-url https://bluek209.github.io/asset-catalog/)"; then
    printf '%s\n' "$catalog_output"
    exit 0
  else
    exit_status=$?
  fi

  if (( attempt == 3 )); then
    exit "$exit_status"
  fi

  retry_delay="${retry_delays[$((attempt - 1))]}"
  echo "Catalog build attempt ${attempt}/3 failed; retrying in ${retry_delay} seconds" >&2
  sleep "$retry_delay"
done
