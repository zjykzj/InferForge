"""Tests for the logging context filter (request_id / task_id fallbacks)."""
import logging

from utils.logger import ContextFilter


def test_context_filter_outside_any_context():
    record = logging.LogRecord("test", logging.INFO, "", 0, "msg", None, None)
    assert ContextFilter().filter(record) is True
    assert record.request_id == "-"
    assert record.task_id == "-"
