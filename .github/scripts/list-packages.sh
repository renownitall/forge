#!/usr/bin/env bash
set -euo pipefail

list=""
for dir in packages/*/; do
  name=$(basename "$dir")
  if [ -f "$dir/PKGBUILD" ] && [ ! -f "$dir/HOLD" ]; then
    list+="$name"$'\n'
  fi
done

# GitHub needs the object form so that matrix.package resolves in each job.
matrix=$(printf '%s' "$list" | jq -R -s -c '{package: split("\n") | map(select(length > 0))}')
count=$(jq '.package | length' <<<"$matrix")

# Anything echoed inside $() is captured into the variable, not
# printed, so notices stay outside substitutions.
for dir in packages/*/HOLD; do
  [ -e "$dir" ] || continue
  echo "::notice title=Held package::$(basename "$(dirname "$dir")") is held ($dir)"
done

echo "matrix=$matrix" >>"$GITHUB_OUTPUT"

if [ "$count" -eq 0 ]; then
  echo "has_packages=false" >>"$GITHUB_OUTPUT"
  echo "::notice title=Nothing to build::The build, repo, and deploy jobs will skip"
  exit 0
fi

echo "has_packages=true" >>"$GITHUB_OUTPUT"
echo "Packages to build ($count): $matrix"
