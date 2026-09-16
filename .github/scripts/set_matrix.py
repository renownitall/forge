#!/usr/bin/env python3
"""Determine which packages the build workflow should build.

Event handling:
* push              - diff-based detection, ci(rebuild): parsing, and pruning
                      of removed packages against the live published manifest
* schedule          - upstream freshness check for every package
* workflow_dispatch - rebuild everything, or run the upstream check when the
                      `check_upstream` input is set

Upstream probes:
* unpinned git source - remote HEAD vs the revision baked into the published
  version; commit-date pkgvers are compared by date instead
* release archive     - newest version-like upstream tag vs the tag in the
  download URL; drift opens a PR that bumps the PKGBUILD (version, URL,
  checksum) instead of rebuilding the stale package

Fail-open: whenever upstream state cannot be determined (manifest missing,
ls-remote failure, unreadable PKGBUILD) the package is scheduled for build.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGES_DIR = ROOT / "packages"
ZERO_SHA = "0" * 40
DRY_RUN = "--dry-run" in sys.argv

PAGES_URL = os.environ.get("PAGES_URL", "")
REPO = os.environ.get("GITHUB_REPOSITORY", "")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
BASE_BRANCH = os.environ.get("GITHUB_REF_NAME", "main")
BOT_NAME = "github-actions[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"

SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
DATE_RE = re.compile(r"^\d{4}\.\d{2}\.\d{2}$")
VERSION_TAG_RE = re.compile(r"^[vV]?\d+(?:[._-]\d+)*$")
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


def http_bytes(url: str, timeout: int = 300) -> bytes | None:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "forge-ci"}), timeout=timeout) as resp:
            return resp.read()
    except Exception:
        return None


def api(method: str, path: str, body: dict | None = None) -> tuple[int, object]:
    headers = {"User-Agent": "forge-ci", "Accept": "application/vnd.github+json"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"https://api.github.com{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = resp.read()
            return resp.status, json.loads(payload) if payload else None
    except urllib.error.HTTPError as err:
        return err.code, None
    except Exception:
        return 0, None


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


def release_archive(sources: list[str]) -> str | None:
    for entry in sources:
        if "/releases/download/" in entry:
            return entry.split("::", 1)[-1]
    return None


def ls_remote(url: str, ref: str = "HEAD") -> str | None:
    for attempt in range(1, 4):
        result = run(["git", "ls-remote", url, ref])
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.split()[0]
        if attempt < 3:
            time.sleep(10)
    return None


def latest_tag(repo_url: str) -> str | None:
    for attempt in range(1, 4):
        result = run(["git", "ls-remote", "--tags", "--refs", repo_url])
        if result.returncode == 0:
            tags = [line.split("refs/tags/", 1)[-1] for line in result.stdout.splitlines()]
            tags = [t for t in tags if VERSION_TAG_RE.match(t)]
            if tags:
                def version_key(tag: str) -> tuple[int, ...]:
                    return tuple(int(p) for p in re.split(r"[._-]", re.sub(r"^[vV]", "", tag)))
                return max(tags, key=version_key)
        if attempt < 3:
            time.sleep(10)
    return None


def upstream_commit_date(git_url: str, sha: str) -> str | None:
    match = GITHUB_REPO_RE.match(git_url)
    if not match:
        return None
    owner, repo = match.group(1), match.group(2)
    if repo.endswith(".git"):
        repo = repo[:-4]
    for _ in range(3):
        data = http_json(f"https://api.github.com/repos/{owner}/{repo}/commits/{sha}", timeout=30)
        date = (data or {}).get("commit", {}).get("committer", {}).get("date", "")
        if date:
            return date[:10]
        time.sleep(10)
    return None


def strip_v(tag: str) -> str:
    return tag[1:] if tag[:1] in ("v", "V") else tag


# -------------------------------------------------------------- release PRs


def bump_pkgbuild(pkg: str, old_tag: str, new_tag: str, new_sha256: str,
                  old_url: str, new_url: str) -> bool:
    """Rewrite version, URL and checksum for a release-archived package.
    Only packages matching the trivial single-source template are bumped.

    The source URL may be templated with ${pkgver}; templating is kept only
    when bumping the version still yields the verified asset URL (upstream
    changing tag schemes, e.g. v1.7.2 -> 1.8.0, falls back to a literal URL).
    """
    old_version, new_version = strip_v(old_tag), strip_v(new_tag)
    path = PACKAGES_DIR / pkg / "PKGBUILD"
    text = path.read_text()
    sums = re.search(r"(?m)^sha256sums=.*$", text)
    hashes = re.findall(r"\b[0-9a-fA-F]{64}\b", sums.group(0)) if sums else []
    url_line = next((line for line in text.splitlines() if "/releases/download/" in line), None)
    if (
        url_line is None
        or not re.search(rf"(?m)^pkgver={re.escape(old_version)}$", text)
        or len(hashes) != 1
    ):
        return False
    if "${pkgver}" in url_line or "$pkgver" in url_line:
        if old_url.replace(old_version, new_version) != new_url:
            # Templated expansion no longer matches the verified asset URL
            # (upstream changed tag schemes, e.g. v1.7.2 -> 1.8.0): fall back
            # to a literal URL, preserving the optional name prefix.
            match = re.search(r'source=\("(.*)"\)', url_line)
            inner = match.group(1) if match else ""
            prefix, sep, tail = inner.partition("::")
            new_inner = f"{prefix}::{new_url}" if sep and "://" in tail else new_url
            text = text.replace(url_line, f'source=("{new_inner}")')
    elif old_tag in url_line:
        text = text.replace(url_line, url_line.replace(old_tag, new_tag))
    else:
        return False
    text = re.sub(rf"(?m)^pkgver={re.escape(old_version)}$", f"pkgver={new_version}", text, count=1)
    text = text.replace(hashes[0], new_sha256)
    path.write_text(text)
    return True


def pr_open(branch: str) -> bool:
    status, prs = api("GET", f"/repos/{REPO}/pulls?head={REPO}:{branch}&state=open")
    return status == 200 and bool(prs)


def handle_release_drift(groups: dict[str, dict]) -> set[str]:
    """Open (or reuse) one PR per upstream for drifted release packages.
    Returns the packages that still need a build because no PR was possible."""
    need_build: set[str] = set()
    for repo_url, info in sorted(groups.items()):
        new_tag, pkgs = info["tag"], info["packages"]
        names = ", ".join(sorted(pkgs))
        slug = repo_url.split("https://github.com/", 1)[-1].strip("/").replace("/", "-")
        branch = f"bump/{slug}-{strip_v(new_tag)}"

        if pr_open(branch):
            log(f"  PR    {names} (already open for {new_tag})")
            continue
        if DRY_RUN:
            log(f"  PR    {names} (dry run: would open a PR bumping to {new_tag})")
            continue

        failed = False
        for pkg in sorted(pkgs):
            archive_url, old_tag = pkgs[pkg]
            new_url = archive_url.replace(old_tag, new_tag)
            blob = http_bytes(new_url)
            if blob is None:
                warn(f"{pkg}: release asset for {new_tag} unreachable, cannot open a PR")
                failed = True
                break
            if not bump_pkgbuild(pkg, old_tag, new_tag, hashlib.sha256(blob).hexdigest(),
                                 archive_url, new_url):
                warn(f"{pkg}: PKGBUILD does not match the release template, cannot open a PR")
                failed = True
                break
        if failed:
            run(["git", "checkout", "--", "packages/"])
            need_build.update(pkgs)
            continue

        staged = sorted(pkgs)
        names = " and ".join(staged) if len(staged) == 2 else ", ".join(staged)
        title = f"chore(packages): update {names} to {new_tag}"
        body = "\n".join([
            "Automated upstream bump opened by the daily freshness check.",
            "",
            f"- Upstream tag: `{new_tag}`",
            f"- Packages: {', '.join(f'`{p}`' for p in staged)}",
            "- `sha256sums` recomputed from the release artifact",
            "",
            "Merging this PR triggers the regular build and publish pipeline.",
        ])
        if run(["git", "add", *(f"packages/{p}/PKGBUILD" for p in staged)]).returncode != 0:
            warn("could not stage PKGBUILD changes")
            run(["git", "checkout", "--", "packages/"])
            need_build.update(pkgs)
            continue
        commit = run(["git", "-c", f"user.name={BOT_NAME}", "-c", f"user.email={BOT_EMAIL}",
                      "commit", "-m", title])
        if commit.returncode != 0:
            warn("could not commit PKGBUILD changes")
            run(["git", "reset", "--hard"])
            need_build.update(pkgs)
            continue
        push = run(["git", "push", "origin", f"HEAD:refs/heads/{branch}"])
        if push.returncode != 0:
            # A branch may linger from an aborted run; replace it and retry.
            run(["git", "push", "origin", f":refs/heads/{branch}"])
            push = run(["git", "push", "origin", f"HEAD:refs/heads/{branch}"])
        if push.returncode != 0:
            warn(f"could not push branch {branch}")
            run(["git", "reset", "--hard", "HEAD~1"])
            need_build.update(pkgs)
            continue
        status, _ = api("POST", f"/repos/{REPO}/pulls",
                        {"title": title, "head": branch, "base": BASE_BRANCH, "body": body})
        if status not in (200, 201):
            warn(f"PR creation for {branch} failed (HTTP {status})")
            run(["git", "reset", "--hard", "HEAD~1"])
            need_build.update(pkgs)
            continue
        log(f"  PR    {names} (opened for {new_tag})")
    return need_build


def upstream_check(packages: list[str], published: dict[str, str]) -> list[str]:
    build: list[str] = []
    drift: dict[str, dict] = {}

    for pkg in packages:
        sha, date = published_revision(published.get(pkg))
        sources = read_sources(pkg)
        if sources is None:
            log(f"  Build {pkg} (could not read PKGBUILD)")
            build.append(pkg)
            continue

        urls = unpinned_git_urls(sources)
        if len(urls) > 1:
            log(f"  Build {pkg} (expected 1 unpinned git source, found {len(urls)})")
            build.append(pkg)
            continue

        if len(urls) == 1:
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
            continue

        archive = release_archive(sources)
        if archive is None:
            log(f"  Build {pkg} (no git source or release archive to probe)")
            build.append(pkg)
            continue
        old_tag = archive.split("/releases/download/", 1)[1].split("/", 1)[0]
        repo_url = archive.split("/releases/", 1)[0]

        new_tag = latest_tag(repo_url)
        if new_tag is None:
            log(f"  Build {pkg} (ls-remote tags failed after 3 attempts)")
            build.append(pkg)
            continue
        if strip_v(new_tag) == strip_v(old_tag):
            log(f"  Skip  {pkg} (latest tag {new_tag} matches published {old_tag})")
            continue
        log(f"  Bump  {pkg} (latest tag {new_tag} != published {old_tag})")
        group = drift.setdefault(repo_url, {"tag": new_tag, "packages": {}})
        group["packages"][pkg] = (archive, old_tag)

    need_build = handle_release_drift(drift) if drift else set()
    return sorted(set(build) | need_build)


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
            and event.get("inputs", {}).get("check_upstream") is True
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
