"""Base predictor contract — the only stable interface in the whole project.

Every algorithm mounts into InferForge by implementing this class; the API and
task layers depend on this contract only, never on a concrete algorithm.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np


@dataclass
class DetectionResult:
    """Raw inference output of a detection predictor."""

    boxes: np.ndarray      # (N, 4) [x1, y1, x2, y2] in pixel coordinates
    scores: np.ndarray     # (N,) confidence
    class_ids: np.ndarray  # (N,) integer class ids

    def __len__(self) -> int:
        return len(self.scores)


@dataclass
class SegmentationResult:
    """Raw inference output of a segmentation predictor."""

    boxes: np.ndarray      # (N, 4) [x1, y1, x2, y2] in pixel coordinates
    scores: np.ndarray     # (N,) confidence
    class_ids: np.ndarray  # (N,) integer class ids
    masks: np.ndarray      # (N, H, W) bool, full original-image size, one per box

    def __len__(self) -> int:
        return len(self.scores)


@dataclass
class ClassificationResult:
    """Raw inference output of a classification predictor."""

    scores: np.ndarray     # (K,) top-k softmax probabilities, sorted descending
    class_ids: np.ndarray  # (K,) integer class ids

    def __len__(self) -> int:
        return len(self.scores)


# The concrete return type of BasePredictor.predict: one of the three, chosen
# by the capability each predictor implements.
PredictResult = DetectionResult | SegmentationResult | ClassificationResult


class BasePredictor(ABC):
    """Inference engine abstraction."""

    @abstractmethod
    def load(self, model_path: str) -> None:
        """Load model weights into memory (kept resident)."""

    @abstractmethod
    def predict(self, image: np.ndarray) -> PredictResult:
        """Run inference on a BGR image; the result type is capability-specific
        (DetectionResult / SegmentationResult / ClassificationResult)."""
