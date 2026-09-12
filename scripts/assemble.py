#!/usr/bin/env python3
"""Selective project assembler — the bootstrap executor.

Reads templates/manifest.yaml and copies the base file set + the selected
capabilities' file sets (+ shared sets + features) into a target directory.
Marker blocks (`# @inferforge:<name>` ... `# @inferforge:end:<name>`) in
wiring files are dropped for unselected capabilities, so a generated project
never references absent files.

Factory tooling: this script ships with the template only — generated
projects never contain it (see tests/test_bootstrap_manifest.py).

Usage:
  python3 scripts/assemble.py --target /srv/my-service
  python3 scripts/assemble.py --target /srv/my-service --with detect,async
  python3 scripts/assemble.py --target /srv/my-service --with detect --features docker

Selection model (docs/workflow/bootstrap.md §2):
  base         — always: the contract kernel (app factory, envelope,
                 health probes, placeholder packages). The default assembly.
  mechanisms   — cross-cutting middleware pieces (metrics/request_id/auth/
                 rate_limit/logging); opt-in via --with.
  capabilities — one file set each; opt-in via --with; `requires` expands
                 the dependency closure automatically.
  shared       — included when ANY of the listed names is selected.
  features     — deployment/tooling extras; opt-in via --features.
  generated    — requirements.txt is written from the MERGE of the
                 selected entries' declared requirements, never copied.
"""
import argparse
import os
import re
import shutil
import sys

import yaml

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST_PATH = os.path.join(PROJECT_ROOT, "templates", "manifest.yaml")

# Factory-only paths: tracked by the template repo but never shipped.
FACTORY_ONLY = {
    "templates/manifest.yaml",
    "scripts/assemble.py",
    "tests/test_bootstrap_manifest.py",
}

_OPEN = re.compile(r"^\s*# @inferforge:([\w+]+)\s*$")
_END = re.compile(r"^\s*# @inferforge:end:([\w+]+)\s*$")


def _tag_kept(tag: str, selected: set) -> bool:
    """A compound tag (a+b) is kept only when EVERY name is selected."""
    return all(name in selected for name in tag.split("+"))


def load_manifest() -> dict:
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve_selection(manifest, selected, features):
    """Expand the dependency closure and collect files + requirements."""
    capabilities = manifest["capabilities"]
    mechanisms = manifest.get("mechanisms", {})
    known = set(capabilities) | set(mechanisms)
    unknown = [name for name in selected if name not in known]
    if unknown:
        raise SystemExit("unknown selections: %s (capabilities: %s; "
                         "mechanisms: %s)" % (", ".join(unknown),
                                              ", ".join(capabilities),
                                              ", ".join(mechanisms)))
    unknown_f = [name for name in features if name not in manifest["features"]]
    if unknown_f:
        raise SystemExit("unknown features: %s" % ", ".join(unknown_f))

    def requires_of(name):
        if name in capabilities:
            return capabilities[name].get("requires", [])
        return mechanisms[name].get("requires", [])

    queue = list(selected)
    chosen = set()
    while queue:
        name = queue.pop()
        if name in chosen:
            continue
        chosen.add(name)
        queue.extend(requires_of(name))

    files = []
    reqs = set(manifest["base"].get("requirements", []))
    for name in sorted(chosen):
        if name in mechanisms:
            entry = mechanisms[name]
        else:
            entry = capabilities[name]
        files.extend(entry["files"])
        reqs.update(entry.get("requirements", []))
    for rule in manifest.get("shared", []):
        if set(rule["any_of"]) & chosen:
            files.extend(rule["files"])
            reqs.update(rule.get("requirements", []))
    for name in sorted(features):
        entry = manifest["features"][name]
        files.extend(entry["files"])
        reqs.update(entry.get("requirements", []))

    return sorted(chosen), manifest["base"]["files"] + files, sorted(reqs)


def strip_markers(text, selected):
    """Drop marker lines and the blocks of unselected capabilities."""
    out = []
    skip = []  # stack of (tag) currently being dropped
    for line in text.splitlines(keepends=True):
        open_match = _OPEN.match(line)
        end_match = _END.match(line)
        if open_match:
            tag = open_match.group(1)
            if _tag_kept(tag, selected):
                continue  # selected block: drop the marker, keep the body
            skip.append(tag)
            continue
        if end_match:
            tag = end_match.group(1)
            if _tag_kept(tag, selected):
                continue
            if not skip or skip[-1] != tag:
                raise SystemExit(
                    "unbalanced @inferforge markers: %r (expected %r)"
                    % (line.strip(), skip[-1] if skip else None))
            skip.pop()
            continue
        if not skip:
            out.append(line)
    if skip:
        raise SystemExit("unterminated @inferforge block: %s" % skip[-1])
    return "".join(out)


def assemble(target, selected, features, force=False):
    manifest = load_manifest()
    chosen, paths, requirements = resolve_selection(manifest, selected, features)

    if os.path.exists(target):
        if not force or os.listdir(target):
            raise SystemExit("target exists: %s (use --force to overwrite)" % target)
    os.makedirs(target, exist_ok=True)

    copied = []
    for rel in paths:
        src = os.path.join(PROJECT_ROOT, rel)
        dst = os.path.join(target, rel)
        if os.path.isdir(src):
            # dirname("a/b/") == "a/b" — creating the parent would collide
            # with copytree's own mkdir; dirs_exist_ok covers the parent
            # already created by a previous claim.
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"),
                            dirs_exist_ok=True)
        else:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(src, encoding="utf-8") as f:
                content = f.read()
            if "@inferforge:" in content:
                # Feature tags (e.g. the benchmark row in docs/README.md)
                # behave like capability tags for marker stripping.
                content = strip_markers(content, set(chosen) | set(features))
            with open(dst, "w", encoding="utf-8") as f:
                f.write(content)
        copied.append(rel)

    # The assembled registry.example.yaml is the selected capabilities'
    # working registry — write it as models/registry.yaml so preflight and
    # routing see exactly the capabilities this project has. No capability
    # selected -> no registry file (the env fallback yields nothing).
    if chosen:
        example = os.path.join(target, "models", "registry.example.yaml")
        if os.path.exists(example):
            with open(example, encoding="utf-8") as f:
                shutil.copyfile(example, os.path.join(target, "models", "registry.yaml"))

    # Generated file: requirements.txt = the MERGE of the selected entries'
    # declared requirements (never a copy of the template's own).
    req_path = os.path.join(target, "requirements.txt")
    with open(req_path, "w", encoding="utf-8") as f:
        f.write("\n".join(requirements) + "\n")
    copied.append("requirements.txt")

    print("[OK] assembled %d paths into %s (selections: %s%s)"
          % (len(copied), target, ", ".join(chosen) or "none",
             "; features: %s" % ", ".join(sorted(features)) if features else ""))
    print("     next: cd %s && git init && (rename checklist) && pytest tests/ -q" % target)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target", required=True, help="target project directory")
    parser.add_argument("--with", dest="capabilities", default="",
                        help="comma-separated capability/mechanism names "
                             "(capabilities: detect/seg/cls/...; mechanisms: "
                             "metrics/request_id/auth/rate_limit/logging; "
                             "default: contract kernel only)")
    parser.add_argument("--features", default="",
                        help="comma-separated feature names (docker/deploy/benchmark)")
    parser.add_argument("--force", action="store_true", help="overwrite an existing target")
    args = parser.parse_args()

    selected = [n.strip() for n in args.capabilities.split(",") if n.strip()]
    features = [n.strip() for n in args.features.split(",") if n.strip()]
    assemble(args.target, selected, features, force=args.force)


if __name__ == "__main__":
    main()
