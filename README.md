# Forge

Hi. This is my custom Arch Linux package repository.

The packages are built, signed with _GNU Privacy Guard (GPG)_, and published automatically. They're hosted on GitHub Pages, and every push to `main` and every scheduled run at 04:37 UTC rebuilds all of them. Git packages recompute `pkgver()` during the build, so versions advance only when upstream has actually moved. If you run Arch Linux, you can install these packages with `pacman`.

> [!CAUTION]
> Every package this repo compiles from source targets `x86-64-v3` and needs a compatible CPU. Prebuilt packages, scripts, and themes run on any `x86_64` machine.

## Setup

1. Import and trust the signing key:

   ```bash
   curl -fsSL https://renownitall.github.io/forge/signing_key.asc -o /tmp/forge-signing-key.asc
   sudo pacman-key --add /tmp/forge-signing-key.asc
   sudo pacman-key --lsign-key 45EAC3E28FC392FC4418F415C0C5B611BF77F6E5
   ```

2. Add the following block to your `/etc/pacman.conf`:

   ```ini
   [forge]
   SigLevel = Required DatabaseOptional
   Server = https://renownitall.github.io/forge
   ```

3. Sync and install:

   ```bash
   sudo pacman -Syu
   sudo pacman -S PACKAGE_NAME
   ```

`pacman -Sl forge` lists everything that's published.

## Development

Run `make check` before committing. To skip a package temporarily, create an empty `packages/NAME/HOLD` file. The package stays out of the next build and leaves the repository on the next publish.

---

Enjoy.
