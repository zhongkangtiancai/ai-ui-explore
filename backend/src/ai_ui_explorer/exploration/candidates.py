"""Navigation candidate extraction from versioned page snapshots."""

from ai_ui_explorer.exploration.queue import NavigationCandidate
from ai_ui_explorer.snapshot.models import SnapshotDocument


def extract_navigation_candidates(
    snapshot: SnapshotDocument,
) -> list[NavigationCandidate]:
    """Return ordered, deduplicated read-only navigation candidates from href metadata."""
    candidates: list[NavigationCandidate] = []
    seen_urls: set[str] = set()
    for frame in snapshot.frames:
        for element in frame.elements:
            if element.href is None or element.href in seen_urls:
                continue
            seen_urls.add(element.href)
            candidates.append(
                NavigationCandidate(
                    url=element.href,
                    action_type="link_navigation",
                    label=element.accessible_name or element.text,
                )
            )
    return candidates
