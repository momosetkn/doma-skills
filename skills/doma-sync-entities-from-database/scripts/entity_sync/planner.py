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
from .lexer import Token, lex_java, lex_kotlin
from .model import AnnotationModel, EntityModel, ParsedEntity, PropertyModel, SourceSpan, TableIdentity


PLAN_FORMAT_VERSION = 2
SNAPSHOT_PATH = "build/doma-codegen/schema-snapshot.json"
_FINDING_ID_MARKER = "{finding_id}"
_STATUS = {"SAFE", "REVIEW_REQUIRED", "BLOCKED"}
_EDIT_KINDS = {"create", "insert", "replace", "delete"}
_SOURCE_SUFFIXES = {".java": "java", ".kt": "kotlin"}
_ENTITY_COLLECTION_TYPES = {
    "ArrayList", "Collection", "Deque", "HashSet", "Iterable",
    "LinkedList", "List", "MutableCollection", "MutableIterable",
    "MutableList", "MutableSet", "NavigableSet", "Queue", "Sequence",
    "Set", "SortedSet", "Stack", "TreeSet", "Vector", "Map",
    "HashMap", "LinkedHashMap", "SortedMap", "TreeMap", "ConcurrentMap",
}
_STANDARD_TYPE_NAMES = {
    "bigint": "Long", "binary": "byte[]", "bit": "Boolean", "blob": "Blob",
    "boolean": "Boolean", "char": "String", "clob": "Clob", "date": "LocalDate",
    "decimal": "BigDecimal", "double": "Double", "float": "Float",
    "integer": "Integer", "longnvarchar": "String", "longvarbinary": "byte[]",
    "longvarchar": "String", "nchar": "String", "nclob": "NClob",
    "numeric": "BigDecimal", "nvarchar": "String", "real": "Float",
    "smallint": "Short", "time": "LocalTime", "timestamp": "LocalDateTime",
    "tinyint": "Short", "varbinary": "byte[]", "varchar": "String", "xml": "SQLXML",
}
_POSTGRES_TYPE_NAMES = {
    "bigserial": "Long", "bit": "byte[]", "bool": "Boolean", "bpchar": "String",
    "bytea": "byte[]", "float4": "Float", "float8": "Double", "int2": "Short",
    "int4": "Integer", "int8": "Long", "money": "Float", "oid": "Blob",
    "serial": "Integer", "text": "String", "timestamptz": "LocalDateTime",
    "timetz": "LocalTime", "varbit": "byte[]", "varchar": "String",
}
_MYSQL_TYPE_NAMES = {
    "bigint": "Long", "bigint unsigned": "BigInteger", "bool": "Boolean",
    "boolean": "Boolean", "date": "LocalDate", "datetime": "LocalDateTime",
    "dec": "BigDecimal", "dec unsigned": "BigDecimal", "decimal": "BigDecimal",
    "decimal unsigned": "BigDecimal", "double": "Double", "double precision": "Double",
    "double precision unsigned": "Double", "double unsigned": "Double", "float": "Float",
    "float unsigned": "Float", "int": "Integer", "int unsigned": "Long",
    "integer": "Integer", "integer unsigned": "Long", "mediumint": "Integer",
    "mediumint unsigned": "Integer", "serial": "BigInteger", "smallint": "Short",
    "smallint unsigned": "Integer", "time": "LocalTime", "timestamp": "LocalDateTime",
    "year": "Short", "tinyblob": "Blob", "blob": "Blob", "mediumblob": "Blob",
    "longblob": "Blob", "binary": "byte[]", "varbinary": "byte[]",
}
_JDBC_FALLBACK_TYPES = {
    -7: "Boolean", -6: "Short", -5: "Long", -4: "byte[]", -3: "byte[]",
    -2: "byte[]", -1: "String", 1: "String", 2: "BigDecimal", 3: "BigDecimal",
    4: "Integer", 5: "Short", 6: "Float", 7: "Float", 8: "Double",
    12: "String", 16: "Boolean", 91: "LocalDate", 92: "LocalTime",
    93: "LocalDateTime", 2004: "Blob", 2005: "Clob", 2009: "SQLXML",
    2011: "NClob", -16: "String", -15: "String", -9: "String",
}
_KOTLIN_BASIC_TYPES = {"Integer": "Int"}
_KOTLIN_DEFAULTS = {
    "Byte": "-1", "Short": "-1", "Int": "-1", "Long": "-1L",
    "Float": "-1f", "Double": "-1.0",
}
_CODEGEN_MARKER = "doma-sync-entities-from-database"
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
    language: Literal["auto", "java", "kotlin"]
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
    database: Literal["postgresql", "mysql"]
    identity: TableIdentity
    raw: dict[str, object]
    columns: tuple[dict[str, object], ...]
    primary_key: tuple[dict[str, object], ...] | None


@dataclass(frozen=True)
class _CodeGenNaming:
    package_name: str
    language: Literal["java", "kotlin"]


@dataclass(frozen=True)
class _CollectionSymbols:
    variables: tuple[tuple[str, int, int, bool, bool], ...]
    factories: frozenset[str]
    wrapper_factories: frozenset[str]

    def names_at(self, position: int) -> frozenset[str]:
        latest: dict[str, tuple[int, bool, bool]] = {}
        for name, declared_at, scope_end, direct, wrapper in self.variables:
            if declared_at <= position <= scope_end:
                latest[name] = (declared_at, direct, wrapper)
        return frozenset(name for name, (_, direct, _) in latest.items() if direct)

    def wrapper_names_at(self, position: int) -> frozenset[str]:
        latest: dict[str, tuple[int, bool, bool]] = {}
        for name, declared_at, scope_end, direct, wrapper in self.variables:
            if declared_at <= position <= scope_end:
                latest[name] = (declared_at, direct, wrapper)
        return frozenset(
            name for name, (_, direct, wrapper) in latest.items()
            if direct and wrapper
        )


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
    if _relative(root, generated_root) != "build/doma-codegen/generated":
        raise PlanInputError("generated candidates must use the managed build path")
    if not existing_roots:
        raise PlanInputError("at least one existing source root is required")
    source_roots = tuple(_input_path(root, item, directory=True) for item in existing_roots)
    if len(set(source_roots)) != len(source_roots):
        raise PlanInputError("duplicate existing source root")
    supported_source_roots = {root / "src/main/java", root / "src/main/kotlin"}
    if any(source_root not in supported_source_roots for source_root in source_roots):
        raise PlanInputError("existing roots must be supported project source roots")
    if any(_contains_path(source_root, generated_root) or _contains_path(generated_root, source_root)
           for source_root in source_roots):
        raise PlanInputError("generated and existing roots must not overlap")

    snapshot_bytes = _read_bytes(snapshot_path)
    _reject_sensitive(snapshot_bytes)
    manifest = _load_json(snapshot_bytes)
    tables = _validate_manifest(manifest)
    snapshot_hash = _sha(snapshot_bytes)

    reference_roots = _reference_source_roots(root, source_roots)
    reference_files = _collect_sources(root, reference_roots, "auto")
    generated_files = _collect_sources(root, (generated_root,), language)
    if not generated_files and tables:
        raise PlanInputError("generated candidate directory contains no entity sources")
    all_files = reference_files + generated_files
    annotation_declarations = _annotation_context(all_files)
    domain_types = _domain_context(all_files, annotation_declarations)
    reference_parsed, reference_failures = _parse_files(
        reference_files, domain_types, annotation_declarations, generated=False
    )
    existing_parsed = tuple(
        item for item in reference_parsed
        if any(_contains_path(source_root, root / item.file.path) for source_root in source_roots)
        if language == "auto" or item.file.language == language
    )
    existing_failures = tuple(
        item for item in reference_failures
        if language == "auto" or item.file.language == language
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

    existing_classes = _by_class(reference_parsed)
    table_identities = {table.identity for table in tables}
    for candidate in generated_parsed:
        if candidate.parsed.entity.table not in table_identities:
            findings.append(_make_finding(
                "BLOCKED", "generated-table-outside-snapshot", candidate.file.path,
                candidate.parsed.entity.table, None, {"scope": manifest["scope"]}, None,
                _entity_excerpt(candidate), "A generated entity is outside the authoritative snapshot.",
                "Regenerate candidates from exactly this schema snapshot.", (),
            ))

    source_root_names = tuple(_relative(root, item) for item in source_roots)
    for table in tables:
        candidate = generated_by_table.get(table.identity)
        if candidate is None:
            metadata_finding = _required_metadata_finding(table, candidate)
            if metadata_finding is not None:
                findings.append(metadata_finding)
                continue
            findings.append(_make_finding(
                "BLOCKED", "missing-generated-entity", SNAPSHOT_PATH, table.identity, None,
                {"table": table.raw}, None, None,
                "The snapshot table has no exact generated @Table match.",
                "Regenerate entities; do not infer a class or file name from the table name.", (),
            ))
            continue
        existing = existing_by_table.get(table.identity)
        if existing is None:
            metadata_finding = _required_metadata_finding(table, candidate)
            if metadata_finding is not None:
                findings.append(metadata_finding)
                continue
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
                root, table, candidate, source_roots, source_root_names,
                reference_files,
            )
            findings.append(finding)
            continue
        if candidate.parsed.entity.unsupported_reasons or not candidate.parsed.entity.generated_only:
            findings.append(_unsupported_finding(candidate, table, generated=True))
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
            findings.extend(_localized_safe_edits_in_unsupported_source(
                table, existing, candidate, reference_files
            ))
            continue
        metadata_findings, incomplete_columns, primary_key_incomplete = (
            _existing_metadata_findings(table, existing)
        )
        findings.extend(metadata_findings)
        file_findings, non_sealing = _block_metadata_dependent_edits(
            _compare_entity(table, existing, candidate, reference_files),
            incomplete_columns,
            primary_key_incomplete,
        )
        findings.extend(_fail_closed_file(file_findings, non_sealing))

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
        language,
        snapshot_hash,
        tuple(sorted((item.path, item.sha256) for item in reference_files)),
        tuple(sorted((item.path, item.sha256) for item in generated_files)),
        ordered,
    )


def plan_json(plan: MergePlan) -> str:
    """Serialize a plan with stable key and collection ordering."""
    value = {
        "format_version": plan.format_version,
        "project_root": plan.project_root,
        "language": plan.language,
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
        "format_version", "project_root", "language", "schema_snapshot_sha256",
        "source_hashes", "generated_hashes", "findings",
    }:
        raise PlanInputError("invalid merge plan fields")
    if value["format_version"] != PLAN_FORMAT_VERSION or value["project_root"] != ".":
        raise PlanInputError("unsupported merge plan version or project root")
    language = value["language"]
    if language not in {"auto", "java", "kotlin"}:
        raise PlanInputError("invalid merge plan language")
    snapshot_hash = _hash_value(value["schema_snapshot_sha256"])
    source_hashes = _hash_pairs(value["source_hashes"])
    generated_hashes = _hash_pairs(value["generated_hashes"])
    raw_findings = value["findings"]
    if not isinstance(raw_findings, list):
        raise PlanInputError("findings must be a list")
    findings = tuple(_load_finding(item) for item in raw_findings)
    if tuple(sorted(findings, key=_finding_sort_key)) != findings:
        raise PlanInputError("findings are not in deterministic order")
    return MergePlan(
        PLAN_FORMAT_VERSION, ".", language, snapshot_hash,
        source_hashes, generated_hashes, findings,
    )


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
        candidate_mismatch = _existing_addition_candidate_mismatch(
            table, candidate, new_prop, path, database_base
        )
        if candidate_mismatch is not None:
            findings.append(candidate_mismatch)
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

    if table.primary_key is not None:
        db_pk = tuple(str(item["column"]) for item in table.primary_key)
        candidate_pk = tuple(
            prop.column for prop in new.properties
            if _annotation(prop, "org.seasar.doma.Id") is not None
        )
        if set(candidate_pk) != set(db_pk) or len(candidate_pk) != len(db_pk):
            findings.append(_make_finding(
                "BLOCKED", "candidate-primary-key-mismatch", path, table.identity, None,
                {**database_base, "primary_key": list(table.primary_key)}, None,
                ", ".join(candidate_pk),
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
                    "Apply the complete @Id membership change as one finding.",
                    tuple(_dedupe_edits(id_edits)),
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
            if (
                old_generated is None
                and new_generated is not None
                and _generated_value_is_proven_identity(table, candidate, new_prop)
            ):
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
        type_changed = old_prop.type_name != new_prop.type_name
        nullability_changed = (
            old.language == "kotlin" and old_prop.nullable != new_prop.nullable
        )
        if type_changed and _is_widening(old_prop.type_name, new_prop.type_name) and not blocked_use:
            type_mismatch = _existing_type_change_candidate_mismatch(
                table, candidate, new_prop, path, database_base
            )
            if type_mismatch is not None:
                findings.append(type_mismatch)
                continue
        if old.language == "kotlin" and type_changed and nullability_changed:
            status = "BLOCKED" if blocked_use else "REVIEW_REQUIRED"
            edits = () if blocked_use else _kotlin_property_declaration_edits(
                existing, candidate, old_prop, new_prop
            )
            findings.append(_make_finding(
                status, "kotlin-type-nullability", path, table.identity, new_prop.column,
                {**database_base, "column": column},
                _property_excerpt(old_source, old_prop),
                _property_excerpt(new_source, new_prop),
                "Kotlin type and nullability change as one application-level declaration.",
                "Migrate the retained property reference before replanning."
                if blocked_use else
                "Review callers, then approve this exact combined generated declaration.", edits,
            ))
        elif type_changed:
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

        if nullability_changed and not type_changed:
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


def _existing_type_change_candidate_mismatch(
    table: _Table,
    candidate: _ParsedFile,
    prop: PropertyModel,
    existing_path: str,
    database_base: dict[str, object],
) -> Finding | None:
    """Require an existing-property change candidate to match JDBC physical type."""
    column = next(
        (item for item in table.columns if item.get("name") == prop.column), None
    )
    expected_type = (
        _expected_basic_type(table, column, candidate.parsed.entity.language)
        if column is not None else None
    )
    if expected_type is not None and prop.type_name == expected_type:
        return None
    return _make_finding(
        "BLOCKED", "generated-type-mismatch", existing_path, table.identity,
        prop.column,
        {
            **database_base,
            "column": column,
            "expected_type": expected_type,
            "generated_path": candidate.file.path,
        },
        None, _property_excerpt(candidate.parsed.source, prop),
        "The changed property candidate is not the proven CodeGen type for the JDBC metadata.",
        "Regenerate the candidate and make the application type decision manually.", (),
    )


def _existing_addition_candidate_mismatch(
    table: _Table,
    candidate: _ParsedFile,
    prop: PropertyModel,
    existing_path: str,
    database_base: dict[str, object],
) -> Finding | None:
    """Reject an inserted candidate member that the snapshot cannot prove.

    Existing Entity synchronization can safely add a property only when the
    candidate carries the same basic physical mapping CodeGen would derive for
    the snapshot.  This mirrors the new-Entity gate without asserting that the
    whole existing source is generated-only.
    """
    column = next(
        (item for item in table.columns if item.get("name") == prop.column), None
    )
    if column is None:
        return _make_finding(
            "BLOCKED", "generated-column-mismatch", existing_path, table.identity,
            prop.column, database_base, None, _property_excerpt(candidate.parsed.source, prop),
            "The generated property has no exact physical column in the snapshot.",
            "Regenerate candidates from the authoritative snapshot.", (),
        )
    expected_type = _expected_basic_type(table, column, candidate.parsed.entity.language)
    context = {
        **database_base,
        "column": column,
        "generated_path": candidate.file.path,
    }
    if expected_type is None or prop.type_name != expected_type:
        return _make_finding(
            "BLOCKED", "generated-type-mismatch", existing_path, table.identity,
            prop.column, {**context, "expected_type": expected_type}, None,
            _property_excerpt(candidate.parsed.source, prop),
            "The candidate basic type is not the proven CodeGen type for the JDBC metadata.",
            "Regenerate the candidate; do not insert an inferred application type.", (),
        )
    if column.get("default") is not None:
        return _make_finding(
            "BLOCKED", "database-default-semantics", existing_path,
            table.identity, prop.column, context, None,
            _property_excerpt(candidate.parsed.source, prop),
            "Adding this property would make Doma bind a value where the database currently supplies a default.",
            "Decide manually whether to preserve the database-default behavior before adding this property.", (),
        )
    for qualified, kind in (
        ("org.seasar.doma.Version", "version-semantics"),
        ("org.seasar.doma.TenantId", "tenant-id-semantics"),
    ):
        if _annotation(prop, qualified) is not None:
            return _make_finding(
                "BLOCKED", kind, existing_path, table.identity, prop.column,
                context, None, _property_excerpt(candidate.parsed.source, prop),
                "Database metadata cannot prove this Doma application semantic.",
                "Choose this special mapping manually.", (),
            )
    generated = _annotation(prop, "org.seasar.doma.GeneratedValue")
    if generated is not None:
        if not _generated_value_is_proven_identity(table, candidate, prop):
            return _make_finding(
                "BLOCKED", "generated-value-semantics", existing_path,
                table.identity, prop.column, context, None,
                _property_excerpt(candidate.parsed.source, prop),
                "The candidate @GeneratedValue does not exactly match auto-increment metadata.",
                "Regenerate the candidate and confirm the generation strategy.", (),
            )
    if candidate.parsed.entity.language == "kotlin":
        expected_nullable, expected_default = _expected_kotlin_property_shape(
            column, expected_type
        )
        if prop.nullable is not expected_nullable:
            return _make_finding(
                "BLOCKED", "generated-nullability-mismatch", existing_path,
                table.identity, prop.column, context, None,
                _property_excerpt(candidate.parsed.source, prop),
                "The candidate Kotlin nullability is not the proven CodeGen resolver output.",
                "Regenerate the candidate from the authoritative snapshot.", (),
            )
        if _kotlin_property_initializer(candidate, prop) != expected_default:
            return _make_finding(
                "BLOCKED", "generated-default-mismatch", existing_path,
                table.identity, prop.column, context, None,
                _property_excerpt(candidate.parsed.source, prop),
                "The candidate Kotlin initializer is not the proven CodeGen resolver default.",
                "Regenerate the candidate from the authoritative snapshot.", (),
            )
    return None


def _generated_value_is_proven_identity(
    table: _Table,
    candidate: _ParsedFile,
    prop: PropertyModel,
) -> bool:
    """Return whether this exact candidate proves Doma IDENTITY semantics."""
    generated = _annotation(prop, "org.seasar.doma.GeneratedValue")
    candidate_pk = tuple(
        item.column for item in candidate.parsed.entity.properties
        if _annotation(item, "org.seasar.doma.Id") is not None
    )
    database_pk = tuple(str(item["column"]) for item in (table.primary_key or ()))
    return (
        generated is not None
        and dict(generated.arguments).get("strategy") == "GenerationType.IDENTITY"
        and prop.column in candidate_pk
        and candidate_pk == database_pk
        and len(database_pk) == 1
        and any(
            column.get("name") == prop.column
            and column.get("auto_increment") is True
            for column in table.columns
        )
    )


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

    candidate_mismatch = _new_entity_candidate_mismatch(root, table, candidate)
    if candidate_mismatch is not None:
        return candidate_mismatch
    if not _new_entity_candidate_is_generated_only(table, candidate):
        return _unsupported_finding(candidate, table, generated=True)

    suffix = candidate.file.absolute.suffix
    relative_candidate = candidate.file.absolute.relative_to(
        root / candidate.file.root
    )
    candidate_fqcn = (
        candidate.parsed.entity.package_name
        + "."
        + candidate.parsed.entity.class_name
    )
    class_collisions = [
        item for item in existing_files
        if candidate_fqcn in _top_level_type_declarations(item)
    ]
    if class_collisions:
        collision = class_collisions[0]
        return _make_finding(
            "BLOCKED", "source-class-path-collision", collision.path,
            table.identity, None,
            {"table": table.raw, "generated_path": candidate.file.path,
             "source_roots": list(source_root_names)},
            None, None,
            "A source declares the candidate's fully qualified top-level type.",
            "Resolve the JVM class-name collision manually before creating the entity.", (),
        )
    expected_root = "src/main/java" if suffix == ".java" else "src/main/kotlin"
    eligible = [
        source_root for source_root in source_roots
        if _relative(root, source_root) == expected_root
    ]
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


def _new_entity_candidate_mismatch(
    root: Path,
    table: _Table,
    candidate: _ParsedFile,
) -> Finding | None:
    entity = candidate.parsed.entity
    path = candidate.file.path
    database_base: dict[str, object] = {
        "table": table.raw,
        "generated_path": path,
    }
    db_columns = {str(column["name"]): column for column in table.columns}
    candidate_columns = {prop.column: prop for prop in entity.properties}
    missing = sorted(set(db_columns) - set(candidate_columns))
    extra = sorted(set(candidate_columns) - set(db_columns))
    if missing or extra:
        return _make_finding(
            "BLOCKED", "generated-column-mismatch", path, table.identity, None,
            {**database_base, "missing_columns": missing, "extra_columns": extra},
            None, None,
            "A new Entity candidate must map exactly the snapshot column set.",
            "Regenerate the complete candidate from the authoritative snapshot.", (),
        )

    naming = _managed_codegen_naming(root)
    expected_class = _codegen_class_name(table.identity.table)
    expected_properties = {
        str(column["name"]): _codegen_property_name(str(column["name"]))
        for column in table.columns
    }
    expected_relative_path: str | None = None
    if naming is not None and expected_class:
        package_path = naming.package_name.replace(".", "/")
        file_name = expected_class + candidate.file.absolute.suffix
        expected_relative_path = file_name if not package_path else package_path + "/" + file_name
    actual_relative_path = candidate.file.absolute.relative_to(
        root / candidate.file.root
    ).as_posix()
    if (
        naming is None
        or naming.language != entity.language
        or entity.package_name != naming.package_name
        or not expected_class
        or entity.class_name != expected_class
        or expected_relative_path != actual_relative_path
        or any(
            candidate_columns[column].name != expected_name
            for column, expected_name in expected_properties.items()
        )
    ):
        return _make_finding(
            "BLOCKED", "generated-identity-mismatch", path, table.identity, None,
            {**database_base, "expected_class": expected_class,
             "expected_properties": expected_properties,
             "expected_relative_path": expected_relative_path},
            None, None,
            "The candidate property, class, package, language, or file identity is not the configured CodeGen output.",
            "Restore the skill-managed CodeGen configuration and regenerate the candidate.", (),
        )

    for column_name, column in db_columns.items():
        prop = candidate_columns[column_name]
        expected_type = _expected_basic_type(table, column, entity.language)
        if expected_type is None or prop.type_name != expected_type:
            return _make_finding(
                "BLOCKED", "generated-type-mismatch", path, table.identity, column_name,
                {**database_base, "column": column, "expected_type": expected_type},
                None, None,
                "The candidate basic type is not the proven CodeGen type for the JDBC metadata.",
                "Regenerate the candidate; do not infer an application type manually.", (),
            )
        if entity.language == "kotlin":
            expected_nullable, expected_default = _expected_kotlin_property_shape(
                column, expected_type
            )
            actual_default = _kotlin_property_initializer(candidate, prop)
            if prop.nullable is not expected_nullable:
                return _make_finding(
                    "BLOCKED", "generated-nullability-mismatch", path, table.identity, column_name,
                    {**database_base, "column": column}, None, None,
                    "The candidate Kotlin nullability is not the proven CodeGen resolver output.",
                    "Regenerate the candidate from the authoritative snapshot.", (),
                )
            if actual_default != expected_default:
                return _make_finding(
                    "BLOCKED", "generated-default-mismatch", path, table.identity, column_name,
                    {**database_base, "column": column}, None, None,
                    "The candidate Kotlin initializer is not the proven CodeGen resolver default.",
                    "Regenerate the candidate from the authoritative snapshot.", (),
                )

    db_pk = tuple(str(item["column"]) for item in (table.primary_key or ()))
    candidate_pk = tuple(
        prop.column
        for prop in entity.properties
        if _annotation(prop, "org.seasar.doma.Id") is not None
    )
    if set(candidate_pk) != set(db_pk) or len(candidate_pk) != len(db_pk):
        return _make_finding(
            "BLOCKED", "candidate-primary-key-mismatch", path, table.identity, None,
            {**database_base, "primary_key": list(table.primary_key or ())}, None, None,
            "The candidate @Id set does not exactly match the snapshot primary key.",
            "Regenerate the complete primary-key mapping.", (),
        )

    for prop in entity.properties:
        column = db_columns[prop.column]
        generated = _annotation(prop, "org.seasar.doma.GeneratedValue")
        expects_identity = (
            column.get("auto_increment") is True
            and len(db_pk) == 1
            and prop.column in candidate_pk
        )
        generated_is_identity = (
            generated is not None
            and dict(generated.arguments).get("strategy") == "GenerationType.IDENTITY"
        )
        if expects_identity != generated_is_identity:
            return _make_finding(
                "BLOCKED", "generated-value-semantics", path, table.identity, prop.column,
                {**database_base, "column": column}, None, None,
                "The candidate @GeneratedValue does not exactly match auto-increment metadata.",
                "Regenerate the candidate and confirm the generation strategy.", (),
            )
        if generated is not None and prop.column not in candidate_pk:
            return _make_finding(
                "BLOCKED", "generated-value-semantics", path, table.identity, prop.column,
                {**database_base, "column": column}, None, None,
                "@GeneratedValue is not attached to a proven primary-key property.",
                "Choose generation semantics manually.", (),
            )
        for qualified, kind in (
            ("org.seasar.doma.Version", "version-semantics"),
            ("org.seasar.doma.TenantId", "special-mapping"),
        ):
            if _annotation(prop, qualified) is not None:
                return _make_finding(
                    "BLOCKED", kind, path, table.identity, prop.column,
                    {**database_base, "column": column}, None, None,
                    "Database metadata cannot prove this Doma application semantic.",
                    "Choose the special mapping manually.", (),
                )
    return None


def _expected_basic_type(
    table: _Table,
    column: dict[str, object],
    language: str,
) -> str | None:
    raw_type_name = column.get("type_name")
    if not isinstance(raw_type_name, str) or not raw_type_name:
        return None
    type_name = raw_type_name.casefold()
    java_type = _STANDARD_TYPE_NAMES.get(type_name)
    if table.database == "postgresql":
        java_type = _POSTGRES_TYPE_NAMES.get(type_name, java_type)
    else:
        java_type = _MYSQL_TYPE_NAMES.get(type_name, java_type)
        if type_name in {"bit", "tinyint"}:
            size = column.get("size")
            if not isinstance(size, int) or isinstance(size, bool):
                return None
            java_type = "Boolean" if size <= 1 else "Byte"
        elif type_name == "tinyint unsigned":
            size = column.get("size")
            if not isinstance(size, int) or isinstance(size, bool):
                return None
            java_type = "Boolean" if size <= 1 else "Short"
    if java_type is None:
        jdbc_type = column.get("jdbc_type")
        if not isinstance(jdbc_type, int) or isinstance(jdbc_type, bool):
            return None
        java_type = _JDBC_FALLBACK_TYPES.get(jdbc_type)
    if java_type is None or language == "java":
        return java_type
    return _KOTLIN_BASIC_TYPES.get(java_type, java_type)


def _expected_kotlin_property_shape(
    column: dict[str, object], type_name: str
) -> tuple[bool, str]:
    default = _KOTLIN_DEFAULTS.get(type_name, "null")
    nullable = column.get("nullable")
    return nullable is True or default == "null", default


def _kotlin_property_initializer(
    candidate: _ParsedFile, prop: PropertyModel
) -> str | None:
    declaration = candidate.parsed.source[
        prop.declaration_span.start:prop.declaration_span.end
    ]
    _, separator, initializer = declaration.partition("=")
    return initializer.strip() if separator else None


def _new_entity_candidate_is_generated_only(
    table: _Table, candidate: _ParsedFile
) -> bool:
    entity = candidate.parsed.entity
    if entity.generated_only:
        return True
    if entity.language != "kotlin" or not entity.unsupported_reasons:
        return False
    columns = {str(column["name"]): column for column in table.columns}
    allowed: set[str] = set()
    for prop in entity.properties:
        column = columns.get(prop.column)
        if column is None:
            continue
        expected_type = _expected_basic_type(table, column, "kotlin")
        if expected_type is None:
            continue
        expected_nullable, expected_default = _expected_kotlin_property_shape(
            column, expected_type
        )
        if expected_nullable and expected_default != "null":
            allowed.add("handwritten initializer: " + prop.name)
    return set(entity.unsupported_reasons).issubset(allowed)


def _required_metadata_finding(
    table: _Table, candidate: _ParsedFile | None
) -> Finding | None:
    primary_key_incomplete, column_gaps = _metadata_gaps(table)
    missing = ["primary_key"] if primary_key_incomplete else []
    missing.extend(
        name + "." + field
        for name, fields in column_gaps.items()
        for field in fields
    )
    if not missing:
        return None
    path = candidate.file.path if candidate is not None else SNAPSHOT_PATH
    return _make_finding(
        "BLOCKED", "schema-metadata-incomplete", path, table.identity, None,
        {"table": table.raw, "missing_facts": sorted(set(missing))},
        None, None,
        "Required JDBC metadata is unknown, so the generated candidate cannot be proven complete.",
        "Refresh the schema snapshot with a driver that reports every required fact.", (),
    )


def _metadata_gaps(
    table: _Table,
) -> tuple[bool, dict[str, tuple[str, ...]]]:
    column_gaps: dict[str, tuple[str, ...]] = {}
    for column in table.columns:
        name = str(column.get("name"))
        missing: list[str] = []
        for field, expected in (
            ("jdbc_type", int),
            ("type_name", str),
            ("nullable", bool),
            ("auto_increment", bool),
        ):
            value = column.get(field)
            if (
                not isinstance(value, expected)
                or isinstance(value, bool) and expected is int
                or expected is str and value == ""
            ):
                missing.append(field)
        type_name = column.get("type_name")
        if (
            table.database == "mysql"
            and isinstance(type_name, str)
            and type_name.casefold() in {"bit", "tinyint", "tinyint unsigned"}
            and (not isinstance(column.get("size"), int) or isinstance(column.get("size"), bool))
        ):
            missing.append("size")
        if _expected_basic_type(table, column, "java") is None:
            missing.append("mapped_type")
        if missing:
            column_gaps[name] = tuple(sorted(set(missing)))
    return table.primary_key is None, column_gaps


def _existing_metadata_findings(
    table: _Table, existing: _ParsedFile
) -> tuple[tuple[Finding, ...], dict[str, frozenset[str]], bool]:
    primary_key_incomplete, column_gaps = _metadata_gaps(table)
    findings: list[Finding] = []
    if primary_key_incomplete:
        findings.append(_make_finding(
            "BLOCKED", "schema-metadata-incomplete", existing.file.path,
            table.identity, None,
            {"table": table.raw, "missing_facts": ["primary_key"]},
            None, None,
            "Primary-key metadata is unknown, so key synchronization cannot be proven.",
            "Refresh the schema snapshot before changing @Id membership.", (),
        ))
    for column_name, fields in sorted(column_gaps.items()):
        column = next(
            item for item in table.columns if item.get("name") == column_name
        )
        findings.append(_make_finding(
            "BLOCKED", "schema-metadata-incomplete", existing.file.path,
            table.identity, column_name,
            {
                "table": table.raw,
                "column": column,
                "missing_facts": [column_name + "." + field for field in fields],
            },
            None, None,
            "This column's JDBC metadata is unknown, so changes to its property cannot be proven.",
            "Refresh the schema snapshot before changing this mapped property.", (),
        ))
    return (
        tuple(findings),
        {name: frozenset(fields) for name, fields in column_gaps.items()},
        primary_key_incomplete,
    )


def _block_metadata_dependent_edits(
    findings: Sequence[Finding],
    incomplete_columns: dict[str, frozenset[str]],
    primary_key_incomplete: bool,
) -> tuple[tuple[Finding, ...], frozenset[str]]:
    result: list[Finding] = []
    non_sealing: set[str] = set()
    for finding in findings:
        affected = _has_incomplete_metadata_dependency(
            finding, incomplete_columns, primary_key_incomplete
        )
        if not affected:
            result.append(finding)
            continue
        if not finding.edits:
            result.append(finding)
            if finding.kind == "generated-value-semantics":
                non_sealing.add(finding.finding_id)
            continue
        blocked = _make_finding(
            "BLOCKED", finding.kind, finding.path, finding.table, finding.column,
            finding.database, finding.existing, finding.candidate,
            finding.reason + " Required metadata for this change is incomplete.",
            "Refresh the schema snapshot and create a fresh plan.", (),
        )
        result.append(blocked)
        non_sealing.add(blocked.finding_id)
    return tuple(result), frozenset(non_sealing)


def _has_incomplete_metadata_dependency(
    finding: Finding,
    incomplete_columns: dict[str, frozenset[str]],
    primary_key_incomplete: bool,
) -> bool:
    column_dependencies: dict[str, frozenset[str]] = {
        "add-property": frozenset({
            "jdbc_type", "type_name", "size", "mapped_type", "nullable",
            "auto_increment",
        }),
        "add-generated-value": frozenset({"auto_increment"}),
        "generated-value-semantics": frozenset({"auto_increment"}),
        "widen-basic-type": frozenset({
            "jdbc_type", "type_name", "size", "mapped_type", "nullable",
        }),
        "narrow-basic-type": frozenset({
            "jdbc_type", "type_name", "size", "mapped_type", "nullable",
        }),
        "domain-basic-mismatch": frozenset({
            "jdbc_type", "type_name", "size", "mapped_type", "nullable",
        }),
        "kotlin-type-nullability": frozenset({
            "jdbc_type", "type_name", "size", "mapped_type", "nullable",
        }),
        "kotlin-nullability": frozenset({"nullable"}),
    }
    primary_key_dependencies = {
        "add-property", "add-generated-value", "generated-value-semantics",
        "synchronize-primary-key", "candidate-primary-key-mismatch",
    }
    missing = incomplete_columns.get(finding.column or "", frozenset())
    return bool(missing & column_dependencies.get(finding.kind, frozenset())) or (
        primary_key_incomplete and finding.kind in primary_key_dependencies
    )


def _managed_codegen_naming(root: Path) -> _CodeGenNaming | None:
    build_files = [path for path in (root / "build.gradle.kts", root / "build.gradle") if path.is_file()]
    if len(build_files) != 1 or build_files[0].is_symlink():
        return None
    try:
        source = build_files[0].read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    begin = "// " + _CODEGEN_MARKER + ":begin"
    end = "// " + _CODEGEN_MARKER + ":end"
    if source.count(begin) != 1 or source.count(end) != 1:
        return None
    start = source.find(begin)
    finish = source.find(end, start + len(begin))
    if finish < 0:
        return None
    managed = source[start:finish]
    packages = re.findall(
        r"packageName\.set\(\s*(['\"])([A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*)\1\s*\)",
        managed,
    )
    languages = re.findall(r"LanguageType\.(JAVA|KOTLIN)\b", managed)
    if len(packages) != 1 or len(languages) != 1:
        return None
    return _CodeGenNaming(packages[0][1], languages[0].lower())


def _codegen_property_name(column_name: str) -> str:
    parts = column_name.split("_")
    while len(parts) > 1 and not parts[-1]:
        parts.pop()
    if not parts:
        return ""
    return parts[0].lower() + "".join(
        part[:1].upper() + part[1:].lower() if part else ""
        for part in parts[1:]
    )


def _codegen_class_name(table_name: str) -> str:
    name = _codegen_property_name(table_name)
    return name[:1].upper() + name[1:] if name else ""


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


def _localized_safe_edits_in_unsupported_source(
    table: _Table,
    existing: _ParsedFile,
    candidate: _ParsedFile,
    references: Sequence[_SourceFile],
) -> tuple[Finding, ...]:
    """Keep additive/ID edits executable when they cannot touch retained semantics."""
    reasons = existing.parsed.entity.unsupported_reasons
    preservable_prefixes = ("handwritten method:", "custom annotation:")
    if not reasons or any(
        not reason.startswith(preservable_prefixes) for reason in reasons
    ):
        return ()
    metadata_findings, incomplete_columns, primary_key_incomplete = (
        _existing_metadata_findings(table, existing)
    )
    compared, _ = _block_metadata_dependent_edits(
        _compare_entity(table, existing, candidate, references),
        incomplete_columns,
        primary_key_incomplete,
    )
    blockers = tuple(finding for finding in compared if finding.status == "BLOCKED")
    if metadata_findings or blockers:
        return metadata_findings + blockers
    allowed = {"add-property", "synchronize-primary-key"}
    localized: list[Finding] = []
    for finding in compared:
        if finding.status != "SAFE" or finding.kind not in allowed:
            continue
        if finding.kind == "add-property":
            collision = _add_property_accessor_collision(existing, candidate, finding.column)
            if collision is not None:
                localized.append(_make_finding(
                    "BLOCKED", finding.kind, finding.path, finding.table, finding.column,
                    finding.database, finding.existing, finding.candidate,
                    "The generated accessor would collide with handwritten method " + collision + ".",
                    "Keep the handwritten method and decide the property API manually before replanning.", (),
                ))
                continue
        localized.append(finding)
    return metadata_findings + tuple(localized)


def _add_property_accessor_collision(
    existing: _ParsedFile,
    candidate: _ParsedFile,
    column: str | None,
) -> str | None:
    """Detect accessor names that an inserted property would duplicate."""
    if column is None:
        return "an unknown method"
    prop = next(
        (item for item in candidate.parsed.entity.properties if item.column == column),
        None,
    )
    if prop is None:
        return "an unknown method"
    accessor_names = {
        method.name for method in candidate.parsed.entity.methods
        if method.generated_accessor_for == prop.name
    }
    if candidate.parsed.entity.language == "kotlin":
        capitalized = prop.name[:1].upper() + prop.name[1:]
        accessor_names.update({"get" + capitalized, "set" + capitalized})
        if (
            prop.type_name.rstrip("?") == "Boolean"
            and prop.name.startswith("is")
            and len(prop.name) > 2
            and prop.name[2].isupper()
        ):
            accessor_names.update({prop.name, "set" + prop.name[2:]})
    for method in existing.parsed.entity.methods:
        if method.name in accessor_names:
            return method.signature
    return None


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


def _fail_closed_file(
    findings: Sequence[Finding],
    non_sealing_blockers: frozenset[str] = frozenset(),
) -> tuple[Finding, ...]:
    if not any(
        finding.status == "BLOCKED"
        and finding.finding_id not in non_sealing_blockers
        for finding in findings
    ):
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
    old_comment_start = old_text.find("/**")
    old_comment_end = old_text.find("*/", old_comment_start + 3) + 2
    new_comment_start = new_text.find("/**")
    new_comment_end = new_text.find("*/", new_comment_start + 3) + 2
    comment_span = SourceSpan(
        old_span.start + old_comment_start,
        old_span.start + old_comment_end,
    )
    replacement = _to_line_ending(
        new_text[new_comment_start:new_comment_end],
        existing.parsed.entity.line_ending,
    )
    return Edit("replace", existing.file.path, comment_span, replacement), old_text, new_text


def _database_comment_matches_snapshot(
    candidate: _ParsedFile,
    prop: PropertyModel,
    remarks: object,
) -> bool:
    candidate_doc = _doc_prefix(candidate.parsed.source, prop)[1]
    return _documentation_matches_snapshot(candidate_doc, remarks)


def _documentation_matches_snapshot(documentation: str, remarks: object) -> bool:
    candidate_payload = _normalized_doc_payload(documentation)
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
    accessor_names = {getter, setter}
    if (
        entity.language == "kotlin"
        and prop.type_name.rsplit(".", 1)[-1] == "Boolean"
        and len(prop.name) > 2
        and prop.name.startswith("is")
        and prop.name[2].isupper()
    ):
        accessor_names.update({prop.name, "set" + prop.name[2:]})
    member_names = accessor_names | {prop.name}
    factory_keys = _entity_factory_keys(files, entity)
    typealias_keys = _entity_wrapper_typealias_keys(files, entity)
    generic_typealias_keys = _entity_generic_wrapper_typealias_keys(files)
    wrapper_factory_keys = _entity_wrapper_factory_keys(
        files, entity, typealias_keys, generic_typealias_keys
    )
    collection_factory_keys = _entity_collection_factory_keys(
        files, entity, generic_typealias_keys
    )
    for item in files:
        if item.path == target_path:
            continue
        tokens = _code_tokens(item)
        if _has_typed_member_reference(
            item, tokens, entity, member_names, factory_keys, typealias_keys,
            wrapper_factory_keys, collection_factory_keys,
        ):
            return True
        if item.language == "kotlin" and _has_kotlin_receiver_scope_reference(
            item, tokens, entity, member_names, factory_keys, typealias_keys,
            wrapper_factory_keys, collection_factory_keys,
        ):
            return True
    return False


def _source_package(item: _SourceFile) -> str:
    match = re.search(
        r"(?m)^\s*package\s+"
        r"([A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*)",
        item.source,
    )
    return match.group(1) if match is not None else ""


def _source_imports(item: _SourceFile) -> frozenset[str]:
    return frozenset(re.findall(
        r"(?m)^\s*import\s+"
        r"([A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$*][A-Za-z0-9_$*]*)+)",
        item.source,
    ))


def _java_static_imports(item: _SourceFile) -> frozenset[str]:
    if item.language != "java":
        return frozenset()
    return frozenset(re.findall(
        r"(?m)^\s*import\s+static\s+"
        r"([A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$*][A-Za-z0-9_$]*)+)",
        item.source,
    ))


def _code_tokens(item: _SourceFile) -> tuple[Token, ...]:
    tokens = lex_java(item.source) if item.language == "java" else lex_kotlin(item.source)
    ignored = {
        "WHITESPACE", "LINE_COMMENT", "BLOCK_COMMENT", "JAVADOC", "KDOC",
        "STRING", "CHAR", "TEXT_BLOCK", "TRIPLE_STRING",
    }
    return tuple(token for token in tokens if token.kind not in ignored)


def _identifier(token: Token) -> str:
    return token.text.strip("`") if token.kind == "IDENT" else ""


def _top_level_type_declarations(item: _SourceFile) -> frozenset[str]:
    keywords = {"class", "interface", "enum", "record"}
    if item.language == "kotlin":
        keywords.add("object")
    excluded_names = {
        "class", "interface", "enum", "record", "object", "fun", "val", "var",
    }
    package_name = _source_package(item)
    tokens = _code_tokens(item)
    depth = 0
    declarations: set[str] = set()
    for index, token in enumerate(tokens):
        if token.text == "}":
            depth = max(0, depth - 1)
            continue
        if depth == 0 and _identifier(token) in keywords and index + 1 < len(tokens):
            previous = tokens[index - 1].text if index else ""
            name = _identifier(tokens[index + 1])
            if previous not in {".", ":"} and name and name not in excluded_names:
                declarations.add((package_name + "." if package_name else "") + name)
        if token.text == "{":
            depth += 1
    if item.language == "kotlin":
        for facade_name in re.findall(
            r"(?m)^\s*@file\s*:\s*(?:kotlin\.jvm\.)?JvmName\s*"
            r"\(\s*\"([A-Za-z_$][A-Za-z0-9_$]*)\"\s*\)",
            item.source,
        ):
            declarations.add(
                (package_name + "." if package_name else "") + facade_name
            )
    return frozenset(declarations)


def _file_resolves_entity(item: _SourceFile, entity: EntityModel) -> bool:
    fqcn = (entity.package_name + "." if entity.package_name else "") + entity.class_name
    imports = _source_imports(item)
    return (
        _source_package(item) == entity.package_name
        or fqcn in imports
        or entity.package_name + ".*" in imports
        or fqcn in item.source
    )


def _entity_type_names(item: _SourceFile, entity: EntityModel) -> frozenset[str]:
    """Return source-level type names that resolve to this entity.

    Kotlin permits an import alias in a receiver or explicit type annotation.
    Retain the canonical name and recognize only aliases for this exact FQCN;
    an uncertain import must never allow a destructive merge edit.
    """
    names = {entity.class_name}
    if item.language != "kotlin" or not _file_resolves_entity(item, entity):
        return frozenset(names)
    fqcn = (entity.package_name + "." if entity.package_name else "") + entity.class_name
    aliases = re.findall(
        r"(?m)^\s*import\s+" + re.escape(fqcn)
        + r"\s+as\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*$",
        item.source,
    )
    names.update(aliases)
    # A local typealias is a source-level Entity type.  We recognize only an
    # exact, non-generic alias to this Entity; other aliases remain unknown and
    # therefore cannot make a destructive change safer.
    typealias_pattern = (
        r"(?m)^\s*typealias\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*"
        r"(?:[A-Za-z_$][A-Za-z0-9_$]*\.)*([A-Za-z_$][A-Za-z0-9_$]*)\s*$"
    )
    for alias, target in re.findall(typealias_pattern, item.source):
        if target in names:
            names.add(alias)
    return frozenset(names)


def _matching_token(
    tokens: Sequence[Token], start: int, opener: str, closer: str
) -> int | None:
    if start >= len(tokens) or tokens[start].text != opener:
        return None
    depth = 0
    for index in range(start, len(tokens)):
        if tokens[index].text == opener:
            depth += 1
        elif tokens[index].text == closer:
            depth -= 1
            if depth == 0:
                return index
    return None


def _entity_factory_keys(
    files: Sequence[_SourceFile], entity: EntityModel
) -> frozenset[tuple[str, ...]]:
    result: set[tuple[str, ...]] = set()
    for item in files:
        if not _file_resolves_entity(item, entity):
            continue
        tokens = _code_tokens(item)
        package_name = _source_package(item)
        if item.language == "kotlin":
            for index, token in enumerate(tokens):
                if _identifier(token) != "fun":
                    continue
                open_index = next((
                    cursor for cursor in range(index + 1, min(len(tokens), index + 32))
                    if tokens[cursor].text == "("
                ), None)
                if open_index is None or open_index == 0:
                    continue
                name = _identifier(tokens[open_index - 1])
                close_index = _matching_token(tokens, open_index, "(", ")")
                if not name or close_index is None:
                    continue
                tail = tokens[close_index + 1:min(len(tokens), close_index + 12)]
                returns_entity = any(
                    tail[cursor].text == ":"
                    and cursor + 1 < len(tail)
                    and _identifier(tail[cursor + 1]) == entity.class_name
                    for cursor in range(len(tail))
                )
                if not returns_entity:
                    returns_entity = any(
                        tail[cursor].text == "="
                        and cursor + 2 < len(tail)
                        and _identifier(tail[cursor + 1]) == entity.class_name
                        and tail[cursor + 2].text == "("
                        for cursor in range(len(tail))
                    )
                if returns_entity:
                    result.add((package_name, name))
        else:
            result.update(_java_entity_factory_keys(item, tokens, entity))
    return frozenset(result)


_JAVA_METHOD_KEYWORDS = {
    "abstract", "assert", "boolean", "break", "byte", "case", "catch",
    "char", "class", "const", "continue", "default", "do", "double",
    "else", "enum", "extends", "false", "final", "finally", "float",
    "for", "goto", "if", "implements", "import", "instanceof", "int",
    "interface", "long", "native", "new", "null", "package", "private",
    "protected", "public", "record", "return", "short", "static", "strictfp",
    "super", "switch", "synchronized", "this", "throw", "throws", "transient",
    "true", "try", "void", "volatile", "while",
}


def _java_type_body_ranges(
    tokens: Sequence[Token], package_name: str
) -> tuple[tuple[str, int, int], ...]:
    ranges: list[tuple[str, int, int]] = []
    for index, token in enumerate(tokens):
        if token.text not in {"class", "interface", "enum", "record"}:
            continue
        name_index = next((
            cursor for cursor in range(index + 1, min(len(tokens), index + 8))
            if _identifier(tokens[cursor])
        ), None)
        if name_index is None:
            continue
        open_index = next((
            cursor for cursor in range(name_index + 1, len(tokens))
            if tokens[cursor].text == "{"
        ), None)
        if open_index is None:
            continue
        close_index = _matching_token(tokens, open_index, "{", "}")
        if close_index is None:
            continue
        fqcn = (package_name + "." if package_name else "") + _identifier(tokens[name_index])
        ranges.append((fqcn, open_index, close_index))
    return tuple(ranges)


def _java_entity_factory_keys(
    item: _SourceFile,
    tokens: Sequence[Token],
    entity: EntityModel,
) -> frozenset[tuple[str, str, bool]]:
    """Return declaring-class-aware Java method return facts.

    A bare method name is not enough to resolve a Java call: unrelated classes
    may expose the same method, and overloads may return different types.
    Retain every project-local declaration for a class/method pair, marking
    exact Entity returns for diagnostics. Resolution treats a visible pair
    containing any return type as external evidence because overload
    resolution is outside this source scanner.
    """
    result: set[tuple[str, ...]] = set()
    entity_fqcn = (entity.package_name + "." if entity.package_name else "") + entity.class_name
    for fqcn, open_index, close_index in _java_type_body_ranges(
        tokens, _source_package(item)
    ):
        for method_index in range(open_index + 1, close_index - 1):
            if not _identifier(tokens[method_index]) or tokens[method_index + 1].text != "(":
                continue
            if tokens[method_index - 1].text == ".":
                continue
            return_index = method_index - 1
            return_name = _identifier(tokens[return_index])
            if not return_name or return_name in _JAVA_METHOD_KEYWORDS:
                continue
            return_parts = [return_name]
            cursor = return_index - 1
            while cursor >= open_index + 1 and tokens[cursor].text == ".":
                previous = _identifier(tokens[cursor - 1])
                if not previous:
                    break
                return_parts.insert(0, previous)
                cursor -= 2
            return_type = ".".join(return_parts)
            is_entity = return_type == entity_fqcn or (
                return_type == entity.class_name and _file_resolves_entity(item, entity)
            )
            type_variables = _java_method_type_variables(
                tokens, open_index, method_index
            )
            generic_return = return_type in type_variables
            result.add((
                fqcn, _identifier(tokens[method_index]), is_entity,
                generic_return,
            ))
    return frozenset(result)


def _java_entity_collection_factory_keys(
    item: _SourceFile,
    tokens: Sequence[Token],
    entity: EntityModel,
) -> frozenset[tuple[str, str, bool, bool]]:
    """Return class-qualified Java generic factory return facts.

    The final boolean records whether the generic argument is this Entity;
    the preceding boolean records whether the generic type is a wrapper rather
    than a collection.  Keep non-Entity generic overloads as negative facts so
    a matching method cannot be selected when Java overload resolution is not
    available to this source scanner.
    """
    result: set[tuple[str, str, bool, bool]] = set()
    for fqcn, open_index, close_index in _java_type_body_ranges(
        tokens, _source_package(item)
    ):
        simple_name = fqcn.rsplit(".", 1)[-1]
        for method_index in range(open_index + 1, close_index - 1):
            if not _identifier(tokens[method_index]) or tokens[method_index + 1].text != "(":
                continue
            if tokens[method_index - 1].text == ".":
                continue
            if _identifier(tokens[method_index]) == simple_name:
                continue
            return_end = method_index - 1
            generic_open = (
                _matching_token_before(tokens, return_end, "<", ">")
                if tokens[return_end].text == ">" else None
            )
            if generic_open is None:
                result.add((fqcn, _identifier(tokens[method_index]), False, False))
                continue
            raw_parts: list[str] = []
            cursor = generic_open - 1
            while cursor >= open_index + 1:
                name = _identifier(tokens[cursor])
                if not name:
                    break
                raw_parts.insert(0, name)
                cursor -= 1
                if cursor < open_index + 1 or tokens[cursor].text != ".":
                    break
                cursor -= 1
            if not raw_parts:
                result.add((fqcn, _identifier(tokens[method_index]), False, False))
                continue
            raw_name = ".".join(raw_parts)
            direct = _direct_entity_type_argument(
                item, tokens, generic_open + 1, return_end, entity
            )
            if not direct:
                # A generic method such as ``<T> List<T> load`` or
                # ``<T extends Employee> Box<T> load`` has no concrete Entity
                # token in its declaration.  The call-site type argument is
                # therefore the only usable substitution proof.  Until the
                # scanner can resolve overloads and inferred arguments, treat
                # a direct method type-variable return as Entity evidence and
                # fail closed for both explicit and inferred calls.
                return_type_variables = _java_method_type_variables(
                    tokens, open_index, method_index
                )
                argument_tokens = tokens[generic_open + 1:return_end]
                direct = _contains_top_level_type_variable(
                    argument_tokens, return_type_variables
                )
            wrapper = raw_name.rsplit(".", 1)[-1] not in _ENTITY_COLLECTION_TYPES
            result.add((fqcn, _identifier(tokens[method_index]), wrapper, direct))
    return frozenset(result)


def _java_method_type_variables(
    tokens: Sequence[Token], body_open: int, method_index: int
) -> frozenset[str]:
    """Return type variables declared by one Java method signature."""
    return_end = method_index - 1
    if return_end < body_open:
        return frozenset()
    if tokens[return_end].text == ">":
        return_open = _matching_token_before(tokens, return_end, "<", ">")
        if return_open is None:
            return frozenset()
        return_start = return_open - 1
    else:
        return_start = return_end
    declaration_close = return_start - 1
    if declaration_close <= body_open or tokens[declaration_close].text != ">":
        return frozenset()
    declaration_open = _matching_token_before(tokens, declaration_close, "<", ">")
    if declaration_open is None or declaration_open <= body_open:
        return frozenset()
    result: set[str] = set()
    cursor = declaration_open + 1
    depth = 0
    while cursor < return_start:
        token = tokens[cursor]
        if token.text == "<":
            depth += 1
        elif token.text == ">":
            depth = max(0, depth - 1)
        elif depth == 0 and _identifier(token):
            previous = tokens[cursor - 1].text if cursor > declaration_open + 1 else ","
            if previous == ",":
                result.add(_identifier(token))
        cursor += 1
    return frozenset(result)


def _contains_top_level_type_variable(
    tokens: Sequence[Token], type_variables: frozenset[str]
) -> bool:
    if not type_variables:
        return False
    depth = 0
    for token in tokens:
        if token.text == "<":
            depth += 1
        elif token.text == ">":
            depth = max(0, depth - 1)
        elif depth == 0 and _identifier(token) in type_variables:
            return True
    return False


def _factory_available(
    item: _SourceFile,
    name: str,
    factory_keys: frozenset[tuple[str, ...]],
    entity: EntityModel | None = None,
) -> bool:
    if item.language == "java":
        explicit_args, base_name = _java_factory_explicit_call(name)
        java_keys = {
            (
                declaring_type, method_name, returns_entity,
                generic_return,
            )
            for key in factory_keys
            if len(key) == 4
            for declaring_type, method_name, returns_entity, generic_return in (key,)
        }
        java_keys.update({
            (declaring_type, method_name, returns_entity, False)
            for key in factory_keys
            if len(key) == 3
            for declaring_type, method_name, returns_entity in (key,)
        })
        parts = base_name.split(".")
        if len(parts) == 1:
            static_imports = _java_static_imports(item)
            candidates = {
                key for key in java_keys
                if key[1] == parts[0]
                and (
                    key[0] + "." + key[1] in static_imports
                    or any(
                        imported.endswith(".*")
                        and key[0].startswith(imported[:-2] + ".")
                        for imported in static_imports
                    )
                )
            }
        else:
            method_name = parts[-1]
            class_name = ".".join(parts[:-1])
            imports = _source_imports(item)
            visible_types = {
                class_name,
                *(
                    imported for imported in imports
                    if not imported.startswith("static.")
                ),
            }
            candidates = {
                key for key in java_keys
                if key[1] == method_name
                and (
                    key[0] == class_name
                    or (
                        "." not in class_name
                        and key[0].rsplit(".", 1)[-1] == class_name
                        and (
                            key[0] in visible_types
                            or _source_package(item) == key[0].rsplit(".", 1)[0]
                            or key[0].rsplit(".", 1)[0] + ".*" in imports
                        )
                    )
                )
            }
        # Once a project-local factory is visible, do not treat an overload
        # set with a non-Entity/unknown return as proof that the call is safe.
        # The source scanner cannot perform Java overload resolution, so any
        # matching declaration is external evidence and must block a
        # potentially destructive Entity change.  Only an empty candidate set
        # means that no factory evidence exists.
        if explicit_args is not None and entity is not None:
            explicit_result = _java_explicit_type_arguments_entity_state(
                item, explicit_args, entity
            )
            if explicit_result is False:
                candidates = {
                    key for key in candidates if not key[3]
                }
        return bool(candidates)
    parts = name.split(".")
    if len(parts) > 1:
        return (".".join(parts[:-1]), parts[-1]) in factory_keys
    name = parts[-1]
    if (_source_package(item), name) in factory_keys:
        return True
    imports = _source_imports(item)
    return any(
        (package_name, name) in factory_keys
        and (package_name + "." + name in imports or package_name + ".*" in imports)
        for key in factory_keys
        if len(key) == 2
        for package_name, factory_name in (key,)
        if factory_name == name
    )


def _java_factory_explicit_call(name: str) -> tuple[tuple[str, ...] | None, str]:
    """Split ``Provider.<Employee>load`` into arguments and base name."""
    marker = name.find(".<")
    if marker < 0:
        return None, name
    open_index = marker + 1
    close_index = name.find(">", open_index + 1)
    if close_index < 0:
        return None, name
    raw = name[open_index + 1:close_index]
    arguments = tuple(part.strip() for part in raw.split(",") if part.strip())
    if not arguments:
        return None, name
    return arguments, name[:marker] + "." + name[close_index + 1:]


def _java_explicit_type_arguments_entity_state(
    item: _SourceFile,
    arguments: tuple[str, ...],
    entity: EntityModel,
) -> bool | None:
    """Classify explicit method type arguments as Entity/non-Entity/unknown."""
    type_names = _entity_type_names(item, entity)
    state: bool | None = False
    for argument in arguments:
        tokens = tuple(
            token for token in lex_java(argument)
            if token.kind not in {"WHITESPACE", "LINE_COMMENT", "BLOCK_COMMENT"}
        )
        if _exact_entity_type_reference(tokens, 0, len(tokens), type_names):
            state = True
            continue
        if not tokens or any(
            token.kind != "IDENT" and token.text not in {".", "?", "extends", "super"}
            for token in tokens
        ):
            return None
        if any(
            _identifier(token) and len(_identifier(token)) == 1
            and _identifier(token).isupper()
            for token in tokens
        ):
            return None
    return state


def _typed_entity_variables(
    item: _SourceFile,
    tokens: Sequence[Token],
    entity: EntityModel,
    factory_keys: frozenset[tuple[str, str]],
    typealias_keys: frozenset[tuple[str, str, bool]],
    wrapper_factory_keys: frozenset[tuple[str, str]] = frozenset(),
    collection_factory_keys: frozenset[tuple[str, str, bool]] = frozenset(),
) -> frozenset[str]:
    result: set[str] = set()
    collection_symbols = _entity_collection_symbols(
        item, tokens, entity, typealias_keys, wrapper_factory_keys,
        collection_factory_keys,
    )
    type_names = _entity_type_names(item, entity)
    if _file_resolves_entity(item, entity) and item.language == "kotlin":
        for index in range(1, len(tokens) - 1):
            if tokens[index].text != ":" or not _identifier(tokens[index - 1]):
                continue
            type_end = next((
                cursor for cursor in range(index + 1, len(tokens))
                if tokens[cursor].text in {"=", "{", "}", ",", ")", ";"}
            ), len(tokens))
            if _exact_entity_type_reference(
                tokens, index + 1, type_end, type_names
            ):
                result.add(_identifier(tokens[index - 1]))
    elif _file_resolves_entity(item, entity):
        for index in range(len(tokens) - 1):
            if (
                _identifier(tokens[index]) == entity.class_name
                and _identifier(tokens[index + 1])
            ):
                result.add(_identifier(tokens[index + 1]))
    changed = True
    while changed:
        changed = False
        for index, token in enumerate(tokens[:-1]):
            if token.text != "=":
                continue
            target = _assignment_target(tokens, index)
            if not target or not _assignment_declares_inferred_variable(
                tokens, index, target
            ):
                continue
            if not target or target in result:
                continue
            if _entity_expression_after(
                item, tokens, index + 1, entity, frozenset(result),
                collection_symbols.names_at(index), collection_symbols.factories,
                collection_symbols.wrapper_factories,
                factory_keys,
            ):
                result.add(target)
                changed = True
    return frozenset(result)


def _entity_collection_symbols(
    item: _SourceFile,
    tokens: Sequence[Token],
    entity: EntityModel,
    typealias_keys: frozenset[tuple[str, str, bool]] = frozenset(),
    wrapper_factory_keys: frozenset[tuple[str, str]] = frozenset(),
    collection_factory_keys: frozenset[tuple[str, ...]] = frozenset(),
) -> _CollectionSymbols:
    imported_typealiases = _available_entity_wrapper_typealiases(item, typealias_keys)
    visible_wrapper_factories = _available_wrapper_factories(
        item, wrapper_factory_keys
    )
    visible_collection_factories = _available_entity_collection_factories(
        item, collection_factory_keys
    )
    if (
        not _file_resolves_entity(item, entity)
        and not imported_typealiases
        and not visible_wrapper_factories
        and not visible_collection_factories
    ):
        return _CollectionSymbols((), frozenset(), frozenset())
    declarations: list[tuple[str, int, int, bool, bool]] = []
    factories: set[str] = set(visible_wrapper_factories)
    wrapper_factories: set[str] = set(visible_wrapper_factories)
    factories.update(visible_collection_factories)
    wrapper_factories.update(
        name for name, wrapper in visible_collection_factories.items() if wrapper
    )
    typealias_wrappers = {
        **imported_typealiases,
        **_direct_generic_entity_typealiases(item, tokens, entity),
    }
    if item.language == "kotlin":
        for index, token in enumerate(tokens):
            typealias_name = _identifier(token)
            if (
                typealias_name in typealias_wrappers
                and index >= 2
                and tokens[index - 1].text == ":"
            ):
                variable = _identifier(tokens[index - 2])
                if tokens[index - 2].text == ")":
                    open_index = _matching_token_before(tokens, index - 2, "(", ")")
                    if open_index is not None and open_index > 0:
                        factory = _identifier(tokens[open_index - 1])
                        if factory:
                            factories.add(factory)
                            if typealias_wrappers[typealias_name]:
                                wrapper_factories.add(factory)
                elif variable:
                    declarations.append((
                        variable, index - 2,
                        _binding_scope_end(tokens, index - 2), True,
                        typealias_wrappers[typealias_name],
                    ))
    for index in range(len(tokens) - 3):
        if tokens[index + 1].text != "<":
            continue
        close = _matching_token(tokens, index + 1, "<", ">")
        if close is None:
            continue
        direct = _direct_entity_type_argument(item, tokens, index + 2, close, entity)
        wrapper = _identifier(tokens[index]) not in _ENTITY_COLLECTION_TYPES
        if item.language == "kotlin":
            if (
                direct
                and index >= 3
                and tokens[index - 1].text == ":"
                and tokens[index - 2].text == ")"
            ):
                open_index = _matching_token_before(tokens, index - 2, "(", ")")
                if open_index is not None and open_index > 0:
                    name = _identifier(tokens[open_index - 1])
                    if name:
                        factories.add(name)
                        if wrapper:
                            wrapper_factories.add(name)
            elif index >= 2 and tokens[index - 1].text == ":":
                variable = _identifier(tokens[index - 2])
                if variable:
                    variable_index = index - 2
                    declarations.append((
                        variable, variable_index,
                        _binding_scope_end(tokens, variable_index), direct, wrapper,
                    ))
        elif close + 1 < len(tokens):
            name = _identifier(tokens[close + 1])
            if name:
                if close + 2 < len(tokens) and tokens[close + 2].text == "(":
                    if direct:
                        factories.add(name)
                        if wrapper:
                            wrapper_factories.add(name)
                else:
                    variable_index = close + 1
                    declarations.append((
                        name, variable_index,
                        _binding_scope_end(tokens, variable_index), direct, wrapper,
                    ))
    declarations.sort(key=lambda item: item[1])
    inferred: list[tuple[str, int, int, bool, bool]] = []
    changed = True
    while changed:
        changed = False
        for index, token in enumerate(tokens[:-1]):
            if token.text != "=":
                continue
            target = _assignment_target(tokens, index)
            statement_start = max(
                (cursor for cursor in range(index) if tokens[cursor].text in {";", "{", "}"}),
                default=-1,
            )
            if any(
                name == target and statement_start < declared_at < index
                for name, declared_at, _, _, _ in declarations
            ):
                continue
            active = _collection_names_at(declarations, inferred, index)
            direct = _collection_expression_after(
                item, tokens, index + 1, active, frozenset(factories), entity
            )
            binding = (target, index, _binding_scope_end(tokens, index), direct, False)
            if target and binding not in inferred:
                inferred = [item for item in inferred if item[:2] != binding[:2]]
                inferred.append(binding)
                changed = True
    merged_bindings: dict[tuple[str, int, int], tuple[str, int, int, bool, bool]] = {}
    for binding in declarations + inferred:
        name, declared_at, scope_end, direct, wrapper = binding
        key = (name, declared_at, scope_end)
        previous = merged_bindings.get(key)
        if previous is None:
            merged_bindings[key] = binding
        else:
            # One Kotlin type can be recognized both by its raw generic syntax
            # and by a visible alias.  Preserve the proven direct-wrapper fact
            # deterministically instead of letting set iteration choose it.
            merged_bindings[key] = (
                name, declared_at, scope_end,
                previous[3] or direct, previous[4] or wrapper,
            )
    return _CollectionSymbols(
        tuple(sorted(merged_bindings.values(), key=lambda item: (item[1], item[0]))),
        frozenset(factories),
        frozenset(wrapper_factories),
    )


def _direct_generic_entity_typealiases(
    item: _SourceFile,
    tokens: Sequence[Token],
    entity: EntityModel,
) -> dict[str, bool]:
    """Return local Kotlin aliases whose direct generic argument is this Entity.

    A direct alias such as ``typealias StaffBox = Box<Employee>`` carries the
    same receiver safety information as its expanded type.  We intentionally
    do not follow aliases through other files: only a declaration visible in
    this source (including an imported Entity name) is syntactically proven.
    Nested arguments remain excluded, so ``List<Box<Employee>>`` does not
    become an Entity receiver merely because it mentions the Entity.
    """
    if item.language != "kotlin" or not _file_resolves_entity(item, entity):
        return {}
    aliases: dict[str, bool] = {}
    for index in range(len(tokens) - 4):
        if _identifier(tokens[index]) != "typealias":
            continue
        alias = _identifier(tokens[index + 1])
        if not alias:
            continue
        type_cursor = index + 2
        if type_cursor < len(tokens) and tokens[type_cursor].text == "<":
            type_cursor = _matching_token(tokens, type_cursor, "<", ">")
            if type_cursor is None:
                continue
            type_cursor += 1
        if type_cursor >= len(tokens) or tokens[type_cursor].text != "=":
            continue
        type_cursor += 1
        type_name = _identifier(tokens[type_cursor])
        if not type_name:
            continue
        while (
            type_cursor + 2 < len(tokens)
            and tokens[type_cursor + 1].text == "."
            and _identifier(tokens[type_cursor + 2])
        ):
            type_cursor += 2
            type_name = _identifier(tokens[type_cursor])
        if type_cursor + 1 >= len(tokens) or tokens[type_cursor + 1].text != "<":
            continue
        close = _matching_token(tokens, type_cursor + 1, "<", ">")
        if close is None:
            continue
        if _direct_entity_type_argument(item, tokens, type_cursor + 2, close, entity):
            aliases[alias] = type_name not in _ENTITY_COLLECTION_TYPES
    return aliases


def _entity_wrapper_typealias_keys(
    files: Sequence[_SourceFile], entity: EntityModel
) -> frozenset[tuple[str, str, bool]]:
    """Return project-local, direct Entity generic Kotlin aliases by FQ name."""
    result: set[tuple[str, str, bool]] = set()
    for item in files:
        if item.language != "kotlin":
            continue
        for alias, wrapper in _direct_generic_entity_typealiases(
            item, _code_tokens(item), entity
        ).items():
            result.add((_source_package(item), alias, wrapper))
    return frozenset(result)


def _generic_wrapper_typealias_declarations(
    item: _SourceFile,
    known_types: frozenset[str],
) -> tuple[tuple[str, str, str, bool], ...]:
    """Return direct, project-local one-parameter wrapper typealiases."""
    if item.language != "kotlin":
        return ()
    tokens = _code_tokens(item)
    package_name = _source_package(item)
    declarations: list[tuple[str, str, str, bool]] = []
    for index, token in enumerate(tokens):
        if _identifier(token) != "typealias" or index + 5 >= len(tokens):
            continue
        alias = _identifier(tokens[index + 1])
        if not alias or tokens[index + 2].text != "<":
            continue
        parameter_end = _matching_token(tokens, index + 2, "<", ">")
        if parameter_end is None or parameter_end != index + 4:
            continue
        parameter = _identifier(tokens[index + 3])
        if not parameter or tokens[index + 5].text != "=":
            continue
        cursor = index + 6
        parts: list[str] = []
        while cursor < len(tokens):
            name = _identifier(tokens[cursor])
            if not name:
                break
            parts.append(name)
            cursor += 1
            if cursor >= len(tokens) or tokens[cursor].text != ".":
                break
            cursor += 1
        if not parts or cursor >= len(tokens) or tokens[cursor].text != "<":
            continue
        target_raw_name = ".".join(parts)
        close = _matching_token(tokens, cursor, "<", ">")
        if close is None or close != cursor + 2:
            continue
        if _identifier(tokens[cursor + 1]) != parameter:
            continue
        if (
            not _kotlin_project_type_resolves(item, target_raw_name, known_types)
            and target_raw_name.rsplit(".", 1)[-1] not in _ENTITY_COLLECTION_TYPES
        ):
            continue
        wrapper = target_raw_name.rsplit(".", 1)[-1] not in _ENTITY_COLLECTION_TYPES
        declarations.append((package_name, alias, target_raw_name, wrapper))
    return tuple(declarations)


def _entity_generic_wrapper_typealias_keys(
    files: Sequence[_SourceFile],
) -> frozenset[tuple[str, str, str, bool]]:
    """Return project-local generic wrapper aliases with one direct parameter."""
    known_types = frozenset(
        declaration
        for source in files
        for declaration in _top_level_type_declarations(source)
    )
    result: set[tuple[str, str, str, bool]] = set()
    for item in files:
        result.update(_generic_wrapper_typealias_declarations(item, known_types))
    return frozenset(result)


def _available_generic_wrapper_typealiases(
    item: _SourceFile,
    aliases: frozenset[tuple[str, str, str, bool]],
) -> dict[str, tuple[str, bool]]:
    """Resolve unambiguous project-local generic aliases visible to a file."""
    if item.language != "kotlin":
        return {}
    imports = _source_imports(item)
    imported_as: dict[str, set[str]] = {}
    for match in re.finditer(
        r"(?m)^\s*import\s+"
        r"([A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*)"
        r"\s+as\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*$",
        item.source,
    ):
        imported_as.setdefault(match.group(2), set()).add(match.group(1))
    candidates: dict[str, set[tuple[str, bool, str]]] = {}
    for package_name, alias, target_raw_name, wrapper in aliases:
        fq_name = (package_name + "." if package_name else "") + alias
        local_names: set[str] = set()
        if (
            _source_package(item) == package_name
            or fq_name in imports
            or package_name + ".*" in imports
        ):
            local_names.add(alias)
        local_names.update(
            local_name for local_name, imported in imported_as.items()
            if imported == {fq_name}
        )
        for local_name in local_names:
            candidates.setdefault(local_name, set()).add(
                (target_raw_name, wrapper, fq_name)
            )
    return {
        local_name: (next(iter(values))[0], next(iter(values))[1])
        for local_name, values in candidates.items()
        if len(values) == 1
    }


def _available_entity_wrapper_typealiases(
    item: _SourceFile,
    aliases: frozenset[tuple[str, str, bool]],
) -> dict[str, bool]:
    """Resolve direct project-local generic aliases visible to one Kotlin file."""
    if item.language != "kotlin":
        return {}
    imports = _source_imports(item)
    imported_as = {
        match.group(2): match.group(1)
        for match in re.finditer(
            r"(?m)^\s*import\s+"
            r"([A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*)"
            r"\s+as\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*$",
            item.source,
        )
    }
    available: dict[str, bool] = {}
    for package_name, alias, wrapper in aliases:
        fqcn = (package_name + "." if package_name else "") + alias
        if (
            _source_package(item) == package_name
            or fqcn in imports
            or package_name + ".*" in imports
        ):
            available[alias] = wrapper
        for local_name, imported in imported_as.items():
            if imported == fqcn:
                available[local_name] = wrapper
    return available


def _entity_wrapper_factory_keys(
    files: Sequence[_SourceFile],
    entity: EntityModel,
    typealias_keys: frozenset[tuple[str, str, bool]],
    generic_typealias_keys: frozenset[tuple[str, str, str, bool]] = frozenset(),
) -> frozenset[tuple[str, str]]:
    """Return project-local Kotlin factories whose declared return is a wrapper.

    The return type is the only proof used here.  Discovering the factory in
    one source and its call in another is necessary because a project-local
    alias can be exported from its defining package.  Unknown/external aliases
    are intentionally absent from ``typealias_keys`` and therefore never make
    a call look safe.
    """
    result: set[tuple[str, str]] = set()
    known_types = frozenset(
        declaration
        for source in files
        for declaration in _top_level_type_declarations(source)
    )
    for item in files:
        if item.language != "kotlin":
            continue
        aliases = {
            **_available_entity_wrapper_typealiases(item, typealias_keys),
            **_direct_generic_entity_typealiases(item, _code_tokens(item), entity),
        }
        generic_aliases = _available_generic_wrapper_typealiases(
            item, generic_typealias_keys
        )
        tokens = _code_tokens(item)
        for index, token in enumerate(tokens):
            if _identifier(token) != "fun":
                continue
            open_index = next((
                cursor for cursor in range(index + 1, min(len(tokens), index + 32))
                if tokens[cursor].text == "("
            ), None)
            if open_index is None:
                continue
            close_index = _matching_token(tokens, open_index, "(", ")")
            if close_index is None or close_index + 2 >= len(tokens):
                continue
            if tokens[close_index + 1].text != ":":
                continue
            if not _kotlin_factory_return_is_entity_wrapper(
                item, tokens, close_index + 2, entity, aliases,
                typealias_keys, known_types, generic_aliases,
                generic_typealias_keys,
            ):
                continue
            name = _identifier(tokens[open_index - 1]) if open_index else ""
            if name:
                result.add((_source_package(item), name))
    return frozenset(result)


def _entity_collection_factory_keys(
    files: Sequence[_SourceFile],
    entity: EntityModel,
    generic_typealias_keys: frozenset[tuple[str, str, str, bool]] = frozenset(),
) -> frozenset[tuple[str, ...]]:
    """Return project-local factories returning generic Entity receivers.

    Kotlin entries use ``(package, name, wrapper)``. Java entries retain the
    declaring class and a separate proof bit so unresolved or ambiguous
    overloads cannot become visible collection/wrapper symbols.
    """
    result: set[tuple[str, ...]] = set()
    known_types = frozenset(
        declaration
        for source in files
        for declaration in _top_level_type_declarations(source)
    )
    for item in files:
        tokens = _code_tokens(item)
        if item.language == "java":
            result.update(_java_entity_collection_factory_keys(item, tokens, entity))
            continue
        if item.language != "kotlin":
            continue
        generic_aliases = _available_generic_wrapper_typealiases(
            item, generic_typealias_keys
        )
        for index, token in enumerate(tokens):
            if _identifier(token) != "fun":
                continue
            open_index = next((
                cursor for cursor in range(index + 1, min(len(tokens), index + 32))
                if tokens[cursor].text == "("
            ), None)
            if open_index is None:
                continue
            close_index = _matching_token(tokens, open_index, "(", ")")
            if close_index is None or close_index + 2 >= len(tokens):
                continue
            if tokens[close_index + 1].text != ":":
                continue
            parsed = _kotlin_factory_return_is_entity_collection(
                item, tokens, close_index + 2, entity, known_types,
                generic_aliases, generic_typealias_keys,
            )
            if parsed is None:
                continue
            name = _identifier(tokens[open_index - 1]) if open_index else ""
            if name:
                result.add((_source_package(item), name, parsed))
    return frozenset(result)


def _kotlin_factory_return_is_entity_collection(
    item: _SourceFile,
    tokens: Sequence[Token],
    start: int,
    entity: EntityModel,
    known_types: frozenset[str],
    generic_aliases: dict[str, tuple[str, bool]],
    generic_typealias_keys: frozenset[tuple[str, str, str, bool]],
) -> bool | None:
    cursor = start
    parts: list[str] = []
    while cursor < len(tokens):
        name = _identifier(tokens[cursor])
        if not name:
            break
        parts.append(name)
        cursor += 1
        if cursor >= len(tokens) or tokens[cursor].text != ".":
            break
        cursor += 1
    if not parts or cursor >= len(tokens) or tokens[cursor].text != "<":
        return None
    close = _matching_token(tokens, cursor, "<", ">")
    if close is None:
        return None
    raw_name = ".".join(parts)
    alias = _kotlin_generic_wrapper_alias_resolves(
        raw_name, generic_aliases, generic_typealias_keys
    )
    collection_name = raw_name.rsplit(".", 1)[-1]
    wrapper = False
    if alias is not None:
        collection_name, wrapper = alias
        collection_name = collection_name.rsplit(".", 1)[-1]
    elif not _kotlin_project_type_resolves(item, raw_name, known_types):
        # Kotlin/JDK collection types are intentionally accepted by terminal
        # name; all other unproven types remain outside the safety model.
        if collection_name not in _ENTITY_COLLECTION_TYPES:
            return None
    if collection_name not in _ENTITY_COLLECTION_TYPES:
        return None
    if not _direct_entity_type_argument(item, tokens, cursor + 1, close, entity):
        return None
    return wrapper


def _kotlin_factory_return_is_entity_wrapper(
    item: _SourceFile,
    tokens: Sequence[Token],
    start: int,
    entity: EntityModel,
    aliases: dict[str, bool],
    typealias_keys: frozenset[tuple[str, str, bool]],
    known_types: frozenset[str],
    generic_aliases: dict[str, tuple[str, bool]] | None = None,
    generic_typealias_keys: frozenset[tuple[str, str, str, bool]] = frozenset(),
) -> bool:
    """Recognize one project-local Kotlin factory return wrapper.

    A factory is useful across files only when its return type is proven from
    source in this project.  Parse the complete qualified type path instead of
    looking only at the first token after ``:``, and inspect exactly one direct
    generic argument when present.  Unknown dependency types remain absent so
    an external ``Box<Employee>`` cannot make a type edit appear safe.
    """
    if start >= len(tokens):
        return False
    cursor = start
    parts: list[str] = []
    while cursor < len(tokens):
        name = _identifier(tokens[cursor])
        if not name:
            break
        parts.append(name)
        cursor += 1
        if cursor >= len(tokens) or tokens[cursor].text != ".":
            break
        cursor += 1
    if not parts:
        return False

    raw_name = ".".join(parts)
    if _kotlin_wrapper_alias_resolves(
        raw_name, aliases, typealias_keys
    ):
        return True
    if cursor >= len(tokens) or tokens[cursor].text != "<":
        return False
    close = _matching_token(tokens, cursor, "<", ">")
    if close is None:
        return False
    generic_alias = _kotlin_generic_wrapper_alias_resolves(
        raw_name, generic_aliases or {}, generic_typealias_keys
    )
    if generic_alias is not None:
        return (
            generic_alias[1]
            and _direct_entity_type_argument(item, tokens, cursor + 1, close, entity)
        )
    if not _kotlin_project_type_resolves(item, raw_name, known_types):
        return False
    return (
        raw_name.rsplit(".", 1)[-1] not in _ENTITY_COLLECTION_TYPES
        and _direct_entity_type_argument(item, tokens, cursor + 1, close, entity)
    )


def _kotlin_wrapper_alias_resolves(
    raw_name: str,
    aliases: dict[str, bool],
    typealias_keys: frozenset[tuple[str, str, bool]],
) -> bool:
    terminal = raw_name.rsplit(".", 1)[-1]
    if len(raw_name.split(".")) == 1:
        return bool(aliases.get(terminal, False))
    return any(
        wrapper
        and (package_name + "." if package_name else "") + alias == raw_name
        for package_name, alias, wrapper in typealias_keys
    )


def _kotlin_generic_wrapper_alias_resolves(
    raw_name: str,
    aliases: dict[str, tuple[str, bool]],
    typealias_keys: frozenset[tuple[str, str, str, bool]],
) -> tuple[str, bool] | None:
    terminal = raw_name.rsplit(".", 1)[-1]
    if len(raw_name.split(".")) == 1:
        return aliases.get(terminal)
    matches = {
        (target_raw_name, wrapper)
        for package_name, alias, target_raw_name, wrapper in typealias_keys
        if (package_name + "." if package_name else "") + alias == raw_name
    }
    return next(iter(matches)) if len(matches) == 1 else None


def _kotlin_project_type_resolves(
    item: _SourceFile,
    raw_name: str,
    known_types: frozenset[str],
) -> bool:
    """Resolve a Kotlin type path against project declarations/imports only."""
    if raw_name in known_types:
        return True
    if "." not in raw_name:
        package_name = _source_package(item)
        if (package_name + "." if package_name else "") + raw_name in known_types:
            return True
        imports = _source_imports(item)
        return any(
            imported in known_types
            and imported.rsplit(".", 1)[-1] == raw_name
            for imported in imports
            if not imported.endswith(".*")
        ) or any(
            imported.endswith(".*")
            and imported[:-2] + "." + raw_name in known_types
            for imported in imports
        )
    return False


def _available_wrapper_factories(
    item: _SourceFile,
    factories: frozenset[tuple[str, str]],
) -> frozenset[str]:
    """Resolve only project-local wrapper factories visible in this Kotlin file."""
    imports = _source_imports(item)
    imported_aliases: dict[str, set[str]] = {}
    for match in re.finditer(
        r"(?m)^\s*import\s+"
        r"([A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*)"
        r"\s+as\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*$",
        item.source,
    ):
        imported_aliases.setdefault(match.group(2), set()).add(match.group(1))
    visible: dict[str, set[tuple[str, str]]] = {}
    for package_name, name in factories:
        fq_name = package_name + "." + name
        visible.setdefault(fq_name, set()).add((package_name, name))
        if (
            package_name == _source_package(item)
            or fq_name in imports
            or package_name + ".*" in imports
        ):
            visible.setdefault(name, set()).add((package_name, name))
        for local_name, imported in imported_aliases.items():
            if imported == {fq_name}:
                visible.setdefault(local_name, set()).add((package_name, name))
    return frozenset(
        name for name, candidates in visible.items() if len(candidates) == 1
    )


def _available_entity_collection_factories(
    item: _SourceFile,
    factories: frozenset[tuple[str, ...]],
) -> dict[str, bool]:
    """Resolve unambiguous collection factories, including FQ calls."""
    if item.language != "kotlin":
        if item.language != "java":
            return {}
        imports = _source_imports(item)
        static_imports = _java_static_imports(item)
        visible: dict[str, set[tuple[str, bool, bool]]] = {}
        for key in factories:
            if len(key) != 4:
                continue
            declaring_type, name, wrapper, direct = key
            fq_name = declaring_type + "." + name
            candidate = (fq_name, wrapper, direct)
            # A fully-qualified project-local call does not require an import.
            visible.setdefault(fq_name, set()).add(candidate)
            class_name = declaring_type.rsplit(".", 1)[-1]
            declaring_package = declaring_type.rsplit(".", 1)[0] if "." in declaring_type else ""
            if (
                declaring_type in imports
                or declaring_package == _source_package(item)
                or declaring_package + ".*" in imports
            ):
                visible.setdefault(class_name + "." + name, set()).add(candidate)
            if (
                declaring_type + "." + name in static_imports
                or declaring_type + ".*" in static_imports
            ):
                visible.setdefault(name, set()).add(candidate)
        return {
            local_name: next(iter(values))[1]
            for local_name, values in visible.items()
            if len(values) == 1 and next(iter(values))[2]
        }
    imports = _source_imports(item)
    imported_aliases: dict[str, set[str]] = {}
    for match in re.finditer(
        r"(?m)^\s*import\s+"
        r"([A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)*)"
        r"\s+as\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*$",
        item.source,
    ):
        imported_aliases.setdefault(match.group(2), set()).add(match.group(1))
    visible: dict[str, set[tuple[str, bool]]] = {}
    for key in factories:
        if len(key) != 3:
            continue
        package_name, name, wrapper = key
        fq_name = (package_name + "." if package_name else "") + name
        # A fully-qualified project-local call does not require an import.
        visible.setdefault(fq_name, set()).add((fq_name, wrapper))
        if (
            package_name == _source_package(item)
            or fq_name in imports
            or package_name + ".*" in imports
        ):
            visible.setdefault(name, set()).add((fq_name, wrapper))
        for local_name, imported in imported_aliases.items():
            if imported == {fq_name}:
                visible.setdefault(local_name, set()).add((fq_name, wrapper))
    return {
        local_name: next(iter(values))[1]
        for local_name, values in visible.items()
        if len(values) == 1
    }


def _collection_names_at(
    declarations: Sequence[tuple[str, int, int, bool, bool]],
    inferred: Sequence[tuple[str, int, int, bool, bool]],
    position: int,
) -> frozenset[str]:
    latest: dict[str, tuple[int, bool, bool]] = {}
    for name, declared_at, scope_end, direct, wrapper in declarations:
        if declared_at <= position <= scope_end:
            latest[name] = (declared_at, direct, wrapper)
    for name, declared_at, scope_end, direct, wrapper in inferred:
        if declared_at <= position <= scope_end and (
            name not in latest or declared_at >= latest[name][0]
        ):
            latest[name] = (declared_at, direct, wrapper)
    return frozenset(name for name, (_, direct, _) in latest.items() if direct)


def _assignment_declares_inferred_variable(
    tokens: Sequence[Token], equal_index: int, target: str
) -> bool:
    start = max(0, equal_index - 12)
    return any(
        _identifier(tokens[index]) in {"val", "var"}
        and any(
            _identifier(tokens[cursor]) == target
            for cursor in range(index + 1, equal_index)
        )
        for index in range(start, equal_index)
    )


def _binding_scope_end(tokens: Sequence[Token], declaration: int) -> int:
    paren_stack: list[int] = []
    brace_stack: list[int] = []
    for index in range(declaration + 1):
        text = tokens[index].text
        if text == "(":
            paren_stack.append(index)
        elif text == ")" and paren_stack:
            paren_stack.pop()
        elif text == "{":
            brace_stack.append(index)
        elif text == "}" and brace_stack:
            brace_stack.pop()
    if paren_stack:
        close = _matching_token(tokens, paren_stack[-1], "(", ")")
        if close is not None:
            for cursor in range(close + 1, len(tokens)):
                if tokens[cursor].text == "=":
                    return _expression_scope_end(tokens, cursor + 1)
                if tokens[cursor].text == "{":
                    body_end = _matching_token(tokens, cursor, "{", "}")
                    if body_end is not None:
                        return body_end
                    break
                if tokens[cursor].text == ";":
                    return cursor
    if brace_stack:
        close = _matching_token(tokens, brace_stack[-1], "{", "}")
        if close is not None:
            return close
    return len(tokens) - 1


def _expression_scope_end(tokens: Sequence[Token], start: int) -> int:
    depths = {"(": 0, "[": 0, "{": 0}
    pairs = {")": "(", "]": "[", "}": "{"}
    for cursor in range(start, len(tokens)):
        text = tokens[cursor].text
        if text in depths:
            depths[text] += 1
            continue
        if text in pairs:
            opener = pairs[text]
            if depths[opener] > 0:
                depths[opener] -= 1
                continue
            return max(start, cursor - 1)
        if any(depths.values()):
            continue
        if text == ";" or _identifier(tokens[cursor]) in {
            "class", "enum", "fun", "interface", "object", "record",
        }:
            return max(start, cursor - 1)
    return len(tokens) - 1


def _direct_entity_type_argument(
    item: _SourceFile,
    tokens: Sequence[Token],
    start: int,
    end: int,
    entity: EntityModel,
) -> bool:
    """Whether one top-level generic argument is an exact Entity type.

    ``Map<String, Employee>`` and ``Box<Employee>`` are Entity receivers,
    whereas ``List<Box<Employee>>`` is not: accessing the list yields ``Box``.
    This deliberately supports qualified names and Kotlin aliases while never
    descending into a nested generic argument.
    """
    type_names = _entity_type_names(item, entity)
    cursor = start
    while cursor < end:
        argument_start = cursor
        depth = 0
        while cursor < end:
            text = tokens[cursor].text
            if text == "<":
                depth += 1
            elif text == ">":
                depth = max(0, depth - 1)
            elif text == "," and depth == 0:
                break
            cursor += 1
        if _exact_entity_type_reference(tokens, argument_start, cursor, type_names):
            return True
        cursor += 1
    return False


def _exact_entity_type_reference(
    tokens: Sequence[Token], start: int, end: int, type_names: frozenset[str]
) -> bool:
    """Recognize one non-generic qualified type reference, including variance."""
    cursor = start
    if cursor < end and _identifier(tokens[cursor]) in {"in", "super"}:
        return False
    while cursor < end and _identifier(tokens[cursor]) in {"out", "extends"}:
        cursor += 1
    if cursor < end and tokens[cursor].text == "?":
        cursor += 1
        if cursor < end and _identifier(tokens[cursor]) == "super":
            return False
        while cursor < end and _identifier(tokens[cursor]) == "extends":
            cursor += 1
    parts: list[str] = []
    while cursor < end:
        name = _identifier(tokens[cursor])
        if not name:
            break
        parts.append(name)
        cursor += 1
        if cursor >= end or tokens[cursor].text != ".":
            break
        cursor += 1
    # Kotlin nullable type syntax does not change the referenced class.
    if cursor < end and tokens[cursor].text == "?":
        cursor += 1
    return bool(parts) and parts[-1] in type_names and cursor == end


def _matching_token_before(
    tokens: Sequence[Token], end: int, opener: str, closer: str
) -> int | None:
    if end < 0 or tokens[end].text != closer:
        return None
    depth = 0
    for index in range(end, -1, -1):
        if tokens[index].text == closer:
            depth += 1
        elif tokens[index].text == opener:
            depth -= 1
            if depth == 0:
                return index
    return None


def _assignment_target(tokens: Sequence[Token], equal_index: int) -> str:
    start = max(0, equal_index - 12)
    for cursor in range(equal_index - 1, start - 1, -1):
        name = _identifier(tokens[cursor])
        if name in {"val", "var"}:
            return next((
                _identifier(tokens[index])
                for index in range(cursor + 1, equal_index)
                if _identifier(tokens[index])
            ), "")
        if tokens[cursor].text in {";", "{", "}", "(", ")"}:
            break
    return _identifier(tokens[equal_index - 1]) if equal_index else ""


def _collection_expression_after(
    item: _SourceFile,
    tokens: Sequence[Token],
    start: int,
    collections: frozenset[str],
    collection_factories: frozenset[str],
    entity: EntityModel,
) -> bool:
    while start < len(tokens) and (
        _identifier(tokens[start]) == "new" or tokens[start].text == "("
    ):
        start += 1
    if start >= len(tokens):
        return False
    name = _identifier(tokens[start])
    callable_cursor = start + 1
    qualified_name = name
    while (
        callable_cursor + 1 < len(tokens)
        and tokens[callable_cursor].text == "."
        and _identifier(tokens[callable_cursor + 1])
    ):
        qualified_name += "." + _identifier(tokens[callable_cursor + 1])
        callable_cursor += 2
    if name in collections:
        return True
    if qualified_name in collection_factories:
        return callable_cursor < len(tokens) and tokens[callable_cursor].text == "("
    if start + 1 >= len(tokens) or tokens[start + 1].text != "<":
        return False
    close = _matching_token(tokens, start + 1, "<", ">")
    return close is not None and _direct_entity_type_argument(
        item, tokens, start + 2, close, entity
    )


def _entity_expression_after(
    item: _SourceFile,
    tokens: Sequence[Token],
    start: int,
    entity: EntityModel,
    variables: frozenset[str],
    collections: frozenset[str],
    collection_factories: frozenset[str],
    wrapper_collection_factories: frozenset[str],
    factory_keys: frozenset[tuple[str, str]],
) -> bool:
    while start < len(tokens) and (
        _identifier(tokens[start]) in {"new", "return"}
        or tokens[start].text == "("
    ):
        start += 1
    if start >= len(tokens):
        return False
    name = _identifier(tokens[start])
    if name in variables:
        return True
    if _collection_chain_returns_entity(
        tokens, start, collections, collection_factories,
        wrapper_collection_factories,
        item=item, entity=entity,
    ):
        return True
    parts: list[str] = []
    cursor = start
    while cursor < len(tokens):
        part = _identifier(tokens[cursor])
        if not part:
            break
        parts.append(part)
        cursor += 1
        if cursor >= len(tokens) or tokens[cursor].text != ".":
            break
        if (
            cursor + 1 < len(tokens)
            and tokens[cursor + 1].text == "<"
        ):
            close = _matching_token(tokens, cursor + 1, "<", ">")
            if close is None or close + 1 >= len(tokens):
                break
            method = _identifier(tokens[close + 1])
            if not method:
                break
            parts.append("<" + "".join(
                token.text for token in tokens[cursor + 2:close]
            ) + ">" + method)
            cursor = close + 2
            break
        cursor += 1
    if not parts or cursor >= len(tokens) or tokens[cursor].text != "(":
        return False
    callable_name = parts[-1]
    if callable_name == entity.class_name:
        fqcn = (
            (entity.package_name + "." if entity.package_name else "")
            + entity.class_name
        )
        return (
            len(parts) == 1 and _file_resolves_entity(item, entity)
        ) or ".".join(parts) == fqcn
    factory_name = ".".join(parts)
    return _factory_available(item, factory_name, factory_keys, entity)


def _entity_expression_before(
    item: _SourceFile,
    tokens: Sequence[Token],
    end: int,
    entity: EntityModel,
    variables: frozenset[str],
    collections: frozenset[str],
    collection_factories: frozenset[str],
    wrapper_collection_factories: frozenset[str],
    factory_keys: frozenset[tuple[str, str]],
) -> bool:
    if end < 0:
        return False
    last = tokens[end]
    name = _identifier(last)
    if name in variables:
        return True
    if name == entity.class_name and _file_resolves_entity(item, entity):
        return True
    start = _receiver_expression_start(tokens, end)
    if start is not None and _collection_chain_returns_entity(
        tokens, start, collections, collection_factories,
        wrapper_collection_factories,
        item=item, entity=entity,
        end=end,
    ):
        return True
    if start is not None and _contains_entity_cast(
        item, tokens, start, end, entity
    ):
        return True
    if last.text != ")":
        return False
    depth = 0
    open_index: int | None = None
    for cursor in range(end, -1, -1):
        if tokens[cursor].text == ")":
            depth += 1
        elif tokens[cursor].text == "(":
            depth -= 1
            if depth == 0:
                open_index = cursor
                break
    if open_index is None or open_index == 0:
        return False
    callable_name = _callable_name_before(tokens, open_index - 1)
    fqcn = (entity.package_name + "." if entity.package_name else "") + entity.class_name
    return (
        (
            callable_name == entity.class_name
            and _file_resolves_entity(item, entity)
        )
        or callable_name == fqcn
        or _factory_available(item, callable_name, factory_keys, entity)
    )


def _callable_name_before(tokens: Sequence[Token], terminal_index: int) -> str:
    """Return a dotted callable path ending at ``terminal_index``.

    Java permits explicit method type arguments between a receiver and the
    method name (``Provider.<Employee>load()``).  Skip that balanced region so
    factory resolution still sees the declaring class and can apply its normal
    visibility and overload checks.  An unmatched ``>`` is treated as unknown
    rather than guessing at a callable path.
    """
    if terminal_index < 0:
        return ""
    terminal_name = _identifier(tokens[terminal_index])
    if not terminal_name:
        return ""
    parts = [terminal_name]
    cursor = terminal_index - 1
    explicit_type_arguments = ""
    if cursor >= 0 and tokens[cursor].text == ">":
        type_open = _matching_token_before(tokens, cursor, "<", ">")
        if (
            type_open is None
            or type_open == 0
            or tokens[type_open - 1].text != "."
        ):
            return ""
        explicit_type_arguments = "<" + "".join(
            token.text for token in tokens[type_open + 1:cursor]
        ) + ">"
        cursor = type_open - 1
    while cursor >= 1 and tokens[cursor].text == ".":
        previous = _identifier(tokens[cursor - 1])
        if not previous:
            break
        parts.insert(0, previous)
        cursor -= 2
    result = ".".join(part for part in parts if part)
    if explicit_type_arguments:
        owner, method = result.rsplit(".", 1)
        result = owner + "." + explicit_type_arguments + method
    return result


def _contains_entity_cast(
    item: _SourceFile,
    tokens: Sequence[Token],
    start: int,
    end: int,
    entity: EntityModel,
) -> bool:
    """Fail closed for an explicit Java/Kotlin cast to this Entity.

    This is intentionally a narrow syntactic proof, not a full type resolver.
    If a cast identifies the Entity, retaining the old API is safer than
    making a type/signature edit based on incomplete source analysis.
    """
    type_names = _entity_type_names(item, entity)
    for cursor in range(start, end):
        if tokens[cursor].text == "(":
            close = _matching_token(tokens, cursor, "(", ")")
            if close is not None and close <= end and _exact_entity_type_reference(
                tokens, cursor + 1, close, type_names
            ):
                return True
        if item.language == "kotlin" and _identifier(tokens[cursor]) == "as":
            type_end = next((
                index for index in range(cursor + 1, end + 1)
                if tokens[index].text in {")", "]", "}", ".", "?", "!", ",", ";"}
            ), end + 1)
            if _exact_entity_type_reference(tokens, cursor + 1, type_end, type_names):
                return True
    return False


def _receiver_expression_start(tokens: Sequence[Token], end: int) -> int | None:
    depth = 0
    for cursor in range(end, -1, -1):
        text = tokens[cursor].text
        if text in {")", "]", "}"}:
            depth += 1
        elif text in {"(", "[", "{"}:
            depth -= 1
            if depth < 0:
                return cursor + 1
        elif depth == 0 and text in {";", "=", ",", "return", "->"}:
            return cursor + 1
    return 0


def _collection_chain_returns_entity(
    tokens: Sequence[Token],
    start: int,
    collections: frozenset[str],
    collection_factories: frozenset[str],
    generic_wrappers: frozenset[str],
    *,
    item: _SourceFile | None = None,
    entity: EntityModel | None = None,
    end: int | None = None,
) -> bool:
    limit = len(tokens) if end is None else end + 1
    if start >= limit:
        return False
    name = _identifier(tokens[start])
    cursor = start + 1
    qualified_name = name
    explicit_type_arguments: tuple[str, ...] | None = None
    if name not in collections:
        while (
            cursor + 1 < limit
            and tokens[cursor].text == "."
        ):
            if tokens[cursor + 1].text == "<":
                type_close = _matching_token(tokens, cursor + 1, "<", ">")
                if (
                    type_close is None
                    or type_close + 1 >= limit
                    or not _identifier(tokens[type_close + 1])
                ):
                    return False
                explicit_type_arguments = tuple(
                    token.text for token in tokens[cursor + 2:type_close]
                )
                qualified_name += "." + _identifier(tokens[type_close + 1])
                cursor = type_close + 2
                continue
            if not _identifier(tokens[cursor + 1]):
                return False
            qualified_name += "." + _identifier(tokens[cursor + 1])
            cursor += 2
    is_factory = qualified_name in collection_factories
    if (
        is_factory and explicit_type_arguments
        and item is not None and entity is not None
    ):
        explicit_state = _java_explicit_type_arguments_entity_state(
            item, ("".join(explicit_type_arguments),), entity
        )
        if explicit_state is False:
            return False
    if name not in collections and not is_factory:
        return False
    if is_factory and (
        cursor >= limit or tokens[cursor].text != "("
    ):
        return False
    if cursor < limit and tokens[cursor].text == "(":
        close = _matching_token(tokens, cursor, "(", ")")
        if close is None or close >= limit:
            return False
        cursor = close + 1
    collection_state = True
    wrapper_state = name in generic_wrappers or qualified_name in generic_wrappers
    iterator_state = False
    while cursor < limit:
        if tokens[cursor].text == "[":
            close = _matching_token(tokens, cursor, "[", "]")
            return bool(
                collection_state
                and close is not None
                and close < limit
                and (end is None or close + 1 == limit)
            )
        if tokens[cursor].text in {"?", "!"}:
            cursor += 1
            continue
        if tokens[cursor].text != "." or cursor + 1 >= limit:
            return False
        method = _identifier(tokens[cursor + 1])
        cursor += 2
        if cursor < limit and tokens[cursor].text == "(":
            close = _matching_token(tokens, cursor, "(", ")")
            if close is None or close >= limit:
                return False
            cursor = close + 1
        elif not (
            collection_state
            and method in {"filter", "filterNot"}
            and cursor < limit
            and tokens[cursor].text == "{"
        ):
            if not (collection_state and wrapper_state):
                return False
        if cursor < limit and tokens[cursor].text == "{":
            lambda_close = _matching_token(tokens, cursor, "{", "}")
            if lambda_close is None or lambda_close >= limit:
                return False
            cursor = lambda_close + 1
        if collection_state and method in {"get", "first", "single"}:
            return end is None or cursor == limit
        if collection_state and method == "iterator":
            collection_state = False
            iterator_state = True
            continue
        if iterator_state and method == "next":
            return end is None or cursor == limit
        if collection_state and method in {
            "filter", "filterNot", "subList",
        }:
            continue
        if collection_state and wrapper_state:
            return _entity_member_chain_end(tokens, cursor, limit, end)
        return False
    return False


def _entity_member_chain_end(
    tokens: Sequence[Token], cursor: int, limit: int, end: int | None
) -> bool:
    """Whether a direct-generic receiver has been unwrapped to its Entity.

    A generic class may expose its direct ``T`` through an arbitrary method or
    Kotlin property (``Optional<Employee>.orElseThrow()``,
    ``Box<Employee>.value``).  We cannot prove which members do that without a
    compiler type model.  For an API-changing Entity merge, conservatively
    treat the first member after a direct generic receiver as an unwrap; if the
    next member is the affected Entity member, block the change.  Nested
    generic arguments remain excluded by ``_direct_entity_type_argument``.
    """
    if end is None:
        return True
    if cursor == limit:
        return True
    while cursor < limit and tokens[cursor].text in {"?", "!"}:
        cursor += 1
    if cursor >= limit or tokens[cursor].text != ".":
        return False
    cursor += 1
    if cursor >= limit or not _identifier(tokens[cursor]):
        return False
    cursor += 1
    if cursor < limit and tokens[cursor].text == "(":
        close = _matching_token(tokens, cursor, "(", ")")
        if close is None or close >= limit:
            return False
        cursor = close + 1
    while cursor < limit and tokens[cursor].text in {"?", "!"}:
        cursor += 1
    return cursor == limit


def _has_typed_member_reference(
    item: _SourceFile,
    tokens: Sequence[Token],
    entity: EntityModel,
    member_names: set[str],
    factory_keys: frozenset[tuple[str, str]],
    typealias_keys: frozenset[tuple[str, str, bool]],
    wrapper_factory_keys: frozenset[tuple[str, str]] = frozenset(),
    collection_factory_keys: frozenset[tuple[str, str, bool]] = frozenset(),
) -> bool:
    variables = _typed_entity_variables(
        item, tokens, entity, factory_keys, typealias_keys, wrapper_factory_keys,
        collection_factory_keys,
    )
    collection_symbols = _entity_collection_symbols(
        item, tokens, entity, typealias_keys, wrapper_factory_keys,
        collection_factory_keys,
    )
    for index, token in enumerate(tokens):
        member = _identifier(token)
        if member not in member_names:
            continue
        if index >= 2 and tokens[index - 1].text == ".":
            receiver_end = _receiver_expression_end(tokens, index - 1)
            if _entity_expression_before(
                item, tokens, receiver_end, entity, variables,
                collection_symbols.names_at(receiver_end),
                collection_symbols.factories,
                collection_symbols.wrapper_names_at(receiver_end)
                | collection_symbols.wrapper_factories,
                factory_keys,
            ):
                return True
        if index >= 3 and tokens[index - 1].text == ":" and tokens[index - 2].text == ":":
            receiver_end = index - 3
            while receiver_end >= 0 and tokens[receiver_end].text == "!":
                receiver_end -= 1
            receiver = _identifier(tokens[receiver_end]) if receiver_end >= 0 else ""
            if _entity_expression_before(
                item, tokens, receiver_end, entity, variables,
                collection_symbols.names_at(receiver_end),
                collection_symbols.factories,
                collection_symbols.wrapper_names_at(receiver_end)
                | collection_symbols.wrapper_factories,
                factory_keys,
            ) or (
                receiver in _entity_type_names(item, entity)
                and _file_resolves_entity(item, entity)
            ):
                return True
    return False


def _range_has_receiver_member(
    tokens: Sequence[Token], start: int, end: int, member_names: set[str]
) -> bool:
    for index in range(start, end):
        if _identifier(tokens[index]) not in member_names:
            continue
        previous = tokens[index - 1].text if index > start else ""
        if previous not in {".", ":"}:
            return True
        if (
            previous == "."
            and index >= start + 2
            and _identifier(tokens[index - 2]) == "this"
        ):
            return True
        if (
            previous == "."
            and index >= start + 4
            and _identifier(tokens[index - 2])
            and tokens[index - 3].text == "@"
            and _identifier(tokens[index - 4]) == "this"
        ):
            return True
    return False


def _range_has_variable_member(
    tokens: Sequence[Token],
    start: int,
    end: int,
    variables: frozenset[str],
    member_names: set[str],
) -> bool:
    for index in range(start, end):
        if _identifier(tokens[index]) not in member_names:
            continue
        if index == 0 or tokens[index - 1].text != ".":
            continue
        receiver_end = _receiver_expression_end(tokens, index - 1)
        if receiver_end >= start and _identifier(tokens[receiver_end]) in variables:
            return True
    return False


def _lambda_parameter(
    tokens: Sequence[Token], body_start: int, body_end: int
) -> tuple[str, int]:
    for index in range(body_start + 1, min(body_end - 1, body_start + 16)):
        if tokens[index].text == "-" and tokens[index + 1].text == ">":
            parameter = next((
                _identifier(tokens[cursor])
                for cursor in range(body_start + 1, index)
                if _identifier(tokens[cursor])
            ), "")
            return parameter, index + 2
    return "it", body_start + 1


def _receiver_expression_end(tokens: Sequence[Token], operator_index: int) -> int:
    end = operator_index - 1
    while end >= 0 and tokens[end].text in {"?", "!"}:
        end -= 1
    return end


def _has_kotlin_receiver_scope_reference(
    item: _SourceFile,
    tokens: Sequence[Token],
    entity: EntityModel,
    member_names: set[str],
    factory_keys: frozenset[tuple[str, str]],
    typealias_keys: frozenset[tuple[str, str, bool]],
    wrapper_factory_keys: frozenset[tuple[str, str]] = frozenset(),
    collection_factory_keys: frozenset[tuple[str, str, bool]] = frozenset(),
) -> bool:
    variables = _typed_entity_variables(
        item, tokens, entity, factory_keys, typealias_keys, wrapper_factory_keys,
        collection_factory_keys,
    )
    collection_symbols = _entity_collection_symbols(
        item, tokens, entity, typealias_keys, wrapper_factory_keys,
        collection_factory_keys,
    )
    for index, token in enumerate(tokens):
        scope_name = _identifier(token)
        if (
            scope_name in {"apply", "run", "let", "also"}
            and index >= 2
            and tokens[index - 1].text == "."
        ):
            receiver_end = _receiver_expression_end(tokens, index - 1)
            if _entity_expression_before(
                item, tokens, receiver_end, entity, variables,
                collection_symbols.names_at(receiver_end),
                collection_symbols.factories,
                collection_symbols.wrapper_names_at(receiver_end)
                | collection_symbols.wrapper_factories,
                factory_keys,
            ):
                body_start = next((
                    cursor for cursor in range(
                        index + 1, min(len(tokens), index + 7)
                    )
                    if tokens[cursor].text == "{"
                ), None)
                if body_start is not None:
                    body_end = _matching_token(tokens, body_start, "{", "}")
                    if body_end is not None:
                        if scope_name in {"apply", "run"} and _range_has_receiver_member(
                            tokens, body_start + 1, body_end, member_names
                        ):
                            return True
                        if scope_name in {"let", "also"}:
                            parameter, lambda_start = _lambda_parameter(
                                tokens, body_start, body_end
                            )
                            if parameter and _range_has_variable_member(
                                tokens, lambda_start, body_end,
                                frozenset({parameter}), member_names,
                            ):
                                return True

        if _identifier(token) == "with" and index + 1 < len(tokens) and tokens[index + 1].text == "(":
            close = _matching_token(tokens, index + 1, "(", ")")
            if close is None or close <= index + 2:
                continue
            if not _entity_expression_before(
                item, tokens, close - 1, entity, variables,
                collection_symbols.names_at(close - 1),
                collection_symbols.factories,
                collection_symbols.wrapper_names_at(close - 1)
                | collection_symbols.wrapper_factories,
                factory_keys,
            ):
                continue
            body_start = close + 1
            if body_start >= len(tokens) or tokens[body_start].text != "{":
                continue
            body_end = _matching_token(tokens, body_start, "{", "}")
            if body_end is not None and _range_has_receiver_member(
                tokens, body_start + 1, body_end, member_names
            ):
                return True

        if _identifier(token) != "fun":
            continue
        open_index = next((
            cursor for cursor in range(index + 1, min(len(tokens), index + 32))
            if tokens[cursor].text == "("
        ), None)
        if open_index is None:
            continue
        receiver = any(
            _identifier(tokens[cursor]) in _entity_type_names(item, entity)
            and cursor + 1 < open_index
            and tokens[cursor + 1].text == "."
            for cursor in range(index + 1, open_index)
        )
        if not receiver or not _file_resolves_entity(item, entity):
            continue
        close = _matching_token(tokens, open_index, "(", ")")
        if close is None:
            continue
        body_start = next((
            cursor for cursor in range(close + 1, len(tokens))
            if tokens[cursor].text in {"=", "{"}
        ), None)
        if body_start is None:
            continue
        if tokens[body_start].text == "{":
            body_end = _matching_token(tokens, body_start, "{", "}")
            if body_end is None:
                continue
        else:
            body_end = _kotlin_expression_body_end(
                item.source, tokens, index, body_start
            )
        if _range_has_receiver_member(tokens, body_start + 1, body_end, member_names):
            return True
    return False


def _kotlin_expression_body_end(
    source: str,
    tokens: Sequence[Token],
    function_start: int,
    expression_start: int,
) -> int:
    """Return the token boundary for an expression-bodied Kotlin function.

    Kotlin permits the expression to start on a continuation line after `=`.
    Stop only at a following declaration at the function's brace and
    indentation level.  In uncertain source, scanning farther is deliberate:
    reference detection must fail closed rather than offer a destructive edit.
    """
    function_indent = _line_indent(source, tokens[function_start].span.start)
    baseline_depth = _brace_depth_at(tokens, function_start)
    for cursor in range(expression_start + 1, len(tokens)):
        if _brace_depth_at(tokens, cursor) != baseline_depth:
            continue
        if _line_indent(source, tokens[cursor].span.start) > function_indent:
            continue
        if _kotlin_declaration_starts_at(tokens, cursor):
            return cursor
    return len(tokens)


def _line_indent(source: str, offset: int) -> int:
    line_start = source.rfind("\n", 0, offset) + 1
    prefix = source[line_start:offset]
    return len(prefix) if prefix.strip(" \t") == "" else len(prefix)


def _brace_depth_at(tokens: Sequence[Token], end: int) -> int:
    depth = 0
    for token in tokens[:end]:
        if token.text == "{":
            depth += 1
        elif token.text == "}":
            depth -= 1
    return depth


def _kotlin_declaration_starts_at(tokens: Sequence[Token], index: int) -> bool:
    token = _identifier(tokens[index])
    if token in {"class", "interface", "object", "fun", "typealias", "val", "var"}:
        return True
    if tokens[index].text == "@":
        return True
    return token in {
        "public", "private", "protected", "internal", "open", "abstract", "final",
        "override", "suspend", "inline", "tailrec", "operator", "infix", "external",
        "expect", "actual", "data", "sealed", "enum", "annotation", "value",
    }


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
        if raw_table["remarks"] is not None and not isinstance(raw_table["remarks"], str):
            raise PlanInputError("invalid table remarks")
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
        tables.append(_Table(database, identity, raw_table, columns, primary_key))
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


def _validate_primary_key(
    value: object, columns: Sequence[dict[str, object]]
) -> tuple[dict[str, object], ...] | None:
    if value is None:
        return None
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


def _reference_source_roots(
    project_root: Path, selected_roots: Sequence[Path]
) -> tuple[Path, ...]:
    """Include conventional compiled test roots in the reference-only scan.

    The selected ``src/main`` roots remain the only Entity merge targets.  Test
    source sets are nevertheless compiled by Gradle's clean build and can bind
    an Entity accessor, so excluding them would make a proposed API change
    unsafe.  Keep the discovery inside ``src`` and list only conventional
    source-set names; generated output under ``build`` is never a reference.
    """
    roots = list(selected_roots)
    src = project_root / "src"
    for source_set in ("test", "integrationTest", "functionalTest", "testFixtures"):
        for language in ("java", "kotlin"):
            candidate = src / source_set / language
            if candidate.is_dir() and candidate not in roots:
                _reject_symlink_components(project_root, candidate)
                roots.append(candidate)
    return tuple(roots)


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


def _by_class(files: Sequence[_ParsedFile]) -> dict[tuple[str, str], tuple[_ParsedFile, ...]]:
    grouped: dict[tuple[str, str], list[_ParsedFile]] = {}
    for item in files:
        grouped.setdefault(_class_key(item.parsed.entity), []).append(item)
    return {key: tuple(items) for key, items in grouped.items()}


def _class_key(entity: EntityModel) -> tuple[str, str]:
    return entity.package_name, entity.class_name


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
