"""Start the local-only fictional site used for permission-comparison acceptance."""

from __future__ import annotations

import sys
from pathlib import Path
from time import sleep

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))

from ai_ui_explorer.acceptance.permission_comparison_site import PermissionAcceptanceSite


def main() -> int:
    """Serve the fixed loopback site until the operator interrupts it."""
    site = PermissionAcceptanceSite()
    site.start()
    print(site.origin, flush=True)
    try:
        while True:
            sleep(1)
    except KeyboardInterrupt:
        return 0
    finally:
        site.close()


if __name__ == "__main__":
    raise SystemExit(main())
