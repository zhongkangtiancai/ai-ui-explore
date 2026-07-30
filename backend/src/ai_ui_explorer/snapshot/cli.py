"""Public command-line interface for collecting bounded page snapshots."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import NoReturn
from urllib.parse import urlsplit

from .browser import PlaywrightBrowserSource
from .collector import SnapshotCollector
from .models import SnapshotLimits
from .writer import compact_snapshot, write_snapshot

CollectorFactory = Callable[[bool], SnapshotCollector]


class _SafeArgumentParser(argparse.ArgumentParser):
    """Avoid echoing user-provided arguments, which may contain credentials."""

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(2, "error: invalid arguments\n")


def build_parser() -> argparse.ArgumentParser:
    """Build the safe, non-interactive snapshot collection parser."""
    parser = _SafeArgumentParser(description="Collect a structured page snapshot.")
    parser.add_argument("--url", required=True, type=_http_url)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout-ms", type=_bounded_int(1_000, 600_000))
    parser.add_argument("--max-frames", type=_bounded_int(1, 500))
    parser.add_argument(
        "--max-scroll-containers-per-frame",
        type=_bounded_int(0, 200),
    )
    parser.add_argument(
        "--max-scroll-rounds-per-container",
        type=_bounded_int(0, 500),
    )
    parser.add_argument("--max-elements", type=_bounded_int(1, 100_000))
    parser.add_argument("--max-text-chars", type=_bounded_int(0, 10_000))
    parser.add_argument(
        "--max-json-bytes",
        type=_bounded_int(64 * 1024, 100 * 1024 * 1024),
    )
    parser.add_argument("--headed", action="store_true")
    return parser


def default_collector_factory(headed: bool) -> SnapshotCollector:
    """Create the production collector with local Playwright browser support."""
    return SnapshotCollector(source=PlaywrightBrowserSource(headless=not headed))


def main(
    argv: Sequence[str] | None = None,
    collector_factory: CollectorFactory = default_collector_factory,
) -> int:
    """Collect, compact, and write one snapshot without exposing page content."""
    try:
        arguments = build_parser().parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2

    try:
        limits = _limits_from_arguments(arguments)
        snapshot = collector_factory(arguments.headed).collect(arguments.url, limits)
        compacted = compact_snapshot(snapshot)
        output_path = write_snapshot(compacted, arguments.output)
    except Exception:
        print("status=fatal")
        return 1

    statistics = compacted.statistics
    print(
        f"output={output_path} status={compacted.status} "
        f"frames={statistics.frame_count} elements={statistics.element_count} "
        f"scroll_containers={statistics.scroll_container_count} "
        f"redactions={statistics.redaction_count} duration_ms={statistics.duration_ms}"
    )
    return 0 if compacted.status == "completed" else 2


def _http_url(value: str) -> str:
    """Accept only URLs that can be safely observed through an HTTP browser page."""
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("URL must use HTTP or HTTPS") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise argparse.ArgumentTypeError("URL must use HTTP or HTTPS")
    return value


def _bounded_int(minimum: int, maximum: int) -> Callable[[str], int]:
    """Build a safe argparse converter for one inclusive integer range."""

    def parse(value: str) -> int:
        try:
            parsed = int(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError("expected an integer") from exc
        if not minimum <= parsed <= maximum:
            raise argparse.ArgumentTypeError("integer is outside the allowed range")
        return parsed

    return parse


def _limits_from_arguments(arguments: argparse.Namespace) -> SnapshotLimits:
    """Build model-validated limits while retaining defaults for omitted flags."""
    values = {
        "total_timeout_ms": arguments.timeout_ms,
        "max_frames": arguments.max_frames,
        "max_scroll_containers_per_frame": arguments.max_scroll_containers_per_frame,
        "max_scroll_rounds_per_container": arguments.max_scroll_rounds_per_container,
        "max_elements": arguments.max_elements,
        "max_text_chars": arguments.max_text_chars,
        "max_json_bytes": arguments.max_json_bytes,
    }
    return SnapshotLimits(**{name: value for name, value in values.items() if value is not None})


if __name__ == "__main__":
    raise SystemExit(main())
