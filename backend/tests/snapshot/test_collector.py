"""Tests for raw-observation collection orchestration."""

from ai_ui_explorer.snapshot.collector import SnapshotCollector
from ai_ui_explorer.snapshot.models import SnapshotLimits

from .fakes import FakeSource


def test_collector_keeps_successful_frames_when_one_frame_fails() -> None:
    source = FakeSource.with_one_success_and_one_failure()

    snapshot = SnapshotCollector(source=source).collect(
        "https://example.test", SnapshotLimits()
    )

    assert snapshot.status == "partial"
    assert snapshot.truncated is False
    assert len(snapshot.frames) == 2
    assert snapshot.frames[0].status == "completed"
    assert snapshot.frames[1].status == "failed"
    assert snapshot.errors[0].recoverable is True


def test_collector_redacts_before_snapshot_validation() -> None:
    source = FakeSource.with_text("token=super-secret")

    snapshot = SnapshotCollector(source=source).collect(
        "https://example.test", SnapshotLimits()
    )

    assert "super-secret" not in snapshot.model_dump_json()


def test_collector_tracks_redactions_per_frame_and_globally() -> None:
    snapshot = SnapshotCollector(
        source=FakeSource.with_one_success_and_one_failure()
    ).collect("https://example.test", SnapshotLimits())

    assert snapshot.frames[0].redaction_count == 2
    assert snapshot.frames[1].redaction_count == 0
    assert snapshot.statistics.redaction_count == 2
