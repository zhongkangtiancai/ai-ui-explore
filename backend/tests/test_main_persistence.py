from unittest.mock import Mock

from ai_ui_explorer.core.config import Settings
from ai_ui_explorer.main import create_app
from ai_ui_explorer.persistence.repositories import SafeTaskRepository


def test_app_factory_interrupts_unfinished_tasks_before_exposing_services() -> None:
    repository = Mock(spec=SafeTaskRepository)
    settings = Settings(database_url="postgresql://user:password@localhost:5432/explorer")

    app = create_app(settings=settings, persistence_repository=repository)

    repository.interrupt_nonterminal_tasks.assert_called_once()
    assert app.state.exploration_task_service is not None
