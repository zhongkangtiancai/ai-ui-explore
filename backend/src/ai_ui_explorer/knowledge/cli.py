"""Public command-line interface for building Knowledge Packages."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import NoReturn

from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

from ai_ui_explorer.knowledge.builder import (
    KnowledgeBuildError,
    KnowledgePackageBuilder,
)
from ai_ui_explorer.knowledge.manifest import ApplicationManifest
from ai_ui_explorer.knowledge.models import KnowledgeLimits, KnowledgePackage
from ai_ui_explorer.knowledge.snapshot_adapter import SnapshotLoadError, load_snapshot
from ai_ui_explorer.knowledge.writer import (
    KnowledgePackageExistsError,
    KnowledgePackageTooLargeError,
    write_knowledge_package,
)


class _SafeArgumentParser(argparse.ArgumentParser):
    """Avoid echoing user-provided paths or values in usage errors."""

    def error(self, message: str) -> NoReturn:
        del message
        self.print_usage(sys.stderr)
        self.exit(2, "error: invalid arguments\n")


def build_parser() -> argparse.ArgumentParser:
    """Build the safe, non-interactive Knowledge Package parser."""

    parser = _SafeArgumentParser(description="Build a Knowledge Package.")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-evidence-chars", type=_bounded_int(1, 10_000))
    parser.add_argument("--max-locators-per-element", type=_bounded_int(1, 100))
    parser.add_argument("--max-facts", type=_bounded_int(1, 1_000_000))
    parser.add_argument("--max-observations", type=_bounded_int(0, 10_000))
    parser.add_argument("--max-knowledge-gaps", type=_bounded_int(1, 10_000))
    parser.add_argument("--max-json-bytes", type=_bounded_int(65_536, 524_288_000))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Build and write one Knowledge Package without disclosing source content."""

    try:
        arguments = build_parser().parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2

    try:
        manifest = _load_manifest(arguments.manifest)
        snapshot = load_snapshot(arguments.snapshot)
        limits = _limits_from_arguments(arguments)
        package = KnowledgePackageBuilder().build(
            manifest=manifest,
            snapshot=snapshot,
            limits=limits,
        )
        output_path = write_knowledge_package(package, arguments.output)
        written = output_path.read_text(encoding="utf-8")
        final_package = KnowledgePackage.model_validate_json(written)
    except (
        KnowledgeBuildError,
        KnowledgePackageExistsError,
        KnowledgePackageTooLargeError,
        OSError,
        RecursionError,
        SnapshotLoadError,
        UnicodeError,
        ValidationError,
        JsonSchemaValidationError,
        ValueError,
    ):
        print("status=fatal")
        return 1

    stats = final_package.statistics
    print(
        f"output={output_path} status={final_package.status} "
        f"entities={stats.entity_count} locators={stats.locator_candidate_count} "
        f"facts={stats.fact_count} evidence={stats.evidence_count} "
        f"gaps={stats.knowledge_gap_count}"
    )
    return 0 if final_package.status == "completed" else 2


def _load_manifest(path: Path) -> ApplicationManifest:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, RecursionError, UnicodeError, ValueError) as error:
        raise ValueError("manifest payload is invalid") from error
    return ApplicationManifest.model_validate(payload)


def _bounded_int(minimum: int, maximum: int) -> Callable[[str], int]:
    def parse(value: str) -> int:
        try:
            parsed = int(value)
        except ValueError as exc:
            raise argparse.ArgumentTypeError("expected an integer") from exc
        if not minimum <= parsed <= maximum:
            raise argparse.ArgumentTypeError("integer is outside the allowed range")
        return parsed

    return parse


def _limits_from_arguments(arguments: argparse.Namespace) -> KnowledgeLimits:
    values = {
        "max_evidence_chars": arguments.max_evidence_chars,
        "max_locators_per_element": arguments.max_locators_per_element,
        "max_facts": arguments.max_facts,
        "max_observations": arguments.max_observations,
        "max_knowledge_gaps": arguments.max_knowledge_gaps,
        "max_json_bytes": arguments.max_json_bytes,
    }
    return KnowledgeLimits(**{key: value for key, value in values.items() if value is not None})


if __name__ == "__main__":
    raise SystemExit(main())
