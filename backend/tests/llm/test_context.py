"""Context manager contract tests for Sprint 3."""

from ai_ui_explorer.llm.context import ContextManager, ContextRequest
from tests.knowledge.factories import make_package


def test_context_envelope_includes_source_records_and_evidence_closure() -> None:
    package = make_package()

    envelope = ContextManager(max_estimated_tokens=20_000).build(
        ContextRequest(
            package=package,
            task="Explain the known controls.",
        )
    )

    assert envelope.application_id == "example-app"
    assert envelope.environment == "test"
    assert envelope.identity_alias is None
    assert envelope.truncated is False
    assert envelope.records
    assert envelope.evidence
    referenced_evidence = {
        evidence_ref
        for record in envelope.records
        for evidence_ref in record.evidence_refs
    }
    assert {item.evidence_id for item in envelope.evidence} == referenced_evidence


def test_context_envelope_truncates_by_whole_records() -> None:
    package = make_package()

    envelope = ContextManager(max_estimated_tokens=1).build(
        ContextRequest(
            package=package,
            task="Keep the context tiny.",
        )
    )

    assert envelope.truncated is True
    assert envelope.records == []
    assert envelope.evidence == []
    assert envelope.stop_reasons == ["context_token_budget"]


def test_context_cache_isolated_by_application_environment_and_identity() -> None:
    package = make_package()
    manager = ContextManager(max_estimated_tokens=20_000, cache_size=8)

    anonymous = manager.build(
        ContextRequest(package=package, task="Summarize.", identity_alias=None)
    )
    same_again = manager.build(
        ContextRequest(package=package, task="Summarize.", identity_alias=None)
    )
    qa_user = manager.build(
        ContextRequest(package=package, task="Summarize.", identity_alias="qa-user")
    )

    assert same_again.cache_hit is True
    assert anonymous.cache_key != qa_user.cache_key
    assert qa_user.cache_hit is False
