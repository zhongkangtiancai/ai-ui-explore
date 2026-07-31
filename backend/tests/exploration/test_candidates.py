"""Navigation candidate extraction from Snapshot documents."""

from ai_ui_explorer.exploration.candidates import extract_navigation_candidates
from tests.snapshot.factories import make_element, make_frame, make_snapshot


def test_extract_navigation_candidates_from_element_hrefs() -> None:
    snapshot = make_snapshot(
        frames=[
            make_frame(
                elements=[
                    make_element(
                        element_id="help-link",
                        tag="a",
                        role="link",
                        accessible_name="Help",
                        text="Help center",
                        href="https://example.test/help",
                    )
                ]
            )
        ]
    )

    candidates = extract_navigation_candidates(snapshot)

    assert len(candidates) == 1
    assert candidates[0].url == "https://example.test/help"
    assert candidates[0].action_type == "link_navigation"
    assert candidates[0].label == "Help"


def test_extract_navigation_candidates_skips_missing_and_duplicate_hrefs() -> None:
    snapshot = make_snapshot(
        frames=[
            make_frame(
                elements=[
                    make_element(
                        element_id="first-link",
                        tag="a",
                        role="link",
                        accessible_name="First",
                        href="https://example.test/help",
                    ),
                    make_element(
                        element_id="second-link",
                        tag="a",
                        role="link",
                        accessible_name="Second",
                        href="https://example.test/help",
                    ),
                    make_element(element_id="button", tag="button", href=None),
                ]
            )
        ]
    )

    candidates = extract_navigation_candidates(snapshot)

    assert [candidate.url for candidate in candidates] == ["https://example.test/help"]
