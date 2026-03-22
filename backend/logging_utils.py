from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any


def _serialise(payload: dict[str, Any]) -> str:
    return json.dumps(payload, default=str, ensure_ascii=True)


@lru_cache(maxsize=1)
def get_logger() -> logging.Logger:
    logger = logging.getLogger("gaia")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def log_event(severity: str, message: str, **fields: Any) -> None:
    payload = {"severity": severity.upper(), "message": message, **fields}
    get_logger().info(_serialise(payload))
