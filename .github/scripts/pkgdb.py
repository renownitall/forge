#!/usr/bin/env python3
"""Shared parser for pacman repository database records.

Both the repository database (`forge.db.tar.gz`) and the files database
(`forge.files.tar.gz`) are tar archives whose members are per-package `desc`
files. A `desc` file is a sequence of `%KEY%` lines, each followed by one or
more value lines until the next `%KEY%`.

This module is the single parser for that format. The build workflow uses
`manifest` to generate `packages.json`, and the fetch-repo action uses `index`
to list the packages that are already published.
"""

from __future__ import annotations

import json
import sys
import tarfile
from collections.abc import Iterator
from pathlib import Path


def parse_desc(text: str) -> dict[str, list[str]]:
    """Parse one `desc` file into a mapping of field name to value lines."""
    fields: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("%") and line.endswith("%"):
            current = line.strip("%")
            fields[current] = []
        elif current is not None and line:
            fields[current].append(line)
    return fields


def read_records(path: Path) -> Iterator[dict[str, list[str]]]:
    """Yield the parsed `desc` record from each package directory in an archive."""
    with tarfile.open(path, "r:*") as archive:
        for member in archive.getmembers():
            if not member.isfile() or Path(member.name).name != "desc":
                continue
            handle = archive.extractfile(member)
            if handle is not None:
                yield parse_desc(handle.read().decode("utf-8", "replace"))


def first(fields: dict[str, list[str]], key: str) -> str:
    values = fields.get(key)
    return values[0] if values else ""


def as_int(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        return 0


def manifest(path: Path) -> dict:
    """Build the site manifest from a repository database archive."""
    packages = []
    for fields in read_records(path):
        name = first(fields, "NAME")
        if not name:
            continue
        packages.append({
            "name": name,
            "base": first(fields, "BASE"),
            "version": first(fields, "VERSION"),
            "description": first(fields, "DESC"),
            "size": as_int(first(fields, "CSIZE")),
            "built": as_int(first(fields, "BUILDDATE")),
            "arch": first(fields, "ARCH"),
        })
    packages.sort(key=lambda package: package["name"].encode())
    return {"packages": packages}


def index(path: Path) -> list[tuple[str, str, str]]:
    """List (name, base, filename) for every package in a files database archive."""
    rows = set()
    for fields in read_records(path):
        name = first(fields, "NAME")
        base = first(fields, "BASE")
        filename = first(fields, "FILENAME")
        if name and base and filename:
            rows.add((name, base, filename))
    return sorted(rows)


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[1] not in ("manifest", "index"):
        print("usage: pkgdb.py {manifest|index} <archive.tar.gz>", file=sys.stderr)
        return 2
    command, archive = argv[1], Path(argv[2])
    if command == "manifest":
        json.dump(manifest(archive), sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        for name, base, filename in index(archive):
            print(f"{name}\t{base}\t{filename}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
