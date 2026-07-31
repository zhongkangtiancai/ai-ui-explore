"""Conservative deterministic token estimates for bounded context handling."""

import json
from collections.abc import Mapping


def estimate_tokens(value: object) -> int:
    """Estimate tokens conservatively without pretending provider precision."""
    if isinstance(value, str):
        text = value
    elif isinstance(value, Mapping):
        text = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    else:
        text = str(value)
    if not text:
        return 0
    # Four characters per token is a common rough estimate; rounding up keeps it
    # conservative and deterministic for tests and offline planning.
    return max(1, (len(text) + 3) // 4)
