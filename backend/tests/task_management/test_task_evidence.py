"""Tests for process-local, bounded task evidence."""

from ai_ui_explorer.exploration.queue import ExplorationTarget
from ai_ui_explorer.exploration.runner import ExplorationRunResult
from ai_ui_explorer.task_management.evidence import TaskEvidenceCollector
from tests.snapshot.factories import make_element, make_frame, make_snapshot


def _target(url: str) -> ExplorationTarget:
    return ExplorationTarget(
        url=url,
        depth=0,
        source_url=None,
        module_id="dashboard",
        action_type="module_entry",
        label="Dashboard",
    )


def test_task_evidence_collector_keeps_projected_pages_after_partial_run() -> None:
    collector = TaskEvidenceCollector()
    collector.record(
        _target("https://app.example.test/one?token=source-secret"),
        make_snapshot(
            frames=[
                make_frame(
                    elements=[
                        make_element(
                            element_id="help-link",
                            tag="a",
                            href="https://app.example.test/help?token=href-secret",
                        )
                    ]
                )
            ]
        ),
    )

    collector.complete(
        ExplorationRunResult(
            status="partial",
            visits=[],
            enqueue_decisions=[],
            errors=[],
            stop_reasons=["collector_failure"],
        )
    )

    pages = collector.pages()
    assert [page.page_id for page in pages] == ["page-1"]
    assert pages[0].page_key != "https://app.example.test/one?token=source-secret"
    assert pages[0].frame_count == 1
    assert pages[0].element_count == 1
    assert pages[0].link_count == 1
    assert pages[0].reason_codes == ["collector_failure"]


def test_task_evidence_detail_and_export_do_not_expose_snapshot_or_browser() -> None:
    collector = TaskEvidenceCollector()
    collector.record(
        _target("https://app.example.test/one"),
        make_snapshot(
            frames=[
                make_frame(
                    elements=[
                        make_element(
                            attributes={"data-note": "password=fixture-secret"}
                        )
                    ]
                )
            ]
        ),
    )
    detail = collector.page_detail("page-1")
    exported = collector.export(
        task_id="task-1",
        state="completed",
    )

    assert detail is not None
    assert not hasattr(detail, "snapshot")
    payload = exported.model_dump_json().lower()
    assert "fixture-secret" not in payload
    assert "snapshotdocument" not in payload
    assert "browser" not in payload
