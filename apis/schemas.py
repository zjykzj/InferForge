"""Pydantic request models for the API layer.

Structural validation only: shape, types, exactly-one-of image/url. Semantic
validation (base64 content, download failures) stays in the task layer and
surfaces as code=1/2 via the endpoint try/except. Model failures become
200 + code=1 envelopes via utils.response.validation_error_handler.
"""
from typing import Optional

from pydantic import BaseModel, Field, model_validator


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


class SearchRequest(ImageSourceRequest):
    """ImageSourceRequest plus an optional top-k size for the gallery search.
    No `model` field: the gallery index is bound to the embed default model
    (see docs/embedding.md §5)."""

    top_k: int = Field(default=5, ge=1, le=50)


class CheckRequest(ImageSourceRequest):
    """ImageSourceRequest without any extra fields: the gallery duplicate
    check always answers top-1 against the shared threshold
    (INFERFORGE_DUP_THRESHOLD). No `model` field (see SearchRequest)."""


class DedupSource(BaseModel):
    """One image source within a dedup batch: exactly one of image/url."""

    image: Optional[str] = None
    url: Optional[str] = None

    @model_validator(mode="after")
    def _exactly_one_source(self):
        if self.image and self.url:
            raise ValueError("provide either 'image' or 'url', not both")
        if not self.image and not self.url:
            raise ValueError("provide either 'image' or 'url'")
        return self


class DedupRequest(BaseModel):
    """A batch of image sources for near-duplicate detection. Group ids in
    the response are 0-based positions of this list. No `model` field (see
    SearchRequest)."""

    images: list[DedupSource] = Field(min_length=2, max_length=50)


class CallbackRequest(PredictRequest):
    callback_url: str  # missing -> "Field required" -> code=1 envelope


class QueryRequest(PredictRequest):
    pass
