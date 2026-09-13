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
  python3 scripts/assemble.py --target /srv/my-service --profile bare
  python3 scripts/assemble.py --target /srv/my-service --with detect,async
  python3 scripts/assemble.py --target /srv/my-service --with detect --features docker

Selection model (docs/assembly.md §2):
  base        — always: the minimal kernel (app factory, health probes,
                placeholder packages, contract guard tests, dev skills).
                With the default profile it is a plain FastAPI service —
                no envelope, request_id or dotenv.
  mechanisms  — cross-cutting pieces, opt-in: envelope (the {code, message,
                data} contract + body limit + 422 fold), request_id,
                dotenv, metrics, auth, rate_limit, logging; `requires`
                expands dependencies (auth->envelope, rate_limit->auth,
                logging->request_id).
  capabilities — one file set each; opt-in via --with; `requires` expands
                the dependency closure automatically.
  capability_contract — selecting ANY capability also selects these
                mechanisms (envelope, request_id, dotenv) so business apis
                keep the serving contract.
  profiles    — named mechanism presets: bare (none), kernel (the contract
                mechanisms, default), production (kernel + metrics/auth/
                rate_limit/logging); --with unions with the profile.
  shared      — included when ANY of the listed names is selected.
  features    — deployment/tooling extras; opt-in via --features.
  generated   — requirements.txt is written from the MERGE of the
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
    "scripts/check_assembly.py",
    "tests/test_bootstrap_manifest.py",
}

_OPEN = re.compile(r"^\s*# @inferforge:([\w+]+)\s*$")
_END = re.compile(r"^\s*# @inferforge:end:([\w+]+)\s*$")


def _tag_kept(tag: str, selected: set) -> bool:
    """A compound tag (a+b) is kept only when EVERY name is selected.

    `base` blocks are always kept — they hold the wiring files' unconditional
    kernel code (see docs/assembly.md §5). The marker lines themselves are
    dropped either way.
    """
    if tag == "base":
        return True
    return all(name in selected for name in tag.split("+"))


def load_manifest() -> dict:
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve_selection(manifest, selected, features, profile):
    """Expand the dependency closure and collect files + requirements.

    The profile's mechanism names union with the explicit --with selections.
    Selecting any capability additionally pulls in the capability_contract
    mechanisms (envelope/request_id/dotenv) via a second closure pass, so
    every business api keeps the serving contract regardless of profile.
    """
    capabilities = manifest["capabilities"]
    mechanisms = manifest.get("mechanisms", {})
    profiles = manifest.get("profiles", {})
    if profile not in profiles:
        raise SystemExit("unknown profile: %s (profiles: %s)"
                         % (profile, ", ".join(profiles)))
    selected = list(set(selected) | set(profiles[profile]))
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

    # Capability contract: business capabilities must keep the serving
    # contract even on the bare profile — seed a second closure pass.
    if manifest.get("capability_contract") and (chosen & set(capabilities)):
        queue = list(manifest["capability_contract"])
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
            # Cap consecutive blank lines at 2 (PEP8 double-blank before
            # top-level defs survives; stripped blocks don't pile up voids).
            if (line.strip() == "" and len(out) >= 2
                    and out[-1].strip() == "" and out[-2].strip() == ""):
                continue
            out.append(line)
    if skip:
        raise SystemExit("unterminated @inferforge block: %s" % skip[-1])
    return "".join(out)


def assemble(target, selected, features, profile="kernel"):
    manifest = load_manifest()
    chosen, paths, requirements = resolve_selection(manifest, selected, features, profile)

    # Target guard: assemble.py never overwrites anything. A missing or
    # empty directory is created/used; a non-empty one is refused (with a
    # hint when it looks like an existing project), and the target may
    # never be inside the template repo itself.
    target_abs = os.path.realpath(target)
    root_abs = os.path.realpath(PROJECT_ROOT)
    if target_abs == root_abs or target_abs.startswith(root_abs + os.sep):
        raise SystemExit("target must be OUTSIDE the template repo: %s" % target)
    if os.path.exists(target) and os.listdir(target):
        project_markers = ["app.py", "requirements.txt", "pyproject.toml", ".git"]
        found = [m for m in project_markers
                 if os.path.exists(os.path.join(target, m))]
        if found:
            raise SystemExit(
                "target exists and is not empty: %s — this looks like an "
                "existing project (found: %s). assemble.py never overwrites; "
                "initialize into a new or empty directory."
                % (target, ", ".join(found)))
        raise SystemExit(
            "target exists and is not empty: %s — assemble.py never "
            "overwrites; initialize into a new or empty directory." % target)
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
                # Capability/mechanism/feature tags strip blocks of
                # unselected names; `base` blocks are always kept (marker
                # lines themselves are dropped either way).
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

    print("[OK] assembled %d paths into %s (profile: %s; selections: %s%s)"
          % (len(copied), target, profile, ", ".join(chosen) or "none",
             "; features: %s" % ", ".join(sorted(features)) if features else ""))
    print("     next: cd %s && git init && (rename checklist) && pytest tests/ -q" % target)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target", required=True, help="target project directory")
    parser.add_argument("--with", dest="capabilities", default="",
                        help="comma-separated capability/mechanism names — "
                             "capabilities: detect/seg/cls/pipeline/embed/"
                             "dedup/async/vlm/agent/search; mechanisms: "
                             "envelope/request_id/dotenv/metrics/auth/"
                             "rate_limit/logging; unions with the profile")
    parser.add_argument("--profile", default="kernel",
                        help="named mechanism preset: bare/kernel/production "
                             "(default: kernel)")
    parser.add_argument("--features", default="",
                        help="comma-separated feature names (ci/docker/deploy/benchmark)")
    args = parser.parse_args()

    selected = [n.strip() for n in args.capabilities.split(",") if n.strip()]
    features = [n.strip() for n in args.features.split(",") if n.strip()]
    assemble(args.target, selected, features, profile=args.profile)


if __name__ == "__main__":
    main()
