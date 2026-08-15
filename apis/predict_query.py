"""POST /predict/query + GET /predict/query/<task_id> — async detection with client polling.

Submit a detection task; the worker stores the result envelope in Redis; the
client polls until the envelope appears. Poll semantics: missing key -> code 4
(never submitted or expired), pending marker -> code 5, final envelope returned
verbatim (code 0/1/2/3 + data).
"""
import json
import logging

from flask import Blueprint, jsonify, request

from tasks.detection_query import detect_query_task
from utils import redis_store, request_id, response

logger = logging.getLogger("apis.predict_query")

predict_query_bp = Blueprint("predict_query", __name__)


@predict_query_bp.route("/predict/query", methods=["POST"])
def submit_query():
    data = request.get_json(silent=True) or {}
    image_b64 = data.get("image")
    image_url = data.get("url")

    logger.info("predict query request: remote=%s has_image=%s has_url=%s",
                request.remote_addr, bool(image_b64), bool(image_url))

    if image_b64 and image_url:
        return response.error("provide either 'image' or 'url', not both", code=1)
    if not image_b64 and not image_url:
        return response.error("provide either 'image' or 'url'", code=1)

    try:
        task = detect_query_task.delay(
            image_b64=image_b64,
            image_url=image_url,
            request_id=request_id.get_request_id(),
        )
        redis_store.set_pending(task.id)  # NX: never clobbers an already-written result
    except Exception:  # broker unreachable, redis down, serialization failure, ...
        logger.exception("failed to submit query task")
        return response.error("failed to submit task", code=3)

    logger.info("query task submitted: task_id=%s", task.id)
    return response.success({"task_id": task.id})


@predict_query_bp.route("/predict/query/<task_id>", methods=["GET"])
def poll_query(task_id):
    logger.info("query poll: task_id=%s", task_id)
    try:
        raw = redis_store.get_result(task_id)
    except Exception:  # redis unreachable
        logger.exception("failed to read result from redis")
        return response.error("internal server error", code=3)
    if raw is None:
        return response.error("task not found", code=4)
    if raw == redis_store.PENDING_VALUE:
        return response.error("task is still processing", code=5)
    try:
        payload = json.loads(raw)
    except ValueError:
        logger.error("corrupt result payload: task_id=%s", task_id)
        return response.error("internal server error", code=3)
    if not isinstance(payload, dict):
        logger.error("result payload is not an envelope: task_id=%s", task_id)
        return response.error("internal server error", code=3)
    return jsonify(payload)  # worker-stored envelope verbatim (code 0/1/2/3 + data)
