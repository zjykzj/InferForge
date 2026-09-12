"""Bootstrap manifest guard: the assembly manifest never drifts from the repo.

Static checks only (no models, no network):

  A. every tracked repo file is claimed by exactly one manifest entry
     (base / capability / shared / feature) — no orphan files, and the
     assembly never ships the same file twice
  B. every manifest path exists in the repo (file or directory)
  C. every `# @inferforge:<tag>` marker block in every claimed file pairs
     up (balanced, nested-safe) and uses known tags (capability + feature
     names) — assemble.py can strip them without guessing
  D. capability dependencies (`requires`, `any_of`) reference known
     capabilities, and capability file sets never overlap base
"""
import importlib.util
import os
import re
import subprocess

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Import scripts/assemble.py (plain directory, no package __init__).
_spec = importlib.util.spec_from_file_location(
    "assemble", os.path.join(PROJECT_ROOT, "scripts", "assemble.py")
)
assemble = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(assemble)


def _tracked_files():
    # Include untracked files (respecting .gitignore) so the guard also
    # covers files created but not yet committed during development.
    out = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, check=True,
    )
    return set(line for line in out.stdout.splitlines() if line)


def _claims():
    """path -> [owners]; a path claimed by more than one owner is an error."""
    manifest = assemble.load_manifest()
    claims = {}
    for path in manifest["base"]["files"]:
        claims.setdefault(path, []).append("base")
    for name, entry in manifest.get("mechanisms", {}).items():
        for path in entry["files"]:
            claims.setdefault(path, []).append("mechanism:%s" % name)
    for name, entry in manifest["capabilities"].items():
        for path in entry["files"]:
            claims.setdefault(path, []).append("capability:%s" % name)
    for rule in manifest.get("shared", []):
        for path in rule["files"]:
            claims.setdefault(path, []).append("shared:%s" % ",".join(rule["any_of"]))
    for name, entry in manifest["features"].items():
        for path in entry["files"]:
            claims.setdefault(path, []).append("feature:%s" % name)
    for path in manifest.get("template", []):
        claims.setdefault(path, []).append("template")
    for path in manifest.get("generated", []):
        claims.setdefault(path, []).append("generated")
    return manifest, claims


def _known_tags(manifest):
    return (set(manifest["capabilities"])
            | set(manifest.get("mechanisms", {}))
            | set(manifest["features"]))


def test_every_tracked_file_is_claimed_exactly_once():
    manifest, claims = _claims()
    tracked = _tracked_files()
    for path in sorted(claims):
        owners = claims[path]
        assert len(set(owners)) == 1, "%s claimed by %s" % (path, owners)
    # A directory claim (trailing "/") covers its whole subtree.
    def covered(filepath):
        for claim in claims:
            if claim == filepath or (claim.endswith("/") and filepath.startswith(claim)):
                return True
        return False
    unclaimed = {f for f in tracked if not covered(f)} - assemble.FACTORY_ONLY
    assert not unclaimed, "tracked but unclaimed: %s" % sorted(unclaimed)
    # Every claim must match a tracked file or cover at least one.
    covered_tracked = {f for f in tracked if covered(f)}
    for claim in sorted(claims):
        if claim.endswith("/"):
            assert any(f.startswith(claim) for f in covered_tracked), \
                "directory claim covers nothing: %s" % claim
        else:
            assert claim in tracked, "claimed but untracked: %s" % claim


def test_manifest_paths_exist():
    manifest, claims = _claims()
    for path in sorted(claims):
        full = os.path.join(PROJECT_ROOT, path)
        assert os.path.exists(full), "manifest path missing: %s" % path


def test_marker_blocks_pair_up():
    manifest, claims = _claims()
    tags = _known_tags(manifest)
    for path in sorted(claims):
        full = os.path.join(PROJECT_ROOT, path)
        if os.path.isdir(full):
            continue
        with open(full, encoding="utf-8") as f:
            text = f.read()
        if "@inferforge:" not in text:
            continue
        stack = []
        for lineno, line in enumerate(text.splitlines(), 1):
            open_match = assemble._OPEN.match(line)
            end_match = assemble._END.match(line)
            if open_match:
                stack.append((open_match.group(1), path, lineno))
            elif end_match:
                tag = end_match.group(1)
                assert stack, "%s:%d end:%s without open" % (path, lineno, tag)
                open_tag, _, open_lineno = stack.pop()
                assert open_tag == tag, (
                    "%s:%d end:%s mismatches open:%s (line %d)"
                    % (path, lineno, tag, open_tag, open_lineno)
                )
        assert not stack, "%s: unterminated markers %s" % (
            path, [(t, n) for t, _, n in stack])
        # every real marker line (docs may quote the syntax in prose) must
        # use a known capability/feature tag
        used = set()
        for line in text.splitlines():
            match = assemble._OPEN.match(line) or assemble._END.match(line)
            if match:
                used.update(match.group(1).split("+"))
        assert used <= tags, "%s uses unknown tags: %s" % (path, sorted(used - tags))


def test_dependencies_reference_known_capabilities():
    manifest = assemble.load_manifest()
    caps = set(manifest["capabilities"])
    for name, entry in manifest["capabilities"].items():
        for dep in entry.get("requires", []):
            assert dep in caps, "%s requires unknown %s" % (name, dep)
    for rule in manifest.get("shared", []):
        for dep in rule["any_of"]:
            assert dep in caps, "shared any_of unknown %s" % dep


def test_capability_files_do_not_overlap_base():
    manifest = assemble.load_manifest()
    base = set(manifest["base"]["files"])
    for name, entry in manifest["capabilities"].items():
        overlap = base & set(entry["files"])
        assert not overlap, "%s overlaps base: %s" % (name, sorted(overlap))
    for name, entry in manifest.get("mechanisms", {}).items():
        overlap = base & set(entry["files"])
        assert not overlap, "mechanism %s overlaps base: %s" % (name, sorted(overlap))


def test_template_section_is_never_assembled():
    manifest = assemble.load_manifest()
    template = set(manifest["template"])
    for name, entry in manifest["capabilities"].items():
        overlap = template & set(entry["files"])
        assert not overlap, "%s claims a template-only file: %s" % (name, sorted(overlap))
    for rule in manifest.get("shared", []):
        overlap = template & set(rule["files"])
        assert not overlap, "shared claims a template-only file: %s" % sorted(overlap)
