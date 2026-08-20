# Forge

Hi. This is my custom Arch Linux package repository. All packages are compiled with `x86-64-v3` optimizations and signed with _GNU Privacy Guard (GPG)_.

A GitHub Actions workflow builds, signs, and publishes the packages, and GitHub Pages hosts the published repository. If you run Arch Linux, you can install these packages with `pacman`.

> [!CAUTION]
> The packages in this repository need an `x86-64-v3` capable CPU. They might not run on older generic `x86_64` machines.

## Set up the repository

To set up the repository, follow these steps:

1. Import and trust the signing key by running the following commands:

   ```bash
   curl -fsSL https://renownitall.github.io/forge/signing_key.asc -o /tmp/forge-signing-key.asc
   sudo pacman-key --add /tmp/forge-signing-key.asc
   sudo pacman-key --lsign-key 45EAC3E28FC392FC4418F415C0C5B611BF77F6E5
   ```

2. Add the following block to `/etc/pacman.conf`:

   ```ini
   [forge]
   SigLevel = Required DatabaseOptional
   Server = https://renownitall.github.io/forge
   ```

3. Sync your system and install a package by running the following commands:

   ```bash
   sudo pacman -Syu
   sudo pacman -S PACKAGE_NAME
   ```

   Replace `PACKAGE_NAME` with the name of the package you want to install, for example `lutgen-cli-git`.

## Available packages

The following packages are available:

| Package                    | Description                                                                                                     |
| -------------------------- | --------------------------------------------------------------------------------------------------------------- |
| `lutgen-cli-git`           | Recolors images, like wallpapers, to match a color theme such as Catppuccin, Gruvbox, or Nord.                  |
| `orchis-theme-square`      | Orchis GTK theme built with fully square corners instead of rounded ones.                                       |
| `ttf-googlesans-code`      | Google Sans Code, Google's monospace coding font.                                                               |
| `ttf-googlesans-code-nerd` | Google Sans Code patched with Nerd Font icons.                                                                  |
| `ttf-noto-sans-mono-nerd`  | Noto Sans Mono patched with Nerd Fonts in all weights, with NF, Mono, and Propo static TrueType variants.       |
| `wayfreeze-git`            | Pauses your screen so you can draw a selection and take a screenshot without anything moving under your cursor. |
| `xdg-terminal-exec-git`    | Lets apps and scripts open your preferred terminal emulator without needing to know which one you use.          |

## Add a package

To add a package to the repository, follow these steps:

1. Create `packages/PACKAGE_NAME/PKGBUILD`, replacing `PACKAGE_NAME` with the name of the package.
2. Push the changes to `main`.
3. The workflow detects the new package, builds it, signs it, and deploys it automatically.

## Remove a package

To remove a package, follow these steps:

1. Delete `packages/PACKAGE_NAME/PKGBUILD`.
2. Push the changes to `main`.
3. The workflow removes the package's binaries and database entry from the published repository on the next run.

## How it works

A GitHub Actions workflow with the following jobs builds and publishes the repository:

| Job                | Purpose                                                                                                                                                      |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `changed-packages` | Determines which packages need rebuilding based on the trigger type and changed files.                                                                       |
| `build`            | Builds each package in an Arch Linux container and signs it with GPG.                                                                                        |
| `repo`             | Collects the built packages and fetches the ones already published. Prunes packages removed from the source tree and generates a signed `repo-add` database. |
| `deploy`           | Publishes the repository to GitHub Pages.                                                                                                                    |

Scheduled builds run daily at 04:37 UTC to pick up upstream changes for `-git` packages.

---

Enjoy.
