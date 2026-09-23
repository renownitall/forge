#!/usr/bin/env python3
"""Determine which packages the build workflow should build.

Event handling:
* push              - diff-based detection, ci(rebuild): parsing, and pruning
                      of removed packages against the live published manifest
* schedule          - upstream freshness check for every package
* workflow_dispatch - rebuild everything, or run the upstream check when the
                      `check_upstream` input is set

Upstream probe: compare the remote HEAD of each unpinned git source against the
revision baked into the published version. Packages whose pkgver is a commit
date are compared by date instead.

Held packages: a `# forge-ci: hold` comment in a PKGBUILD skips the
upstream probe for that package entirely, so intentionally held
versions are never rebuilt by the scheduled check.

Fail-open: whenever upstream state cannot be determined (manifest missing,
ls-remote failure, unreadable PKGBUILD) the package is scheduled for build.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGES_DIR = ROOT / "packages"
ZERO_SHA = "0" * 40

PAGES_URL = os.environ.get("PAGES_URL", "")
TOKEN = os.environ.get("GITHUB_TOKEN", "")

SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
DATE_RE = re.compile(r"^\d{4}\.\d{2}\.\d{2}$")
GITHUB_REPO_RE = re.compile(r"^https://github\.com/([^/]+)/([^/]+)")


def log(msg: str) -> None:
    print(msg, flush=True)


def warn(msg: str) -> None:
    print(f"::warning::{msg}", flush=True)


def set_output(key: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as fh:
            fh.write(f"{key}={value}\n")


def run(cmd: list[str], cwd: Path | None = None, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def http_json(url: str, timeout: int = 60) -> dict | None:
    headers = {"User-Agent": "forge-ci", "Accept": "application/vnd.github+json"}
    if TOKEN and "://api.github.com/" in url:
        headers["Authorization"] = f"Bearer {TOKEN}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as resp:
            return json.load(resp)
    except Exception:
        return None


# ---------------------------------------------------------------- repo state


def all_packages() -> list[str]:
    if not PACKAGES_DIR.is_dir():
        return []
    return sorted(p.name for p in PACKAGES_DIR.iterdir() if (p / "PKGBUILD").is_file())


def object_exists(sha: str) -> bool:
    return run(["git", "cat-file", "-e", sha]).returncode == 0


def diff_bases(before: str, after: str) -> list[str]:
    result = run(["git", "diff", "--name-only", before, after, "--", "packages/"])
    if result.returncode != 0:
        return []
    bases = set()
    for line in result.stdout.splitlines():
        parts = line.split("/")
        if len(parts) > 1 and parts[1]:
            bases.add(parts[1])
    return sorted(bases)


def commit_subject(sha: str) -> str:
    result = run(["git", "log", "-1", "--format=%s", sha])
    return result.stdout.strip() if result.returncode == 0 else ""


def read_sources(pkg: str) -> list[str] | None:
    # PKGBUILDs are bash; sourcing them resolves variables like $_pkgname
    # used in the source array.
    result = run(
        ["bash", "-c", 'source ./PKGBUILD >/dev/null 2>&1 && printf \'%s\\n\' "${source[@]}"'],
        cwd=PACKAGES_DIR / pkg,
    )
    if result.returncode != 0:
        return None
    return [line for line in result.stdout.splitlines() if line]


def on_hold(pkg: str) -> bool:
    return bool(re.search(r"(?m)^#\s*forge-ci:\s*hold\b", (PACKAGES_DIR / pkg / "PKGBUILD").read_text()))


# ------------------------------------------------------------------ upstream


def published_revision(version: str | None) -> tuple[str, str]:
    """Extract (sha, date) from a published version such as
    0.0.0.r16.gcdef1c8-1, r7135.8775477-1 or 2026.08.24-1."""
    if not version:
        return "", ""
    base = version.rsplit("-", 1)[0].rsplit(":", 1)[-1]
    last = base.rsplit(".", 1)[-1]
    if last.startswith("g"):
        last = last[1:]
    sha = last if SHA_RE.match(last) else ""
    return sha, (base if DATE_RE.match(base) else "")


def unpinned_git_urls(sources: list[str]) -> list[str]:
    # Pinned sources (#commit=/#tag=) can only change via a PKGBUILD push,
    # which has its own path.
    urls = []
    for entry in sources:
        if "git+" not in entry:
            continue
        tail = entry.split("git+", 1)[1]
        if re.search(r"#(commit|tag)=", tail):
            continue
        urls.append(tail)
    return urls


def retrying(attempt: Callable[[], tuple[bool, str | None]]) -> str | None:
    """Call attempt() up to 3 times; (True, value) stops, (False, None) retries."""
    for i in range(1, 4):
        done, value = attempt()
        if done:
            return value
        if i < 3:
            time.sleep(10)
    return None


def ls_remote(url: str, ref: str = "HEAD") -> str | None:
    def attempt() -> tuple[bool, str | None]:
        result = run(["git", "ls-remote", url, ref])
        if result.returncode == 0 and result.stdout.strip():
            return True, result.stdout.split()[0]
        return False, None

    return retrying(attempt)


def upstream_commit_date(git_url: str, sha: str) -> str | None:
    match = GITHUB_REPO_RE.match(git_url)
    if not match:
        return None
    owner, repo = match.group(1), match.group(2)
    if repo.endswith(".git"):
        repo = repo[:-4]

    def attempt() -> tuple[bool, str | None]:
        data = http_json(f"https://api.github.com/repos/{owner}/{repo}/commits/{sha}", timeout=30)
        date = (data or {}).get("commit", {}).get("committer", {}).get("date", "")
        return (True, date[:10]) if date else (False, None)

    return retrying(attempt)


def upstream_check(packages: list[str], published: dict[str, str]) -> list[str]:
    build: list[str] = []

    for pkg in packages:
        sha, date = published_revision(published.get(pkg))
        if on_hold(pkg):
            log(f"  Skip  {pkg} (forge-ci: hold)")
            continue
        sources = read_sources(pkg)
        if sources is None:
            log(f"  Build {pkg} (could not read PKGBUILD)")
            build.append(pkg)
            continue

        urls = unpinned_git_urls(sources)
        if len(urls) != 1:
            log(f"  Build {pkg} (expected 1 unpinned git source, found {len(urls)})")
            build.append(pkg)
            continue

        url = urls[0]
        ref = "HEAD"
        if "#branch=" in url:
            ref = "refs/heads/" + url.split("#branch=", 1)[1]
        clean_url = url.split("#", 1)[0]

        remote = ls_remote(clean_url, ref)
        if remote is None:
            log(f"  Build {pkg} (ls-remote failed after 3 attempts)")
            build.append(pkg)
            continue
        if sha:
            if remote.startswith(sha):
                log(f"  Skip  {pkg} (upstream {remote[:7]} matches published {sha})")
            else:
                log(f"  Build {pkg} (upstream {remote[:7]} != published {sha})")
                build.append(pkg)
        elif date:
            upstream = upstream_commit_date(clean_url, remote)
            if upstream is None:
                log(f"  Build {pkg} (could not resolve upstream commit date)")
                build.append(pkg)
                continue
            upstream = upstream.replace("-", ".")
            # A newer upstream date means upstream moved; equal or older
            # means the published build is already current.
            if upstream > date:
                log(f"  Build {pkg} (upstream {upstream} != published {date})")
                build.append(pkg)
            else:
                log(f"  Skip  {pkg} (upstream {upstream} not past published {date})")
        else:
            log(f"  Build {pkg} (not published or no comparable revision in '{published.get(pkg, '')}')")
            build.append(pkg)

    return sorted(set(build))


# -------------------------------------------------------------- event paths


def push_path(packages: list[str], event: dict) -> tuple[list[str], list[str]]:
    before, after = event.get("before", ""), event.get("after", "")

    if before == ZERO_SHA:
        return list(packages), []

    if not object_exists(before):
        warn(f"before SHA {before} not found locally, attempting to fetch")
        run(["git", "fetch", "origin", before, "--depth=1"])
    if object_exists(before):
        bases = diff_bases(before, after)
    else:
        warn("before SHA still not found, falling back to HEAD~1 diff")
        bases = diff_bases("HEAD~1", "HEAD")

    build = [p for p in bases if p in packages]
    removed = [p for p in bases if p not in packages]
    if removed:
        log(f"Removed packages detected: {' '.join(removed)}")

    if not build:
        match = re.match(r"^ci\(rebuild\):\s+(.+)$", commit_subject(event.get("sha", "")))
        if match:
            for raw in match.group(1).split(","):
                pkg = raw.strip()
                if pkg in packages:
                    build.append(pkg)
                elif pkg:
                    warn(f"unknown package '{pkg}' in ci(rebuild)")
            build = sorted(set(build))

    prune = list(removed)
    live = http_json(f"{PAGES_URL}/packages.json", timeout=30) if PAGES_URL else None
    if live:
        stale = sorted({p.get("base") for p in live.get("packages", [])
                        if p.get("base") and p.get("base") not in packages})
        if stale:
            log(f"Stale published packages detected: {' '.join(stale)}")
        prune = sorted(set(removed) | set(stale))
    return build, prune


def check_path(packages: list[str], check_upstream: bool) -> list[str]:
    if not check_upstream:
        return list(packages)
    manifest = http_json(f"{PAGES_URL}/packages.json", timeout=60) if PAGES_URL else None
    if manifest is None:
        warn("Could not fetch published manifest; rebuilding all candidates")
        return list(packages)
    published = {p.get("base"): p.get("version", "") for p in manifest.get("packages", []) if p.get("base")}
    return upstream_check(packages, published)


def main() -> None:
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    event: dict = {}
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if event_path and Path(event_path).is_file():
        event = json.loads(Path(event_path).read_text())

    packages = all_packages()
    if not packages:
        log("No packages found in repository")
        set_output("has_packages", "false")
        set_output("matrix", json.dumps({"package": []}))
        set_output("has_removed", "false")
        return

    if event_name == "push":
        build, prune = push_path(packages, event)
    else:
        check = event_name == "schedule" or (
            event_name == "workflow_dispatch"
            and event.get("inputs", {}).get("check_upstream") in (True, "true")
        )
        build, prune = check_path(packages, check), []

    build = sorted(set(build))
    if build:
        set_output("has_packages", "true")
        set_output("matrix", json.dumps({"package": build}))
        log("Building: " + " ".join(build))
    else:
        set_output("has_packages", "false")
        set_output("matrix", json.dumps({"package": []}))
        log("No packages to build")

    if event_name == "push" and prune:
        set_output("has_removed", "true")
        log("Pruning required for: " + " ".join(prune))
    else:
        set_output("has_removed", "false")


if __name__ == "__main__":
    main()
