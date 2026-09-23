"""Bounded, anonymous latency samples for the current warm instance."""

from __future__ import annotations

import logging
from collections import deque
from math import ceil

LOGGER = logging.getLogger(__name__)
OPERATIONS = {"lookup", "queue_delay", "queue_delivery"}


def record_duration(bot_data: dict, operation: str, milliseconds: float) -> None:
    if operation not in OPERATIONS:
        raise ValueError("Unknown operation")
    value = max(0, round(milliseconds))
    samples = bot_data.setdefault("operation_samples", {}).setdefault(
        operation, deque(maxlen=200)
    )
    samples.append(value)
    LOGGER.info("operation=%s latency_ms=%d", operation, value)


def latency_summary(bot_data: dict) -> dict[str, dict[str, int]]:
    result = {}
    for name, values in bot_data.get("operation_samples", {}).items():
        ordered = sorted(values)
        if ordered:
            result[name] = {
                "samples": len(ordered),
                "p50_ms": ordered[ceil(len(ordered) * 0.5) - 1],
                "p95_ms": ordered[ceil(len(ordered) * 0.95) - 1],
            }
    return result
