#!/usr/bin/env bash
# Retries a command up to 3 attempts with a fixed pause between tries.
# Mirrors are occasionally flaky; this keeps one transient mirror/network
# failure from failing every package for the day.
set -u

attempt=1
until "$@"; do
  attempt=$((attempt + 1))
  if [ "$attempt" -gt 3 ]; then
    echo "::error::Command failed after 3 attempts: $*"
    exit 1
  fi
  echo "::warning::Command failed (attempt $((attempt - 1))/3), retrying in 10s: $*"
  sleep 10
done
