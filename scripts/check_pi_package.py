#!/usr/bin/env python3
"""Validate the repo root Pi package manifest and wrapper skills."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def fail(message: str) -> int:
    print(f"ERROR: {message}", file=sys.stderr)
    return 1


def main() -> int:
    package_path = REPO_ROOT / "package.json"
    package = json.loads(package_path.read_text(encoding="utf-8"))

    if "pi-package" not in package.get("keywords", []):
        return fail("package.json must include the pi-package keyword")

    pi_manifest = package.get("pi")
    if not isinstance(pi_manifest, dict):
        return fail("package.json must contain a pi manifest object")

    for bin_name, relpath in package.get("bin", {}).items():
        path = REPO_ROOT / relpath
        if not path.exists():
            return fail(f"bin {bin_name!r} points at missing path {relpath}")
        if not path.is_file():
            return fail(f"bin {bin_name!r} path is not a file: {relpath}")

    for relpath in pi_manifest.get("extensions", []):
        path = REPO_ROOT / relpath
        if not path.exists():
            return fail(f"pi extension path is missing: {relpath}")
        if path.suffix not in {".js", ".ts"}:
            return fail(f"pi extension must be .js or .ts: {relpath}")

    skill_files: list[Path] = []
    for relpath in pi_manifest.get("skills", []):
        path = REPO_ROOT / relpath
        if not path.exists():
            return fail(f"pi skills path is missing: {relpath}")
        if path.is_file():
            skill_files.append(path)
        else:
            skill_files.extend(path.rglob("SKILL.md"))

    if not skill_files:
        return fail("pi manifest did not expose any SKILL.md files")

    for skill_file in skill_files:
        text = skill_file.read_text(encoding="utf-8")
        match = re.search(r"^---\n(.*?)\n---", text, flags=re.DOTALL)
        if not match:
            return fail(f"skill lacks YAML frontmatter: {skill_file.relative_to(REPO_ROOT)}")
        name_match = re.search(r"^name:\s*([a-z0-9-]+)\s*$", match.group(1), flags=re.MULTILINE)
        if not name_match:
            return fail(f"skill frontmatter lacks a valid name: {skill_file.relative_to(REPO_ROOT)}")
        if name_match.group(1) != skill_file.parent.name:
            return fail(
                f"skill name {name_match.group(1)!r} must match parent directory "
                f"{skill_file.parent.name!r}"
            )

        for rel in re.findall(r"`([^`]+plugins/gepa-research/skills/[^`]+/SKILL\.md)`", text):
            target = (skill_file.parent / rel).resolve()
            if not target.exists():
                return fail(
                    f"skill {skill_file.relative_to(REPO_ROOT)} references missing canonical skill {rel}"
                )

    extension_count = len(pi_manifest.get("extensions", []))
    print(
        f"OK: Pi package exposes {len(skill_files)} skill(s) "
        f"and {extension_count} extension(s)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
