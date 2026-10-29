from __future__ import annotations

import logging


def quiet_transport_logs() -> None:
    """Keep credentials embedded in transport URLs out of runtime logs."""
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
