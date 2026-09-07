"""Immutable normalized models shared by the entity parsers and merge planner."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, order=True)
class TableIdentity:
    catalog: str | None
    schema: str | None
    table: str


@dataclass(frozen=True)
class SourceSpan:
    start: int
    end: int


@dataclass(frozen=True)
class AnnotationModel:
    qualified_name: str
    arguments: tuple[tuple[str, str], ...]
    span: SourceSpan


@dataclass(frozen=True)
class PropertyModel:
    name: str
    column: str
    type_name: str
    nullable: bool | None
    annotations: tuple[AnnotationModel, ...]
    declaration_span: SourceSpan
    full_span: SourceSpan
    constructor_property: bool


@dataclass(frozen=True)
class MethodModel:
    name: str
    signature: str
    span: SourceSpan
    generated_accessor_for: str | None
    referenced_names: tuple[str, ...]


@dataclass(frozen=True)
class EntityModel:
    path: str
    language: Literal["java", "kotlin"]
    package_name: str
    class_name: str
    table: TableIdentity
    properties: tuple[PropertyModel, ...]
    imports: tuple[str, ...]
    methods: tuple[MethodModel, ...]
    superclass: str | None
    interfaces: tuple[str, ...]
    custom_annotations: tuple[str, ...]
    import_region: SourceSpan | None
    class_body: SourceSpan
    generated_only: bool
    unsupported_reasons: tuple[str, ...]
    line_ending: Literal["\n", "\r\n"]


@dataclass(frozen=True)
class ParsedEntity:
    source: str
    entity: EntityModel
