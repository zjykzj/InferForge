"""Image utilities: base64 / URL <-> numpy BGR image conversions."""
import base64
import logging
from typing import Optional

import cv2
import numpy as np
import requests

logger = logging.getLogger("utils.image")

DOWNLOAD_TIMEOUT = 10  # seconds
MAX_DOWNLOAD_SIZE = 20 * 1024 * 1024  # bytes


def base64_to_image(data: str) -> np.ndarray:
    """Decode a base64 string (data URL prefix allowed) into a BGR image."""
    if data.startswith("data:") and "," in data:
        data = data.split(",", 1)[1]
    raw = base64.b64decode(data)
    image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("failed to decode base64 image")
    logger.info("decoded base64 image: shape=%s", image.shape)
    return image


def url_to_image(url: str) -> np.ndarray:
    """Download an image from a URL and decode it into a BGR image."""
    logger.info("downloading image: %s", url)
    resp = requests.get(url, timeout=DOWNLOAD_TIMEOUT)
    resp.raise_for_status()
    if len(resp.content) > MAX_DOWNLOAD_SIZE:
        raise ValueError("downloaded image too large: %d bytes" % len(resp.content))
    image = cv2.imdecode(np.frombuffer(resp.content, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("failed to decode image downloaded from url")
    logger.info("downloaded image: shape=%s", image.shape)
    return image


def image_to_base64(image: np.ndarray, ext: str = ".jpg") -> str:
    """Encode a BGR image into a base64 JPEG string."""
    ok, buf = cv2.imencode(ext, image)
    if not ok:
        raise ValueError("failed to encode image to %s" % ext)
    return base64.b64encode(buf.tobytes()).decode("utf-8")


def input_to_image(image_b64: Optional[str] = None, image_url: Optional[str] = None) -> np.ndarray:
    """Resolve exactly one of base64 / url into a BGR image."""
    if image_b64 and image_url:
        raise ValueError("provide either 'image' or 'url', not both")
    if image_b64:
        return base64_to_image(image_b64)
    if image_url:
        return url_to_image(image_url)
    raise ValueError("provide either 'image' or 'url'")
