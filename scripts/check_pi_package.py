#!/usr/bin/env python3
"""Validate the repo root Pi package manifest and wrapper skills."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Keep this explicit: adding a new Pi wrapper skill requires adding it here
# and under pi/skills/. That prevents accidental exposure of generic skill
# names that could collide with other Pi packages.
WRAPPER_SKILLS = {
    "gepa-research-discover": "plugins/gepa-research/skills/discover/SKILL.md",
    "gepa-research-optimize": "plugins/gepa-research/skills/optimize/SKILL.md",
}


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
        if not os.access(path, os.X_OK):
            return fail(f"bin {bin_name!r} path is not executable: {relpath}")

    for relpath in pi_manifest.get("extensions", []):
        path = REPO_ROOT / relpath
        if not path.exists():
            return fail(f"pi extension path is missing: {relpath}")
        if path.suffix != ".js":
            return fail(f"pi extension must be plain .js with no build step: {relpath}")

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

    found_skill_names: set[str] = set()
    for skill_file in skill_files:
        text = skill_file.read_text(encoding="utf-8")
        match = re.search(r"^---\n(.*?)\n---", text, flags=re.DOTALL)
        if not match:
            return fail(f"skill lacks YAML frontmatter: {skill_file.relative_to(REPO_ROOT)}")

        name_match = re.search(r"^name:\s*([a-z0-9-]+)\s*$", match.group(1), flags=re.MULTILINE)
        if not name_match:
            return fail(f"skill frontmatter lacks a valid name: {skill_file.relative_to(REPO_ROOT)}")

        skill_name = name_match.group(1)
        found_skill_names.add(skill_name)
        if skill_name != skill_file.parent.name:
            return fail(
                f"skill name {skill_name!r} must match parent directory "
                f"{skill_file.parent.name!r}"
            )

        canonical_relpath = WRAPPER_SKILLS.get(skill_name)
        if canonical_relpath is None:
            return fail(f"unexpected Pi wrapper skill exposed: {skill_name}")

        canonical_path = REPO_ROOT / canonical_relpath
        if not canonical_path.exists():
            return fail(f"wrapper skill {skill_name} maps to missing {canonical_relpath}")

        linked_skill_paths = re.findall(r"`([^`]+SKILL\.md)`", text)
        resolved_links = {(skill_file.parent / linked_path).resolve() for linked_path in linked_skill_paths}
        expected_link = Path("..") / ".." / ".." / canonical_relpath
        if canonical_path.resolve() not in resolved_links:
            return fail(
                f"wrapper skill {skill_name} must link to canonical skill path "
                f"{expected_link}"
            )

        canonical_links = {
            (skill_file.parent / linked_path).resolve()
            for linked_path in linked_skill_paths
            if "plugins/gepa-research/skills/" in linked_path.replace("\\", "/")
        }
        if canonical_links != {canonical_path.resolve()}:
            return fail(
                f"wrapper skill {skill_name} must link only to canonical skill path "
                f"{expected_link}"
            )

    missing = set(WRAPPER_SKILLS) - found_skill_names
    if missing:
        return fail(f"Pi manifest did not expose expected wrapper skill(s): {sorted(missing)}")

    extension_count = len(pi_manifest.get("extensions", []))
    print(
        f"OK: Pi package exposes {len(skill_files)} skill(s) "
        f"and {extension_count} extension(s)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
