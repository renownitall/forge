#!/usr/bin/env bash
set -euo pipefail

pacman-key --init
pacman-key --populate archlinux
.github/scripts/retry.sh pacman -Syu --noconfirm --noprogressbar
.github/scripts/retry.sh pacman -S --noconfirm --needed --noprogressbar git mold pacman-contrib

sed -i 's/-march=x86-64 -mtune=generic/-march=x86-64-v3/g' /etc/makepkg.conf
sed -i '/^OPTIONS=/s/!lto/lto/' /etc/makepkg.conf
sed -i '/^OPTIONS=/s/ debug / !debug /' /etc/makepkg.conf
sed -i 's/-mno-omit-leaf-frame-pointer"/-mno-omit-leaf-frame-pointer -mpclmul"/' /etc/makepkg.conf
sed -i 's/LTOFLAGS="-flto=auto"/LTOFLAGS="-flto=auto -falign-functions=32"/' /etc/makepkg.conf

NPROC=$(nproc)
sed -i "s/#MAKEFLAGS=\"-j2\"/MAKEFLAGS=\"-j${NPROC}\"/" /etc/makepkg.conf

cat >>/etc/makepkg.conf <<'EOF'
RUSTFLAGS="-Cforce-frame-pointers=yes -Copt-level=3 -Ctarget-cpu=x86-64-v3 -Clink-arg=-z -Clink-arg=pack-relative-relocs -Ccodegen-units=1 -Clink-arg=-fuse-ld=mold"
export CARGO_PROFILE_RELEASE_LTO=fat
export GOAMD64=v3
EOF

sed -i 's/COMPRESSZST=(zstd -c -T0 -)/COMPRESSZST=(zstd -c -T0 -q -19 -)/' /etc/makepkg.conf

# Every mutation above has to have applied. A silent no-op here
# publishes packages with the wrong build options, which already
# happened when the compression sed stopped matching Arch's line.
assert() {
  grep -qE -- "$1" /etc/makepkg.conf || {
    echo "::error::makepkg.conf: expected but missing: $1"
    exit 1
  }
}
reject() {
  if grep -qE -- "$1" /etc/makepkg.conf; then
    echo "::error::makepkg.conf: unexpected state still present: $1"
    exit 1
  fi
}

assert '^CFLAGS=.*-march=x86-64-v3'
reject '^CFLAGS=.*-mtune=generic'
assert '^OPTIONS=.*\blto\b'
reject '^OPTIONS=.*!lto'
assert '^OPTIONS=.*!debug'
assert -- '-mpclmul'
assert -- '-falign-functions=32'
assert '^MAKEFLAGS="-j[0-9]+"'
assert '^COMPRESSZST=.*-19'
assert '^RUSTFLAGS="-Cforce-frame-pointers=yes'
assert '^export CARGO_PROFILE_RELEASE_LTO=fat'
assert '^export GOAMD64=v3'
