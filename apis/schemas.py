"""Pydantic request models for the API layer.

Structural validation only: shape, types, exactly-one-of image/url. Semantic
validation (base64 content, download failures) stays in the task layer and
surfaces as code=1/2 via the endpoint try/except. Model failures become
200 + code=1 envelopes via utils.response.validation_error_handler.
"""
from typing import Optional

from pydantic import BaseModel, model_validator


class ImageSourceRequest(BaseModel):
    """Exactly one of image (base64) or url. Shared by every request schema;
    messages mirror the task-layer errors so callers see identical text."""

    image: Optional[str] = None
    url: Optional[str] = None

    @model_validator(mode="after")
    def _exactly_one_source(self):
        if self.image and self.url:
            raise ValueError("provide either 'image' or 'url', not both")
        if not self.image and not self.url:
            raise ValueError("provide either 'image' or 'url'")
        return self


class PredictRequest(ImageSourceRequest):
    """ImageSourceRequest plus an optional registered model name (see
    docs/model-registry.md)."""

    model: Optional[str] = None  # absent -> the capability's default model


class PipelineRequest(ImageSourceRequest):
    """ImageSourceRequest without `model`: the pipeline always composes the
    detect + classify DEFAULTS (see docs/api.md) — there is no per-request
    model routing to ask for."""


class CallbackRequest(PredictRequest):
    callback_url: str  # missing -> "Field required" -> code=1 envelope


class QueryRequest(PredictRequest):
    pass
