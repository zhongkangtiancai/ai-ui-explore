from ai_ui_explorer.persistence.models import Base


def test_persistence_metadata_defines_only_safe_projection_tables() -> None:
    assert set(Base.metadata.tables) == {
        "exploration_tasks",
        "task_evidence_exports",
        "task_workflows",
        "permission_comparisons",
        "exploration_knowledge_sources",
    }


def test_exploration_task_index_excludes_login_state_columns() -> None:
    table = Base.metadata.tables["exploration_tasks"]

    column_names = set(table.columns.keys())
    assert {"task_id", "state", "phase", "updated_at"} <= column_names
    assert not {"cookie", "token", "storage_state", "password"} & column_names
