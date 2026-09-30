#!/usr/bin/env bash
set -euo pipefail

mkdir -p repo
cp signing_key.asc repo/
find artifacts/ -name pkg.tar -exec tar -xf {} -C repo \;

cd repo
shopt -s nullglob
pkgs=(*.pkg.tar.zst)
sigs=(*.pkg.tar.zst.sig)
if [ "${#pkgs[@]}" -eq 0 ]; then
  echo "::error::No packages found to build repository"
  exit 1
fi
# Under SigLevel = Required a package without a signature cannot be
# installed, so refuse to publish one.
if [ "${#sigs[@]}" -ne "${#pkgs[@]}" ]; then
  echo "::error::Signatures (${#sigs[@]}) do not match packages (${#pkgs[@]}), refusing to publish"
  exit 1
fi
echo "Publishing packages (${#pkgs[@]}):"
printf '  %s\n' "${pkgs[@]}"

repo-add --sign "${REPO_NAME}.db.tar.gz" "${pkgs[@]}"

# repo-add leaves the short names as symlinks. Pages preserves
# them as symlink entries, so turn them into real files.
for link in "${REPO_NAME}.db" "${REPO_NAME}.db.sig" "${REPO_NAME}.files" "${REPO_NAME}.files.sig"; do
  if [ -L "$link" ]; then
    target=$(readlink "$link")
    rm "$link"
    cp "$target" "$link"
  fi
done

echo "Repository contents:"
ls -lah
