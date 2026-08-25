"""Models and services for bounded, evidence-based identity comparisons."""

from typing import Any

__all__ = ["CreatePermissionComparisonCommand", "PermissionComparisonService"]


def __getattr__(name: str) -> Any:
    """Load service objects lazily to keep shared evidence models acyclic."""
    if name in __all__:
        from ai_ui_explorer.permission_comparison.service import (
            CreatePermissionComparisonCommand,
            PermissionComparisonService,
        )

        return {
            "CreatePermissionComparisonCommand": CreatePermissionComparisonCommand,
            "PermissionComparisonService": PermissionComparisonService,
        }[name]
    raise AttributeError(name)
