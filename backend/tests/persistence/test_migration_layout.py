from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def test_alembic_configuration_uses_environment_database_url_without_literal_credentials() -> None:
    configuration = (BACKEND_ROOT / "alembic.ini").read_text(encoding="utf-8")
    environment = (BACKEND_ROOT / "alembic" / "env.py").read_text(encoding="utf-8")

    assert "sqlalchemy.url =" in configuration
    assert "AI_UI_EXPLORER_DATABASE_URL" not in configuration
    assert "get_settings" in environment
    assert "database_url" in environment


def test_initial_migration_declares_all_safe_projection_tables() -> None:
    migration = (
        BACKEND_ROOT / "alembic" / "versions" / "20260818_01_safe_task_persistence.py"
    ).read_text(encoding="utf-8")

    for table_name in (
        "exploration_tasks",
        "task_evidence_exports",
        "task_workflows",
        "permission_comparisons",
        "exploration_knowledge_sources",
    ):
        assert table_name in migration
