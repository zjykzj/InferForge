"""Environment feature-switch helper.

Single source of the truthy-set truth: app.py (router registration) and
apis/health.py (readiness) must agree on what "on" means.
"""
import os

_TRUTHY = ("1", "true", "yes")


def switch_on(name: str) -> bool:
    """Whether the env switch `name` is on (1/true/yes, case-insensitive)."""
    return os.environ.get(name, "").lower() in _TRUTHY
