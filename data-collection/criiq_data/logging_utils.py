from __future__ import annotations

import logging
import sys

_CONFIGURED = False


def get_logger(name: str = "criiq") -> logging.Logger:
    global _CONFIGURED
    if not _CONFIGURED:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s | %(message)s",
                              datefmt="%H:%M:%S")
        )
        root = logging.getLogger("criiq")
        root.setLevel(logging.INFO)
        root.addHandler(handler)
        root.propagate = False
        _CONFIGURED = True
    return logging.getLogger(name if name.startswith("criiq") else f"criiq.{name}")
