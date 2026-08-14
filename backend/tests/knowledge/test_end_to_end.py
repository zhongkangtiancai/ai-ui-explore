"""End-to-end acceptance for the local Snapshot-to-Knowledge workflow."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import site
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from jsonschema import Draft202012Validator, FormatChecker

from ai_ui_explorer.knowledge.cli import main as knowledge_main
from ai_ui_explorer.knowledge.ids import resolve_json_pointer
from ai_ui_explorer.knowledge.models import KnowledgePackage
from ai_ui_explorer.snapshot.browser import PlaywrightBrowserSource
from ai_ui_explorer.snapshot.collector import SnapshotCollector
from ai_ui_explorer.snapshot.models import SnapshotLimits
from ai_ui_explorer.snapshot.redaction import CustomRedactionRule, Redactor
from ai_ui_explorer.snapshot.writer import write_snapshot

_FIXTURE_MANIFEST_PATH = (
    Path(__file__).parents[1]
    / "fixtures"
    / "knowledge"
    / "application-manifest.json"
)
_KNOWLEDGE_SCHEMA_PATH = (
    Path(__file__).parents[2]
    / "src"
    / "ai_ui_explorer"
    / "knowledge"
    / "schema"
    / "knowledge-package-v1.schema.json"
)
_SNAPSHOT_ID = UUID("12345678-1234-5678-1234-567812345678")
_FORBIDDEN_FIXTURE_VALUES = (
    "fixture-password-allowlisted-do-not-return",
    "fixture-password-attribute-do-not-return",
    "fixture-token-allowlisted-do-not-return",
    "fixture-token-attribute-do-not-return",
    "fixture-input-value-do-not-return",
)
_RUNTIME_FIELDS = frozenset(
    {
        "started_at",
        "completed_at",
        "occurred_at",
        "duration_ms",
    }
)


def _wheel_source_copy_ignore() -> shutil.ignore_patterns:
    return shutil.ignore_patterns(
        "build",
        "*.egg-info",
        "__pycache__",
        ".pytest-tmp-*",
    )


def test_wheel_source_copy_ignores_pytest_temporary_directories(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "pyproject.toml").write_text("[build-system]\n", encoding="utf-8")
    temporary_directory = source / ".pytest-tmp-sprint7-final"
    temporary_directory.mkdir()
    (temporary_directory / "locked-artifact.txt").write_text("ignored", encoding="utf-8")

    destination = tmp_path / "destination"
    shutil.copytree(source, destination, ignore=_wheel_source_copy_ignore())

    assert (destination / "pyproject.toml").is_file()
    assert not (destination / ".pytest-tmp-sprint7-final").exists()


def test_wheel_contains_schemas_and_installed_console_entry_point(
    tmp_path: Path,
) -> None:
    backend_root = Path(__file__).parents[2]
    isolated_source = tmp_path / "backend-source"
    shutil.copytree(
        backend_root,
        isolated_source,
        ignore=_wheel_source_copy_ignore(),
    )
    wheel_dir = tmp_path / "wheel"
    wheel_dir.mkdir()
    build_environment = os.environ.copy()
    build_environment["PIP_CACHE_DIR"] = str(tmp_path / "pip-cache")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(wheel_dir),
            str(isolated_source),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=build_environment,
    )
    wheel_path = next(wheel_dir.glob("*.whl"))
    environment_dir = tmp_path / "installed"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "venv",
            str(environment_dir),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    executable_dir = environment_dir / ("Scripts" if os.name == "nt" else "bin")
    installed_python = executable_dir / (
        "python.exe" if os.name == "nt" else "python"
    )
    if os.name == "nt":
        installed_site_packages = environment_dir / "Lib" / "site-packages"
    else:
        installed_site_packages = (
            environment_dir
            / "lib"
            / f"python{sys.version_info.major}.{sys.version_info.minor}"
            / "site-packages"
        )
    installed_site_packages.joinpath("project-dependencies.pth").write_text(
        str(
            next(
                Path(path).resolve()
                for path in site.getsitepackages()
                if Path(path).name == "site-packages"
            )
        ),
        encoding="utf-8",
    )
    subprocess.run(
        [
            str(installed_python),
            "-m",
            "pip",
            "install",
            "--no-deps",
            str(wheel_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    resource_check = (
        "from importlib import resources;"
        "root=resources.files('ai_ui_explorer');"
        "paths=("
        "'snapshot/schema/snapshot-v1.schema.json',"
        "'snapshot/schema/snapshot-v1.1.schema.json',"
        "'knowledge/schema/application-manifest-v1.schema.json',"
        "'knowledge/schema/knowledge-package-v1.schema.json'"
        ");"
        "assert all(root.joinpath(path).is_file() for path in paths)"
    )
    subprocess.run(
        [str(installed_python), "-c", resource_check],
        check=True,
        capture_output=True,
        text=True,
    )
    console = executable_dir / (
        "ai-ui-knowledge.exe" if os.name == "nt" else "ai-ui-knowledge"
    )
    completed = subprocess.run(
        [str(console), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "--manifest" in completed.stdout
    assert "--snapshot" in completed.stdout


def test_local_snapshot_builds_traceable_knowledge_package(
    locator_page_url: str,
    tmp_path: Path,
) -> None:
    snapshot = SnapshotCollector(
        source=PlaywrightBrowserSource(headless=True),
        redactor=Redactor(
            custom_rules=[
                CustomRedactionRule(
                    name="fixture-credential",
                    category="FIXTURE_CREDENTIAL",
                    pattern=(
                        r"fixture-(?:password|token)-"
                        r"[a-z-]+-do-not-return"
                    ),
                )
            ]
        ),
        uuid_factory=lambda: _SNAPSHOT_ID,
    ).collect(locator_page_url, SnapshotLimits())
    snapshot_path = write_snapshot(snapshot, tmp_path / "snapshot")
    snapshot_payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    repeated_snapshot = SnapshotCollector(
        source=PlaywrightBrowserSource(headless=True),
        redactor=Redactor(
            custom_rules=[
                CustomRedactionRule(
                    name="fixture-credential",
                    category="FIXTURE_CREDENTIAL",
                    pattern=(
                        r"fixture-(?:password|token)-"
                        r"[a-z-]+-do-not-return"
                    ),
                )
            ]
        ),
        uuid_factory=lambda: _SNAPSHOT_ID,
    ).collect(locator_page_url, SnapshotLimits())
    repeated_snapshot_path = write_snapshot(
        repeated_snapshot,
        tmp_path / "snapshot-repeated",
    )
    repeated_snapshot_payload = json.loads(
        repeated_snapshot_path.read_text(encoding="utf-8")
    )
    assert _without_runtime_fields(snapshot_payload) == _without_runtime_fields(
        repeated_snapshot_payload
    )

    manifest_payload = json.loads(_FIXTURE_MANIFEST_PATH.read_text(encoding="utf-8"))
    parsed_url = urlsplit(locator_page_url)
    manifest_payload["allowed_origins"] = [
        f"{parsed_url.scheme}://{parsed_url.netloc}"
    ]
    manifest_path = tmp_path / "application-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest_payload, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )

    output_dir = tmp_path / "knowledge"
    result = knowledge_main(
        [
            "--manifest",
            str(manifest_path),
            "--snapshot",
            str(snapshot_path),
            "--output",
            str(output_dir),
        ]
    )

    output_path = output_dir / "knowledge-package.json"
    serialized = output_path.read_text(encoding="utf-8")
    payload = json.loads(serialized)
    package = KnowledgePackage.model_validate(payload)
    schema = json.loads(_KNOWLEDGE_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(
        schema,
        format_checker=FormatChecker(),
    ).validate(payload)

    evidence_by_id = {item.evidence_id: item for item in package.evidence}
    for fact in package.facts:
        for evidence_ref in fact.evidence_refs:
            evidence = evidence_by_id[evidence_ref]
            resolve_json_pointer(snapshot_payload, evidence.json_pointer)

    strategies = {locator.strategy for locator in package.locator_candidates}
    assert result == 0
    assert package.inferences == []
    assert strategies & {"role", "label", "text", "placeholder", "alt", "title"}
    assert strategies & {"css", "xpath"}
    assert "position" in strategies
    assert all(value not in serialized for value in _FORBIDDEN_FIXTURE_VALUES)

    repeated_output_dir = tmp_path / "knowledge-repeated"
    repeated_result = knowledge_main(
        [
            "--manifest",
            str(manifest_path),
            "--snapshot",
            str(snapshot_path),
            "--output",
            str(repeated_output_dir),
        ]
    )
    repeated_path = repeated_output_dir / "knowledge-package.json"
    assert repeated_result == 0
    assert hashlib.sha256(output_path.read_bytes()).digest() == hashlib.sha256(
        repeated_path.read_bytes()
    ).digest()

    partial_output_dir = tmp_path / "knowledge-partial"
    partial_result = knowledge_main(
        [
            "--manifest",
            str(manifest_path),
            "--snapshot",
            str(snapshot_path),
            "--output",
            str(partial_output_dir),
            "--max-facts",
            "1",
        ]
    )
    partial_path = partial_output_dir / "knowledge-package.json"
    partial_serialized = partial_path.read_text(encoding="utf-8")
    partial_payload = json.loads(partial_serialized)
    partial_package = KnowledgePackage.model_validate(partial_payload)
    Draft202012Validator(
        schema,
        format_checker=FormatChecker(),
    ).validate(partial_payload)

    assert partial_result == 2
    assert partial_package.status == "partial"
    assert len(partial_package.facts) == 1
    assert any(
        gap.reason_code == "collection_truncated"
        for gap in partial_package.knowledge_gaps
    )
    assert all(
        value not in partial_serialized for value in _FORBIDDEN_FIXTURE_VALUES
    )
    for directory in (output_dir, repeated_output_dir, partial_output_dir):
        assert [path.name for path in directory.iterdir()] == [
            "knowledge-package.json"
        ]


def _without_runtime_fields(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _without_runtime_fields(item)
            for key, item in sorted(value.items())
            if key not in _RUNTIME_FIELDS
        }
    if isinstance(value, list):
        return [_without_runtime_fields(item) for item in value]
    return value
