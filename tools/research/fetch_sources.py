#!/usr/bin/env python3
"""Reproducible fetcher for the external research corpus this project's architecture work draws on.

Scope note (deliberate): this covers the P0 sources only - DLSS, Streamline, NRD, upstream
OptiScaler, and RTX-Kit (fetched for its .gitmodules map, not exhaustively expanded). P1-P3
(RTXNS/RTXPT/RTXDI/RTXGI/RTXCR/RTXMU/RTXTS/RTXTF/RTXMG/OMM/STBN/NIS, papers, issue mining) are not
fetched by this script. Extend SOURCES below when a specific investigation needs one of them -
cloning all of them unconditionally costs real disk/bandwidth for repos this project may never
open.

Never touches this repository's own working tree. Everything lands under research/, one directory
per source, and research/ is listed in .gitignore (large binary clones do not belong in this
project's own history).

Usage:
    tools/research/fetch_sources.py            # clone missing, fetch+report existing
    tools/research/fetch_sources.py --update    # same as default (fetch is always non-destructive)
    tools/research/fetch_sources.py --verify    # re-check without fetching, rewrite VALIDATION.md
    tools/research/fetch_sources.py --index     # regenerate MANIFEST.md/sources.json from current state only
"""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RESEARCH_DIR = REPO_ROOT / "research"
LOG_PATH = RESEARCH_DIR / "fetch.log"


@dataclass
class Source:
    name: str
    url: str
    subdir: str  # relative to research/
    priority: str  # P0, P1, ...
    notes: str = ""
    # None = default branch; a specific ref pins to a known-good point for reproducibility.
    ref: str | None = None
    status: str = "unknown"
    commit: str = ""
    tag: str = ""
    branch: str = ""
    error: str = ""
    discovered_submodules: list[str] = field(default_factory=list)


# P0 only. See module docstring for why P1-P3 are listed in comments, not fetched.
SOURCES: list[Source] = [
    Source("DLSS", "https://github.com/NVIDIA/DLSS", "nvidia/dlss", "P0",
           "Official DLSS SDK - integration docs, headers, sample integration code."),
    Source("Streamline", "https://github.com/NVIDIA-RTX/Streamline", "nvidia/streamline", "P0",
           "Highest priority: sl.dlss_g / sl.dlss_nr / resource tagging / frame indexing / Reflex."),
    Source("NRD", "https://github.com/NVIDIA-RTX/NRD", "nvidia/nrd", "P0",
           "REBLUR/RELAX denoisers - the closest official analogue to this fork's own DLSS-NR pass."),
    Source("RTX-Kit", "https://github.com/NVIDIA-RTX/RTX-Kit", "nvidia/rtx-kit", "P0",
           "Fetched to enumerate .gitmodules as a live map of NVIDIA's public RTX components - "
           "not expanded into its submodules by this script."),
    Source("OptiScaler-upstream", "https://github.com/optiscaler/OptiScaler", "optiscaler/upstream", "P0",
           "Upstream OptiScaler, to distinguish upstream behavior from this fork's modifications."),
    # P1 (not fetched - add here and re-run when a specific investigation needs one):
    #   RTXNS  https://github.com/NVIDIA-RTX/RTXNS
    #   RTXPT  https://github.com/NVIDIA-RTX/RTXPT
    #   RTXDI  https://github.com/NVIDIA-RTX/RTXDI
    #   RTXGI  https://github.com/NVIDIA-RTX/RTXGI
    # P2 (not fetched):
    #   RTXCR  https://github.com/NVIDIA-RTX/RTXCR
    #   RTXMU  https://github.com/NVIDIA-RTX/RTXMU
    #   RTXTS  https://github.com/NVIDIA-RTX/RTXTS
    #   RTXTF  https://github.com/NVIDIA-RTX/RTXTF
    #   RTXMG  https://github.com/NVIDIA-RTX/RTXMG
    #   OMM    https://github.com/NVIDIA-RTX/OMM
    #   STBN   https://github.com/NVIDIA-RTX/STBN
    # P3 (not fetched):
    #   NVIDIAImageScaling  https://github.com/NVIDIAGameWorks/NVIDIAImageScaling
    #   (already present locally at ~/Dev/github_gaming/NVIDIAImageScaling - see docs/LINUX-PROTON-RTX50.md)
]


def log(message: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"[{stamp}] {message}"
    print(line)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a") as f:
        f.write(line + "\n")


def run(args: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=600)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def clone_or_fetch(src: Source) -> None:
    path = RESEARCH_DIR / src.subdir
    if (path / ".git").exists():
        log(f"{src.name}: existing checkout at {path}, fetching (never git pull - see module docstring)")
        rc, out, err = run(["git", "fetch", "--all", "--tags", "--prune"], cwd=path)
        if rc != 0:
            src.status, src.error = "FAIL", f"git fetch failed: {err or out}"
            log(f"{src.name}: FETCH FAILED - {src.error}")
            return
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        log(f"{src.name}: cloning {src.url} -> {path}")
        rc, out, err = run(["git", "clone", "--filter=blob:none", src.url, str(path)])
        if rc != 0:
            src.status, src.error = "FAIL", f"git clone failed: {err or out}"
            log(f"{src.name}: CLONE FAILED - {src.error}")
            return

    if src.ref:
        rc, out, err = run(["git", "checkout", src.ref], cwd=path)
        if rc != 0:
            src.status, src.error = "WARN", f"checkout {src.ref} failed: {err or out}"
            log(f"{src.name}: {src.error}")

    record_revision(src, path)


def record_revision(src: Source, path: Path) -> None:
    rc, commit, _ = run(["git", "rev-parse", "HEAD"], cwd=path)
    if rc != 0 or not commit:
        src.status = "FAIL"
        src.error = src.error or "could not determine HEAD commit"
        return
    src.commit = commit

    _, branch, _ = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=path)
    src.branch = branch

    _, tag, _ = run(["git", "describe", "--tags", "--exact-match", "HEAD"], cwd=path)
    src.tag = tag

    if not src.status or src.status == "unknown":
        src.status = "PASS"

    if src.name == "RTX-Kit":
        gm = path / ".gitmodules"
        if gm.exists():
            src.discovered_submodules = parse_gitmodules(gm)


def parse_gitmodules(path: Path) -> list[str]:
    urls = []
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if line.startswith("url = "):
            urls.append(line[len("url = "):].strip())
    return urls


def verify_only() -> None:
    for src in SOURCES:
        path = RESEARCH_DIR / src.subdir
        if not (path / ".git").exists():
            src.status, src.error = "FAIL", "not cloned"
            log(f"{src.name}: FAIL - not cloned (run without --verify to fetch)")
            continue
        record_revision(src, path)
        log(f"{src.name}: {src.status} @ {src.commit[:12]}")


def write_manifest() -> None:
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    lines = ["# Research corpus manifest", "", f"Generated: {now}", "",
             "P0 sources only - see fetch_sources.py's module docstring and the commented-out",
             "P1-P3 lists in its SOURCES table for what was deliberately not fetched, and why.", ""]
    for src in SOURCES:
        lines += [
            f"## {src.name} ({src.priority})",
            "",
            f"URL: {src.url}",
            f"Local path: research/{src.subdir}",
            f"Status: {src.status}",
            f"Commit: {src.commit or '(none)'}",
            f"Tag: {src.tag or '(none)'}",
            f"Branch: {src.branch or '(none)'}",
        ]
        if src.error:
            lines.append(f"Error: {src.error}")
        if src.notes:
            lines.append(f"Notes: {src.notes}")
        if src.discovered_submodules:
            lines.append("Discovered submodules (from .gitmodules, not fetched by this script):")
            for u in src.discovered_submodules:
                lines.append(f"  - {u}")
        lines.append("")
    (RESEARCH_DIR / "MANIFEST.md").write_text("\n".join(lines))

    data = [
        {
            "name": s.name, "url": s.url, "local_path": f"research/{s.subdir}",
            "priority": s.priority, "status": s.status, "commit": s.commit,
            "tag": s.tag, "branch": s.branch, "error": s.error,
            "discovered_submodules": s.discovered_submodules,
        }
        for s in SOURCES
    ]
    (RESEARCH_DIR / "sources.json").write_text(json.dumps(data, indent=2) + "\n")


def write_validation() -> None:
    lines = ["# Corpus validation", "", f"Run: {datetime.now(timezone.utc).isoformat()}", ""]
    any_fail = False
    for src in SOURCES:
        mark = {"PASS": "PASS", "WARN": "WARN", "FAIL": "FAIL"}.get(src.status, "FAIL")
        if mark == "FAIL":
            any_fail = True
        lines.append(f"- [{mark}] {src.name} ({src.priority}) - {src.commit[:12] if src.commit else src.error}")
    lines.append("")
    lines.append("Any FAIL above means: SOURCE / URL / ERROR is in fetch.log - do not silently retry" \
                 " forever, read the log first.")
    (RESEARCH_DIR / "VALIDATION.md").write_text("\n".join(lines))
    if any_fail:
        log("VALIDATION: at least one source FAILED - see research/VALIDATION.md and research/fetch.log")


def write_readme() -> None:
    readme = RESEARCH_DIR / "README.md"
    if readme.exists():
        return  # don't clobber hand edits
    readme.write_text(
        "# Research corpus\n\n"
        "External sources this project's architecture work draws on. Generated and updated by\n"
        "`tools/research/fetch_sources.py` - never hand-edit the cloned checkouts under here.\n\n"
        "- `MANIFEST.md` - human-readable source list with exact commits/tags fetched.\n"
        "- `sources.json` - the same, machine-readable.\n"
        "- `VALIDATION.md` - PASS/WARN/FAIL per source from the last run.\n"
        "- `fetch.log` - append-only log of every fetch attempt, including failures.\n\n"
        "Run `tools/research/fetch_sources.py --verify` to re-check without fetching, or with no\n"
        "flags to clone missing sources and fetch (never blind-pull) existing ones.\n\n"
        "P0 only by design - see the script's module docstring for what P1-P3 would add and why\n"
        "they're deferred until a specific investigation needs them.\n"
    )


def main() -> int:
    args = sys.argv[1:]
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    write_readme()

    if "--verify" in args:
        verify_only()
    elif "--index" in args:
        pass  # fall through to manifest/validation writers using whatever state exists on disk
    else:
        for src in SOURCES:
            clone_or_fetch(src)

    write_manifest()
    write_validation()
    log("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
