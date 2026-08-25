"""Cross-layer exception types.

These live in utils because the api layer must be able to catch them while
the raising code sits in engines — and `apis -> engines` would skip the
one-way dependency chain (app -> apis -> tasks -> engines). utils is
cross-cutting and these classes depend on nothing, so both ends can import
them without anyone reaching backwards.

Task-local failures stay task-local: tasks.vlm defines its own
LLMConfigError / LLMUpstreamError because those never cross into apis.
"""


class ModelNotFound(Exception):
    """Requested model is not registered, or not for the asked capability.

    Deliberately NOT a ValueError subclass: the endpoint try/except ladders
    catch ValueError first and map it to code=1, which would swallow this
    into "invalid request" instead of the dedicated code=10.
    """


class RegistryConfigError(Exception):
    """The model registry itself is broken — unparseable YAML, missing
    required keys, an ambiguous default, or an unreadable classes file.

    An operator error, not a caller error: it falls through to the generic
    `except Exception` and surfaces as code=3, with the traceback naming
    this class in the logs.
    """
