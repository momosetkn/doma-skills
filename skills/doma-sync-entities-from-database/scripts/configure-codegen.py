#!/usr/bin/env python3
"""Create and safely apply deterministic Doma CodeGen Gradle configuration plans."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal


EXIT_OK = 0
EXIT_CHANGES = 2
EXIT_INVALID = 64
EXIT_UNSAFE = 65
EXIT_STALE = 66
MARKER = "doma-sync-entities-from-database"
CREDENTIAL_URL_PATTERN = re.compile(r"jdbc:[^\s'\"]+://[^/@\s'\"]+@", re.IGNORECASE)


@dataclass(frozen=True)
class BuildSpan:
    start: int
    end: int


@dataclass(frozen=True)
class BuildSpec:
    project_root: Path
    build_file: Path
    dsl: Literal["kotlin", "groovy"]
    language: Literal["java", "kotlin"]
    database: Literal["postgresql", "mysql"]
    entity_package: str
    schema: str | None
    catalog: str | None
    table_pattern: str
    codegen_version: str
    driver_coordinate: str


@dataclass(frozen=True)
class TextEdit:
    start: int
    end: int
    replacement: str


@dataclass(frozen=True)
class FileMutation:
    path: str
    before_sha256: str
    after_sha256: str
    edits: tuple[TextEdit, ...]


@dataclass(frozen=True)
class ConfigurationPlan:
    format_version: int
    project_root: Literal["."]
    inputs: dict[str, str | None]
    mutations: tuple[FileMutation, ...]


class SafetyError(Exception):
    pass


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _scan_string(source: str, index: int) -> int:
    quote = source[index]
    if source.startswith(quote * 3, index):
        end = source.find(quote * 3, index + 3)
        return len(source) if end < 0 else end + 3
    index += 1
    while index < len(source):
        if source[index] == "\\":
            index += 2
        elif source[index] == quote:
            return index + 1
        else:
            index += 1
    return len(source)


def _scan_slashy(source: str, index: int) -> int:
    index += 1
    while index < len(source):
        if source[index] == "\\":
            index += 2
        elif source[index] == "/":
            return index + 1
        else:
            index += 1
    return len(source)


def _skip_non_code(source: str, index: int) -> int:
    if source.startswith("//", index):
        end = source.find("\n", index + 2)
        return len(source) if end < 0 else end + 1
    if source.startswith("/*", index):
        end = source.find("*/", index + 2)
        return len(source) if end < 0 else end + 2
    if source[index:index + 1] in {"'", '"'}:
        return _scan_string(source, index)
    if source[index:index + 1] == "/" and not source.startswith(("//", "/*"), index):
        return _scan_slashy(source, index)
    return index


def _balanced_end(source: str, brace: int) -> int | None:
    depth, index = 0, brace
    while index < len(source):
        skipped = _skip_non_code(source, index)
        if skipped != index:
            index = skipped
            continue
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return index + 1
            if depth < 0:
                return None
        index += 1
    return None


def _top_level_blocks(source: str, name: str) -> tuple[BuildSpan, ...]:
    """Return all unambiguous top-level Gradle blocks with the requested name."""
    depth, index = 0, 0
    blocks: list[BuildSpan] = []
    while index < len(source):
        skipped = _skip_non_code(source, index)
        if skipped != index:
            index = skipped
            continue
        char = source[index]
        if char == "{":
            depth += 1
            index += 1
            continue
        if char == "}":
            depth -= 1
            index += 1
            continue
        if depth == 0 and (char.isalpha() or char == "_"):
            end = index + 1
            while end < len(source) and (source[end].isalnum() or source[end] in "_-"):
                end += 1
            if source[index:end] == name:
                cursor = end
                while cursor < len(source) and source[cursor].isspace():
                    cursor += 1
                if cursor < len(source) and source[cursor] == "{":
                    block_end = _balanced_end(source, cursor)
                    if block_end is not None:
                        blocks.append(BuildSpan(index, block_end))
                        index = block_end
                        continue
            index = end
            continue
        index += 1
    return tuple(blocks)


def find_top_level_block(source: str, name: str) -> BuildSpan | None:
    """Return the first unambiguous top-level Gradle block with the requested name."""
    blocks = _top_level_blocks(source, name)
    return blocks[0] if blocks else None


def find_managed_region(source: str, region: str) -> BuildSpan | None:
    begin = f"// {MARKER}:{region}"
    end = f"// {MARKER}:end"
    starts = [match.start() for match in re.finditer(re.escape(begin), source)]
    ends = [match.end() for match in re.finditer(re.escape(end), source)]
    if not starts and not ends:
        return None
    if len(starts) != 1 or len(ends) != 1 or ends[0] <= starts[0]:
        raise SafetyError("managed configuration markers are incomplete or ambiguous")
    return BuildSpan(starts[0], ends[0])


def contains_dynamic_structure(source: str, span: BuildSpan) -> bool:
    body = source[span.start:span.end]
    return bool(
        re.search(r"\bid\s*\(\s*[^\s\"']", body)
        or re.search(r"\bdomaCodeGen\s*\(\s*[^\s\"']", body)
        or "${" in body
        or re.search(r"\bid\s+[^\s\"']", body)
    )


def _safe_child(root: Path, candidate: Path) -> Path:
    resolved_root = root.resolve()
    resolved = candidate.resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError:
        raise SafetyError("path resolves outside the project")
    return resolved


def _read_text(path: Path) -> str:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return handle.read()
    except UnicodeDecodeError:
        raise SafetyError("build inputs must be UTF-8 text")


def _has_secret_literal(project: Path, source: str) -> bool:
    if CREDENTIAL_URL_PATTERN.search(source):
        return True
    properties = project / "gradle.properties"
    if not properties.exists():
        return False
    if properties.is_symlink():
        raise SafetyError("gradle.properties symlink is unsafe")
    text = _read_text(properties)
    return bool(CREDENTIAL_URL_PATTERN.search(text)) or any(
        re.match(r"\s*(?:.*password.*|.*token.*|.*secret.*|.*aws.*key.*)\s*=", line, re.IGNORECASE)
        for line in text.splitlines()
    )


def _assert_supported_prerequisites(spec: BuildSpec, source: str) -> None:
    wrapper = spec.project_root / "gradle/wrapper/gradle-wrapper.properties"
    if wrapper.exists():
        if wrapper.is_symlink():
            raise SafetyError("Gradle wrapper properties symlink is unsafe")
        match = re.search(r"gradle-(\d+)(?:\.\d+)*(?:-[A-Za-z0-9]+)?\.zip", _read_text(wrapper))
        if match and int(match.group(1)) < 8:
            raise SafetyError("Gradle 8+ is required by Doma CodeGen")
    java_versions = [
        int(version)
        for pattern in (
            r"JavaLanguageVersion\.of\(\s*(\d+)",
            r"jvmToolchain\(\s*(\d+)",
            r"JavaVersion\.VERSION_(\d+)",
            r"jvmTarget\s*=\s*['\"]?(\d+)",
        )
        for version in re.findall(pattern, source)
    ]
    if java_versions and min(java_versions) < 17:
        raise SafetyError("Java 17+ is required by Doma CodeGen")


def _kotlin_managed(spec: BuildSpec, metamodel: bool) -> str:
    database_property = "schemaName" if spec.database == "postgresql" else "catalogName"
    database_value = spec.schema if spec.database == "postgresql" else spec.catalog
    language = "JAVA" if spec.language == "java" else "KOTLIN"
    return f'''// {MARKER}:begin
tasks.register("domaSyncWriteCodeGenClasspath") {{
    doLast {{
        file("build/doma-codegen/codegen-classpath.txt").apply {{
            parentFile.mkdirs()
            writeText(configurations.getByName("domaCodeGen").asPath)
        }}
    }}
}}
if (gradle.startParameter.taskNames.any {{ it.substringAfterLast(":").startsWith("domaCodeGenDomaSync") }}) {{
    domaCodeGen {{
        register("domaSync") {{
            val domaSyncJdbcUrl = providers.environmentVariable("DOMA_SYNC_JDBC_URL").orElse(providers.gradleProperty("domaSyncJdbcUrl")).map {{ jdbcUrl ->
                if (Regex("""jdbc:[^\\s]+://[^/@\\s]+@""", RegexOption.IGNORE_CASE).containsMatchIn(jdbcUrl)) {{
                    throw GradleException("Credential-bearing JDBC URL is unsafe")
                }}
                jdbcUrl
            }}
            url.set(domaSyncJdbcUrl)
            user.set(providers.environmentVariable("DOMA_SYNC_JDBC_USER").orElse(providers.gradleProperty("domaSyncJdbcUser")))
            password.set(providers.environmentVariable("DOMA_SYNC_JDBC_PASSWORD").orElse(providers.gradleProperty("domaSyncJdbcPassword")))
            sourceDir.set(layout.projectDirectory.dir("build/doma-codegen/generated"))
            languageType.set(org.seasar.doma.gradle.codegen.desc.LanguageType.{language})
            entity {{
                packageName.set("{spec.entity_package}")
                {database_property}.set("{database_value}")
                tableNamePattern.set("{spec.table_pattern}")
                showCatalogName.set({str(spec.database == "mysql").lower()})
                showSchemaName.set({str(spec.database == "postgresql").lower()})
                showTableName.set(true)
                showColumnName.set(true)
                showDbComment.set(true)
                overwrite.set(true)
                useListener.set(false)
                useMappedSuperclass.set(false)
                useMetamodel.set({str(metamodel).lower()})
            }}
        }}
    }}
}}
// {MARKER}:end'''


def _groovy_managed(spec: BuildSpec, metamodel: bool) -> str:
    database_property = "schemaName" if spec.database == "postgresql" else "catalogName"
    database_value = spec.schema if spec.database == "postgresql" else spec.catalog
    language = "JAVA" if spec.language == "java" else "KOTLIN"
    return f'''// {MARKER}:begin
tasks.register('domaSyncWriteCodeGenClasspath') {{
    doLast {{
        file('build/doma-codegen/codegen-classpath.txt').with {{
            parentFile.mkdirs()
            text = configurations.getByName('domaCodeGen').asPath
        }}
    }}
}}
if (gradle.startParameter.taskNames.any {{ it.tokenize(':').last().startsWith('domaCodeGenDomaSync') }}) {{
    domaCodeGen {{
        register('domaSync') {{
            def domaSyncJdbcUrl = providers.environmentVariable('DOMA_SYNC_JDBC_URL').orElse(providers.gradleProperty('domaSyncJdbcUrl')).map {{ jdbcUrl ->
                if (jdbcUrl =~ /(?i)jdbc:[^\\s]+:\\/\\/[^\\/@\\s]+@/) {{
                    throw new GradleException('Credential-bearing JDBC URL is unsafe')
                }}
                jdbcUrl
            }}
            url.set(domaSyncJdbcUrl)
            user.set(providers.environmentVariable('DOMA_SYNC_JDBC_USER').orElse(providers.gradleProperty('domaSyncJdbcUser')))
            password.set(providers.environmentVariable('DOMA_SYNC_JDBC_PASSWORD').orElse(providers.gradleProperty('domaSyncJdbcPassword')))
            sourceDir.set(layout.projectDirectory.dir('build/doma-codegen/generated'))
            languageType.set(org.seasar.doma.gradle.codegen.desc.LanguageType.{language})
            entity {{
                packageName.set('{spec.entity_package}')
                {database_property}.set('{database_value}')
                tableNamePattern.set('{spec.table_pattern}')
                showCatalogName.set({str(spec.database == "mysql").lower()})
                showSchemaName.set({str(spec.database == "postgresql").lower()})
                showTableName.set(true)
                showColumnName.set(true)
                showDbComment.set(true)
                overwrite.set(true)
                useListener.set(false)
                useMappedSuperclass.set(false)
                useMetamodel.set({str(metamodel).lower()})
            }}
        }}
    }}
}}
// {MARKER}:end'''


def _plugin_line(spec: BuildSpec) -> str:
    return f"    // {MARKER}:plugin\n    {_plugin_declaration(spec)}\n"


def _plugin_declaration(spec: BuildSpec) -> str:
    if spec.dsl == "kotlin":
        return f'id("org.domaframework.doma.codegen") version "{spec.codegen_version}"'
    return f"id 'org.domaframework.doma.codegen' version '{spec.codegen_version}'"


def _driver_line(spec: BuildSpec) -> str:
    return f"    // {MARKER}:driver\n    {_driver_declaration(spec)}\n"


def _driver_declaration(spec: BuildSpec) -> str:
    if spec.dsl == "kotlin":
        return f'domaCodeGen("{spec.driver_coordinate}")'
    return f"domaCodeGen '{spec.driver_coordinate}'"


def _add_to_block(source: str, span: BuildSpan | None, name: str, line: str) -> TextEdit:
    if span is None:
        return TextEdit(len(source), len(source), f"\n{name} {{\n{line}}}\n")
    return TextEdit(span.end - 1, span.end - 1, line)


def _is_code_position(source: str, position: int) -> bool:
    index = 0
    while index < len(source):
        skipped = _skip_non_code(source, index)
        if skipped != index:
            if index <= position < skipped:
                return False
            index = skipped
            continue
        if index == position:
            return True
        index += 1
    return False


def _matching_declarations(source: str, spec: BuildSpec, kind: Literal["plugin", "driver"]) -> list[re.Match[str]]:
    if kind == "plugin":
        pattern = (
            r'\bid\(\s*["\']org\.domaframework\.doma\.codegen["\']\s*\)\s*version\s*["\'][^"\']+["\']'
            r'|\bid\s+["\']org\.domaframework\.doma\.codegen["\']\s+version\s+["\'][^"\']+["\']'
        )
    elif spec.dsl == "kotlin":
        pattern = r'\bdomaCodeGen\s*\(\s*"[^"]+"\s*\)'
    else:
        pattern = r"\bdomaCodeGen\s+['\"][^'\"]+['\"]"
    matches = list(re.finditer(pattern, source))
    if kind != "plugin":
        return matches
    plugin_blocks = _top_level_blocks(source, "plugins")
    return [
        match
        for match in matches
        if _is_code_position(source, match.start())
        and any(block.start <= match.start() < block.end for block in plugin_blocks)
    ]


def _edits_for(spec: BuildSpec, source: str, metamodel: bool) -> tuple[TextEdit, ...]:
    if _has_secret_literal(spec.project_root, source):
        raise SafetyError("credential-bearing build configuration must be removed before planning")
    _assert_supported_prerequisites(spec, source)
    managed = find_managed_region(source, "begin")
    if "domaSync" in source and managed is None:
        raise SafetyError("unmanaged domaSync configuration is ambiguous")
    plugin_blocks = _top_level_blocks(source, "plugins")
    dependency_blocks = _top_level_blocks(source, "dependencies")
    plugins = plugin_blocks[0] if plugin_blocks else None
    dependencies = dependency_blocks[0] if dependency_blocks else None
    for span in (*plugin_blocks, *dependency_blocks):
        if span is not None and contains_dynamic_structure(source, span):
            raise SafetyError("dynamic Gradle plugin or dependency structure is unsafe")
    edits: list[TextEdit] = []
    plugin_matches = _matching_declarations(source, spec, "plugin")
    if len(plugin_matches) > 1:
        raise SafetyError("multiple Doma CodeGen plugin declarations are ambiguous")
    if not plugin_matches:
        edits.append(_add_to_block(source, plugins, "plugins", _plugin_line(spec)))
    elif plugin_matches[0].group() != _plugin_declaration(spec):
        match = plugin_matches[0]
        edits.append(TextEdit(match.start(), match.end(), _plugin_declaration(spec)))
    driver_matches = _matching_declarations(source, spec, "driver")
    if len(driver_matches) > 1:
        raise SafetyError("multiple domaCodeGen driver declarations are ambiguous")
    if not driver_matches:
        edits.append(_add_to_block(source, dependencies, "dependencies", _driver_line(spec)))
    elif driver_matches[0].group() != _driver_declaration(spec):
        match = driver_matches[0]
        edits.append(TextEdit(match.start(), match.end(), _driver_declaration(spec)))
    rendered = _kotlin_managed(spec, metamodel) if spec.dsl == "kotlin" else _groovy_managed(spec, metamodel)
    newline = "\r\n" if "\r\n" in source else "\n"
    rendered_for_source = rendered.replace("\n", newline)
    if managed is None:
        edits.append(TextEdit(len(source), len(source), "\n" + rendered + "\n"))
    elif source[managed.start:managed.end] != rendered_for_source:
        edits.append(TextEdit(managed.start, managed.end, rendered))
    normalized_edits = tuple(
        TextEdit(edit.start, edit.end, edit.replacement.replace("\n", newline)) for edit in edits
    )
    return tuple(sorted(normalized_edits, key=lambda edit: (edit.start, edit.end), reverse=True))


def _apply_edits(source: str, edits: tuple[TextEdit, ...]) -> str:
    output = source
    latest = len(source) + 1
    for edit in edits:
        if edit.end > latest or edit.start > edit.end:
            raise SafetyError("overlapping configuration edits")
        output = output[:edit.start] + edit.replacement + output[edit.end:]
        latest = edit.start
    return output


def _spec_from_args(args: argparse.Namespace) -> BuildSpec:
    root = Path(args.project_root).resolve()
    if not root.is_dir():
        raise ValueError("project root must be a directory")
    kotlin, groovy = root / "build.gradle.kts", root / "build.gradle"
    if kotlin.exists() and groovy.exists():
        raise SafetyError("both Gradle DSL build files are present")
    if kotlin.exists():
        build, dsl = kotlin, "kotlin"
    elif groovy.exists():
        build, dsl = groovy, "groovy"
    else:
        raise ValueError("project needs build.gradle.kts or build.gradle")
    if build.is_symlink():
        raise SafetyError("build file symlink is unsafe")
    if args.database == "postgresql" and not args.schema:
        raise ValueError("PostgreSQL requires --schema")
    if args.database == "mysql" and not args.catalog:
        raise ValueError("MySQL requires --catalog")
    if args.schema and args.catalog:
        raise ValueError("use only --schema or --catalog")
    return BuildSpec(root, build, dsl, args.language, args.database, args.entity_package,
                     args.schema, args.catalog, args.table_pattern, args.codegen_version,
                     args.driver_coordinate)


def _plan_for(spec: BuildSpec, metamodel: bool) -> ConfigurationPlan:
    source = _read_text(spec.build_file)
    edits = _edits_for(spec, source, metamodel)
    after = _apply_edits(source, edits)
    mutations: tuple[FileMutation, ...] = ()
    if after != source:
        mutations = (FileMutation(spec.build_file.name, sha256(source), sha256(after), edits),)
    return ConfigurationPlan(1, ".", {
        "language": spec.language, "database": spec.database, "entity_package": spec.entity_package,
        "schema": spec.schema, "catalog": spec.catalog, "table_pattern": spec.table_pattern,
        "codegen_version": spec.codegen_version, "driver_coordinate": spec.driver_coordinate,
        "metamodel": str(metamodel).lower(),
    }, mutations)


def _plan_json(plan: ConfigurationPlan) -> str:
    return json.dumps(asdict(plan), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.is_symlink():
        raise SafetyError("refusing to write through a symlink")
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=str(path.parent), delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    temporary.replace(path)


def _cmd_plan(args: argparse.Namespace) -> int:
    spec = _spec_from_args(args)
    plan = _plan_for(spec, args.metamodel == "true")
    output = _safe_child(spec.project_root, spec.project_root / args.output_plan)
    _atomic_write(output, _plan_json(plan))
    return EXIT_CHANGES if plan.mutations else EXIT_OK


def _cmd_apply(args: argparse.Namespace) -> int:
    root = Path(args.project_root).resolve()
    if not root.is_dir():
        raise ValueError("project root must be a directory")
    plan_path = _safe_child(root, Path(args.plan) if Path(args.plan).is_absolute() else root / args.plan)
    data = json.loads(_read_text(plan_path))
    if data.get("format_version") != 1 or data.get("project_root") != ".":
        raise ValueError("unsupported configuration plan")
    pending: list[tuple[Path, str]] = []
    for mutation in data.get("mutations", []):
        path = _safe_child(root, root / mutation["path"])
        if path.is_symlink() or not path.is_file() or sha256(_read_text(path)) != mutation["before_sha256"]:
            return EXIT_STALE
        edits = tuple(TextEdit(**edit) for edit in mutation["edits"])
        updated = _apply_edits(_read_text(path), edits)
        if sha256(updated) != mutation["after_sha256"]:
            raise ValueError("plan replacement hash is invalid")
        pending.append((path, updated))
    for path, updated in pending:
        _atomic_write(path, updated)
    return EXIT_OK


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan")
    plan.add_argument("--project-root", required=True)
    plan.add_argument("--language", choices=("java", "kotlin"), required=True)
    plan.add_argument("--database", choices=("postgresql", "mysql"), required=True)
    plan.add_argument("--entity-package", required=True)
    plan.add_argument("--schema")
    plan.add_argument("--catalog")
    plan.add_argument("--table-pattern", required=True)
    plan.add_argument("--codegen-version", required=True)
    plan.add_argument("--driver-coordinate", required=True)
    plan.add_argument("--metamodel", choices=("true", "false"), required=True)
    plan.add_argument("--output-plan", required=True)
    apply = commands.add_parser("apply")
    apply.add_argument("--project-root", required=True)
    apply.add_argument("--plan", required=True)
    return parser


def main() -> int:
    try:
        args = _parser().parse_args()
        return _cmd_plan(args) if args.command == "plan" else _cmd_apply(args)
    except SafetyError as error:
        print(str(error), file=sys.stderr)
        return EXIT_UNSAFE
    except (ValueError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return EXIT_INVALID


if __name__ == "__main__":
    raise SystemExit(main())
