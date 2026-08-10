"""Adapters that let controlled exploration reuse Sprint 1 snapshot collection."""

from ai_ui_explorer.snapshot.collector import CollectionFailedError, SnapshotCollector
from ai_ui_explorer.snapshot.models import SnapshotDocument, SnapshotLimits


class SnapshotCollectorAdapter:
    def __init__(
        self,
        *,
        collector: SnapshotCollector,
        limits: SnapshotLimits,
    ) -> None:
        self._collector = collector
        self._limits = limits

    def collect(self, url: str) -> SnapshotDocument:
        try:
            return self._collector.collect(url, self._limits)
        except CollectionFailedError:
            raise CollectionFailedError(
                "Controlled exploration snapshot collection failed."
            ) from None


class SessionSnapshotCollectorAdapter(SnapshotCollectorAdapter):
    """Bind controlled exploration to a task-scoped browser session collector."""
