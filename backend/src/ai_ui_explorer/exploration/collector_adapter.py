"""Adapters that let controlled exploration reuse Sprint 1 snapshot collection."""

from ai_ui_explorer.exploration.task import ExplorationTask
from ai_ui_explorer.snapshot.browser import PlaywrightBrowserSession
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

    def __init__(
        self,
        *,
        session: PlaywrightBrowserSession,
        task: ExplorationTask,
        limits: SnapshotLimits,
        collector: SnapshotCollector | None = None,
    ) -> None:
        bound_collector = collector or SnapshotCollector(source=session)
        if not bound_collector.is_bound_to_source(session):
            raise ValueError(
                "Session collector source does not match browser session."
            )
        self._session = session
        self._task = task
        super().__init__(collector=bound_collector, limits=limits)


def _session_collector_matches_binding(
    collector: object,
    *,
    session: PlaywrightBrowserSession,
    task: ExplorationTask,
) -> bool:
    """Verify the exact controlled adapter and its private process-local identities."""
    return (
        type(collector) is SessionSnapshotCollectorAdapter
        and object.__getattribute__(collector, "_session") is session
        and object.__getattribute__(collector, "_task") is task
    )


def _session_collector_matches_task(
    collector: object,
    task: ExplorationTask,
) -> bool:
    """Verify task identity without trusting a caller-provided port capability."""
    return (
        type(collector) is SessionSnapshotCollectorAdapter
        and object.__getattribute__(collector, "_task") is task
    )
