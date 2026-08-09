"""Deterministic, fail-closed planning for Doma entity synchronization."""
from __future__ import annotations

import dataclasses
import difflib
import hashlib
import json
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal, Sequence

from .java_parser import (
    JavaParseError,
    find_java_annotation_declarations,
    find_java_domain_declarations,
    parse_java,
)
from .kotlin_parser import (
    KotlinParseError,
    find_kotlin_annotation_declarations,
    find_kotlin_domain_declarations,
    parse_kotlin,
)
from .lexer import lex_java, lex_kotlin
from .model import AnnotationModel, EntityModel, ParsedEntity, PropertyModel, SourceSpan, TableIdentity


PLAN_FORMAT_VERSION = 1
SNAPSHOT_PATH = "build/doma-codegen/schema-snapshot.json"
_FINDING_ID_MARKER = "{finding_id}"
_STATUS = {"SAFE", "REVIEW_REQUIRED", "BLOCKED"}
_EDIT_KINDS = {"create", "insert", "replace", "delete"}
_SOURCE_SUFFIXES = {".java": "java", ".kt": "kotlin"}
_SENSITIVE = re.compile(
    r"(?i)(?:\b(?:https?|jdbc:[a-z0-9]+)://|\b(?:user|password|passwd|token|access[_-]?key|secret)\s*[:=]|\bAKIA[0-9A-Z]{12,})"
)


class PlanInputError(ValueError):
    """Raised for malformed, sensitive, or unsafe planning inputs."""


@dataclass(frozen=True)
class Edit:
    kind: Literal["create", "insert", "replace", "delete"]
    path: str
    span: SourceSpan | None
    text: str


@dataclass(frozen=True)
class Finding:
    finding_id: str
    status: Literal["SAFE", "REVIEW_REQUIRED", "BLOCKED"]
    kind: str
    path: str
    table: TableIdentity
    column: str | None
    database: dict[str, object]
    existing: str | None
    candidate: str | None
    reason: str
    action: str
    edits: tuple[Edit, ...]


@dataclass(frozen=True)
class MergePlan:
    format_version: int
    project_root: Literal["."]
    schema_snapshot_sha256: str
    source_hashes: tuple[tuple[str, str], ...]
    generated_hashes: tuple[tuple[str, str], ...]
    findings: tuple[Finding, ...]


@dataclass(frozen=True)
class _SourceFile:
    absolute: Path
    path: str
    source: str
    sha256: str
    bom: bool
    language: Literal["java", "kotlin"]
    root: str


@dataclass(frozen=True)
class _ParsedFile:
    file: _SourceFile
    parsed: ParsedEntity


@dataclass(frozen=True)
class _ParseFailure:
    file: _SourceFile
    reason: str


@dataclass(frozen=True)
class _Table:
    identity: TableIdentity
    raw: dict[str, object]
    columns: tuple[dict[str, object], ...]
    primary_key: tuple[dict[str, object], ...]


def build_plan(
    project_root: Path | str,
    schema_snapshot: Path | str,
    generated_dir: Path | str,
    existing_roots: Sequence[Path | str],
    language: Literal["java", "kotlin", "auto"] = "auto",
) -> MergePlan:
    """Build a stable plan without writing source files."""
    if language not in {"java", "kotlin", "auto"}:
        raise PlanInputError("language must be java, kotlin, or auto")
    root = _project_root(project_root)
    snapshot_path = _input_path(root, schema_snapshot, file=True)
    if _relative(root, snapshot_path) != SNAPSHOT_PATH:
        raise PlanInputError("schema snapshot must use the managed build path")
    generated_root = _input_path(root, generated_dir, directory=True)
    if not existing_roots:
        raise PlanInputError("at least one existing source root is required")
    source_roots = tuple(_input_path(root, item, directory=True) for item in existing_roots)
    if len(set(source_roots)) != len(source_roots):
        raise PlanInputError("duplicate existing source root")
    if any(_contains_path(source_root, generated_root) or _contains_path(generated_root, source_root)
           for source_root in source_roots):
        raise PlanInputError("generated and existing roots must not overlap")

    snapshot_bytes = _read_bytes(snapshot_path)
    _reject_sensitive(snapshot_bytes)
    manifest = _load_json(snapshot_bytes)
    tables = _validate_manifest(manifest)
    snapshot_hash = _sha(snapshot_bytes)

    source_files = _collect_sources(root, source_roots, language)
    generated_files = _collect_sources(root, (generated_root,), language)
    if not generated_files and tables:
        raise PlanInputError("generated candidate directory contains no entity sources")
    all_files = source_files + generated_files
    annotation_declarations = _annotation_context(all_files)
    domain_types = _domain_context(all_files, annotation_declarations)
    existing_parsed, existing_failures = _parse_files(
        source_files, domain_types, annotation_declarations, generated=False
    )
    generated_parsed, generated_failures = _parse_files(
        generated_files, domain_types, annotation_declarations, generated=True
    )

    findings: list[Finding] = []
    fallback_table = tables[0].identity if len(tables) == 1 else TableIdentity(None, None, "<unknown>")
    for failure in existing_failures + generated_failures:
        findings.append(_make_finding(
            "BLOCKED", "parser-error", failure.file.path, fallback_table, None,
            {"parser": failure.file.language}, None, None,
            "The conservative parser could not prove a safe entity model.",
            "Fix the source syntax or regenerate the candidate, then create a new plan.", (),
        ))

    generated_by_table, generated_duplicates = _by_table(generated_parsed)
    existing_by_table, existing_duplicates = _by_table(existing_parsed)
    for identity, duplicates, kind in (
        *[(identity, files, "duplicate-generated-table") for identity, files in generated_duplicates.items()],
        *[(identity, files, "duplicate-existing-table") for identity, files in existing_duplicates.items()],
    ):
        for parsed_file in duplicates:
            findings.append(_make_finding(
                "BLOCKED", kind, parsed_file.file.path, identity, None,
                {"table": _table_dict(identity)}, None, None,
                "More than one source maps to the same physical table.",
                "Choose one mapping explicitly; the database cannot choose an application type.", (),
            ))

    existing_classes = _by_class(existing_parsed)
    table_identities = {table.identity for table in tables}
    for candidate in generated_parsed:
        if candidate.parsed.entity.table not in table_identities:
            findings.append(_make_finding(
                "BLOCKED", "generated-table-outside-snapshot", candidate.file.path,
                candidate.parsed.entity.table, None, {"scope": manifest["scope"]}, None,
                _entity_excerpt(candidate), "A generated entity is outside the authoritative snapshot.",
                "Regenerate candidates from exactly this schema snapshot.", (),
            ))

    reference_files = source_files
    source_root_names = tuple(_relative(root, item) for item in source_roots)
    for table in tables:
        candidate = generated_by_table.get(table.identity)
        if candidate is None:
            findings.append(_make_finding(
                "BLOCKED", "missing-generated-entity", SNAPSHOT_PATH, table.identity, None,
                {"table": table.raw}, None, None,
                "The snapshot table has no exact generated @Table match.",
                "Regenerate entities; do not infer a class or file name from the table name.", (),
            ))
            continue
        if candidate.parsed.entity.unsupported_reasons or not candidate.parsed.entity.generated_only:
            findings.append(_unsupported_finding(candidate, table, generated=True))
            continue
        existing = existing_by_table.get(table.identity)
        if existing is None:
            same_class = existing_classes.get(_class_key(candidate.parsed.entity), ())
            if same_class:
                findings.append(_make_finding(
                    "BLOCKED", "table-schema-rename", same_class[0].file.path, table.identity, None,
                    {"table": table.raw}, _entity_excerpt(same_class[0]), _entity_excerpt(candidate),
                    "The class matches but its physical @Table identity changed.",
                    "Decide whether this is a table/schema rename or a new entity; no rename is inferred.", (),
                ))
                continue
            finding = _new_entity_finding(
                root, table, candidate, source_roots, source_root_names, source_files
            )
            findings.append(finding)
            continue
        if existing.parsed.entity.class_name != candidate.parsed.entity.class_name:
            findings.append(_make_finding(
                "BLOCKED", "class-rename", existing.file.path, table.identity, None,
                {"table": table.raw}, existing.parsed.entity.class_name,
                candidate.parsed.entity.class_name,
                "The exact table maps to different class names.",
                "Choose the application class name manually; the database has no class-name semantics.", (),
            ))
            continue
        if existing.parsed.entity.unsupported_reasons or not existing.parsed.entity.generated_only:
            findings.append(_unsupported_finding(existing, table, generated=False))
            findings.extend(_blocked_changes_in_unsupported_source(table, existing, candidate))
            continue
        file_findings = _compare_entity(table, existing, candidate, reference_files)
        findings.extend(_fail_closed_file(file_findings))

    for existing in existing_parsed:
        identity = existing.parsed.entity.table
        if identity in table_identities or identity in existing_duplicates:
            continue
        if not _identity_in_scope(identity, manifest):
            continue
        findings.append(_make_finding(
            "BLOCKED", "removed-entity", existing.file.path, identity, None,
            {"scope": manifest["scope"], "table_present": False},
            _entity_excerpt(existing), None,
            "The mapped table is absent from the authoritative snapshot, but deleting an application type is not automatic.",
            "Confirm the scope and remove or migrate the entity manually if the table was intentionally dropped.", (),
        ))

    ordered = tuple(sorted(findings, key=_finding_sort_key))
    return MergePlan(
        PLAN_FORMAT_VERSION,
        ".",
        snapshot_hash,
        tuple(sorted((item.path, item.sha256) for item in source_files)),
        tuple(sorted((item.path, item.sha256) for item in generated_files)),
        ordered,
    )


def plan_json(plan: MergePlan) -> str:
    """Serialize a plan with stable key and collection ordering."""
    value = {
        "format_version": plan.format_version,
        "project_root": plan.project_root,
        "schema_snapshot_sha256": plan.schema_snapshot_sha256,
        "source_hashes": [list(item) for item in plan.source_hashes],
        "generated_hashes": [list(item) for item in plan.generated_hashes],
        "findings": [_finding_dict(finding) for finding in plan.findings],
    }
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    _reject_sensitive(rendered.encode("utf-8"))
    return rendered


def load_plan(path: Path | str) -> MergePlan:
    """Load and strictly validate a plan file."""
    raw = _read_bytes(Path(path))
    _reject_sensitive(raw)
    value = _load_json(raw)
    if not isinstance(value, dict) or set(value) != {
        "format_version", "project_root", "schema_snapshot_sha256", "source_hashes",
        "generated_hashes", "findings",
    }:
        raise PlanInputError("invalid merge plan fields")
    if value["format_version"] != PLAN_FORMAT_VERSION or value["project_root"] != ".":
        raise PlanInputError("unsupported merge plan version or project root")
    snapshot_hash = _hash_value(value["schema_snapshot_sha256"])
    source_hashes = _hash_pairs(value["source_hashes"])
    generated_hashes = _hash_pairs(value["generated_hashes"])
    raw_findings = value["findings"]
    if not isinstance(raw_findings, list):
        raise PlanInputError("findings must be a list")
    findings = tuple(_load_finding(item) for item in raw_findings)
    if tuple(sorted(findings, key=_finding_sort_key)) != findings:
        raise PlanInputError("findings are not in deterministic order")
    return MergePlan(1, ".", snapshot_hash, source_hashes, generated_hashes, findings)


def render_diff(plan: MergePlan) -> str:
    """Render deterministic proposal diffs without reading mutable source files."""
    chunks: list[str] = []
    for finding in plan.findings:
        if not finding.edits:
            continue
        chunks.append(_proposal_diff(finding.path, finding.existing, finding.candidate))
    return "".join(chunks)


def result_state(plan: MergePlan, approvals: Iterable[str] = ()) -> str:
    approved = frozenset(approvals)
    if any(finding.status == "BLOCKED" for finding in plan.findings):
        return "BLOCKED"
    if any(
        finding.status == "REVIEW_REQUIRED" and finding.finding_id not in approved
        for finding in plan.findings
    ):
        return "PENDING_REVIEW"
    return "SUCCESS"


def contains_sensitive(value: str | bytes) -> bool:
    text = value.decode("utf-8", "ignore") if isinstance(value, bytes) else value
    return bool(_SENSITIVE.search(text))


def _compare_entity(
    table: _Table,
    existing: _ParsedFile,
    candidate: _ParsedFile,
    references: Sequence[_SourceFile],
) -> tuple[Finding, ...]:
    old = existing.parsed.entity
    new = candidate.parsed.entity
    old_source = existing.parsed.source
    new_source = candidate.parsed.source
    path = existing.file.path
    database_base: dict[str, object] = {
        "table": table.raw,
        "existing_root": existing.file.root,
        "generated_path": candidate.file.path,
    }
    findings: list[Finding] = []
    db_columns = {str(column["name"]): column for column in table.columns}
    new_by_column = {prop.column: prop for prop in new.properties}
    old_by_column = {prop.column: prop for prop in old.properties}
    old_by_name = {prop.name: prop for prop in old.properties}

    documentation_mismatches = tuple(
        (prop, db_columns[prop.column])
        for prop in new.properties
        if prop.column in db_columns
        and not _database_comment_matches_snapshot(
            candidate, prop, db_columns[prop.column].get("remarks")
        )
    )
    if documentation_mismatches:
        return tuple(
            _database_comment_mismatch_finding(
                table,
                path,
                prop.column,
                {**database_base, "column": column},
            )
            for prop, column in documentation_mismatches
        )

    missing_candidate = sorted(set(db_columns) - set(new_by_column))
    extra_candidate = sorted(set(new_by_column) - set(db_columns))
    if missing_candidate or extra_candidate:
        findings.append(_make_finding(
            "BLOCKED", "generated-column-mismatch", path, table.identity, None,
            database_base, ", ".join(extra_candidate) or None,
            ", ".join(missing_candidate) or None,
            "Generated @Column mappings do not exactly cover the schema snapshot.",
            "Regenerate candidates from the authoritative snapshot.", (),
        ))

    matches: dict[str, PropertyModel] = {}
    added: list[PropertyModel] = []
    corrections: list[tuple[PropertyModel, PropertyModel]] = []
    for new_prop in new.properties:
        old_prop = old_by_column.get(new_prop.column)
        if old_prop is not None:
            if old_prop.name != new_prop.name:
                findings.append(_make_finding(
                    "BLOCKED", "property-rename", path, table.identity, new_prop.column,
                    {**database_base, "column": db_columns.get(new_prop.column, {})},
                    old_prop.name, new_prop.name,
                    "One physical column maps to different property names.",
                    "Choose the property rename manually; the database cannot name application properties.", (),
                ))
            else:
                matches[new_prop.column] = old_prop
            continue
        same_name = old_by_name.get(new_prop.name)
        if same_name is not None:
            if same_name.column in db_columns and same_name.column != new_prop.column:
                findings.append(_make_finding(
                    "BLOCKED", "property-rename", path, table.identity, new_prop.column,
                    {**database_base, "column": db_columns.get(new_prop.column, {})},
                    _property_excerpt(old_source, same_name), _property_excerpt(new_source, new_prop),
                    "A property-name match would remap between two live database columns.",
                    "Resolve the application property mapping manually.", (),
                ))
            else:
                matches[new_prop.column] = same_name
                corrections.append((same_name, new_prop))
            continue
        added.append(new_prop)

    for old_prop, new_prop in corrections:
        old_column = _annotation(old_prop, "org.seasar.doma.Column")
        new_column = _annotation(new_prop, "org.seasar.doma.Column")
        if new_column is None:
            findings.append(_make_finding(
                "BLOCKED", "generated-column-mismatch", path, table.identity, new_prop.column,
                {**database_base, "column": db_columns.get(new_prop.column, {})},
                _property_excerpt(old_source, old_prop), _property_excerpt(new_source, new_prop),
                "The candidate has no exact @Column proposal for the physical mapping.",
                "Regenerate with explicit column names.", (),
            ))
            continue
        kind = "add-column" if old_column is None else "correct-column"
        edits = _annotation_change_edits(existing, candidate, old_prop, new_prop, old_column, new_column)
        findings.append(_make_finding(
            "SAFE", kind, path, table.identity, new_prop.column,
            {**database_base, "column": db_columns.get(new_prop.column, {})},
            _annotation_text(old_source, old_column), _annotation_text(new_source, new_column),
            "The generated property name is unchanged and the database column identity is exact.",
            "Synchronize only the @Column annotation.", edits,
        ))

    for new_prop in added:
        if new_prop.column not in db_columns:
            continue
        edits = _add_property_edits(existing, candidate, new_prop, matches)
        findings.append(_make_finding(
            "SAFE", "add-property", path, table.identity, new_prop.column,
            {**database_base, "column": db_columns[new_prop.column]}, None,
            _property_with_accessors(candidate, new_prop),
            "The database column and generated property are unique and have no source collision.",
            "Insert the generated body property and its generated accessors.", edits,
        ))

    mapped_old = set(matches.values())
    for old_prop in old.properties:
        if old_prop in mapped_old:
            continue
        if old_prop.column in db_columns:
            continue
        has_reference = _has_external_reference(references, existing.file.path, old, old_prop)
        generated_accessors = tuple(
            method for method in old.methods if method.generated_accessor_for == old_prop.name
        )
        executable = old.generated_only and not has_reference and (
            old.language == "kotlin" or len(generated_accessors) in {0, 2}
        )
        edits: tuple[Edit, ...] = ()
        status = "REVIEW_REQUIRED" if executable else "BLOCKED"
        if executable:
            edit_list = [Edit("delete", path, old_prop.full_span, "")]
            edit_list.extend(Edit("delete", path, method.span, "") for method in generated_accessors)
            edits = tuple(edit_list)
        findings.append(_make_finding(
            status, "remove-property", path, table.identity, old_prop.column,
            {**database_base, "column_present": False}, _property_with_accessors(existing, old_prop), None,
            "The column is absent from the authoritative snapshot; deletion may break application APIs."
            if executable else "The removed column is referenced or is not a generated-shaped member.",
            "Delete only after reviewing call sites and persistence compatibility."
            if executable else "Remove or migrate handwritten references manually before replanning.", edits,
        ))

    db_pk = tuple(str(item["column"]) for item in table.primary_key)
    candidate_pk = tuple(
        prop.column for prop in new.properties if _annotation(prop, "org.seasar.doma.Id") is not None
    )
    if set(candidate_pk) != set(db_pk) or len(candidate_pk) != len(db_pk):
        findings.append(_make_finding(
            "BLOCKED", "candidate-primary-key-mismatch", path, table.identity, None,
            {**database_base, "primary_key": list(table.primary_key)}, None, ", ".join(candidate_pk),
            "Generated @Id membership does not exactly match the database primary key.",
            "Regenerate candidates; never infer primary-key membership from names.", (),
        ))
    else:
        id_edits: list[Edit] = []
        existing_membership: list[str] = []
        for new_prop in new.properties:
            old_prop = matches.get(new_prop.column)
            if old_prop is None:
                continue
            old_id = _annotation(old_prop, "org.seasar.doma.Id")
            new_id = _annotation(new_prop, "org.seasar.doma.Id")
            if old_id is not None:
                existing_membership.append(new_prop.column)
            if (old_id is None) != (new_id is None):
                id_edits.extend(_annotation_change_edits(
                    existing, candidate, old_prop, new_prop, old_id, new_id
                ))
        if id_edits:
            findings.append(_make_finding(
                "SAFE", "synchronize-primary-key", path, table.identity, None,
                {**database_base, "primary_key": list(table.primary_key)},
                ", ".join(existing_membership), ", ".join(db_pk),
                "Every primary-key column is uniquely mapped; membership is synchronized atomically.",
                "Apply the complete @Id membership change as one finding.", tuple(_dedupe_edits(id_edits)),
            ))

    for new_prop in new.properties:
        old_prop = matches.get(new_prop.column)
        if old_prop is None:
            continue
        column = db_columns.get(new_prop.column, {})
        old_annotations = {annotation.qualified_name: annotation for annotation in old_prop.annotations}
        new_annotations = {annotation.qualified_name: annotation for annotation in new_prop.annotations}
        old_generated = old_annotations.get("org.seasar.doma.GeneratedValue")
        new_generated = new_annotations.get("org.seasar.doma.GeneratedValue")
        if not _annotation_equivalent(old_generated, new_generated):
            if old_generated is None and new_generated is not None and column.get("auto_increment") is True:
                edits = _annotation_change_edits(
                    existing, candidate, old_prop, new_prop, old_generated, new_generated
                )
                findings.append(_make_finding(
                    "SAFE", "add-generated-value", path, table.identity, new_prop.column,
                    {**database_base, "column": column}, None,
                    _annotation_text(new_source, new_generated),
                    "Both database auto-increment metadata and the generated candidate agree.",
                    "Add the exact generated @GeneratedValue annotation.", edits,
                ))
            else:
                findings.append(_make_finding(
                    "BLOCKED", "generated-value-semantics", path, table.identity, new_prop.column,
                    {**database_base, "column": column},
                    _annotation_text(old_source, old_generated), _annotation_text(new_source, new_generated),
                    "Database metadata cannot prove the requested generation semantics.",
                    "Choose the Doma generation strategy manually.", (),
                ))
        elif new_generated is not None and column.get("auto_increment") is not True:
            findings.append(_make_finding(
                "BLOCKED", "generated-value-semantics", path, table.identity, new_prop.column,
                {**database_base, "column": column}, _annotation_text(old_source, old_generated),
                _annotation_text(new_source, new_generated),
                "@GeneratedValue is present without affirmative auto-increment metadata.",
                "Confirm generation semantics manually.", (),
            ))

        for qualified, kind in (
            ("org.seasar.doma.Version", "version-semantics"),
            ("org.seasar.doma.TenantId", "tenant-id-semantics"),
        ):
            old_special = old_annotations.get(qualified)
            new_special = new_annotations.get(qualified)
            if (old_special is None) != (new_special is None):
                findings.append(_make_finding(
                    "BLOCKED", kind, path, table.identity, new_prop.column,
                    {**database_base, "column": column}, _annotation_text(old_source, old_special),
                    _annotation_text(new_source, new_special),
                    "The database describes physical columns, not Doma application semantics.",
                    "Choose this special mapping manually.", (),
                ))

        blocked_use = _has_external_reference(references, existing.file.path, old, old_prop)
        if old_prop.type_name != new_prop.type_name:
            domain = any(
                reason == "domain-typed property: " + old_prop.name
                for reason in old.unsupported_reasons
            )
            if domain:
                status, kind = "BLOCKED", "domain-basic-mismatch"
            elif _is_widening(old_prop.type_name, new_prop.type_name) and not blocked_use:
                status, kind = "SAFE", "widen-basic-type"
            elif blocked_use:
                status, kind = "BLOCKED", "narrow-basic-type"
            else:
                status, kind = "REVIEW_REQUIRED", "narrow-basic-type"
            edits = () if status == "BLOCKED" else _type_change_edits(
                existing, candidate, old_prop, new_prop
            )
            findings.append(_make_finding(
                status, kind, path, table.identity, new_prop.column,
                {**database_base, "column": column},
                _property_with_accessors(existing, old_prop),
                _property_with_accessors(candidate, new_prop),
                "The generated database type widens a generated-only basic property."
                if status == "SAFE" else
                "The type change may alter application assignments or uses.",
                "Apply the exact generated type spans."
                if edits else "Review Domain conversion and all source uses manually.", edits,
            ))

        if old.language == "kotlin" and old_prop.nullable != new_prop.nullable:
            status = "BLOCKED" if blocked_use else "REVIEW_REQUIRED"
            edits = () if blocked_use else _kotlin_property_declaration_edits(
                existing, candidate, old_prop, new_prop
            )
            findings.append(_make_finding(
                status, "kotlin-nullability", path, table.identity, new_prop.column,
                {**database_base, "column": column},
                _property_excerpt(old_source, old_prop),
                _property_excerpt(new_source, new_prop),
                "Kotlin nullability changes a property retained by handwritten source."
                if blocked_use else
                "Kotlin nullability changes the application type even when database metadata is exact.",
                "Migrate the retained property reference before replanning."
                if blocked_use else
                "Review callers, then approve this exact generated property declaration.", edits,
            ))

        doc_edit = _database_comment_edit(existing, candidate, old_prop, new_prop)
        if doc_edit is not None:
            findings.append(_make_finding(
                "SAFE", "add-database-comment", path, table.identity, new_prop.column,
                {**database_base, "column": column}, doc_edit[1], doc_edit[2],
                "A generated database comment replaces only an empty generated placeholder.",
                "Add the generated Javadoc or KDoc without replacing handwritten documentation.",
                (doc_edit[0],),
            ))
    return tuple(findings)


def _new_entity_finding(
    root: Path,
    table: _Table,
    candidate: _ParsedFile,
    source_roots: Sequence[Path],
    source_root_names: Sequence[str],
    existing_files: Sequence[_SourceFile],
) -> Finding:
    table_documentation = _entity_documentation(candidate)
    if not _documentation_matches_snapshot(table_documentation, table.raw.get("remarks")):
        return _database_comment_mismatch_finding(
            table,
            candidate.file.path,
            None,
            {"table": table.raw, "generated_path": candidate.file.path},
        )
    db_columns = {str(column["name"]): column for column in table.columns}
    for prop in candidate.parsed.entity.properties:
        column = db_columns.get(prop.column)
        if column is not None and not _database_comment_matches_snapshot(
            candidate, prop, column.get("remarks")
        ):
            return _database_comment_mismatch_finding(
                table,
                candidate.file.path,
                prop.column,
                {"table": table.raw, "column": column, "generated_path": candidate.file.path},
            )

    suffix = candidate.file.absolute.suffix
    eligible = [source_root for source_root in source_roots if any(
        item.absolute.suffix == suffix and item.root == _relative(root, source_root)
        for item in existing_files
    )]
    if not eligible and len(source_roots) == 1:
        eligible = [source_roots[0]]
    relative_candidate = candidate.file.absolute.relative_to(
        root / candidate.file.root
    )
    if len(eligible) != 1:
        return _make_finding(
            "BLOCKED", "ambiguous-source-root", candidate.file.path, table.identity, None,
            {"table": table.raw, "source_roots": list(source_root_names)}, None,
            _entity_excerpt(candidate), "More than one source root can receive the new entity.",
            "Choose one language-specific source root explicitly.", (),
        )
    target = eligible[0] / relative_candidate
    target_path = _relative(root, target)
    if target.exists() or target.is_symlink():
        return _make_finding(
            "BLOCKED", "source-path-collision", target_path, table.identity, None,
            {"table": table.raw, "existing_root": _relative(root, eligible[0])}, None,
            _entity_excerpt(candidate), "The generated target path already exists.",
            "Resolve the path collision manually.", (),
        )
    text = ("\ufeff" if candidate.file.bom else "") + candidate.parsed.source
    edit = Edit("create", target_path, None, text)
    return _make_finding(
        "SAFE", "create-entity", target_path, table.identity, None,
        {"table": table.raw, "existing_root": _relative(root, eligible[0]),
         "generated_root": candidate.file.root, "generated_path": candidate.file.path},
        None, candidate.parsed.source,
        "The table, generated entity, language, package path, and source root are unique.",
        "Create the generated entity without deleting or renaming any existing type.", (edit,),
    )


def _unsupported_finding(parsed_file: _ParsedFile, table: _Table, generated: bool) -> Finding:
    reasons = parsed_file.parsed.entity.unsupported_reasons
    kind = _unsupported_kind(reasons)
    side = "generated candidate" if generated else "existing source"
    if kind == "domain-basic-mismatch":
        action = (
            "Keep the Domain and update its mapping/conversion, or explicitly replace the Domain type "
            "after reviewing every application use."
        )
    else:
        action = "Preserve the " + side + " and resolve its application semantics manually."
    return _make_finding(
        "BLOCKED", kind, parsed_file.file.path, table.identity, None,
        {"table": table.raw, "unsupported_reasons": list(reasons)},
        None if generated else _entity_excerpt(parsed_file),
        _entity_excerpt(parsed_file) if generated else None,
        "Every parser uncertainty is a file-level automatic-edit stop: " + "; ".join(reasons or ("not generated-only",)),
        action, (),
    )


def _blocked_changes_in_unsupported_source(
    table: _Table,
    existing: _ParsedFile,
    candidate: _ParsedFile,
) -> tuple[Finding, ...]:
    """Report concrete DB changes while keeping every edit disabled for this file."""
    db_columns = {str(column["name"]): column for column in table.columns}
    candidate_columns = {prop.column for prop in candidate.parsed.entity.properties}
    result: list[Finding] = []
    for prop in existing.parsed.entity.properties:
        if prop.column in db_columns or prop.column in candidate_columns:
            continue
        result.append(_make_finding(
            "BLOCKED", "remove-property", existing.file.path, table.identity, prop.column,
            {"table": table.raw, "column_present": False, "existing_root": existing.file.root,
             "generated_path": candidate.file.path},
            _property_with_accessors(existing, prop), None,
            "The column is absent, but handwritten or unsupported source semantics refer to this member.",
            "Migrate the handwritten references first, or retain an explicitly transient compatibility member.", (),
        ))
    return tuple(result)


def _unsupported_kind(reasons: Sequence[str]) -> str:
    text = " ".join(reasons).lower()
    if "domain-typed" in text:
        return "domain-basic-mismatch"
    if "primary constructor" in text or "data class" in text:
        return "kotlin-primary-constructor"
    if "record" in text:
        return "java-record"
    if "lombok" in text:
        return "lombok-template"
    if "duplicate column" in text or "embedded" in text:
        return "duplicate-or-embedded-mapping"
    if "tenant-id" in text or "transient" in text or "association" in text:
        return "special-mapping"
    if "custom annotation" in text:
        return "custom-template"
    return "unsupported-source"


def _fail_closed_file(findings: Sequence[Finding]) -> tuple[Finding, ...]:
    if not any(finding.status == "BLOCKED" for finding in findings):
        return tuple(findings)
    sealed: list[Finding] = []
    for finding in findings:
        if finding.status == "BLOCKED":
            sealed.append(finding)
        else:
            sealed.append(_make_finding(
                "BLOCKED", finding.kind, finding.path, finding.table, finding.column,
                finding.database, finding.existing, finding.candidate,
                finding.reason + " Another finding blocks every automatic edit in this file.",
                "Resolve all blocked findings and create a fresh plan.", (),
            ))
    return tuple(sealed)


def _annotation_change_edits(
    existing: _ParsedFile,
    candidate: _ParsedFile,
    old_prop: PropertyModel,
    new_prop: PropertyModel,
    old_annotation: AnnotationModel | None,
    new_annotation: AnnotationModel | None,
) -> tuple[Edit, ...]:
    edits: list[Edit] = []
    path = existing.file.path
    if old_annotation is not None and new_annotation is None:
        span = _annotation_line_span(existing.parsed.source, old_annotation.span)
        edits.append(Edit("delete", path, span, ""))
    elif old_annotation is None and new_annotation is not None:
        position = min(
            (annotation.span.start for annotation in old_prop.annotations),
            default=old_prop.declaration_span.start,
        )
        prefix = _line_prefix(existing.parsed.source, position)
        text = _annotation_text(candidate.parsed.source, new_annotation) or ""
        insertion = text + existing.parsed.entity.line_ending + prefix
        edits.append(Edit("insert", path, SourceSpan(position, position), insertion))
        edits.extend(_import_edits(existing, candidate, _annotation_imports(candidate, new_annotation)))
    elif old_annotation is not None and new_annotation is not None:
        replacement = _annotation_text(candidate.parsed.source, new_annotation) or ""
        edits.append(Edit("replace", path, old_annotation.span, replacement))
        edits.extend(_import_edits(existing, candidate, _annotation_imports(candidate, new_annotation)))
    return tuple(_dedupe_edits(edits))


def _add_property_edits(
    existing: _ParsedFile,
    candidate: _ParsedFile,
    new_prop: PropertyModel,
    matches: dict[str, PropertyModel],
) -> tuple[Edit, ...]:
    old_entity = existing.parsed.entity
    new_entity = candidate.parsed.entity
    path = existing.file.path
    new_index = new_entity.properties.index(new_prop)
    position = min((method.span.start for method in old_entity.methods), default=old_entity.class_body.end)
    for later in new_entity.properties[new_index + 1:]:
        mapped = matches.get(later.column)
        if mapped is not None:
            position = mapped.full_span.start
            break
    field_text = _to_line_ending(
        candidate.parsed.source[new_prop.full_span.start:new_prop.full_span.end],
        old_entity.line_ending,
    )
    edits: list[Edit] = [Edit("insert", path, SourceSpan(position, position), field_text)]
    accessors = sorted(
        (method for method in new_entity.methods if method.generated_accessor_for == new_prop.name),
        key=lambda method: method.span.start,
    )
    if accessors:
        method_text = "".join(
            _to_line_ending(candidate.parsed.source[item.span.start:item.span.end], old_entity.line_ending)
            for item in accessors
        )
        edits.append(Edit(
            "insert", path, SourceSpan(old_entity.class_body.end, old_entity.class_body.end), method_text
        ))
    edits.extend(_import_edits(existing, candidate, _property_imports(candidate, new_prop)))
    return tuple(_dedupe_edits(edits))


def _type_change_edits(
    existing: _ParsedFile,
    candidate: _ParsedFile,
    old_prop: PropertyModel,
    new_prop: PropertyModel,
) -> tuple[Edit, ...]:
    old_span = _property_type_span(existing, old_prop)
    new_span = _property_type_span(candidate, new_prop)
    replacement = candidate.parsed.source[new_span.start:new_span.end]
    edits: list[Edit] = [Edit("replace", existing.file.path, old_span, replacement)]
    if existing.parsed.entity.language == "java":
        for method in existing.parsed.entity.methods:
            if method.generated_accessor_for != old_prop.name:
                continue
            method_type = _method_type_span(existing, method.span, old_prop.name)
            if method_type is not None:
                edits.append(Edit("replace", existing.file.path, method_type, replacement))
    edits.extend(_import_edits(existing, candidate, _property_imports(candidate, new_prop)))
    return tuple(_dedupe_edits(edits))


def _kotlin_property_declaration_edits(
    existing: _ParsedFile,
    candidate: _ParsedFile,
    old_prop: PropertyModel,
    new_prop: PropertyModel,
) -> tuple[Edit, ...]:
    replacement = candidate.parsed.source[
        new_prop.declaration_span.start:new_prop.declaration_span.end
    ]
    replacement = _to_line_ending(replacement, existing.parsed.entity.line_ending)
    edits = [Edit("replace", existing.file.path, old_prop.declaration_span, replacement)]
    edits.extend(_import_edits(existing, candidate, _property_imports(candidate, new_prop)))
    return tuple(_dedupe_edits(edits))


def _property_type_span(parsed_file: _ParsedFile, prop: PropertyModel) -> SourceSpan:
    source = parsed_file.parsed.source
    lexer = lex_java if parsed_file.file.language == "java" else lex_kotlin
    trivia = {"WHITESPACE", "LINE_COMMENT", "BLOCK_COMMENT", "JAVADOC", "KDOC"}
    tokens = [token for token in lexer(source) if token.kind not in trivia
              and prop.declaration_span.start <= token.span.start < prop.declaration_span.end]
    name_index = next((index for index, token in enumerate(tokens) if token.text.strip("`") == prop.name), None)
    if name_index is None:
        raise PlanInputError("parser property span is inconsistent")
    if parsed_file.file.language == "java":
        start = tokens[0].span.start
        while tokens and tokens[0].text in {"public", "protected", "private", "static", "final", "volatile", "transient"}:
            tokens.pop(0)
            name_index -= 1
        return SourceSpan(tokens[0].span.start, tokens[name_index].span.start)
    colon = next((index for index in range(name_index + 1, len(tokens)) if tokens[index].text == ":"), None)
    if colon is None or colon + 1 >= len(tokens):
        raise PlanInputError("parser Kotlin type span is inconsistent")
    end = next(
        (tokens[index].span.start for index in range(colon + 1, len(tokens))
         if tokens[index].text in {"=", "by"}),
        prop.declaration_span.end,
    )
    return SourceSpan(tokens[colon + 1].span.start, end)


def _method_type_span(parsed_file: _ParsedFile, span: SourceSpan, prop_name: str) -> SourceSpan | None:
    tokens = [token for token in lex_java(parsed_file.parsed.source)
              if token.kind not in {"WHITESPACE", "LINE_COMMENT", "BLOCK_COMMENT", "JAVADOC"}
              and span.start <= token.span.start < span.end]
    open_index = next((index for index, token in enumerate(tokens) if token.text == "("), None)
    if open_index is None or open_index == 0:
        return None
    method_name = tokens[open_index - 1].text
    if method_name.startswith("get"):
        start = 1 if tokens and tokens[0].text == "public" else 0
        return SourceSpan(tokens[start].span.start, tokens[open_index - 1].span.start)
    close_index = next((index for index in range(open_index + 1, len(tokens)) if tokens[index].text == ")"), None)
    if method_name.startswith("set") and close_index is not None:
        name_index = next(
            (index for index in range(open_index + 1, close_index)
             if tokens[index].text == prop_name), None
        )
        if name_index is not None and name_index > open_index + 1:
            return SourceSpan(tokens[open_index + 1].span.start, tokens[name_index].span.start)
    return None


def _database_comment_edit(
    existing: _ParsedFile,
    candidate: _ParsedFile,
    old_prop: PropertyModel,
    new_prop: PropertyModel,
) -> tuple[Edit, str, str] | None:
    old_span, old_text = _doc_prefix(existing.parsed.source, old_prop)
    new_span, new_text = _doc_prefix(candidate.parsed.source, new_prop)
    if old_span is None or new_span is None or old_text == new_text:
        return None
    if _doc_payload(old_text) or not _doc_payload(new_text):
        return None
    replacement = _to_line_ending(new_text, existing.parsed.entity.line_ending)
    return Edit("replace", existing.file.path, old_span, replacement), old_text, new_text


def _database_comment_matches_snapshot(
    candidate: _ParsedFile,
    prop: PropertyModel,
    remarks: object,
) -> bool:
    candidate_doc = _doc_prefix(candidate.parsed.source, prop)[1]
    return _documentation_matches_snapshot(candidate_doc, remarks)


def _documentation_matches_snapshot(documentation: str, remarks: object) -> bool:
    candidate_payload = _normalized_doc_payload(documentation)
    if not candidate_payload:
        return True
    snapshot_payload = "" if remarks is None else " ".join(str(remarks).split())
    return candidate_payload == snapshot_payload


def _database_comment_mismatch_finding(
    table: _Table,
    path: str,
    column: str | None,
    database: dict[str, object],
) -> Finding:
    scope = "entity" if column is None else "property"
    return _make_finding(
        "BLOCKED",
        "database-comment-mismatch",
        path,
        table.identity,
        column,
        database,
        None,
        None,
        "The generated " + scope
        + " documentation does not match the authoritative database remarks.",
        "Regenerate the candidate from this exact snapshot before applying documentation.",
        (),
    )


def _entity_documentation(candidate: _ParsedFile) -> str:
    source = candidate.parsed.source
    lexer = lex_java if candidate.file.language == "java" else lex_kotlin
    document_kind = "JAVADOC" if candidate.file.language == "java" else "KDOC"
    documents = [
        token
        for token in lexer(source)
        if token.kind == document_kind
        and token.span.end <= candidate.parsed.entity.class_body.start
    ]
    if not documents:
        return ""
    document = documents[-1]
    return source[document.span.start:document.span.end]


def _doc_prefix(source: str, prop: PropertyModel) -> tuple[SourceSpan | None, str]:
    boundary = min((item.span.start for item in prop.annotations), default=prop.declaration_span.start)
    text = source[prop.full_span.start:boundary]
    if "/**" not in text or "*/" not in text:
        return None, ""
    return SourceSpan(prop.full_span.start, boundary), text


def _doc_payload(text: str) -> str:
    start = text.find("/**")
    end = text.find("*/", start + 3)
    if start < 0 or end < 0:
        return ""
    return "".join(character for character in text[start + 3:end] if not character.isspace() and character != "*")


def _normalized_doc_payload(text: str) -> str:
    start = text.find("/**")
    end = text.find("*/", start + 3)
    if start < 0 or end < 0:
        return ""
    lines = []
    for line in text[start + 3:end].splitlines():
        stripped = line.strip()
        if stripped.startswith("*"):
            stripped = stripped[1:].strip()
        lines.append(stripped)
    return " ".join(" ".join(lines).split())


def _property_imports(candidate: _ParsedFile, prop: PropertyModel) -> tuple[str, ...]:
    simple_names = set(re.findall(r"[A-Za-z_$][A-Za-z0-9_$]*", prop.type_name))
    required = {
        imported for imported in candidate.parsed.entity.imports
        if imported.rsplit(".", 1)[-1] in simple_names
    }
    for annotation in prop.annotations:
        required.update(_annotation_imports(candidate, annotation))
    return tuple(sorted(required))


def _annotation_imports(candidate: _ParsedFile, annotation: AnnotationModel) -> tuple[str, ...]:
    required = {annotation.qualified_name}
    expression_names = set(re.findall(r"[A-Za-z_$][A-Za-z0-9_$]*", " ".join(
        value for _, value in annotation.arguments
    )))
    required.update(
        imported for imported in candidate.parsed.entity.imports
        if imported.rsplit(".", 1)[-1] in expression_names
    )
    return tuple(sorted(
        item for item in required
        if item in candidate.parsed.entity.imports and not item.startswith("java.lang.")
    ))


def _import_edits(
    existing: _ParsedFile,
    candidate: _ParsedFile,
    imports: Iterable[str],
) -> tuple[Edit, ...]:
    missing = sorted(set(imports) - set(existing.parsed.entity.imports))
    if not missing:
        return ()
    locations = _import_locations(existing)
    if not locations:
        raise PlanInputError("an automatic annotation/type edit requires a proven import region")
    edits: list[Edit] = []
    ending = existing.parsed.entity.line_ending
    java = existing.file.language == "java"
    for imported in missing:
        group = imported.split(".", 1)[0]
        same_group = [item for item in locations if item[0].split(".", 1)[0] == group]
        if same_group:
            later = next((item for item in same_group if item[0] > imported), None)
            position = later[1] if later is not None else same_group[-1][2]
        else:
            later_group = next((item for item in locations if item[0].split(".", 1)[0] > group), None)
            position = later_group[1] if later_group is not None else locations[-1][2]
        statement = "import " + imported + (";" if java else "") + ending
        edits.append(Edit("insert", existing.file.path, SourceSpan(position, position), statement))
    return tuple(edits)


def _import_locations(parsed_file: _ParsedFile) -> list[tuple[str, int, int]]:
    source = parsed_file.parsed.source
    ending = parsed_file.parsed.entity.line_ending
    result: list[tuple[str, int, int]] = []
    cursor = 0
    for line in source.splitlines(keepends=True):
        stripped = line.strip()
        for imported in parsed_file.parsed.entity.imports:
            expected = "import " + imported + (";" if parsed_file.file.language == "java" else "")
            if stripped == expected:
                result.append((imported, cursor, cursor + len(line)))
                break
        cursor += len(line)
    return result


def _has_external_reference(
    files: Sequence[_SourceFile],
    target_path: str,
    entity: EntityModel,
    prop: PropertyModel,
) -> bool:
    getter = "get" + prop.name[:1].upper() + prop.name[1:]
    setter = "set" + prop.name[:1].upper() + prop.name[1:]
    for item in files:
        if item.path == target_path:
            continue
        tokens = lex_java(item.source) if item.language == "java" else lex_kotlin(item.source)
        significant = [
            token for token in tokens
            if token.kind == "IDENT" or token.text in {".", ":"}
        ]
        if item.language == "java" and any(token.text in {getter, setter} for token in significant):
            return True
        for index, token in enumerate(significant[:-1]):
            if token.text == "." and significant[index + 1].text.strip("`") == prop.name:
                return True
            if (
                token.text == ":"
                and index + 2 < len(significant)
                and significant[index + 1].text == ":"
                and significant[index + 2].text.strip("`") == prop.name
            ):
                return True
    return False


def _is_widening(old: str, new: str) -> bool:
    chains = (
        ("byte", "short", "int", "long"),
        ("Byte", "Short", "Integer", "Long", "BigInteger", "BigDecimal"),
        ("float", "double"),
        ("Float", "Double", "BigDecimal"),
        ("UByte", "UShort", "UInt", "ULong"),
    )
    return any(old in chain and new in chain and chain.index(old) < chain.index(new) for chain in chains)


def _annotation(prop: PropertyModel, qualified: str) -> AnnotationModel | None:
    return next((item for item in prop.annotations if item.qualified_name == qualified), None)


def _annotation_equivalent(
    left: AnnotationModel | None, right: AnnotationModel | None
) -> bool:
    if left is None or right is None:
        return left is right
    return left.qualified_name == right.qualified_name and left.arguments == right.arguments


def _annotation_text(source: str, annotation: AnnotationModel | None) -> str | None:
    return None if annotation is None else source[annotation.span.start:annotation.span.end]


def _annotation_line_span(source: str, span: SourceSpan) -> SourceSpan:
    line_start = source.rfind("\n", 0, span.start) + 1
    start = line_start if source[line_start:span.start].strip() == "" else span.start
    end = span.end
    while end < len(source) and source[end] in " \t":
        end += 1
    if source.startswith("\r\n", end):
        end += 2
    elif end < len(source) and source[end] == "\n":
        end += 1
    return SourceSpan(start, end)


def _line_prefix(source: str, position: int) -> str:
    start = source.rfind("\n", 0, position) + 1
    return source[start:position]


def _to_line_ending(text: str, ending: str) -> str:
    normalized = text.replace("\r\n", "\n")
    return normalized if ending == "\n" else normalized.replace("\n", "\r\n")


def _property_excerpt(source: str, prop: PropertyModel) -> str:
    return source[prop.full_span.start:prop.full_span.end]


def _property_with_accessors(parsed_file: _ParsedFile, prop: PropertyModel) -> str:
    source = parsed_file.parsed.source
    snippets = [source[prop.full_span.start:prop.full_span.end]]
    snippets.extend(
        source[method.span.start:method.span.end]
        for method in parsed_file.parsed.entity.methods
        if method.generated_accessor_for == prop.name
    )
    return "".join(snippets)


def _entity_excerpt(parsed_file: _ParsedFile) -> str:
    entity = parsed_file.parsed.entity
    return entity.package_name + "." + entity.class_name if entity.package_name else entity.class_name


def _proposal_diff(path: str, existing: str | None, candidate: str | None) -> str:
    old = [] if existing is None else existing.splitlines(keepends=True)
    new = [] if candidate is None else candidate.splitlines(keepends=True)
    diff = "".join(difflib.unified_diff(old, new, fromfile="a/" + path, tofile="b/" + path))
    if diff and not diff.endswith("\n"):
        diff += "\n"
    return diff


def _make_finding(
    status: Literal["SAFE", "REVIEW_REQUIRED", "BLOCKED"],
    kind: str,
    path: str,
    table: TableIdentity,
    column: str | None,
    database: dict[str, object],
    existing: str | None,
    candidate: str | None,
    reason: str,
    action: str,
    edits: Sequence[Edit],
) -> Finding:
    safe_path = _plan_path(path)
    if status == "REVIEW_REQUIRED":
        action_template = (
            f"Approve {_FINDING_ID_MARKER} to apply this exact proposal. Impact: {reason} "
            f"Manual action: {action}\nProposed diff:\n{_proposal_diff(safe_path, existing, candidate)}"
        )
    elif status == "BLOCKED":
        action_template = "No automatic edit. " + action
        edits = ()
    else:
        action_template = action
    finding_id = _finding_id(
        status, kind, table, column, safe_path, database, existing, candidate,
        reason, action_template, edits,
    )
    final_action = action_template.replace(_FINDING_ID_MARKER, finding_id)
    return Finding(
        finding_id, status, kind, safe_path, table, column, database,
        existing, candidate, reason, final_action, tuple(edits),
    )


def _finding_id(
    status: str,
    kind: str,
    table: TableIdentity,
    column: str | None,
    path: str,
    database: dict[str, object],
    existing: str | None,
    candidate: str | None,
    reason: str,
    action_template: str,
    edits: Sequence[Edit],
) -> str:
    normalized = {
        "status": status,
        "kind": kind,
        "table": [
            unicodedata.normalize("NFKC", table.catalog or "").casefold(),
            unicodedata.normalize("NFKC", table.schema or "").casefold(),
            unicodedata.normalize("NFKC", table.table).casefold(),
        ],
        "column": unicodedata.normalize("NFKC", column or "").casefold(),
        "path": path,
        "database": database,
        "existing": existing,
        "candidate": candidate,
        "reason": reason,
        "action": action_template,
        "edits": [_edit_dict(edit) for edit in edits],
    }
    try:
        encoded = json.dumps(
            normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError) as exception:
        raise PlanInputError("finding proposal is not canonical JSON") from exception
    digest = hashlib.sha256(encoded).hexdigest()[:12]
    prefix = re.sub(r"[^a-z0-9]+", "-", (status + "-" + kind).lower()).strip("-")
    return prefix + "-" + digest


def _finding_action_template(status: str, finding_id: str, action: str) -> str:
    if status == "REVIEW_REQUIRED":
        if action.count(finding_id) != 1:
            raise PlanInputError("review action does not bind its exact finding ID")
        return action.replace(finding_id, _FINDING_ID_MARKER)
    if finding_id in action:
        raise PlanInputError("non-review action unexpectedly contains its finding ID")
    return action


def _expected_finding_id(finding: Finding) -> str:
    return _finding_id(
        finding.status,
        finding.kind,
        finding.table,
        finding.column,
        finding.path,
        finding.database,
        finding.existing,
        finding.candidate,
        finding.reason,
        _finding_action_template(finding.status, finding.finding_id, finding.action),
        finding.edits,
    )


def _finding_sort_key(finding: Finding) -> tuple[object, ...]:
    table = finding.table
    return (
        finding.path, table.catalog or "", table.schema or "", table.table,
        finding.column or "", finding.status, finding.kind, finding.finding_id,
    )


def _finding_dict(finding: Finding) -> dict[str, object]:
    return {
        "finding_id": finding.finding_id,
        "status": finding.status,
        "kind": finding.kind,
        "path": finding.path,
        "table": _table_dict(finding.table),
        "column": finding.column,
        "database": finding.database,
        "existing": finding.existing,
        "candidate": finding.candidate,
        "reason": finding.reason,
        "action": finding.action,
        "edits": [_edit_dict(edit) for edit in finding.edits],
    }


def _edit_dict(edit: Edit) -> dict[str, object]:
    return {
        "kind": edit.kind,
        "path": edit.path,
        "span": None if edit.span is None else {"start": edit.span.start, "end": edit.span.end},
        "text": edit.text,
    }


def _load_finding(value: object) -> Finding:
    if not isinstance(value, dict) or set(value) != {
        "finding_id", "status", "kind", "path", "table", "column", "database",
        "existing", "candidate", "reason", "action", "edits",
    }:
        raise PlanInputError("invalid finding fields")
    if value["status"] not in _STATUS or not isinstance(value["kind"], str):
        raise PlanInputError("invalid finding status or kind")
    path = _plan_path(value["path"])
    table = _load_table_identity(value["table"])
    column = value["column"]
    if column is not None and not isinstance(column, str):
        raise PlanInputError("invalid finding column")
    if not isinstance(value["database"], dict):
        raise PlanInputError("invalid database facts")
    for name in ("finding_id", "reason", "action"):
        if not isinstance(value[name], str):
            raise PlanInputError("invalid finding text")
    for name in ("existing", "candidate"):
        if value[name] is not None and not isinstance(value[name], str):
            raise PlanInputError("invalid finding excerpt")
    raw_edits = value["edits"]
    if not isinstance(raw_edits, list):
        raise PlanInputError("invalid edits")
    edits = tuple(_load_edit(item) for item in raw_edits)
    action_template = _finding_action_template(value["status"], value["finding_id"], value["action"])
    expected_id = _finding_id(
        value["status"], value["kind"], table, column, path, value["database"],
        value["existing"], value["candidate"], value["reason"], action_template, edits,
    )
    if value["finding_id"] != expected_id:
        raise PlanInputError("finding ID does not match its stable identity")
    if value["status"] == "BLOCKED" and edits:
        raise PlanInputError("blocked finding must not contain edits")
    return Finding(
        value["finding_id"], value["status"], value["kind"], path, table, column,
        value["database"], value["existing"], value["candidate"], value["reason"],
        value["action"], edits,
    )


def _load_edit(value: object) -> Edit:
    if not isinstance(value, dict) or set(value) != {"kind", "path", "span", "text"}:
        raise PlanInputError("invalid edit fields")
    if value["kind"] not in _EDIT_KINDS or not isinstance(value["text"], str):
        raise PlanInputError("invalid edit")
    path = _plan_path(value["path"])
    raw_span = value["span"]
    span = None
    if raw_span is not None:
        if not isinstance(raw_span, dict) or set(raw_span) != {"start", "end"}:
            raise PlanInputError("invalid source span")
        start, end = raw_span["start"], raw_span["end"]
        if not isinstance(start, int) or isinstance(start, bool) or not isinstance(end, int) or isinstance(end, bool):
            raise PlanInputError("invalid source span offsets")
        if start < 0 or end < start:
            raise PlanInputError("invalid source span range")
        span = SourceSpan(start, end)
    if value["kind"] == "create" and span is not None:
        raise PlanInputError("create edit must not have a span")
    if value["kind"] != "create" and span is None:
        raise PlanInputError("source edit must have a span")
    return Edit(value["kind"], path, span, value["text"])


def _load_table_identity(value: object) -> TableIdentity:
    if not isinstance(value, dict) or set(value) != {"catalog", "schema", "table"}:
        raise PlanInputError("invalid table identity")
    if value["catalog"] is not None and not isinstance(value["catalog"], str):
        raise PlanInputError("invalid table catalog")
    if value["schema"] is not None and not isinstance(value["schema"], str):
        raise PlanInputError("invalid table schema")
    if not isinstance(value["table"], str) or not value["table"]:
        raise PlanInputError("invalid table name")
    return TableIdentity(value["catalog"], value["schema"], value["table"])


def _hash_pairs(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, list):
        raise PlanInputError("hash list must be a list")
    result: list[tuple[str, str]] = []
    for item in value:
        if not isinstance(item, list) or len(item) != 2:
            raise PlanInputError("invalid hash entry")
        result.append((_plan_path(item[0]), _hash_value(item[1])))
    if len({path for path, _ in result}) != len(result) or tuple(sorted(result)) != tuple(result):
        raise PlanInputError("hash entries must be unique and sorted")
    return tuple(result)


def _hash_value(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise PlanInputError("invalid SHA-256")
    return value


def _table_dict(identity: TableIdentity) -> dict[str, object]:
    return {"catalog": identity.catalog, "schema": identity.schema, "table": identity.table}


def _validate_manifest(value: object) -> tuple[_Table, ...]:
    if not isinstance(value, dict) or set(value) != {"format_version", "database", "scope", "tables"}:
        raise PlanInputError("invalid schema snapshot fields")
    if value["format_version"] != 1:
        raise PlanInputError("unsupported schema snapshot version")
    database = value["database"]
    scope = value["scope"]
    raw_tables = value["tables"]
    if database not in {"postgresql", "mysql"}:
        raise PlanInputError("unsupported database family")
    if not isinstance(scope, dict) or set(scope) != {"catalog", "schema", "table_pattern"}:
        raise PlanInputError("invalid schema snapshot scope")
    catalog, schema, pattern_text = scope["catalog"], scope["schema"], scope["table_pattern"]
    if not isinstance(pattern_text, str):
        raise PlanInputError("invalid table pattern")
    if database == "postgresql":
        if catalog is not None or not isinstance(schema, str) or not schema:
            raise PlanInputError("snapshot scope does not match PostgreSQL")
    else:
        if schema is not None or not isinstance(catalog, str) or not catalog:
            raise PlanInputError("snapshot scope does not match MySQL")
    try:
        pattern = re.compile(pattern_text)
    except re.error as exception:
        raise PlanInputError("invalid table pattern") from exception
    if not isinstance(raw_tables, list):
        raise PlanInputError("tables must be a list")
    tables: list[_Table] = []
    identities: set[TableIdentity] = set()
    for raw_table in raw_tables:
        if not isinstance(raw_table, dict) or set(raw_table) != {
            "catalog", "schema", "name", "type", "remarks", "primary_key", "columns",
        }:
            raise PlanInputError("invalid table fields")
        identity = TableIdentity(raw_table["catalog"], raw_table["schema"], raw_table["name"])
        if any(item is not None and not isinstance(item, str) for item in (identity.catalog, identity.schema)):
            raise PlanInputError("invalid table qualifier")
        if not isinstance(identity.table, str) or not identity.table or raw_table["type"] != "TABLE":
            raise PlanInputError("invalid table identity or type")
        if pattern.fullmatch(identity.table) is None:
            raise PlanInputError("table is outside the declared scope")
        if database == "postgresql" and identity.schema != schema:
            raise PlanInputError("table is outside the PostgreSQL schema scope")
        if database == "mysql" and identity.catalog != catalog:
            raise PlanInputError("table is outside the MySQL catalog scope")
        if identity in identities:
            raise PlanInputError("duplicate table identity")
        identities.add(identity)
        columns = _validate_columns(raw_table["columns"])
        primary_key = _validate_primary_key(raw_table["primary_key"], columns)
        tables.append(_Table(identity, raw_table, columns, primary_key))
    if tuple(sorted((item.identity for item in tables))) != tuple(item.identity for item in tables):
        raise PlanInputError("tables are not canonically sorted")
    return tuple(tables)


def _identity_in_scope(identity: TableIdentity, manifest: dict[str, object]) -> bool:
    scope = manifest["scope"]
    assert isinstance(scope, dict)
    pattern_text = scope["table_pattern"]
    assert isinstance(pattern_text, str)
    if re.fullmatch(pattern_text, identity.table) is None:
        return False
    if manifest["database"] == "postgresql":
        return identity.schema == scope["schema"]
    return identity.catalog == scope["catalog"]


def _validate_columns(value: object) -> tuple[dict[str, object], ...]:
    if not isinstance(value, list):
        raise PlanInputError("columns must be a list")
    required = {"name", "ordinal", "jdbc_type", "type_name", "size", "scale", "nullable", "default", "auto_increment", "remarks"}
    result: list[dict[str, object]] = []
    names: set[str] = set()
    ordinals: set[int] = set()
    for raw in value:
        if not isinstance(raw, dict) or set(raw) != required:
            raise PlanInputError("invalid column fields")
        name, ordinal = raw["name"], raw["ordinal"]
        if not isinstance(name, str) or not name or not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal <= 0:
            raise PlanInputError("invalid column identity")
        if name in names or ordinal in ordinals:
            raise PlanInputError("duplicate column identity or ordinal")
        names.add(name); ordinals.add(ordinal)
        for numeric in ("jdbc_type", "size", "scale"):
            if raw[numeric] is not None and (not isinstance(raw[numeric], int) or isinstance(raw[numeric], bool)):
                raise PlanInputError("invalid numeric column metadata")
        for boolean in ("nullable", "auto_increment"):
            if raw[boolean] is not None and not isinstance(raw[boolean], bool):
                raise PlanInputError("invalid boolean column metadata")
        for text in ("type_name", "default", "remarks"):
            if raw[text] is not None and not isinstance(raw[text], str):
                raise PlanInputError("invalid text column metadata")
        result.append(raw)
    expected = sorted(result, key=lambda item: (item["ordinal"], item["name"]))
    if result != expected:
        raise PlanInputError("columns are not canonically sorted")
    return tuple(result)


def _validate_primary_key(value: object, columns: Sequence[dict[str, object]]) -> tuple[dict[str, object], ...]:
    if not isinstance(value, list):
        raise PlanInputError("primary_key must be a list")
    names = {item["name"] for item in columns}
    result: list[dict[str, object]] = []
    seen_columns: set[str] = set()
    for expected_sequence, raw in enumerate(value, 1):
        if not isinstance(raw, dict) or set(raw) != {"name", "column", "sequence"}:
            raise PlanInputError("invalid primary-key fields")
        if raw["name"] is not None and not isinstance(raw["name"], str):
            raise PlanInputError("invalid primary-key name")
        column, sequence = raw["column"], raw["sequence"]
        if not isinstance(column, str) or column not in names or column in seen_columns:
            raise PlanInputError("invalid primary-key column")
        if sequence != expected_sequence or isinstance(sequence, bool):
            raise PlanInputError("invalid primary-key sequence")
        seen_columns.add(column)
        result.append(raw)
    return tuple(result)


def _collect_sources(
    project_root: Path,
    roots: Sequence[Path],
    language: str,
) -> tuple[_SourceFile, ...]:
    result: list[_SourceFile] = []
    for root in roots:
        root_name = _relative(project_root, root)
        for current, directories, files in os.walk(root, followlinks=False):
            current_path = Path(current)
            for name in tuple(directories) + tuple(files):
                if (current_path / name).is_symlink():
                    raise PlanInputError("source roots must not contain symbolic links")
            directories.sort(); files.sort()
            for name in files:
                path = current_path / name
                source_language = _SOURCE_SUFFIXES.get(path.suffix)
                if source_language is None or (language != "auto" and source_language != language):
                    continue
                raw = _read_bytes(path)
                _reject_sensitive(raw)
                bom = raw.startswith(b"\xef\xbb\xbf")
                payload = raw[3:] if bom else raw
                try:
                    source = payload.decode("utf-8")
                except UnicodeDecodeError as exception:
                    raise PlanInputError("entity sources must be UTF-8") from exception
                result.append(_SourceFile(
                    path, _relative(project_root, path), source, _sha(raw), bom,
                    source_language, root_name,
                ))
    return tuple(sorted(result, key=lambda item: item.path))


def _annotation_context(files: Sequence[_SourceFile]) -> tuple[str, ...]:
    declarations: set[str] = set()
    for item in files:
        finder = find_java_annotation_declarations if item.language == "java" else find_kotlin_annotation_declarations
        declarations.update(finder(item.source))
    return tuple(sorted(declarations))


def _domain_context(files: Sequence[_SourceFile], annotation_declarations: tuple[str, ...]) -> tuple[str, ...]:
    declarations: set[str] = set()
    for item in files:
        finder = find_java_domain_declarations if item.language == "java" else find_kotlin_domain_declarations
        declarations.update(finder(item.source, annotation_declarations=annotation_declarations))
    return tuple(sorted(declarations))


def _parse_files(
    files: Sequence[_SourceFile],
    domain_types: tuple[str, ...],
    annotation_declarations: tuple[str, ...],
    generated: bool,
) -> tuple[tuple[_ParsedFile, ...], tuple[_ParseFailure, ...]]:
    parsed: list[_ParsedFile] = []
    failures: list[_ParseFailure] = []
    for item in files:
        parser = parse_java if item.language == "java" else parse_kotlin
        try:
            model = parser(
                item.source, path=item.path, domain_types=domain_types,
                annotation_declarations=annotation_declarations,
            )
        except (JavaParseError, KotlinParseError, ValueError):
            if generated or _looks_like_entity(item):
                failures.append(_ParseFailure(item, "parser rejected entity source"))
            continue
        parsed.append(_ParsedFile(item, model))
    return tuple(parsed), tuple(failures)


def _looks_like_entity(item: _SourceFile) -> bool:
    lexer = lex_java if item.language == "java" else lex_kotlin
    tokens = lexer(item.source)
    return any(
        token.kind == "IDENT" and token.text.strip("`") in {"Entity", "Embeddable"}
        for token in tokens
    )


def _by_table(files: Sequence[_ParsedFile]) -> tuple[dict[TableIdentity, _ParsedFile], dict[TableIdentity, tuple[_ParsedFile, ...]]]:
    grouped: dict[TableIdentity, list[_ParsedFile]] = {}
    for item in files:
        grouped.setdefault(item.parsed.entity.table, []).append(item)
    unique = {identity: items[0] for identity, items in grouped.items() if len(items) == 1}
    duplicate = {identity: tuple(items) for identity, items in grouped.items() if len(items) > 1}
    return unique, duplicate


def _by_class(files: Sequence[_ParsedFile]) -> dict[tuple[str, str, str], tuple[_ParsedFile, ...]]:
    grouped: dict[tuple[str, str, str], list[_ParsedFile]] = {}
    for item in files:
        grouped.setdefault(_class_key(item.parsed.entity), []).append(item)
    return {key: tuple(items) for key, items in grouped.items()}


def _class_key(entity: EntityModel) -> tuple[str, str, str]:
    return entity.language, entity.package_name, entity.class_name


def _dedupe_edits(edits: Iterable[Edit]) -> list[Edit]:
    result: list[Edit] = []
    for edit in edits:
        if edit not in result:
            result.append(edit)
    return result


def _load_json(raw: bytes) -> object:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise PlanInputError("duplicate JSON field")
            result[key] = value
        return result
    try:
        return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exception:
        raise PlanInputError("invalid JSON input") from exception


def _project_root(value: Path | str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = Path.cwd() / path
    if path.is_symlink() or not path.is_dir():
        raise PlanInputError("project root must be an existing real directory")
    return path.resolve()


def _input_path(root: Path, value: Path | str, *, file: bool = False, directory: bool = False) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    normalized = Path(os.path.abspath(str(path)))
    if not _contains_path(root, normalized):
        raise PlanInputError("input path must stay inside the project root")
    _reject_symlink_components(root, normalized)
    if file and not normalized.is_file():
        raise PlanInputError("required input file does not exist")
    if directory and not normalized.is_dir():
        raise PlanInputError("required input directory does not exist")
    return normalized


def _reject_symlink_components(root: Path, path: Path) -> None:
    relative = path.relative_to(root)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise PlanInputError("input path must not traverse symbolic links")


def _contains_path(parent: Path, child: Path) -> bool:
    try:
        return os.path.commonpath((str(parent), str(child))) == str(parent)
    except ValueError:
        return False


def _relative(root: Path, path: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError as exception:
        raise PlanInputError("path escapes project root") from exception
    return _plan_path(relative.as_posix())


def _plan_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise PlanInputError("invalid project-relative path")
    path = Path(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise PlanInputError("invalid project-relative path")
    normalized = path.as_posix()
    if normalized != value:
        raise PlanInputError("project-relative path is not normalized")
    return normalized


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exception:
        raise PlanInputError("input file could not be read") from exception


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _reject_sensitive(value: bytes) -> None:
    if contains_sensitive(value):
        raise PlanInputError("input contains credential-like content")
