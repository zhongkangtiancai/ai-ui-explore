"""Controlled predicate vocabulary for observed knowledge facts."""

from enum import StrEnum


class Predicate(StrEnum):
    """Finite predicate namespace accepted by the Sprint 2 contract."""

    APPLICATION_NAME = "application.name"
    APPLICATION_ENVIRONMENT = "application.environment"
    APPLICATION_ALLOWED_ORIGIN = "application.allowed_origin"
    APPLICATION_AUTHENTICATION_ORIGIN = "application.authentication_origin"

    PAGE_REQUESTED_URL = "page.requested_url"
    PAGE_FINAL_URL = "page.final_url"
    PAGE_TITLE = "page.title"
    PAGE_LANGUAGE = "page.language"
    PAGE_VIEWPORT_WIDTH = "page.viewport_width"
    PAGE_VIEWPORT_HEIGHT = "page.viewport_height"

    FRAME_PARENT = "frame.parent"
    FRAME_NAME = "frame.name"
    FRAME_URL = "frame.url"
    FRAME_STATUS = "frame.status"
    FRAME_DEPTH = "frame.depth"
    FRAME_TRUNCATED = "frame.truncated"

    ELEMENT_LOCATED_IN = "element.located_in"
    ELEMENT_TAG = "element.tag"
    ELEMENT_ROLE = "element.role"
    ELEMENT_ACCESSIBLE_NAME = "element.accessible_name"
    ELEMENT_TEXT = "element.text"
    ELEMENT_VISIBLE = "element.visible"
    ELEMENT_ENABLED = "element.enabled"
    ELEMENT_CHECKED = "element.checked"
    ELEMENT_SELECTED = "element.selected"
    ELEMENT_EXPANDED = "element.expanded"
    ELEMENT_ATTRIBUTE = "element.attribute"

    LOCATOR_LOCATES = "locator.locates"
    LOCATOR_STRATEGY = "locator.strategy"
    LOCATOR_UNIQUENESS = "locator.uniqueness"
    LOCATOR_STABILITY = "locator.stability"
    LOCATOR_RECOMMENDED = "locator.recommended"

    EXPLORATION_SOURCE_SNAPSHOT = "exploration.source_snapshot"
    EXPLORATION_COLLECTION_STATUS = "exploration.collection_status"
    EXPLORATION_CONTENT_STATUS = "exploration.content_status"
    EXPLORATION_ACCESS_STATUS = "exploration.access_status"

    IDENTITY_STATUS = "identity.status"
    ACCESS_STATUS = "access.status"
