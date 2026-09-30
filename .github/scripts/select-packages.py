#!/usr/bin/env python3
"""Chooses what this run rebuilds and stages published copies of the rest.

Results go to GITHUB_OUTPUT, and staging/pkg.tar carries the published
copies of packages that are not rebuilt when the repo job will run.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import NoReturn

DOC_PATHS = {".editorconfig", ".gitignore", ".prettierrc", "LICENSE", "Makefile"}


def notice(title: str, message: str) -> None:
    print(f"::notice title={title}::{message}")


def fail(message: str) -> NoReturn:
    print(f"::error::{message}")
    sys.exit(1)


def list_packages() -> tuple[list[str], set[str]]:
    """Returns the packages to build and every name present under packages/."""
    target: list[str] = []
    present: set[str] = set()
    for pkgdir in sorted(Path("packages").iterdir()):
        if not (pkgdir / "PKGBUILD").is_file():
            continue
        present.add(pkgdir.name)
        if (pkgdir / "HOLD").is_file():
            notice("Held package", f"{pkgdir.name} is held ({pkgdir}/HOLD)")
        else:
            target.append(pkgdir.name)
    return target, present


def classify(event: str, before: str, sha: str) -> tuple[bool, set[str]]:
    """Returns whether the run rebuilds everything and the changed package names."""
    if event != "push":
        print(f"A {event} event arrives without a push diff")
        return True, set()
    if not before or set(before) == {"0"}:
        print("No previous commit accompanied this push")
        return True, set()
    try:
        diff = subprocess.run(
            ["git", "diff", "--name-status", before, sha],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except subprocess.CalledProcessError:
        print("The previous commit has vanished from this history")
        return True, set()

    full = False
    changed: set[str] = set()
    reasons: list[str] = []
    for line in diff.splitlines():
        for path in line.split("\t")[1:]:
            if path.startswith("packages/"):
                changed.add(path.split("/")[1])
            elif path.startswith(".github/") or path == "signing_key.asc":
                full = True
                reasons.append(path)
            elif path.endswith(".md") or path in DOC_PATHS:
                continue
            else:
                full = True
                reasons.append(path)
    if full:
        unique = list(dict.fromkeys(reasons))
        shown = ", ".join(unique[:5])
        if len(unique) > 5:
            shown += f" and {len(unique) - 5} more files"
        print(f"Every package joins because the diff touches {shown}")
    return full, changed


def parse_desc(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    lines = text.splitlines()
    for index in range(len(lines) - 1):
        line = lines[index]
        if line.startswith("%") and line.endswith("%") and len(line) > 2:
            fields[line.strip("%")] = lines[index + 1]
    return fields


def fetch_database(pages_base: str, repo_name: str) -> dict[str, str] | None:
    """Returns published names mapped to filenames, or None when unreadable."""
    url = f"{pages_base}/{repo_name}.db"
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read()
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            mapping: dict[str, str] = {}
            for member in archive.getmembers():
                if not member.name.endswith("/desc"):
                    continue
                stream = archive.extractfile(member)
                if stream is None:
                    continue
                fields = parse_desc(stream.read().decode("utf-8"))
                name = fields.get("NAME", "")
                filename = fields.get("FILENAME", "")
                if name and filename:
                    mapping[name] = filename
            return mapping
    # Every kind of failure here means bootstrap mode.
    except Exception:  # noqa: BLE001
        return None


def gpg(
    env: dict[str, str], *args: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["gpg", *args],
        env=env,
        check=check,
        capture_output=True,
        text=True,
    )


def signing_fingerprint(env: dict[str, str]) -> str:
    result = gpg(env, "--batch", "--with-colons", "--list-keys", check=False)
    for line in result.stdout.splitlines():
        if line.startswith("fpr:"):
            return line.split(":")[9]
    return ""


def verify_signature(
    env: dict[str, str], signature: Path, package: Path, expected: str
) -> bool:
    result = gpg(
        env,
        "--batch",
        "--status-fd=1",
        "--verify",
        str(signature),
        str(package),
        check=False,
    )
    for line in result.stdout.splitlines():
        if line.startswith("[GNUPG:] VALIDSIG "):
            tokens = line.split()
            return expected in tokens
    return False


def stage_published(
    needed: list[str], published: dict[str, str], pages_base: str
) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "gnupg"
        home.mkdir(mode=0o700)
        env = {**os.environ, "GNUPGHOME": str(home)}
        gpg(env, "--batch", "--import", "signing_key.asc", check=False)
        expected = signing_fingerprint(env)
        if not expected:
            fail("No fingerprint in signing_key.asc")

        files = Path(tmp) / "files"
        files.mkdir()
        for name in needed:
            filename = published.get(name, "")
            if not filename:
                fail(f"{name} is missing from the published database")
            for url_path in (filename, filename + ".sig"):
                url = f"{pages_base}/{url_path}"
                try:
                    with urllib.request.urlopen(url, timeout=60) as response:
                        (files / url_path).write_bytes(response.read())
                except (urllib.error.URLError, OSError) as exc:
                    fail(f"Downloading {url} failed with {exc}")
            signature = files / (filename + ".sig")
            if not verify_signature(env, signature, files / filename, expected):
                fail(f"The signature on {filename} does not match {expected}")

        staging = Path("staging")
        staging.mkdir(exist_ok=True)
        with tarfile.open(staging / "pkg.tar", "w") as archive:
            for path in sorted(files.iterdir()):
                archive.add(path, arcname=path.name)
    notice(
        "Staged published copies",
        f"{len(needed)} packages carry over from the published repository",
    )


def main() -> None:
    target, present = list_packages()
    event = os.environ.get("GITHUB_EVENT_NAME", "push")
    before = os.environ.get("EVENT_BEFORE", "")
    sha = os.environ.get("GITHUB_SHA", "")
    pages_base = os.environ["PAGES_BASE"]
    full, changed = classify(event, before, sha)

    published = fetch_database(pages_base, os.environ["REPO_NAME"])
    if published is None:
        print("The published database failed to load")
        full = True

    if full:
        selected = set(target)
    else:
        # Packages the published database is missing join the matrix here,
        # catching up after a failed run.
        selected = (changed & set(target)) | (set(target) - set(published or {}))
    removals = set(published or {}) - present

    if removals:
        notice("Leaving the repository", " ".join(sorted(removals)))

    will_publish = bool(selected) or bool(removals)
    needed = sorted(set(target) - selected) if will_publish else []
    if needed:
        stage_published(needed, published or {}, pages_base)

    if selected:
        print(f"Packages to build ({len(selected)}): {', '.join(sorted(selected))}")
    elif removals:
        notice(
            "Nothing to build",
            "The build job will skip while the repo job publishes the removals",
        )
    else:
        notice("Nothing to publish", "The build, repo, and deploy jobs will skip")

    matrix = json.dumps({"package": sorted(selected)})
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"matrix={matrix}\n")
        output.write(f"has_packages={'true' if selected else 'false'}\n")
        output.write(f"has_removals={'true' if removals else 'false'}\n")
        output.write(f"staged={'true' if needed else 'false'}\n")


if __name__ == "__main__":
    main()
