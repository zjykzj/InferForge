#!/usr/bin/env python3
"""Assembly self-proof: generate the representative selections and verify each.

Factory tooling (never shipped — see FACTORY_ONLY in scripts/assemble.py):
assembles bare/kernel/detect/detect-async/production/full into temp dirs and
for each output runs py_compile + pyflakes + pytest — a generated project
must compile, lint clean and pass its own tests (docs/assembly.md §7:
生成物自证). Each selection proves one assembly axis:

  bare          — the minimal kernel: no envelope/request_id/dotenv, plain
                  health responses, no dead code (pyflakes-clean app.py)
  kernel        — the default profile: byte-behavior equivalence of the old
                  base (envelope + request_id + dotenv)
  detect        — capability_contract auto-adds the serving contract
  detect-async  — celery_app marker surgery (metrics/logging/vlm/agent/
                  search blocks strip without breaking imports)
  production    — mechanism `requires` closure (auth->envelope,
                  rate_limit->auth, logging->request_id)
  full          — every capability + mechanism + benchmark feature: maximal
                  marker interaction and registry generation

pyflakes is optional on dev machines (warned + skipped); CI installs it.
pyflakes does not honor `# noqa` — celery_app.py's task-registration imports
(detection_callback/detection_query, imported for their side effect) are
filtered here.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSEMBLE = os.path.join(PROJECT_ROOT, "scripts", "assemble.py")

# (name, extra assemble args) — kernel (the default profile) needs none.
SELECTIONS = [
    ("bare", ["--profile", "bare"]),
    ("kernel", []),
    ("detect", ["--with", "detect"]),
    ("detect-async", ["--with", "detect,async"]),
    ("production", ["--profile", "production"]),
    ("full", ["--with",
              "detect,seg,cls,pipeline,embed,dedup,async,vlm,agent,search,"
              "metrics,auth,rate_limit,logging",
              "--features", "benchmark"]),
]

# Intentional F401s: task modules imported for registration side effects.
# pyflakes prints absolute paths here — match the file name + location.
_CELERY_TASK_IMPORTS = re.compile(
    r"(?:^|/)celery_app\.py:\d+:\d+: .*imported but unused$")


def _py_files(target):
    out = []
    for root, dirs, files in os.walk(target):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git")]
        for name in files:
            if name.endswith(".py"):
                out.append(os.path.join(root, name))
    return sorted(out)


def _scrubbed_env():
    """Tests must not see the developer's shell INFERFORGE_* switches."""
    env = dict(os.environ)
    for key in list(env):
        if key.startswith("INFERFORGE_"):
            del env[key]
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _run(cmd, cwd):
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                          env=_scrubbed_env())
    if proc.returncode != 0:
        print("  FAIL: %s" % " ".join(cmd))
        print(proc.stdout)
        print(proc.stderr)
        return False
    return True


def check(name, extra):
    tmp = tempfile.mkdtemp(prefix="inferforge-%s-" % name)
    try:
        proc = subprocess.run([sys.executable, ASSEMBLE, "--target", tmp] + extra,
                              capture_output=True, text=True)
        if proc.returncode != 0:
            print("  assemble failed:\n%s%s" % (proc.stdout, proc.stderr))
            return False
        files = _py_files(tmp)

        if not _run([sys.executable, "-m", "py_compile"] + files, cwd=tmp):
            return False

        proc = subprocess.run([sys.executable, "-m", "pyflakes"] + files,
                              capture_output=True, text=True, env=_scrubbed_env())
        if "No module named" in proc.stderr:
            print("  (pyflakes not installed — lint skipped)")
        elif proc.returncode not in (0, 1):
            print("  pyflakes crashed:\n%s" % proc.stderr)
            return False
        else:
            complaints = [line for line in (proc.stdout + proc.stderr).splitlines()
                          if line and not _CELERY_TASK_IMPORTS.search(line)]
            if complaints:
                print("  pyflakes complaints:")
                for line in complaints:
                    print("    " + line)
                return False

        if not _run([sys.executable, "-m", "pytest", "tests/", "-q"], cwd=tmp):
            return False
        return True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    failures = []
    for name, extra in SELECTIONS:
        print("[%s] assembling + verifying ..." % name)
        ok = check(name, extra)
        print("[%s] %s" % (name, "OK" if ok else "FAILED"))
        if not ok:
            failures.append(name)
    if failures:
        print("assembly self-proof failed for: %s" % ", ".join(failures))
        return 1
    print("assembly self-proof: all %d selections OK" % len(SELECTIONS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
