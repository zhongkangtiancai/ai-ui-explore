"""Deterministic mapping from validated Snapshots to knowledge packages."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal, cast

from ai_ui_explorer.knowledge.evidence import EvidenceBuilder
from ai_ui_explorer.knowledge.ids import canonical_json, stable_id
from ai_ui_explorer.knowledge.manifest import ApplicationManifest
from ai_ui_explorer.knowledge.models import (
    AccessStatus,
    CollectionStatus,
    ContentStatus,
    EntityType,
    Evidence,
    ExplorationRun,
    ExplorationStatus,
    Fact,
    FactValue,
    IdentityContext,
    KnowledgeApplication,
    KnowledgeEntity,
    KnowledgeGap,
    KnowledgeGapReason,
    KnowledgeLimits,
    KnowledgeLocator,
    KnowledgePackage,
    KnowledgeStatistics,
    KnowledgeStatus,
    LocatorParameter,
    LocatorSource,
    LocatorStability,
    LocatorStrategy,
    LocatorUniqueness,
    MatchHint,
    MatchHintType,
    Observation,
)
from ai_ui_explorer.knowledge.predicates import Predicate
from ai_ui_explorer.snapshot.models import (
    AnySnapshotDocument,
    ElementSnapshot,
    ElementSnapshotV1,
    FrameSnapshot,
    FrameSnapshotV1,
    SnapshotDocument,
    SnapshotDocumentV1,
    SnapshotError,
)
from ai_ui_explorer.snapshot.redaction import Redactor

UrlClassification = Literal["target", "authentication", "outside"]
SnapshotFrame = FrameSnapshot | FrameSnapshotV1
SnapshotElement = ElementSnapshot | ElementSnapshotV1

_ALLOWED_ATTRIBUTES = frozenset(
    {
        "id",
        "name",
        "type",
        "placeholder",
        "data-testid",
        "alt",
        "title",
    }
)
_CONTROLLED_ACCESS_CODES = {
    "authentication_required": AccessStatus.AUTHENTICATION_REQUIRED,
    "permission_denied": AccessStatus.PERMISSION_DENIED,
    "anti_automation_blocked": AccessStatus.ANTI_AUTOMATION_BLOCKED,
    "rate_limited": AccessStatus.RATE_LIMITED,
}
_ACCESS_PRECEDENCE = (
    "permission_denied",
    "anti_automation_blocked",
    "rate_limited",
    "authentication_required",
)
_OBSERVATION_TEXT = {
    AccessStatus.AUTHENTICATION_REQUIRED: (
        "The source reported that authentication is required.",
        "The controlled error records an access state, not a verified identity.",
    ),
    AccessStatus.PERMISSION_DENIED: (
        "The source reported that access was denied.",
        "One exploration result does not prove the complete permission rule.",
    ),
    AccessStatus.ANTI_AUTOMATION_BLOCKED: (
        "The source reported an anti-automation block.",
        "The source error does not identify the blocking mechanism.",
    ),
    AccessStatus.RATE_LIMITED: (
        "The source reported rate limiting.",
        "The source error does not establish the complete rate-limit policy.",
    ),
}
_UNSUPPORTED_ASPECTS = (
    "entity.module",
    "entity.action",
    "entity.workflow",
    "entity.permission",
    "entity.data_scope",
    "entity.change_history",
)


class KnowledgeBuildError(ValueError):
    """A knowledge package could not be built safely."""


class _BuildFailure(StrEnum):
    OUTSIDE_REQUEST_ORIGIN = "outside_request_origin"
    INVALID_INPUT = "invalid_input"
    MAPPING_FAILED = "mapping_failed"


@dataclass(frozen=True, slots=True)
class _SourceError:
    error: SnapshotError
    pointer: str


class KnowledgePackageBuilder:
    """Build one immutable knowledge package without I/O or inference."""

    def build(
        self,
        manifest: ApplicationManifest,
        snapshot: AnySnapshotDocument,
        limits: KnowledgeLimits | None = None,
    ) -> KnowledgePackage:
        """Map validated inputs to a complete or source-partial package."""

        package, failure = self._try_build(
            manifest=manifest,
            snapshot=snapshot,
            limits=limits,
        )
        del manifest, snapshot, limits
        if failure == _BuildFailure.OUTSIDE_REQUEST_ORIGIN:
            raise KnowledgeBuildError(
                "Snapshot request origin is not allowed."
            )
        if failure is not None:
            raise KnowledgeBuildError("Knowledge package could not be built.")
        assert package is not None
        return package

    def _try_build(
        self,
        *,
        manifest: ApplicationManifest,
        snapshot: AnySnapshotDocument,
        limits: KnowledgeLimits | None,
    ) -> tuple[KnowledgePackage | None, _BuildFailure | None]:
        if not isinstance(manifest, ApplicationManifest) or not isinstance(
            snapshot,
            SnapshotDocument | SnapshotDocumentV1,
        ):
            return None, _BuildFailure.INVALID_INPUT
        if limits is not None and not isinstance(limits, KnowledgeLimits):
            return None, _BuildFailure.INVALID_INPUT

        requested_classification = _safe_classify_url(
            manifest,
            snapshot.source.requested_url,
        )
        if requested_classification != "target":
            return None, _BuildFailure.OUTSIDE_REQUEST_ORIGIN
        final_classification = _safe_classify_url(
            manifest,
            snapshot.source.final_url,
        )
        if final_classification is None:
            final_classification = "outside"

        failed = False
        package: KnowledgePackage | None = None
        try:
            package = _BuildContext(
                manifest=manifest,
                snapshot=snapshot,
                limits=limits or KnowledgeLimits(),
                final_classification=final_classification,
            ).build()
        except Exception:
            failed = True
        if failed:
            return None, _BuildFailure.MAPPING_FAILED
        return package, None


class _BuildContext:
    def __init__(
        self,
        *,
        manifest: ApplicationManifest,
        snapshot: AnySnapshotDocument,
        limits: KnowledgeLimits,
        final_classification: UrlClassification,
    ) -> None:
        self.manifest = manifest
        self.snapshot = snapshot
        self.limits = limits
        self.final_classification = final_classification
        self.redactor = Redactor()
        self.evidence_builder = EvidenceBuilder(
            snapshot=snapshot,
            redactor=self.redactor,
            excerpt_limit=limits.max_evidence_chars,
        )
        self.evidence: dict[str, Evidence] = {}
        self.entities: list[KnowledgeEntity] = []
        self.locators: list[KnowledgeLocator] = []
        self.facts: list[Fact] = []
        self.observations: list[Observation] = []
        self.gaps: list[KnowledgeGap] = []
        self.entity_source_pointers: dict[str, str] = {}
        self.frame_entity_ids: dict[str, str] = {}
        self.frames_by_id: dict[str, SnapshotFrame] = {}
        self.element_entity_ids_by_pointer: dict[str, str] = {}
        self.element_entity_ids_by_source_ref: dict[tuple[str, str], str] = {}
        self.element_source_order: dict[str, tuple[int, int, int, int]] = {}
        self.extra_entity_hints: dict[str, list[MatchHint]] = {}
        self.locator_counts: dict[str, int] = {}
        self.budget_stop_reasons: set[str] = set()
        self.critical_mapping_failure = False
        self._initialize_source_indexes()

        source_evidence = self._evidence(
            "/snapshot_id",
            Predicate.EXPLORATION_SOURCE_SNAPSHOT.value,
        )
        self.snapshot_sha256 = source_evidence.snapshot_sha256
        self.run_id = stable_id(
            "exploration-run",
            str(snapshot.snapshot_id),
            self.snapshot_sha256,
        )
        self.page_id = stable_id(
            "page",
            str(snapshot.snapshot_id),
            "/page",
        )

    def build(self) -> KnowledgePackage:
        application = self._application()
        source_errors = self._source_errors()
        access_status = self._access_status(source_errors)
        self._map_observations(source_errors)

        if self.final_classification == "target":
            self._map_entities()
            self._map_page_facts()
            self._map_frame_and_element_facts()
            self._map_locators()
            self._finalize_entity_hints()

        source_incomplete = self.snapshot.status != "completed"
        package_is_partial = (
            source_incomplete or self.critical_mapping_failure
        )
        collection_status = (
            CollectionStatus.PARTIAL
            if source_incomplete
            else CollectionStatus.COMPLETED
        )
        exploration_status = (
            ExplorationStatus.PARTIAL
            if package_is_partial
            else ExplorationStatus.COMPLETED
        )
        exploration_run = ExplorationRun(
            exploration_run_id=self.run_id,
            snapshot_id=self.snapshot.snapshot_id,
            snapshot_schema_version=self.snapshot.schema_version,
            snapshot_sha256=self.snapshot_sha256,
            collection_status=collection_status,
            content_status=ContentStatus.INSUFFICIENT_EVIDENCE,
            access_status=access_status,
            exploration_status=exploration_status,
            identity_context=IdentityContext(
                status="not_provided",
                identity_alias=None,
                role_label=None,
                authorization_scope=[],
            ),
            started_at=self.snapshot.started_at,
            completed_at=self.snapshot.completed_at,
        )
        self._map_exploration_facts(
            exploration_run=exploration_run,
        )
        self._map_gaps(source_incomplete=source_incomplete)
        if self.budget_stop_reasons:
            self._ensure_truncation_gap()

        stop_reasons = self._stop_reasons(source_incomplete)
        entities = sorted(
            self.entities,
            key=lambda entity: (
                entity.entity_type.value,
                self.entity_source_pointers[entity.entity_id],
            ),
        )
        locators = sorted(
            self.locators,
            key=lambda locator: (
                self.element_source_order[locator.element_ref],
                locator.rank,
                locator.locator_id,
            ),
        )
        facts = sorted(
            self.facts,
            key=lambda fact: (
                fact.subject_ref,
                fact.predicate.value,
                fact.fact_id,
            ),
        )
        observations = sorted(
            self.observations,
            key=lambda item: (
                item.subject_ref,
                item.summary,
                item.observation_id,
            ),
        )
        gaps = sorted(
            self.gaps,
            key=lambda gap: (
                gap.subject_ref,
                gap.reason_code.value,
                gap.gap_id,
            ),
        )
        referenced_evidence = {
            evidence_ref
            for collection in (
                entities,
                locators,
                facts,
                observations,
                gaps,
            )
            for item in collection
            for evidence_ref in getattr(
                item,
                "source_refs",
                getattr(item, "evidence_refs", []),
            )
        }
        evidence = sorted(
            (
                item
                for item in self.evidence.values()
                if item.evidence_id in referenced_evidence
            ),
            key=lambda item: (
                item.json_pointer,
                item.evidence_type,
                item.evidence_id,
            ),
        )
        if self.budget_stop_reasons:
            package_is_partial = True
            stop_reasons = sorted(
                {*stop_reasons, *self.budget_stop_reasons}
            )
            if exploration_run.exploration_status == ExplorationStatus.COMPLETED:
                exploration_run = exploration_run.model_copy(
                    update={
                        "exploration_status": ExplorationStatus.PARTIAL,
                    }
                )
        statistics = KnowledgeStatistics(
            entity_count=len(entities),
            locator_candidate_count=len(locators),
            evidence_count=len(evidence),
            fact_count=len(facts),
            observation_count=len(observations),
            inference_count=0,
            knowledge_gap_count=len(gaps),
        )
        package = KnowledgePackage(
            package_id=stable_id(
                "kp",
                self.manifest.application_id,
                canonical_json(self.manifest.model_dump(mode="json")),
                str(self.snapshot.snapshot_id),
                self.snapshot_sha256,
            ),
            status=(
                KnowledgeStatus.PARTIAL
                if package_is_partial
                else KnowledgeStatus.COMPLETED
            ),
            limits=self.limits,
            application=application,
            exploration_run=exploration_run,
            entities=entities,
            locator_candidates=locators,
            evidence=evidence,
            facts=facts,
            observations=observations,
            inferences=[],
            knowledge_gaps=gaps,
            statistics=statistics,
            stop_reasons=stop_reasons,
        )
        return KnowledgePackage.model_validate(
            package.model_dump(mode="python")
        )

    def _application(self) -> KnowledgeApplication:
        return KnowledgeApplication(
            application_id=self.manifest.application_id,
            name=self.manifest.name,
            environment=self.manifest.environment,
            manifest_schema_version=self.manifest.schema_version,
            allowed_origins=self.manifest.allowed_origins,
            authentication_origins=self.manifest.authentication_origins,
        )

    def _map_entities(self) -> None:
        page_evidence = self._evidence(
            "/page/main_frame_id",
            "page.main_frame_id",
        )
        page_hints: list[MatchHint] = []
        if self.final_classification == "target":
            final_url = self.redactor.redact_url(
                self.snapshot.source.final_url
            ).value
            if final_url.strip():
                page_hints.append(
                    MatchHint(hint_type=MatchHintType.URL, value=final_url)
                )
        self._add_entity(
            KnowledgeEntity(
                entity_id=self.page_id,
                entity_type=EntityType.PAGE,
                label=self._label(self.snapshot.source.title, "Page"),
                application_ref=self.manifest.application_id,
                source_refs=[page_evidence.evidence_id],
                observed_from=self.snapshot.started_at,
                observed_to=self.snapshot.completed_at,
                match_hints=page_hints,
            ),
            source_pointer="/page",
        )

        indexed_frames = sorted(
            enumerate(self._frames()),
            key=lambda item: (
                item[1].traversal_index,
                item[0],
            ),
        )
        for frame_index, frame in indexed_frames:
            pointer = f"/frames/{frame_index}"
            entity_id = stable_id(
                "frame",
                str(self.snapshot.snapshot_id),
                pointer,
            )
            self.frame_entity_ids[frame.frame_id] = entity_id

        for frame_index, frame in indexed_frames:
            pointer = f"/frames/{frame_index}"
            entity_id = self.frame_entity_ids[frame.frame_id]
            ancestry = self._frame_ancestry(frame)
            frame_hints: list[MatchHint] = []
            if ancestry:
                frame_hints.append(
                    MatchHint(
                        hint_type=MatchHintType.FRAME_ANCESTRY,
                        value=canonical_json(ancestry),
                    )
                )
            frame_url = self.redactor.redact_url(frame.url).value
            if frame_url.strip():
                frame_hints.append(
                    MatchHint(
                        hint_type=MatchHintType.URL,
                        value=frame_url,
                    )
                )
            frame_source = self._evidence(
                f"{pointer}/frame_id",
                "frame.frame_id",
            )
            self._add_entity(
                KnowledgeEntity(
                    entity_id=entity_id,
                    entity_type=EntityType.FRAME,
                    label=self._label(frame.name, "Frame"),
                    application_ref=self.manifest.application_id,
                    source_refs=[frame_source.evidence_id],
                    observed_from=self.snapshot.started_at,
                    observed_to=self.snapshot.completed_at,
                    match_hints=frame_hints,
                ),
                source_pointer=pointer,
            )

            indexed_elements = sorted(
                enumerate(frame.elements),
                key=lambda item: (
                    item[1].traversal_index,
                    item[0],
                ),
            )
            for element_index, element in indexed_elements:
                element_pointer = (
                    f"{pointer}/elements/{element_index}"
                )
                element_id = stable_id(
                    "element",
                    str(self.snapshot.snapshot_id),
                    element_pointer,
                )
                self.element_entity_ids_by_pointer[element_pointer] = element_id
                self.element_entity_ids_by_source_ref[
                    (frame.frame_id, element.element_id)
                ] = element_id
                self.element_source_order[element_id] = (
                    frame.traversal_index,
                    element.traversal_index,
                    frame_index,
                    element_index,
                )
                element_source = self._evidence(
                    f"{element_pointer}/element_id",
                    "element.element_id",
                )
                self._add_entity(
                    KnowledgeEntity(
                        entity_id=element_id,
                        entity_type=EntityType.ELEMENT,
                        label=self._element_label(element),
                        application_ref=self.manifest.application_id,
                        source_refs=[element_source.evidence_id],
                        observed_from=self.snapshot.started_at,
                        observed_to=self.snapshot.completed_at,
                        match_hints=self._element_hints(element),
                    ),
                    source_pointer=element_pointer,
                )

    def _map_page_facts(self) -> None:
        page_values: tuple[tuple[Predicate, str, FactValue | None], ...] = (
            (
                Predicate.PAGE_REQUESTED_URL,
                "/source/requested_url",
                self.redactor.redact_url(
                    self.snapshot.source.requested_url
                ).value,
            ),
            (
                Predicate.PAGE_FINAL_URL,
                "/source/final_url",
                self.redactor.redact_url(
                    self.snapshot.source.final_url
                ).value,
            ),
            (
                Predicate.PAGE_TITLE,
                "/source/title",
                self._safe_text(self.snapshot.source.title),
            ),
            (
                Predicate.PAGE_LANGUAGE,
                "/page/language",
                (
                    self._safe_text(self.snapshot.page.language)
                    if self.snapshot.page.language is not None
                    else None
                ),
            ),
            (
                Predicate.PAGE_VIEWPORT_WIDTH,
                "/page/viewport_width",
                self.snapshot.page.viewport_width,
            ),
            (
                Predicate.PAGE_VIEWPORT_HEIGHT,
                "/page/viewport_height",
                self.snapshot.page.viewport_height,
            ),
        )
        for predicate, pointer, value in page_values:
            if not self._has_observed_value(value):
                continue
            self._record_fact(
                subject_ref=self.page_id,
                predicate=predicate,
                pointer=pointer,
                observed_at=self.snapshot.completed_at,
                value=value,
            )

    def _map_frame_and_element_facts(self) -> None:
        for frame_index, frame in enumerate(self._frames()):
            frame_pointer = f"/frames/{frame_index}"
            frame_entity_id = self.frame_entity_ids[frame.frame_id]
            if frame.parent_frame_id is not None:
                parent_ref = self.frame_entity_ids.get(
                    frame.parent_frame_id
                )
                if parent_ref is None:
                    self.critical_mapping_failure = True
                else:
                    self._record_fact(
                        subject_ref=frame_entity_id,
                        predicate=Predicate.FRAME_PARENT,
                        pointer=f"{frame_pointer}/parent_frame_id",
                        observed_at=self.snapshot.completed_at,
                        object_ref=parent_ref,
                    )
            frame_values: tuple[
                tuple[Predicate, str, FactValue | None],
                ...,
            ] = (
                (
                    Predicate.FRAME_NAME,
                    f"{frame_pointer}/name",
                    self._safe_text(frame.name),
                ),
                (
                    Predicate.FRAME_URL,
                    f"{frame_pointer}/url",
                    self.redactor.redact_url(frame.url).value,
                ),
                (
                    Predicate.FRAME_STATUS,
                    f"{frame_pointer}/status",
                    frame.status,
                ),
                (
                    Predicate.FRAME_DEPTH,
                    f"{frame_pointer}/depth",
                    frame.depth,
                ),
                (
                    Predicate.FRAME_TRUNCATED,
                    f"{frame_pointer}/truncated",
                    frame.truncated,
                ),
            )
            for predicate, pointer, value in frame_values:
                if not self._has_observed_value(value):
                    continue
                self._record_fact(
                    subject_ref=frame_entity_id,
                    predicate=predicate,
                    pointer=pointer,
                    observed_at=self.snapshot.completed_at,
                    value=value,
                )

            for element_index, element in enumerate(frame.elements):
                element_pointer = (
                    f"{frame_pointer}/elements/{element_index}"
                )
                element_id = self._element_entity_id(
                    frame_index,
                    element_index,
                )
                self._record_fact(
                    subject_ref=element_id,
                    predicate=Predicate.ELEMENT_LOCATED_IN,
                    pointer=f"{element_pointer}/frame_id",
                    observed_at=self.snapshot.completed_at,
                    object_ref=frame_entity_id,
                )
                self._map_element_values(
                    element_id=element_id,
                    element=element,
                    pointer=element_pointer,
                )

    def _map_element_values(
        self,
        *,
        element_id: str,
        element: SnapshotElement,
        pointer: str,
    ) -> None:
        values: tuple[
            tuple[Predicate, str, FactValue | None],
            ...,
        ] = (
            (
                Predicate.ELEMENT_TAG,
                f"{pointer}/tag",
                self._safe_text(element.tag),
            ),
            (
                Predicate.ELEMENT_ROLE,
                f"{pointer}/role",
                (
                    self._safe_text(element.role)
                    if element.role is not None
                    else None
                ),
            ),
            (
                Predicate.ELEMENT_ACCESSIBLE_NAME,
                f"{pointer}/accessible_name",
                (
                    self._safe_text(element.accessible_name)
                    if element.accessible_name is not None
                    else None
                ),
            ),
            (
                Predicate.ELEMENT_TEXT,
                f"{pointer}/text",
                (
                    self._safe_text(element.text)
                    if element.text is not None
                    else None
                ),
            ),
            (
                Predicate.ELEMENT_VISIBLE,
                f"{pointer}/visible",
                element.visible,
            ),
            (
                Predicate.ELEMENT_ENABLED,
                f"{pointer}/enabled",
                element.enabled,
            ),
            (
                Predicate.ELEMENT_CHECKED,
                f"{pointer}/checked",
                element.checked,
            ),
            (
                Predicate.ELEMENT_SELECTED,
                f"{pointer}/selected",
                element.selected,
            ),
            (
                Predicate.ELEMENT_EXPANDED,
                f"{pointer}/expanded",
                element.expanded,
            ),
        )
        for predicate, value_pointer, value in values:
            if not self._has_observed_value(value):
                continue
            self._record_fact(
                subject_ref=element_id,
                predicate=predicate,
                pointer=value_pointer,
                observed_at=self.snapshot.completed_at,
                value=value,
            )

        allowed = {
            key: value
            for key, value in element.attributes.items()
            if key in _ALLOWED_ATTRIBUTES or key.startswith("aria-")
        }
        redacted, _ = self.redactor.redact_mapping(allowed)
        for key in sorted(redacted):
            self._record_fact(
                subject_ref=element_id,
                predicate=Predicate.ELEMENT_ATTRIBUTE,
                pointer=(
                    f"{pointer}/attributes/"
                    f"{_json_pointer_token(key)}"
                ),
                observed_at=self.snapshot.completed_at,
                value=canonical_json(
                    {"name": key, "value": redacted[key]}
                ),
            )

    def _map_locators(self) -> None:
        if isinstance(self.snapshot, SnapshotDocument):
            self._map_current_locators()
            return
        self._map_legacy_locators()

    def _map_current_locators(self) -> None:
        assert isinstance(self.snapshot, SnapshotDocument)
        for candidate_index, candidate in enumerate(
            self.snapshot.locator_candidates
        ):
            element_ref = self.element_entity_ids_by_source_ref[
                (candidate.frame_ref, candidate.element_ref)
            ]
            frame_ref = self.frame_entity_ids[candidate.frame_ref]
            if not self._can_add_locator(element_ref, frame_ref):
                continue
            parameters = self._redact_parameters(candidate.parameters)
            candidate_pointer = (
                f"/locator_candidates/{candidate_index}"
            )
            source_evidence = self._evidence(
                candidate_pointer,
                "locator.candidate",
            )
            locator = KnowledgeLocator(
                locator_id=stable_id(
                    "locator",
                    element_ref,
                    candidate_pointer,
                ),
                element_ref=element_ref,
                frame_ref=frame_ref,
                strategy=LocatorStrategy(candidate.strategy),
                parameters=parameters,
                source=LocatorSource(candidate.source),
                uniqueness=LocatorUniqueness(candidate.uniqueness),
                match_count=candidate.match_count,
                stability=LocatorStability(candidate.stability),
                confidence=candidate.confidence,
                rank=candidate.rank,
                recommended=candidate.recommended,
                evidence_refs=[source_evidence.evidence_id],
                limitations=[
                    self._safe_text(item)
                    for item in candidate.limitations
                ],
            )
            self._add_locator(
                locator,
                observed_pointers={
                    Predicate.LOCATOR_LOCATES: (
                        f"{candidate_pointer}/element_ref"
                    ),
                    Predicate.LOCATOR_STRATEGY: (
                        f"{candidate_pointer}/strategy"
                    ),
                    Predicate.LOCATOR_UNIQUENESS: (
                        f"{candidate_pointer}/uniqueness"
                    ),
                    Predicate.LOCATOR_STABILITY: (
                        f"{candidate_pointer}/stability"
                    ),
                    Predicate.LOCATOR_RECOMMENDED: (
                        f"{candidate_pointer}/recommended"
                    ),
                },
            )

    def _map_legacy_locators(self) -> None:
        assert isinstance(self.snapshot, SnapshotDocumentV1)
        legacy_frames = self.snapshot.frames
        indexed_frames = sorted(
            enumerate(legacy_frames),
            key=lambda item: (item[1].traversal_index, item[0]),
        )
        for frame_index, frame in indexed_frames:
            indexed_elements = sorted(
                enumerate(frame.elements),
                key=lambda item: (item[1].traversal_index, item[0]),
            )
            for element_index, element in indexed_elements:
                element_ref = self._element_entity_id(
                    frame_index,
                    element_index,
                )
                frame_ref = self.frame_entity_ids[frame.frame_id]
                rank = 1
                for hint_index, hint in enumerate(
                    element.locator_hints
                ):
                    if not self._can_add_locator(element_ref, frame_ref):
                        continue
                    pointer = (
                        f"/frames/{frame_index}/elements/{element_index}"
                        f"/locator_hints/{hint_index}"
                    )
                    parameters = self._redact_parameters(
                        {hint.strategy: hint.value}
                    )
                    evidence = self._evidence(
                        pointer,
                        "locator.legacy_hint",
                    )
                    locator = KnowledgeLocator(
                        locator_id=stable_id(
                            "locator",
                            element_ref,
                            hint.strategy,
                            parameters,
                        ),
                        element_ref=element_ref,
                        frame_ref=frame_ref,
                        strategy=LocatorStrategy(hint.strategy),
                        parameters=parameters,
                        source=LocatorSource.OBSERVED,
                        uniqueness=LocatorUniqueness.UNVERIFIED,
                        match_count=None,
                        stability=LocatorStability.UNKNOWN,
                        confidence=0.5,
                        rank=rank,
                        recommended=False,
                        evidence_refs=[evidence.evidence_id],
                        limitations=[
                            "Snapshot 1.0 did not verify locator uniqueness."
                        ],
                    )
                    self._add_locator(
                        locator,
                        observed_pointers={
                            Predicate.LOCATOR_STRATEGY: (
                                f"{pointer}/strategy"
                            ),
                        },
                    )
                    rank += 1

                if element.bounds is None:
                    continue
                if not self._can_add_locator(element_ref, frame_ref):
                    continue
                pointer = (
                    f"/frames/{frame_index}/elements/{element_index}"
                    "/bounds"
                )
                parameters = {
                    "x": element.bounds.x,
                    "y": element.bounds.y,
                    "width": element.bounds.width,
                    "height": element.bounds.height,
                }
                evidence = self._evidence(
                    pointer,
                    "locator.legacy_bounds",
                )
                locator = KnowledgeLocator(
                    locator_id=stable_id(
                        "locator",
                        element_ref,
                        LocatorStrategy.POSITION.value,
                        parameters,
                    ),
                    element_ref=element_ref,
                    frame_ref=frame_ref,
                    strategy=LocatorStrategy.POSITION,
                    parameters=parameters,
                    source=LocatorSource.DIAGNOSTIC,
                    uniqueness=LocatorUniqueness.UNVERIFIED,
                    match_count=None,
                    stability=LocatorStability.LOW,
                    confidence=0.25,
                    rank=rank,
                    recommended=False,
                    evidence_refs=[evidence.evidence_id],
                    limitations=[
                        "Position is diagnostic and was not uniqueness-verified."
                    ],
                )
                self._add_locator(
                    locator,
                    observed_pointers={},
                )

    def _add_locator(
        self,
        locator: KnowledgeLocator,
        *,
        observed_pointers: dict[Predicate, str],
    ) -> None:
        if not self._can_add_locator(locator.element_ref, locator.frame_ref):
            return
        locator_count = self.locator_counts.get(locator.element_ref, 0)
        self.locator_counts[locator.element_ref] = locator_count + 1
        self.locators.append(locator)
        if locator.parameters:
            self.extra_entity_hints.setdefault(
                locator.element_ref,
                [],
            ).append(
                MatchHint(
                    hint_type=MatchHintType.LOCATOR_PARAMETER,
                    value=canonical_json(
                        {
                            "strategy": locator.strategy.value,
                            "parameters": dict(locator.parameters),
                        }
                    ),
                )
            )
        for predicate, value, object_ref in (
            (
                Predicate.LOCATOR_LOCATES,
                None,
                locator.element_ref,
            ),
            (
                Predicate.LOCATOR_STRATEGY,
                locator.strategy.value,
                None,
            ),
            (
                Predicate.LOCATOR_UNIQUENESS,
                locator.uniqueness.value,
                None,
            ),
            (
                Predicate.LOCATOR_STABILITY,
                locator.stability.value,
                None,
            ),
            (
                Predicate.LOCATOR_RECOMMENDED,
                locator.recommended,
                None,
            ),
        ):
            pointer = observed_pointers.get(predicate)
            if pointer is None:
                continue
            self._record_fact(
                subject_ref=locator.locator_id,
                predicate=predicate,
                pointer=pointer,
                observed_at=self.snapshot.completed_at,
                value=value,
                object_ref=object_ref,
            )

    def _can_add_locator(
        self,
        element_ref: str,
        frame_ref: str,
    ) -> bool:
        has_frame_relationship = any(
            fact.subject_ref == element_ref
            and fact.predicate == Predicate.ELEMENT_LOCATED_IN
            and fact.object_ref == frame_ref
            for fact in self.facts
        )
        if not has_frame_relationship:
            return False
        locator_count = self.locator_counts.get(element_ref, 0)
        if locator_count >= self.limits.max_locators_per_element:
            self.budget_stop_reasons.add("knowledge_locator_limit")
            return False
        return True

    def _finalize_entity_hints(self) -> None:
        finalized: list[KnowledgeEntity] = []
        for entity in self.entities:
            hints = [
                *entity.match_hints,
                *self.extra_entity_hints.get(entity.entity_id, []),
            ]
            unique = {
                (hint.hint_type.value, hint.value): hint
                for hint in hints
            }
            finalized.append(
                KnowledgeEntity.model_validate(
                    {
                        **entity.model_dump(mode="python"),
                        "match_hints": [
                            unique[key] for key in sorted(unique)
                        ],
                    }
                )
            )
        self.entities = finalized

    def _map_exploration_facts(
        self,
        *,
        exploration_run: ExplorationRun,
    ) -> None:
        values: tuple[tuple[Predicate, str, FactValue], ...] = (
            (
                Predicate.EXPLORATION_SOURCE_SNAPSHOT,
                "/snapshot_id",
                str(self.snapshot.snapshot_id),
            ),
            (
                Predicate.EXPLORATION_COLLECTION_STATUS,
                "/status",
                exploration_run.collection_status.value,
            ),
        )
        for predicate, pointer, value in values:
            self._record_fact(
                subject_ref=self.run_id,
                predicate=predicate,
                pointer=pointer,
                observed_at=self.snapshot.completed_at,
                value=value,
            )

    def _map_observations(
        self,
        source_errors: list[_SourceError],
    ) -> None:
        for source_error in source_errors:
            access_status = _CONTROLLED_ACCESS_CODES.get(
                source_error.error.error_code
            )
            if access_status is None:
                continue
            if len(self.observations) >= self.limits.max_observations:
                self.budget_stop_reasons.add("knowledge_observation_limit")
                continue
            summary, limitation = _OBSERVATION_TEXT[access_status]
            evidence = self._evidence(
                source_error.pointer,
                "observation.access",
            )
            self.observations.append(
                Observation(
                    observation_id=stable_id(
                        "observation",
                        self.run_id,
                        access_status.value,
                        evidence.evidence_id,
                    ),
                    subject_ref=self.run_id,
                    summary=summary,
                    evidence_refs=[evidence.evidence_id],
                    confidence=0.9,
                    limitations=[limitation],
                )
            )

    def _map_gaps(self, *, source_incomplete: bool) -> None:
        for aspect in _UNSUPPORTED_ASPECTS:
            self._record_gap(
                subject_ref=self.manifest.application_id,
                aspect=aspect,
                reason_code=(
                    KnowledgeGapReason.UNSUPPORTED_IN_CURRENT_SPRINT
                ),
                reason="This entity type is outside the current Sprint.",
                evidence_refs=[],
                verification=(
                    "Implement and validate the dedicated future mapper."
                ),
            )
        self._record_gap(
            subject_ref=self.run_id,
            aspect="identity.context",
            reason_code=KnowledgeGapReason.IDENTITY_NOT_AVAILABLE,
            reason="No controlled identity was provided for this Snapshot.",
            evidence_refs=[],
            verification=(
                "Repeat exploration with an authorized controlled identity."
            ),
        )
        if isinstance(self.snapshot, SnapshotDocumentV1):
            self._record_gap(
                subject_ref=self.run_id,
                aspect="locator.structural_selectors",
                reason_code=(
                    KnowledgeGapReason.SNAPSHOT_VERSION_LIMITED
                ),
                reason=(
                    "Snapshot 1.0 has no verified CSS or XPath candidates."
                ),
                evidence_refs=[],
                verification=(
                    "Capture a Snapshot 1.1 with verified locator candidates."
                ),
            )
        if source_incomplete or self.critical_mapping_failure:
            evidence_refs: list[str] = []
            if source_incomplete:
                evidence_refs.append(
                    self._evidence(
                        "/status",
                        Predicate.EXPLORATION_COLLECTION_STATUS.value,
                    ).evidence_id
                )
            self._record_gap(
                subject_ref=self.run_id,
                aspect="exploration.collection",
                reason_code=KnowledgeGapReason.COLLECTION_TRUNCATED,
                reason=(
                    "The source or a critical mapping did not complete."
                ),
                evidence_refs=evidence_refs,
                verification=(
                    "Repeat collection and rebuild from a complete Snapshot."
                ),
            )

    def _access_status(
        self,
        source_errors: list[_SourceError],
    ) -> AccessStatus:
        for error_code in _ACCESS_PRECEDENCE:
            matching = [
                item
                for item in source_errors
                if item.error.error_code == error_code
            ]
            if matching:
                return _CONTROLLED_ACCESS_CODES[error_code]
        if (
            self.final_classification == "target"
            and self.snapshot.status == "completed"
        ):
            return AccessStatus.PUBLIC
        return AccessStatus.UNKNOWN

    def _source_errors(self) -> list[_SourceError]:
        errors = [
            _SourceError(error=error, pointer=f"/errors/{index}")
            for index, error in enumerate(self.snapshot.errors)
        ]
        for frame_index, frame in enumerate(self._frames()):
            errors.extend(
                _SourceError(
                    error=error,
                    pointer=f"/frames/{frame_index}/errors/{error_index}",
                )
                for error_index, error in enumerate(frame.errors)
            )
        return sorted(errors, key=lambda item: item.pointer)

    def _frame_ancestry(self, frame: SnapshotFrame) -> list[str]:
        ancestry: list[str] = []
        current: SnapshotFrame | None = frame
        seen: set[str] = set()
        while current is not None:
            if current.frame_id in seen:
                self.critical_mapping_failure = True
                return []
            seen.add(current.frame_id)
            label = self._safe_text(current.frame_id).strip()
            ancestry.append(label or "unnamed-frame")
            if current.parent_frame_id is None:
                break
            current = self.frames_by_id.get(current.parent_frame_id)
            if current is None:
                self.critical_mapping_failure = True
                return []
        return list(reversed(ancestry))

    def _element_hints(
        self,
        element: SnapshotElement,
    ) -> list[MatchHint]:
        hints: list[MatchHint] = []
        values = (
            (MatchHintType.TAG, element.tag),
            (MatchHintType.ROLE, element.role),
            (
                MatchHintType.TEST_ID,
                element.attributes.get("data-testid"),
            ),
        )
        for hint_type, raw_value in values:
            if raw_value is None:
                continue
            value = self._safe_text(raw_value)
            if value.strip():
                hints.append(MatchHint(hint_type=hint_type, value=value))
        return hints

    def _element_label(self, element: SnapshotElement) -> str:
        for value in (
            element.accessible_name,
            element.role,
            element.tag,
        ):
            if value is None:
                continue
            redacted = self._safe_text(value)
            if redacted.strip():
                return redacted
        return "Element"

    def _redact_parameters(
        self,
        parameters: dict[str, LocatorParameter],
    ) -> dict[str, LocatorParameter]:
        redacted_parameters: dict[str, LocatorParameter] = {}
        for key in sorted(parameters):
            value = parameters[key]
            redacted, _ = self.redactor.redact_mapping(
                {key: str(value)}
            )
            redacted_value = redacted[key]
            if redacted_value != str(value):
                redacted_parameters[key] = redacted_value
            elif isinstance(value, str):
                redacted_parameters[key] = self._safe_text(value)
            else:
                redacted_parameters[key] = value
        return redacted_parameters

    def _record_fact(
        self,
        *,
        subject_ref: str,
        predicate: Predicate,
        pointer: str,
        observed_at: datetime,
        value: FactValue | None = None,
        object_ref: str | None = None,
    ) -> None:
        if len(self.facts) >= self.limits.max_facts:
            self.budget_stop_reasons.add("knowledge_fact_limit")
            return
        self.facts.append(
            self._fact(
                subject_ref=subject_ref,
                predicate=predicate,
                pointer=pointer,
                observed_at=observed_at,
                value=value,
                object_ref=object_ref,
            )
        )

    def _fact(
        self,
        *,
        subject_ref: str,
        predicate: Predicate,
        pointer: str,
        observed_at: datetime,
        value: FactValue | None = None,
        object_ref: str | None = None,
    ) -> Fact:
        evidence = self._evidence(pointer, predicate.value)
        return Fact(
            fact_id=stable_id(
                "fact",
                subject_ref,
                predicate.value,
                value,
                object_ref,
                evidence.evidence_id,
            ),
            subject_ref=subject_ref,
            predicate=predicate,
            value=value,
            object_ref=object_ref,
            evidence_refs=[evidence.evidence_id],
            observed_at=observed_at,
        )

    def _record_gap(
        self,
        *,
        subject_ref: str,
        aspect: str,
        reason_code: KnowledgeGapReason,
        reason: str,
        evidence_refs: list[str],
        verification: str,
    ) -> None:
        if len(self.gaps) >= self.limits.max_knowledge_gaps:
            self.budget_stop_reasons.add("knowledge_gap_limit")
            return
        self.gaps.append(
            self._gap(
                subject_ref=subject_ref,
                aspect=aspect,
                reason_code=reason_code,
                reason=reason,
                evidence_refs=evidence_refs,
                verification=verification,
            )
        )

    def _ensure_truncation_gap(self) -> None:
        if any(
            gap.reason_code == KnowledgeGapReason.COLLECTION_TRUNCATED
            for gap in self.gaps
        ):
            return
        truncation_gap = self._gap(
            subject_ref=self.run_id,
            aspect="exploration.collection",
            reason_code=KnowledgeGapReason.COLLECTION_TRUNCATED,
            reason=(
                "The Knowledge Package was compacted to satisfy configured budgets."
            ),
            evidence_refs=[],
            verification="Increase budgets or rebuild from a smaller Snapshot.",
        )
        if len(self.gaps) < self.limits.max_knowledge_gaps:
            self.gaps.append(truncation_gap)
            return
        self.gaps[-1] = truncation_gap

    def _evidence(
        self,
        pointer: str,
        evidence_type: str,
    ) -> Evidence:
        evidence = self.evidence_builder.at(pointer, evidence_type)
        self.evidence[evidence.evidence_id] = evidence
        return evidence

    def _gap(
        self,
        *,
        subject_ref: str,
        aspect: str,
        reason_code: KnowledgeGapReason,
        reason: str,
        evidence_refs: list[str],
        verification: str,
    ) -> KnowledgeGap:
        return KnowledgeGap(
            gap_id=stable_id(
                "gap",
                subject_ref,
                aspect,
                reason_code.value,
                evidence_refs,
            ),
            subject_ref=subject_ref,
            aspect=aspect,
            reason_code=reason_code,
            reason=reason,
            evidence_refs=evidence_refs,
            verification=verification,
        )

    def _add_entity(
        self,
        entity: KnowledgeEntity,
        *,
        source_pointer: str,
    ) -> None:
        self.entities.append(entity)
        self.entity_source_pointers[entity.entity_id] = source_pointer

    def _safe_text(self, value: str) -> str:
        return self.redactor.redact_text(value).value

    def _has_observed_value(self, value: FactValue | None) -> bool:
        if value is None:
            return False
        return not isinstance(value, str) or bool(value.strip())

    def _label(self, value: str, fallback: str) -> str:
        label = self._safe_text(value)
        return label if label.strip() else fallback

    def _stop_reasons(self, source_incomplete: bool) -> list[str]:
        reasons: list[str] = []
        if source_incomplete:
            reasons.append("source_snapshot_incomplete")
        if self.critical_mapping_failure:
            reasons.append("critical_mapping_failure")
        return reasons

    def _frames(self) -> list[SnapshotFrame]:
        return cast(list[SnapshotFrame], self.snapshot.frames)

    def _initialize_source_indexes(self) -> None:
        self.frames_by_id = {
            frame.frame_id: frame for frame in self._frames()
        }
        if len(self.frames_by_id) != len(self._frames()):
            raise ValueError("Snapshot frame identifiers are ambiguous.")

        seen_element_refs: set[tuple[str, str]] = set()
        for frame in self._frames():
            for element in frame.elements:
                source_ref = (frame.frame_id, element.element_id)
                if source_ref in seen_element_refs:
                    raise ValueError("Snapshot element identifiers are ambiguous.")
                seen_element_refs.add(source_ref)

    def _element_entity_id(
        self,
        frame_index: int,
        element_index: int,
    ) -> str:
        pointer = f"/frames/{frame_index}/elements/{element_index}"
        return self.element_entity_ids_by_pointer[pointer]


def _safe_classify_url(
    manifest: ApplicationManifest,
    value: str,
) -> UrlClassification | None:
    classification: UrlClassification | None = None
    try:
        classification = manifest.classify_url(value)
    except (TypeError, ValueError):
        pass
    return classification


def _json_pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")
