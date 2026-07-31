"""Sprint 4 page state fingerprint tests."""

from ai_ui_explorer.exploration.state import StateDeduplicator, fingerprint_snapshot
from tests.snapshot.factories import make_element, make_frame, make_snapshot


def test_snapshot_fingerprint_is_stable_for_same_semantic_content() -> None:
    first = make_snapshot()
    second = make_snapshot()

    assert fingerprint_snapshot(first).fingerprint == fingerprint_snapshot(second).fingerprint


def test_snapshot_fingerprint_changes_for_url_and_element_structure() -> None:
    base = make_snapshot()
    changed_url = make_snapshot(
        source={
            "requested_url": "https://example.test/settings",
            "final_url": "https://example.test/settings",
            "title": "Example page",
        }
    )
    changed_element = make_snapshot(
        frames=[
            make_frame(
                elements=[
                    make_element(
                        element_id="element-0",
                        tag="a",
                        role="link",
                        accessible_name="Settings",
                        text="Settings",
                    )
                ]
            )
        ]
    )

    assert fingerprint_snapshot(base).fingerprint != fingerprint_snapshot(changed_url).fingerprint
    assert (
        fingerprint_snapshot(base).fingerprint
        != fingerprint_snapshot(changed_element).fingerprint
    )


def test_state_deduplicator_marks_repeated_states() -> None:
    snapshot = make_snapshot()
    deduplicator = StateDeduplicator()

    first = deduplicator.observe(snapshot)
    second = deduplicator.observe(snapshot)

    assert first.seen_before is False
    assert second.seen_before is True
    assert first.fingerprint == second.fingerprint
