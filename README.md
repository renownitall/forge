# Forge

My custom Arch Linux package repository, built with GitHub Actions and served via GitHub Pages.

All packages are compiled with `x86-64-v3` optimizations and signed with GPG.

> [!WARNING]
> Binary packages in this repository require an `x86-64-v3` capable CPU. They may not run on older generic `x86_64` machines.

## Setup

Import the signing key:

```bash
sudo pacman-key --add <(curl -fsSL https://renownitall.github.io/forge/signing_key.asc)
sudo pacman-key --lsign-key 45EAC3E28FC392FC4418F415C0C5B611BF77F6E5
```

Add the repository to `/etc/pacman.conf`:

```ini
[forge]
SigLevel = Required DatabaseOptional
Server = https://renownitall.github.io/forge
```

Sync and install packages:

```bash
sudo pacman -Syu
sudo pacman -S <package-name>
```

## Available packages

| Package                    | Description                                                                                                             |
| -------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `lutgen-cli-git`           | Recolors images (like wallpapers) to match a color theme such as Catppuccin, Gruvbox, or Nord                           |
| `orchis-theme-square`      | Orchis GTK theme built with fully square corners instead of rounded ones                                                |
| `ttf-googlesans-code`      | Google Sans Code font (Google's monospace/coding font)                                                                  |
| `ttf-googlesans-code-nerd` | Google Sans Code font patched with Nerd Font icons                                                                      |
| `wayfreeze-git`            | Pauses your screen in place so you can draw a selection and take a screenshot without anything moving under your cursor |
| `wl-screenrec`             | Records your screen to a video file using your GPU, so recording doesn't slow down your other apps                      |
| `xdg-terminal-exec`        | Lets apps and scripts open your preferred terminal emulator without needing to know which one you use                   |

## Adding a package

1. Create `packages/<package-name>/PKGBUILD`.
2. Push to `main`.
3. The workflow detects the new package, builds it, signs it, and deploys it automatically.

## How it works

1. **`changed-packages`:** Determines which packages need rebuilding based on the trigger type and changed files.
2. **`build`:** Builds each package in an Arch Linux container, signs it with GPG.
3. **`repo`:** Collects all built packages, generates a signed `repo-add` database.
4. **`deploy`:** Publishes the repository to GitHub Pages.

Scheduled builds run daily at 04:37 UTC to pick up upstream changes for `-git` packages.

---

Enjoy.
