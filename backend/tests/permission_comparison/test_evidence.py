"""Tests for bounded Snapshot-to-identity evidence projection."""

from ai_ui_explorer.exploration.queue import ExplorationTarget
from ai_ui_explorer.permission_comparison.evidence import IdentityEvidenceCollector
from tests.snapshot.factories import (
    make_element,
    make_frame,
    make_locator_candidate,
    make_snapshot,
)


def _target(url: str = "https://app.example.test/admin") -> ExplorationTarget:
    return ExplorationTarget(
        url=url,
        depth=0,
        source_url=None,
        module_id="admin",
        action_type="module_entry",
        label="Admin",
    )


def test_evidence_collector_projects_only_redacted_snapshot_fields() -> None:
    snapshot = make_snapshot(
        source={
            "requested_url": "https://app.example.test/admin?token=source-secret",
            "final_url": "https://app.example.test/admin?token=final-secret",
            "title": "Admin",
        },
        frames=[
            make_frame(
                elements=[
                    make_element(
                        element_id="admin-link",
                        tag="a",
                        role="link",
                        accessible_name="Admin",
                        text="token=element-secret",
                        href="https://app.example.test/admin?token=href-secret",
                        attributes={"data-note": "password=attribute-secret"},
                    )
                ]
            )
        ],
        locator_candidates=[
            make_locator_candidate(
                element_ref="admin-link",
                frame_ref="main",
                parameters={"role": "link", "name": "Admin", "exact": True},
            )
        ],
        statistics={
            "frame_count": 1,
            "completed_frame_count": 1,
            "failed_frame_count": 0,
            "element_count": 1,
            "scroll_container_count": 0,
            "redaction_count": 0,
            "redaction_categories": [],
            "locator_candidate_count": 1,
            "duration_ms": 1,
        },
    )
    collector = IdentityEvidenceCollector(identity_id="identity-1")

    collector.record(_target(), snapshot)
    bundle = collector.bundle(state="completed")
    payload = bundle.model_dump_json().lower()
    element = bundle.pages[0].elements[0]

    assert "source-secret" not in payload
    assert "final-secret" not in payload
    assert "element-secret" not in payload
    assert "href-secret" not in payload
    assert "attribute-secret" not in payload
    assert element.text is not None
    assert element.attributes["data-note"] != "password=attribute-secret"
    assert len(element.locator_hints) == 1
    assert element.evidence_refs[0].json_pointer == "/frames/0/elements/0"
