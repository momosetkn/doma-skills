# Doma Database-to-Entity Synchronization Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an installable `doma-sync-entities-from-database` skill that permanently configures Doma CodeGen in an existing Gradle project, snapshots selected PostgreSQL/MySQL metadata, generates Java/Kotlin entity candidates outside source roots, and safely synchronizes existing entities without losing application semantics or exposing credentials.

**Architecture:** Use a token-aware Python configurator to add one idempotent `domaSync` Gradle configuration, a Bash wrapper to resolve local/AWS credentials and invoke the workflow, a Java 17 JDBC metadata helper to preserve physical database facts, and a Python structural merge engine with separate plan/apply phases. Keep public workflow guidance concise in `SKILL.md`, route detail to eight direct references, and prove the implementation with deterministic unit tests, four clean-build Gradle fixtures, optional Testcontainers integration, AWS stubs, copied-install validation, and trigger-boundary evaluations.

**Tech Stack:** Agent Skills Markdown/YAML, Python 3 standard library, Bash, Java 17 source-file launch, JDBC `DatabaseMetaData`, Doma `3.14.1-SNAPSHOT` research baseline, released Doma `3.14.0` fixture baseline, Doma CodeGen Plugin `3.2.2`, Gradle `9.4.1` compatibility fixture, PostgreSQL JDBC `42.7.10`, MySQL Connector/J `26.7.0`, Kotlin/JVM and KAPT `2.3.20`, Testcontainers `2.0.4`, AWS CLI v2, Git, and `npx skills`.

## Global Constraints

- Work only in the existing `feature/doma-sync-entities-from-database` worktree and preserve all unrelated user changes.
- Support only Gradle Kotlin DSL and Gradle Groovy DSL; Maven is excluded.
- Support Java and Kotlin Doma entities for PostgreSQL and MySQL, including local, Docker Compose, RDS, Aurora, and RDS Proxy connections.
- Treat bundled Doma `3.14.1-SNAPSHOT` only as the research baseline and use released, versioned dependencies in executable fixtures.
- Preserve compatible target-project versions; never upgrade Gradle, Java, Kotlin, Doma, CodeGen, or JDBC dependencies implicitly.
- Require Java 17 and Gradle 8 or later for CodeGen Plugin `3.2.2`; report incompatible projects without rewriting their toolchain.
- Permanently add or repair CodeGen configuration in the target's existing `build.gradle` or `build.gradle.kts`; never create a disposable Gradle project for a real synchronization run.
- Run official entity generation through `domaCodeGenDomaSyncEntity` and write candidates only under `build/doma-codegen/generated`.
- Never add the candidate directory to a production source set or point CodeGen at `src/main/java` or `src/main/kotlin`.
- Keep generation, plan, and apply as separate operations.
- Treat the JDBC schema snapshot as authoritative for physical schema facts and the generated source as authoritative for Doma's candidate language mapping.
- Treat exact, unambiguous single and composite primary-key `@Id` synchronization as `SAFE`; apply the complete key atomically.
- Never auto-delete an entity or property; emit a `REVIEW_REQUIRED` patch and require its exact proposal ID.
- Preserve Domain types, custom annotations, `@Transient`, `@Association`, `@Embedded`, Metamodel settings, handwritten methods, inheritance, interfaces, formatting, line endings, and unrelated imports.
- Never infer property/class renames, Domain adoption/removal, `@Version`, or `@TenantId` from database metadata alone.
- Never run DDL, DML, a database CLI, an AWS resource mutation command, or an unscoped AWS inventory command.
- Resolve connection inputs in order: environment, user-home Gradle properties, then AWS profile/execution role.
- Permit Secrets Manager `GetSecretValue` only for the exact approved Secret immediately before generation; never put a password, Secret value, IAM token, access key, or credential-bearing JDBC URL in source, Gradle files, command-line arguments, repository files, plans, logs, reports, or responses.
- Use `--no-daemon` for every Gradle process that receives a password or IAM token.
- Keep the installed skill self-contained; never require root source bundles, `prisma-skills.md`, another installed skill, or repository-only tests.
- Use `apply_patch` for repository file edits, TDD for production scripts, and a focused commit after each completed task.

---

## File Map

- Create `skills/doma-sync-entities-from-database/SKILL.md`: trigger boundary, prerequisites, ordered workflow, approval gates, verification, exclusions, and reference routing.
- Create `skills/doma-sync-entities-from-database/agents/openai.yaml`: Codex UI metadata matching existing skills.
- Create `skills/doma-sync-entities-from-database/references/supported-projects.md`: Gradle/language/version/source-layout detection and routing.
- Create `skills/doma-sync-entities-from-database/references/database-connections.md`: local, Docker, RDS/Aurora, and Proxy input contracts.
- Create `skills/doma-sync-entities-from-database/references/codegen-configuration.md`: verified Plugin `3.2.2` configuration and task behavior for both DSLs.
- Create `skills/doma-sync-entities-from-database/references/entity-merge-rules.md`: normalized model, database authority, `SAFE`, `REVIEW_REQUIRED`, `BLOCKED`, plan, and approval rules.
- Create `skills/doma-sync-entities-from-database/references/java-entity-merge.md`: Java parsing, edits, generated-only detection, and fail-closed cases.
- Create `skills/doma-sync-entities-from-database/references/kotlin-entity-merge.md`: Kotlin parsing, nullability, body/constructor properties, and fail-closed cases.
- Create `skills/doma-sync-entities-from-database/references/aws-security.md`: exact-target discovery, Secrets Manager, IAM tokens, Proxy behavior, allowlist, and redaction.
- Create `skills/doma-sync-entities-from-database/references/troubleshooting.md`: layered failures and recovery.
- Create `skills/doma-sync-entities-from-database/scripts/configure-codegen.py`: deterministic Gradle inspection, plan, and idempotent apply.
- Create `skills/doma-sync-entities-from-database/scripts/generate-entities.sh`: local/AWS input resolution, masking, metadata snapshot, and CodeGen invocation.
- Create `skills/doma-sync-entities-from-database/scripts/schema-snapshot.java`: deterministic JDBC metadata manifest generator.
- Create `skills/doma-sync-entities-from-database/scripts/compare-and-merge-entities.py`: public plan/apply CLI.
- Create `skills/doma-sync-entities-from-database/scripts/entity_sync/__init__.py`: internal package boundary and format version constants.
- Create `skills/doma-sync-entities-from-database/scripts/entity_sync/model.py`: immutable normalized model and plan dataclasses.
- Create `skills/doma-sync-entities-from-database/scripts/entity_sync/lexer.py`: shared Java/Kotlin lexical states, tokens, and source spans.
- Create `skills/doma-sync-entities-from-database/scripts/entity_sync/java_parser.py`: conservative Java entity parser.
- Create `skills/doma-sync-entities-from-database/scripts/entity_sync/kotlin_parser.py`: conservative Kotlin entity parser.
- Create `skills/doma-sync-entities-from-database/scripts/entity_sync/planner.py`: snapshot/candidate/existing comparison and deterministic findings.
- Create `skills/doma-sync-entities-from-database/scripts/entity_sync/applier.py`: stale-plan checks and atomic source edits.
- Create `tests/doma-sync-entities-from-database/test-configure-codegen.py`: Gradle DSL mutation and idempotence tests.
- Create `tests/doma-sync-entities-from-database/test-schema-snapshot.py`: fixture JDBC metadata and manifest tests.
- Create `tests/doma-sync-entities-from-database/test-generate-wrapper.py`: local/AWS wrapper and redaction tests.
- Create `tests/doma-sync-entities-from-database/test-source-model.py`: Java/Kotlin lexer/parser tests.
- Create `tests/doma-sync-entities-from-database/test-entity-merge.py`: planning, SAFE, review, blocked, apply, and determinism tests.
- Create `tests/doma-sync-entities-from-database/test-security.py`: artifact, command, URL, plan, and output secret-leak tests.
- Create `tests/doma-sync-entities-from-database/test-install.sh`: copied-install and installed-script tests.
- Create `tests/doma-sync-entities-from-database/run-compile-fixtures.sh`: mandatory four-fixture clean-build runner.
- Create `tests/doma-sync-entities-from-database/run-testcontainers.sh`: optional real PostgreSQL/MySQL metadata and CodeGen runner.
- Create `tests/doma-sync-entities-from-database/fixtures/fixture-jdbc/FixtureJdbcDriver.java`: dynamic-proxy JDBC driver for deterministic metadata tests.
- Create `tests/doma-sync-entities-from-database/fixtures/java-kotlin-dsl-postgresql/**`: Java/Kotlin-DSL PostgreSQL build fixture.
- Create `tests/doma-sync-entities-from-database/fixtures/kotlin-kotlin-dsl-postgresql/**`: Kotlin/Kotlin-DSL PostgreSQL build fixture.
- Create `tests/doma-sync-entities-from-database/fixtures/java-groovy-dsl-mysql/**`: Java/Groovy-DSL MySQL build fixture.
- Create `tests/doma-sync-entities-from-database/fixtures/kotlin-groovy-dsl-mysql/**`: Kotlin/Groovy-DSL MySQL build fixture.
- Create `tests/doma-sync-entities-from-database/fixtures/generated-candidates/**`: deterministic official-template-shaped candidates.
- Create `tests/doma-sync-entities-from-database/fixtures/schema-snapshots/**`: deterministic credential-free PostgreSQL/MySQL manifests.
- Create `tests/doma-sync-entities-from-database/fixtures/aws-stubs/**`: sanitized instance, cluster, Proxy, Secret, and IAM fixtures.
- Create `tests/doma-sync-entities-from-database/fixtures/secret-redaction/**`: sentinel output fixtures.
- Modify `README.md`: catalog entry, support matrix, safety model, Secret handling, install commands, and invocation examples.

### Task 1: Re-verify Sources and Establish RED Behavior

**Files:**
- Read: `docs/superpowers/specs/2026-08-03-doma-sync-entities-from-database-design.md`
- Read: `skills/doma-setup-project/SKILL.md`
- Read: `skills/doma-setup-kotlin-project/SKILL.md`
- Read from sibling worktree: `../doma-connect-aws-rds/skills/doma-connect-aws-rds/SKILL.md`
- Read narrow ranges from: root `doma-project-bundle-1.md` through `doma-project-bundle-4.md`
- Temporary output only: a fresh `mktemp -d` source-note and evaluation directory

**Interfaces:**
- Consumes: the approved design, repository `AGENTS.md`, official Doma/Gradle/AWS/JDBC sources, and the current branch.
- Produces: a source-note matrix, exact compatible release matrix, RED prompt evidence, and frozen CLI decisions supplied to Tasks 2-8.

- [ ] **Step 1: Confirm the branch and clean boundary**

Run:

```bash
git status --short --branch
git log -3 --oneline
git diff --cached --name-only
```

Expected: branch `feature/doma-sync-entities-from-database`, design commits `30b2fb0` and `a47ef53`, no staged or unstaged implementation changes.

- [ ] **Step 2: Re-read the authoring and implementation disciplines**

Read completely:

```text
/home/momose/.codex/skills/.system/skill-creator/SKILL.md
/home/momose/.codex/plugins/cache/openai-curated-remote/superpowers/6.2.0/skills/writing-skills/SKILL.md
/home/momose/.codex/plugins/cache/openai-curated-remote/superpowers/6.2.0/skills/test-driven-development/SKILL.md
```

Carry their validation, RED/GREEN, trigger-testing, and self-contained-install rules through every later task.

- [ ] **Step 3: Freeze current released versions from primary sources**

Verify and record this matrix with access date `2026-08-08`:

```text
Doma release fixture:              3.14.0
Doma source research baseline:     3.14.1-SNAPSHOT
Doma CodeGen Plugin:               3.2.2
CodeGen-tested Gradle fixture:      9.4.1
CodeGen-tested Kotlin fixture:      2.3.20
PostgreSQL JDBC:                    42.7.10
MySQL Connector/J:                 26.7.0
Testcontainers:                    2.0.4
Minimum Java:                      17
```

Use the Doma and CodeGen GitHub releases, CodeGen `v3.2.2` version catalog/wrapper, official Gradle distribution checksum, MySQL Connector/J documentation plus Maven Central publication metadata, and official PostgreSQL JDBC publication metadata. If a coordinate has been withdrawn or is incompatible, stop and amend this plan rather than substituting a guessed version.

Record Gradle `9.4.1` distribution SHA-256 exactly:

```text
2ab2958f2a1e51120c326cad6f385153bb11ee93b3c216c5fccebfdfbb7ec6cb
```

- [ ] **Step 4: Gather narrow Doma/CodeGen source notes**

Locate exact bundled headings and upstream `v3.2.2` files for:

```text
docs/codegen.md
CodeGenPlugin
CodeGenConfig
EntityConfig
CodeGenEntityTask
TableMetaReader
ColumnMeta
EntityDesc
EntityPropertyDesc
Java and Kotlin entity.ftl
```

For each exact claim, record source path, symbol/section, and implementation consequence. Include task naming, `afterEvaluate` validation, `Property<String>` connection inputs, `DirectoryProperty` output, default overwrite/listener/metamodel/mapped-superclass behavior, JDBC metadata/comment reads, Kotlin nullable generation, and the absence of native SQL type names from generated entities.

- [ ] **Step 5: Capture RED trigger behavior without the new skill**

Use fresh sessions for the four positive prompts in the approved design. Save output only in the temporary evaluation directory. Mark failures under:

```markdown
| Prompt | Retrieval failure | Application failure | Boundary failure | Secret/safety failure |
| --- | --- | --- | --- | --- |
```

Expected RED evidence: generic behavior directly overwrites source, uses text diff only, cannot report native SQL types, guesses a CodeGen task/configuration, loses Domain/handwritten code, lacks proposal approval, or mishandles AWS credentials.

- [ ] **Step 6: Capture negative-boundary behavior**

Run the six negative prompts from the design. The finished skill must route schema creation/migration, slow-query/index work, DAO/SQL generation, provisioning, and unapproved property deletion without performing them.

- [ ] **Step 7: Freeze public CLI contracts**

Record these exact commands in the Task 1 handoff:

```bash
python3 skills/doma-sync-entities-from-database/scripts/configure-codegen.py plan \
  --project-root . --language java --database postgresql \
  --entity-package com.example.entity --schema public \
  --table-pattern 'tenant_.*' --codegen-version 3.2.2 \
  --driver-coordinate org.postgresql:postgresql:42.7.10 \
  --metamodel true --output-plan build/doma-codegen/configure-plan.json
python3 skills/doma-sync-entities-from-database/scripts/configure-codegen.py apply \
  --project-root . --language java --database postgresql \
  --entity-package com.example.entity --schema public \
  --table-pattern 'tenant_.*' --codegen-version 3.2.2 \
  --driver-coordinate org.postgresql:postgresql:42.7.10 \
  --metamodel true --plan build/doma-codegen/configure-plan.json
skills/doma-sync-entities-from-database/scripts/generate-entities.sh --project-root . --connection local --database postgresql
python3 skills/doma-sync-entities-from-database/scripts/compare-and-merge-entities.py plan \
  --project-root . --schema-snapshot build/doma-codegen/schema-snapshot.json \
  --generated-dir build/doma-codegen/generated --existing-root src/main/java \
  --language java --output-plan build/doma-codegen/merge-plan.json \
  --output-diff build/doma-codegen/merge.diff
python3 skills/doma-sync-entities-from-database/scripts/compare-and-merge-entities.py apply --plan build/doma-codegen/merge-plan.json
python3 skills/doma-sync-entities-from-database/scripts/compare-and-merge-entities.py apply --plan build/doma-codegen/merge-plan.json --approve DB-REMOVE-001
```

Do not edit or commit repository files in Task 1.

### Task 2: Initialize the Skill and Implement Idempotent Gradle Configuration with TDD

**Files:**
- Create: `skills/doma-sync-entities-from-database/SKILL.md`
- Create: `skills/doma-sync-entities-from-database/agents/openai.yaml`
- Create: `skills/doma-sync-entities-from-database/scripts/configure-codegen.py`
- Create: `tests/doma-sync-entities-from-database/test-configure-codegen.py`
- Create: minimal Gradle build inputs under `tests/doma-sync-entities-from-database/fixtures/gradle-config/`

**Interfaces:**
- Consumes: Task 1 version matrix and CodeGen `afterEvaluate` behavior.
- Produces: `configure-codegen.py` with deterministic `plan` and `apply` subcommands, plan format version `1`, managed Gradle fragments, and the permanent `domaSyncWriteCodeGenClasspath` helper task used by Tasks 3-4.

- [ ] **Step 1: Initialize the skill once**

Run from the worktree root:

```bash
python3 /home/momose/.codex/skills/.system/skill-creator/scripts/init_skill.py \
  doma-sync-entities-from-database \
  --path skills \
  --resources references,scripts \
  --interface 'display_name=Sync Doma Entities from Database' \
  --interface 'short_description=Generate and safely merge Java or Kotlin Doma entities' \
  --interface 'default_prompt=Use $doma-sync-entities-from-database to generate Doma entity candidates from this database and apply only structurally safe changes.'
```

Delete initializer example files with `apply_patch`. Do not run the initializer twice.

- [ ] **Step 2: Make the initial skill identity valid**

Use this exact frontmatter:

```yaml
---
name: doma-sync-entities-from-database
description: Use when configuring Doma CodeGen in an existing Java or Kotlin Gradle project to generate entities from PostgreSQL/MySQL, compare them structurally with existing entities, and apply only safe database-authoritative changes without overwriting handwritten code.
---
```

The temporary body must already state the supported project prerequisite, isolated output rule, plan/apply separation, and exclusions. Do not link references until they exist.

- [ ] **Step 3: Write failing Gradle configuration tests**

Create tests using only `unittest`, `tempfile`, `subprocess`, and `pathlib`. Establish a helper with this signature:

```python
def run_configurator(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CONFIGURATOR), *args, "--project-root", str(project)],
        text=True,
        capture_output=True,
        check=False,
    )
```

Add named tests for:

```text
test_kotlin_dsl_plan_contains_plugin_dependency_provider_block_and_temp_output
test_groovy_dsl_plan_contains_plugin_dependency_provider_block_and_temp_output
test_apply_then_plan_is_byte_identical_and_returns_no_change
test_existing_plugin_and_driver_are_not_duplicated
test_existing_managed_doma_sync_block_is_repaired
test_unmanaged_ambiguous_doma_sync_block_stops_without_write
test_dynamic_plugins_block_stops_without_write
test_project_gradle_properties_secret_key_stops_without_echoing_value
test_ordinary_build_guard_is_present
test_codegen_task_registration_guard_is_present
test_classpath_writer_is_credential_independent
test_stale_configuration_plan_is_rejected
```

Use sentinel `S3CR3T-CONFIG-FIXTURE` and assert it never appears in stdout, stderr, or a generated plan.

- [ ] **Step 4: Run the focused tests to prove RED**

Run:

```bash
python3 -m unittest tests/doma-sync-entities-from-database/test-configure-codegen.py -v
```

Expected: FAIL because `configure-codegen.py` and its interfaces do not exist.

- [ ] **Step 5: Define immutable configuration types and exit categories**

Implement these exact public Python types:

```python
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
```

The plan stores only relative paths, hashes, non-secret inputs, and replacement fragments owned by the configurator. It must not copy the complete existing build file into JSON. Proposal output uses zero-context diffs and the script stops before planning when it detects a credential literal in a build/configuration input.

Use exit `0` for no change/applied, `2` for a valid plan containing changes, `64` for invalid inputs, `65` for unsafe/ambiguous project state, and `66` for stale apply input.

- [ ] **Step 6: Implement token-aware Gradle block discovery**

Scan strings, escaped strings, Kotlin triple-quoted strings, Groovy slashy strings, line/block comments, and balanced braces. Expose:

```python
def find_top_level_block(source: str, name: str) -> BuildSpan | None: ...
def find_managed_region(source: str, region: str) -> BuildSpan | None: ...
def contains_dynamic_structure(source: str, span: BuildSpan) -> bool: ...
```

Never modify a block whose brace boundary or plugin/dependency expression is ambiguous.

- [ ] **Step 7: Render exact Kotlin and Groovy managed behavior**

The generated configuration must include:

```text
CodeGen plugin id org.domaframework.doma.codegen
domaCodeGen dependency using the explicit driver coordinate
environmentVariable(...).orElse(gradleProperty(...)) providers
generic rejection of credential-bearing JDBC URLs without echoing the URL
task-name guard for domaCodeGenDomaSync
register("domaSync")
build/doma-codegen/generated sourceDir
LanguageType.JAVA or LanguageType.KOTLIN
explicit schema/catalog and table pattern
entity overwrite true
listener and mapped-superclass generation false
inspected Metamodel policy
domaSyncWriteCodeGenClasspath writing build/doma-codegen/codegen-classpath.txt
```

Use stable comments:

```text
// doma-sync-entities-from-database:plugin
// doma-sync-entities-from-database:driver
// doma-sync-entities-from-database:begin
// doma-sync-entities-from-database:end
```

Register `domaSync` only when `gradle.startParameter.taskNames` contains a basename starting with `domaCodeGenDomaSync`. Register the classpath writer outside that guard. Never render a password, token, Secret ID value, AWS key, or credential-bearing URL.

- [ ] **Step 8: Implement deterministic plan and stale-safe apply**

Use these CLI options for `plan`:

```text
--project-root
--language java|kotlin
--database postgresql|mysql
--entity-package
--schema or --catalog
--table-pattern
--codegen-version
--driver-coordinate
--metamodel true|false
--output-plan
```

Require `--schema` for PostgreSQL and `--catalog` for MySQL. Write canonical UTF-8 JSON with `sort_keys=True`, two-space indentation, and a final newline. `apply` accepts only `--project-root` and `--plan`, verifies every before-hash and target path, writes atomically, and never follows a symlink outside the project.

- [ ] **Step 9: Run GREEN tests and syntax validation**

Run:

```bash
python3 -m py_compile skills/doma-sync-entities-from-database/scripts/configure-codegen.py
python3 -m unittest tests/doma-sync-entities-from-database/test-configure-codegen.py -v
python3 /home/momose/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  skills/doma-sync-entities-from-database
git diff --check -- skills/doma-sync-entities-from-database \
  tests/doma-sync-entities-from-database
```

Expected: all focused tests pass and the initial skill validates.

- [ ] **Step 10: Commit the configurator**

```bash
git add -- skills/doma-sync-entities-from-database \
  tests/doma-sync-entities-from-database/test-configure-codegen.py \
  tests/doma-sync-entities-from-database/fixtures/gradle-config
git commit -m "feat: configure Doma entity synchronization"
```

### Task 3: Implement the JDBC Schema Snapshot Helper with TDD

**Files:**
- Create: `skills/doma-sync-entities-from-database/scripts/schema-snapshot.java`
- Create: `tests/doma-sync-entities-from-database/test-schema-snapshot.py`
- Create: `tests/doma-sync-entities-from-database/fixtures/fixture-jdbc/FixtureJdbcDriver.java`
- Create: `tests/doma-sync-entities-from-database/fixtures/fixture-jdbc/META-INF/services/java.sql.Driver`

**Interfaces:**
- Consumes: Task 2 classpath file location and Task 1 Java/JDBC baseline.
- Produces: manifest format version `1` at `DOMA_CODEGEN_SCHEMA_SNAPSHOT`, containing sorted physical metadata and no connection identity or secret material.

- [ ] **Step 1: Write the manifest contract in a failing test**

Assert this exact top-level shape:

```json
{
  "format_version": 1,
  "database": "postgresql",
  "scope": {"catalog": null, "schema": "public", "table_pattern": "tenant_.*"},
  "tables": []
}
```

Each table contains sorted `catalog`, `schema`, `name`, `type`, `remarks`, `primary_key`, and `columns`. Each column contains `name`, `ordinal`, `jdbc_type`, `type_name`, `size`, `scale`, `nullable`, `default`, `auto_increment`, and `remarks`. The primary key contains ordered `name`, `column`, and `sequence` values.

- [ ] **Step 2: Build the fixture JDBC driver**

Implement `FixtureJdbcDriver` with Java dynamic proxies for `Connection`, `DatabaseMetaData`, and `ResultSet`. It must:

```text
accept jdbc:fixture:postgresql and jdbc:fixture:mysql
record calls to getTables, getColumns, and getPrimaryKeys
throw AssertionError from createStatement, prepareStatement, prepareCall, and every mutation method
return deliberately unsorted tables, columns, and primary-key rows
return optional null metadata in one fixture row
include sentinel host/user/password strings only in the connection inputs and thrown exception source
```

Package it as a service-loaded driver JAR during the test setup.

- [ ] **Step 3: Add RED tests**

Cover:

```text
test_postgresql_snapshot_is_sorted_and_complete
test_mysql_catalog_filter_is_used_instead_of_schema
test_primary_key_sequence_is_numeric_and_stable
test_unknown_optional_metadata_is_json_null
test_table_regex_filters_after_metadata_read
test_output_is_byte_identical_on_second_run
test_credential_bearing_url_is_rejected_without_echo
test_manifest_and_errors_do_not_contain_connection_sentinels
test_no_statement_or_mutating_connection_method_is_called
test_output_path_outside_build_directory_is_rejected
```

- [ ] **Step 4: Run RED**

```bash
python3 -m unittest tests/doma-sync-entities-from-database/test-schema-snapshot.py -v
```

Expected: FAIL because `schema-snapshot.java` does not exist.

- [ ] **Step 5: Implement environment parsing and URL rejection**

The helper reads only:

```text
DOMA_CODEGEN_DB_URL
DOMA_CODEGEN_DB_USER
DOMA_CODEGEN_DB_PASSWORD
DOMA_CODEGEN_DB_KIND=postgresql|mysql
DOMA_CODEGEN_DB_SCHEMA
DOMA_CODEGEN_DB_CATALOG
DOMA_CODEGEN_TABLE_PATTERN
DOMA_CODEGEN_SCHEMA_SNAPSHOT
DOMA_CODEGEN_PROJECT_ROOT
```

Reject missing required values, JDBC URL user-info, password/token query parameters, NUL/control characters, an invalid regex, a snapshot path outside the resolved project root's `build/doma-codegen` directory, and a PostgreSQL/MySQL URL-family mismatch. Error messages name only the field and reason.

- [ ] **Step 6: Implement metadata reads and canonical JSON**

Use a package-private top-level `final class SchemaSnapshot` so the lower-kebab `schema-snapshot.java` filename works in Java source-file mode. Use only:

```java
DriverManager.getConnection(url, properties)
metadata.getTables(catalog, schemaPattern, "%", new String[] {"TABLE"})
metadata.getColumns(catalog, schemaPattern, tableName, "%")
metadata.getPrimaryKeys(catalog, schema, tableName)
```

Filter table names with the compiled Java regex after reading metadata. Sort tables by catalog/schema/name, columns by ordinal/name, and primary-key entries by sequence/column. Implement a small JSON writer with full control-character escaping and atomic `Files.move` from a sibling temporary file. Do not depend on a JSON library.

- [ ] **Step 7: Run GREEN and source-file launch checks**

```bash
python3 -m unittest tests/doma-sync-entities-from-database/test-schema-snapshot.py -v
javac -Xlint:all -d "$(mktemp -d)" \
  skills/doma-sync-entities-from-database/scripts/schema-snapshot.java
```

Also run the helper through `java --class-path fixture-driver.jar schema-snapshot.java`, not only through `javac`.

- [ ] **Step 8: Commit the snapshot helper**

```bash
git add -- skills/doma-sync-entities-from-database/scripts/schema-snapshot.java \
  tests/doma-sync-entities-from-database/test-schema-snapshot.py \
  tests/doma-sync-entities-from-database/fixtures/fixture-jdbc
git commit -m "feat: snapshot database schema metadata"
```

### Task 4: Implement Secure Local and AWS Generation with TDD

**Files:**
- Create: `skills/doma-sync-entities-from-database/scripts/generate-entities.sh`
- Create: `tests/doma-sync-entities-from-database/test-generate-wrapper.py`
- Create: `tests/doma-sync-entities-from-database/fixtures/aws-stubs/fake-aws`
- Create: `tests/doma-sync-entities-from-database/fixtures/aws-stubs/fake-gradlew`
- Create: sanitized JSON fixtures under `tests/doma-sync-entities-from-database/fixtures/aws-stubs/`

**Interfaces:**
- Consumes: Task 2 Gradle tasks and Task 3 helper/environment contract.
- Produces: `generate-entities.sh` supporting `local`, `aws-secret`, and `aws-iam`, with exact-target AWS discovery, short-lived credentials, redacted output, metadata manifest, and candidate generation.

- [ ] **Step 1: Write failing wrapper tests with a controlled PATH**

Build each test environment with fake `aws`, `java`, and `gradlew` executables first on `PATH`. Log command names and non-secret arguments only. Tests must include:

```text
test_local_environment_values_win_over_user_gradle_properties
test_user_gradle_properties_are_used_when_environment_is_absent
test_missing_local_credentials_stop_before_java_or_gradle
test_project_wrapper_is_preferred_and_path_gradle_is_safe_fallback
test_project_gradle_properties_secret_stops_before_generation
test_aws_identity_mismatch_stops_before_rds_and_secret_calls
test_exact_rds_instance_secret_flow
test_exact_aurora_cluster_iam_flow
test_proxy_target_engine_is_resolved_before_connection
test_secret_host_cannot_redirect_confirmed_rds_target
test_iam_token_is_generated_for_confirmed_endpoint_user_and_region
test_classpath_snapshot_and_entity_tasks_run_with_no_daemon
test_secret_and_token_sentinels_are_redacted_from_both_streams
test_no_secret_appears_in_child_argv_or_call_log
test_generated_candidate_containing_secret_sentinel_is_removed_and_fails
test_output_paths_outside_project_build_are_rejected
test_aws_mutation_and_database_cli_commands_never_run
```

- [ ] **Step 2: Run RED**

```bash
python3 -m unittest tests/doma-sync-entities-from-database/test-generate-wrapper.py -v
```

Expected: FAIL because the wrapper does not exist.

- [ ] **Step 3: Implement argument and environment contracts**

Support these exact options:

```text
--project-root PATH
--connection local|aws-secret|aws-iam
--database postgresql|mysql
--expected-account 12_DIGITS
--region AWS_REGION
--target-kind instance|cluster|proxy
--target-id RDS_IDENTIFIER
--profile AWS_PROFILE
--secret-id RDS_SECRET_ID
--db-name DB_NAME
--db-user DB_USER
```

Reject password, token, access-key, Secret value, or JDBC URL command-line options. Require the AWS-specific targeting set only for AWS modes. Validate region and resource IDs before any AWS call.

- [ ] **Step 4: Resolve local values in the required priority**

Read `DOMA_CODEGEN_DB_URL`, `DOMA_CODEGEN_DB_USER`, and `DOMA_CODEGEN_DB_PASSWORD` from the environment first. Otherwise parse only the named `domaCodegenDbUrl`, `domaCodegenDbUser`, and `domaCodegenDbPassword` keys from `${GRADLE_USER_HOME:-$HOME/.gradle}/gradle.properties` without `source` or `eval`.

Scan the target Gradle build tree for project-local secret keys and stop with a field-name-only error. Reject embedded credentials in the resolved URL.

- [ ] **Step 5: Implement exact-target AWS discovery**

Use arrays and an allowlisted dispatcher. The only allowed calls are:

```text
sts get-caller-identity
rds describe-db-instances
rds describe-db-clusters
rds describe-db-proxies
rds describe-db-proxy-targets
secretsmanager describe-secret
secretsmanager get-secret-value
rds generate-db-auth-token
```

Confirm account first. Describe only the exact target. Resolve every Proxy target to its exact instance or cluster and require a single supported engine family. Build a credential-free TLS-verifying JDBC URL from the confirmed endpoint, port, database, and selected family. Do not trust Secret host/port/engine routing fields.

- [ ] **Step 6: Implement Secret and IAM lifetimes**

For `aws-secret`, describe and retrieve only the explicit Secret immediately before child processes. Accept JSON `username` and `password`; use an explicitly selected `dbname` only when it matches `--db-name`. Reject SecretBinary, missing fields, newlines/NUL, and target-routing conflicts.

For `aws-iam`, call `generate-db-auth-token` immediately before snapshot/CodeGen for the confirmed endpoint, port, region, and DB user. Keep the token only in a shell variable and child environment. Disable tracing and install a trap that unsets every secret-bearing variable.

- [ ] **Step 7: Implement redacted child execution**

Resolve Gradle as an argument array: prefer an executable `gradlew` in the selected project, then an explicitly supplied non-secret `GRADLE_CMD`, then a `gradle` executable on `PATH`. Reject a command containing shell metacharacters and never execute it through `eval` or `sh -c`.

Run in order:

```text
"${gradle_command[@]}" --no-daemon domaSyncWriteCodeGenClasspath
java --class-path "$codegen_classpath" "$script_dir/schema-snapshot.java"
"${gradle_command[@]}" --no-daemon domaCodeGenDomaSyncEntity
```

The first Gradle process needs no DB credentials. The Java and second Gradle processes receive credentials through environment variables only. Pipe both output streams through a Python standard-library streaming redactor whose sentinel values arrive through environment variables, not argv. Preserve the failing child exit status with `set -o pipefail`.

After snapshot and generation, scan the manifest and generated candidate tree for the actual password/token values and known credential patterns without printing a match. If a match exists, remove only the validated `build/doma-codegen/generated` and `schema-snapshot.json` outputs, emit a generic security failure, and do not start comparison.

- [ ] **Step 8: Run GREEN, syntax, and forbidden-command checks**

```bash
bash -n skills/doma-sync-entities-from-database/scripts/generate-entities.sh
python3 -m unittest tests/doma-sync-entities-from-database/test-generate-wrapper.py -v
! rg -n 'create-db-|modify-db-|delete-db-|failover-db-|restore-db-|rotate-secret|psql|mysql[[:space:]]' \
  skills/doma-sync-entities-from-database/scripts/generate-entities.sh
if command -v shellcheck >/dev/null; then
  shellcheck skills/doma-sync-entities-from-database/scripts/generate-entities.sh
fi
```

- [ ] **Step 9: Commit the secure wrapper**

```bash
git add -- skills/doma-sync-entities-from-database/scripts/generate-entities.sh \
  tests/doma-sync-entities-from-database/test-generate-wrapper.py \
  tests/doma-sync-entities-from-database/fixtures/aws-stubs
git commit -m "feat: generate Doma entities from safe database inputs"
```

### Task 5: Implement Java and Kotlin Structural Models with TDD

**Files:**
- Create: `skills/doma-sync-entities-from-database/scripts/entity_sync/__init__.py`
- Create: `skills/doma-sync-entities-from-database/scripts/entity_sync/model.py`
- Create: `skills/doma-sync-entities-from-database/scripts/entity_sync/lexer.py`
- Create: `skills/doma-sync-entities-from-database/scripts/entity_sync/java_parser.py`
- Create: `skills/doma-sync-entities-from-database/scripts/entity_sync/kotlin_parser.py`
- Create: `tests/doma-sync-entities-from-database/test-source-model.py`
- Create: parser fixtures under `tests/doma-sync-entities-from-database/fixtures/source-model/`

**Interfaces:**
- Consumes: official Java/Kotlin CodeGen templates and Doma annotation definitions from Task 1.
- Produces: immutable `EntityModel` instances with exact source spans and explicit unsupported-feature findings used by Task 6.

- [ ] **Step 1: Define model tests before implementation**

Use these exact core dataclasses:

```python
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
```

- [ ] **Step 2: Add RED lexer/parser cases**

Cover Java and Kotlin strings, escaped strings, character literals, text blocks/triple strings, line/block/KDoc/Javadoc comments, annotations with nested arguments, generics, arrays, nullable markers, imports, `@Entity`, `@Table`, and fields/body properties.

Add explicit tests for:

```text
official Java CodeGen class with fields and generated accessors
official Kotlin CodeGen class with body vars
single and composite @Id
@GeneratedValue, @Version, @TenantId, @Transient, @Association
@Domain declaration and Domain-typed property
@Embeddable and @Embedded
custom class/property annotations
handwritten methods and initializers
superclass and interfaces
Kotlin primary-constructor property and data class
Java record and Lombok annotation
duplicate column mappings
CRLF and final-newline preservation
```

- [ ] **Step 3: Run RED**

```bash
python3 -m unittest tests/doma-sync-entities-from-database/test-source-model.py -v
```

Expected: FAIL because the model and parsers do not exist.

- [ ] **Step 4: Implement the shared lexer**

Emit tokens with kind, decoded-free raw text, and absolute `SourceSpan`. Never evaluate annotations or source expressions. Preserve comments and whitespace as spans so edits can retain untouched bytes.

Expose:

```python
def lex_java(source: str) -> tuple[Token, ...]: ...
def lex_kotlin(source: str) -> tuple[Token, ...]: ...
def balanced_region(tokens: Sequence[Token], start: int, opener: str, closer: str) -> SourceSpan: ...
```

- [ ] **Step 5: Implement conservative Java parsing**

Parse one top-level Doma entity class per file. Resolve imports for Doma annotations and project Domain types. Recognize official generated getter/setter shapes exactly. Mark records, Lombok-dependent members, multiple top-level entities, ambiguous annotations, anonymous/nested edit targets, and unmatched spans as unsupported.

- [ ] **Step 6: Implement conservative Kotlin parsing**

Parse official body `var` properties and detect primary-constructor `val`/`var` properties without editing them. Normalize `T?` nullability. Mark data classes, delegated properties, destructuring, custom accessors, complex constructor changes, ambiguous annotations, and unmatched spans as unsupported for automatic edits.

- [ ] **Step 7: Classify generated-only source**

Set `generated_only=True` only when the class contains official-template-shaped fields/body properties, recognized CodeGen comments, and recognized generated Java accessors, with no custom annotation, handwritten method, initializer, inheritance/interface change, constructor property, record/data-class behavior, or unsupported syntax. Unknown means handwritten, never generated-only.

- [ ] **Step 8: Run GREEN and module syntax checks**

```bash
python3 -m py_compile skills/doma-sync-entities-from-database/scripts/entity_sync/*.py
python3 -m unittest tests/doma-sync-entities-from-database/test-source-model.py -v
```

- [ ] **Step 9: Commit the structural parsers**

```bash
git add -- skills/doma-sync-entities-from-database/scripts/entity_sync \
  tests/doma-sync-entities-from-database/test-source-model.py \
  tests/doma-sync-entities-from-database/fixtures/source-model
git commit -m "feat: parse Java and Kotlin Doma entities"
```

### Task 6: Implement Deterministic Planning and Safe Apply with TDD

**Files:**
- Create: `skills/doma-sync-entities-from-database/scripts/entity_sync/planner.py`
- Create: `skills/doma-sync-entities-from-database/scripts/entity_sync/applier.py`
- Create: `skills/doma-sync-entities-from-database/scripts/compare-and-merge-entities.py`
- Create: `tests/doma-sync-entities-from-database/test-entity-merge.py`
- Create: `tests/doma-sync-entities-from-database/test-security.py`
- Create: merge fixtures under `tests/doma-sync-entities-from-database/fixtures/generated-candidates/` and `fixtures/schema-snapshots/`

**Interfaces:**
- Consumes: Task 3 manifest format and Task 5 `EntityModel`.
- Produces: merge plan format version `1`, stable finding/proposal IDs, deterministic diff, `SAFE` apply, explicitly approved review apply, stale-plan rejection, and result states.

- [ ] **Step 1: Define finding and edit contracts in failing tests**

Use:

```python
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
```

Derive IDs from `status`, `kind`, normalized table, column, and path through SHA-256, rendered as a readable prefix plus the first 12 lowercase hex characters. Never use time, traversal order, random values, or absolute machine-specific paths.

- [ ] **Step 2: Add all required RED merge cases**

Test:

```text
new Java and Kotlin entity creation
new body property insertion
@Column addition and unambiguous correction
database comment Javadoc/KDoc addition without replacing handwritten docs
strict non-narrowing basic-type update in generated-only source
new-property nullability
single @Id addition/removal
composite @Id addition/removal as one atomic SAFE finding
@GeneratedValue only with matching auto-increment metadata and candidate
Metamodel, custom annotation, method, inheritance, interface, and formatting preservation
Domain/basic mismatch BLOCKED with options
existing Kotlin nullability REVIEW_REQUIRED
removed column REVIEW_REQUIRED with executable deletion only for generated-shaped members
removed column BLOCKED when handwritten code refers to it
Kotlin primary constructor/data class BLOCKED
Java record/Lombok/custom-template BLOCKED
type narrowing REVIEW_REQUIRED or BLOCKED according to source use
table/schema/class/property rename inference BLOCKED
@Version and @TenantId inference BLOCKED
duplicate or embedded mapping BLOCKED
file-level skip when edit/import ranges interact with a blocked finding
same input produces identical JSON, IDs, and diff
second complete run produces no source diff
```

- [ ] **Step 3: Run RED**

```bash
python3 -m unittest tests/doma-sync-entities-from-database/test-entity-merge.py -v
```

Expected: FAIL because the planner, applier, and CLI do not exist.

- [ ] **Step 4: Implement manifest validation and three-way matching**

Load canonical JSON and reject unknown format versions, missing fields, duplicate table/column identities, out-of-scope tables, invalid primary-key sequence, path traversal, and mismatched database family. Match:

```text
schema snapshot table identity -> generated @Table identity -> existing @Table identity
schema snapshot column identity -> generated @Column/property -> existing @Column/property
```

Do not use class/file/property-name similarity as proof of a rename.

- [ ] **Step 5: Implement the `SAFE` classifier**

Encode a closed allowlist. Apply complete primary-key membership atomically only when every key column is uniquely mapped and only `@Id` spans change. Keep basic-type widening in an explicit mapping table and require generated-only source plus a project reference scan that finds no incompatible use. New entities and properties must have unambiguous package/source roots and no path/column collision.

- [ ] **Step 6: Implement review proposals and blocked reports**

Create executable delete edits only for generated-shaped property/accessor spans with no handwritten reference. Every review proposal includes database facts, existing source excerpt, generated candidate excerpt, unified diff, impact, exact approval ID, and manual action. A blocked finding has no executable edits but includes concrete options.

- [ ] **Step 7: Implement source-preserving edits**

Group edits by file, reject overlaps, apply spans in descending offset order, and preserve encoding, BOM absence/presence, LF/CRLF, final newline, permissions, and untouched bytes. Insert imports according to the existing group/order; remove an import after an approved deletion only when the parser proves it is unused.

- [ ] **Step 8: Implement public CLI and stale-safe apply**

`plan` accepts:

```text
--project-root
--schema-snapshot
--generated-dir
--existing-root (repeatable)
--language java|kotlin|auto
--output-plan
--output-diff
```

`apply` accepts:

```text
--project-root
--plan
--approve FINDING_ID (repeatable)
```

Apply all executable `SAFE` findings by default. Apply only explicitly approved executable review findings. Before the first write, verify every snapshot/source/generated hash, Git status, real path, plan version, and approval ID. Write all target temporaries first, then atomically replace; on preparation failure replace none.

Exit `0` for `SUCCESS`, `2` for `PENDING_REVIEW`, `3` for `BLOCKED`, `64` for input misuse, `65` for unsafe project state, `66` for stale plan, and `1` for operational failure.

- [ ] **Step 9: Add security regression tests**

Seed manifest, source, generated files, stdout/stderr fixtures, and exceptions with distinct URL, user, password, token, access-key, and Secret sentinels. Assert no plan, diff, report, file, stdout, or stderr contains them. Assert the tool never writes outside existing roots or through a symlink escape.

- [ ] **Step 10: Run GREEN and the combined deterministic suite**

```bash
python3 -m py_compile \
  skills/doma-sync-entities-from-database/scripts/compare-and-merge-entities.py \
  skills/doma-sync-entities-from-database/scripts/entity_sync/*.py
python3 -m unittest \
  tests/doma-sync-entities-from-database/test-source-model.py \
  tests/doma-sync-entities-from-database/test-entity-merge.py \
  tests/doma-sync-entities-from-database/test-security.py -v
```

- [ ] **Step 11: Commit the merge engine**

```bash
git add -- skills/doma-sync-entities-from-database/scripts/compare-and-merge-entities.py \
  skills/doma-sync-entities-from-database/scripts/entity_sync \
  tests/doma-sync-entities-from-database/test-entity-merge.py \
  tests/doma-sync-entities-from-database/test-security.py \
  tests/doma-sync-entities-from-database/fixtures/generated-candidates \
  tests/doma-sync-entities-from-database/fixtures/schema-snapshots
git commit -m "feat: safely plan and merge Doma entity changes"
```

### Task 7: Build Four Compile Fixtures and Real Metadata Integration

**Files:**
- Create: `tests/doma-sync-entities-from-database/run-compile-fixtures.sh`
- Create: `tests/doma-sync-entities-from-database/run-testcontainers.sh`
- Create: all four fixture directories and their Gradle/source/resource files
- Modify only for integration-proven defects: scripts and tests from Tasks 2-6

**Interfaces:**
- Consumes: complete runtime scripts and Task 1 release matrix.
- Produces: mandatory four-fixture clean-build evidence, actual Doma annotation-processing evidence, idempotence evidence, and optional real PostgreSQL/MySQL CodeGen/metadata evidence.

- [ ] **Step 1: Create the Java/Kotlin-DSL/PostgreSQL fixture**

Use Java 17, Doma `3.14.0`, Doma CodeGen `3.2.2`, PostgreSQL JDBC `42.7.10`, and Gradle Kotlin DSL. Include an existing `Customer.java` with a handwritten method and a generated candidate/snapshot that adds one column and synchronizes a composite key. Add a DAO so `clean build` proves Doma annotation processing.

- [ ] **Step 2: Create the Kotlin/Kotlin-DSL/PostgreSQL fixture**

Use Kotlin/KAPT `2.3.20`, Java 17, Doma `3.14.0`, and the same PostgreSQL/CodeGen versions. Include a body-property entity with handwritten KDoc/method and a separate data-class fixture that must remain blocked. Add a DAO and assert generated implementation output.

- [ ] **Step 3: Create the Java/Groovy-DSL/MySQL fixture**

Use Java 17, Doma `3.14.0`, CodeGen `3.2.2`, MySQL Connector/J `26.7.0`, and Groovy DSL. Include an existing Domain-typed property that remains unchanged, plus a safe new column in another entity. Add a DAO and MySQL catalog snapshot.

- [ ] **Step 4: Create the Kotlin/Groovy-DSL/MySQL fixture**

Use Kotlin/KAPT `2.3.20`, Java 17, Doma `3.14.0`, CodeGen `3.2.2`, MySQL Connector/J `26.7.0`, and Groovy DSL. Include a safe body property, custom annotation, Metamodel setting, and handwritten method that must survive byte-for-byte outside edit ranges.

- [ ] **Step 5: Implement the mandatory fixture runner**

Use an existing `GRADLE_CMD` when supplied. Otherwise download `gradle-9.4.1-bin.zip` into a fresh `mktemp -d`, verify SHA-256 `2ab2958f2a1e51120c326cad6f385153bb11ee93b3c216c5fccebfdfbb7ec6cb`, and extract it outside the repository.

For each copied fixture:

```text
configure plan -> configure apply -> configure plan with no change
merge plan -> merge apply -> clean build
assert Doma generated DAO implementation exists
rerun merge plan and assert empty diff
compare handwritten source slices against expected fixtures
assert build/doma-codegen/generated is outside source roots
run clean build again without DB credentials
```

- [ ] **Step 6: Run all four fixtures and fix only proven failures**

```bash
bash tests/doma-sync-entities-from-database/run-compile-fixtures.sh
```

Expected: four named PASS results, zero build failures, annotation-generated DAO outputs present, handwritten code preserved, and second-run diffs empty.

- [ ] **Step 7: Implement Testcontainers integration**

Use Testcontainers `2.0.4` PostgreSQL and MySQL modules through disposable Gradle fixture builds. For each engine:

```text
create schema and comments with an administrator container init script
create a distinct read-only metadata user
configure the real CodeGen JDBC dependencies
run schema-snapshot.java using the resolved CodeGen classpath
run domaCodeGenDomaSyncEntity
assert SQL type, size, nullable, comments, auto-increment, and composite key metadata
assert the read-only user cannot execute INSERT, UPDATE, DELETE, CREATE, ALTER, or DROP
merge candidates and compile Java/Kotlin outputs
```

Do not require AWS credentials. If Docker is unavailable, exit `77` and print one `SKIP: Docker unavailable` line.

- [ ] **Step 8: Run the integration layer when Docker is available**

```bash
bash tests/doma-sync-entities-from-database/run-testcontainers.sh
```

Record PASS or the explicit exit-77 skip. Never convert a real failure into a skip.

- [ ] **Step 9: Commit fixtures and integration fixes**

```bash
git add -- tests/doma-sync-entities-from-database \
  skills/doma-sync-entities-from-database/scripts
git commit -m "test: verify Doma entity synchronization fixtures"
```

### Task 8: Author the Complete Skill, References, README, and Behavioral Evaluations

**Files:**
- Modify: `skills/doma-sync-entities-from-database/SKILL.md`
- Modify: `skills/doma-sync-entities-from-database/agents/openai.yaml`
- Create: all eight reference files from the File Map
- Modify: `README.md`
- Create: `tests/doma-sync-entities-from-database/test-install.sh`
- Modify only for observed evaluation defects: implementation/test files from Tasks 2-7

**Interfaces:**
- Consumes: verified scripts, CLI behavior, source notes, compile/integration evidence, and RED prompt outputs.
- Produces: a concise self-contained public skill, complete catalog/discovery content, copied-install proof, and GREEN trigger-boundary evidence.

- [ ] **Step 1: Write `SKILL.md` as the ordered controller**

Keep the body procedural and route details directly. It must contain:

```text
existing-project and annotation-processing prerequisite
supported Gradle/language/database gate
Git status and target-file cleanliness gate
explicit schema/table and connection-mode confirmation
configuration plan/diff/apply
metadata snapshot and official entity-only generation
structural plan with SAFE/REVIEW_REQUIRED/BLOCKED
exact proposal-ID approval
Git diff, clean build, annotation-processing, and idempotence verification
required final report
Maven/migration/DAO/performance/provisioning exclusions
```

Link every reference and script directly and state when to read or run it.

- [ ] **Step 2: Author project and connection references**

`supported-projects.md` must define both DSLs, Java/Kotlin source roots, multi-project selection, Gradle 8+/Java 17 compatibility, existing Doma/KAPT/AP inspection, and fail-closed unsupported shapes.

`database-connections.md` must define local/Docker, direct RDS/Aurora, and Proxy inputs, PostgreSQL schema versus MySQL catalog, explicit table filters, credential-free URL rules, and read-only user recommendations.

- [ ] **Step 3: Author CodeGen configuration guidance from executable templates**

`codegen-configuration.md` must explain Plugin `3.2.2`, task-name construction, the `afterEvaluate` missing-input problem, the conditional `domaSync` registration, custom classpath helper task, Provider priority, temporary output, language/metamodel/listener/mapped-superclass choices, and both DSL examples copied from the tested renderer.

Mark `domaCodeGenDomaSyncEntity` as official and `domaSyncWriteCodeGenClasspath` as skill-managed.

- [ ] **Step 4: Author merge policy and language references**

`entity-merge-rules.md` must define snapshot/generated/existing authority, normalized identities, exact SAFE gates including composite keys, review proposals and approval IDs, blocked application semantics, hashes, atomic edits, result states, and complete conflict/proposal report shape.

`java-entity-merge.md` and `kotlin-entity-merge.md` must document only behavior actually exercised by tests. Include Java generated accessors/records/Lombok and Kotlin body/constructor/data-class/nullability distinctions.

- [ ] **Step 5: Author AWS security and troubleshooting**

`aws-security.md` must include exact account/region/target confirmation, the allowlist, Secret retrieval constraints, token lifetime, Proxy target resolution, endpoint authority, child-environment handling, `--no-daemon`, masking, no AWS mutations, and no DDL/DML.

`troubleshooting.md` must stop at the first failed layer: project, Git, Gradle/CodeGen, inputs, AWS, network/TLS/JDBC, metadata snapshot, generation, parse/plan, stale apply, or build/AP.

- [ ] **Step 6: Finalize OpenAI metadata**

Use exactly:

```yaml
interface:
  display_name: "Sync Doma Entities from Database"
  short_description: "Generate and safely merge Java or Kotlin Doma entities"
  default_prompt: "Use $doma-sync-entities-from-database to generate Doma entity candidates from this database and apply only structurally safe changes."
```

- [ ] **Step 7: Add the README catalog entry**

Add:

```text
skill name and triggers
Java/Kotlin and Kotlin/Groovy DSL support
PostgreSQL/MySQL and local/Docker/RDS/Aurora/Proxy support
temporary generation plus JDBC snapshot and structural merge
SAFE versus explicit review approval
environment, user-home Gradle, Secrets Manager, and IAM token handling
single-skill install command
local PostgreSQL and Aurora MySQL invocation examples
CodeGen 3.2.2 and Doma research/released baselines
```

Use the exact public command:

```bash
npx skills add momosetkn/doma-skills --skill doma-sync-entities-from-database
```

- [ ] **Step 8: Run structural and copied-install checks**

Create `test-install.sh` and run:

```bash
python3 /home/momose/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  skills/doma-sync-entities-from-database
npx skills add . --list
bash tests/doma-sync-entities-from-database/test-install.sh
```

The copy test must find all scripts/modules/references, preserve executable Bash/Python entrypoints, run Python/Java syntax checks from the copied skill, and prove no installed file references root bundles, `prisma-skills.md`, another skill path, or repository-only fixtures.

- [ ] **Step 9: Run positive and negative fresh-session evaluations**

Use the exact Task 1 prompts. Each positive response must select the workflow, preserve source, use the snapshot and official CodeGen task, classify changes correctly, require proposal IDs for destructive changes, and report verification/secrets. Each negative response must route without taking project, DB, or AWS actions.

Classify failures as retrieval, application, or boundary failures. Patch only the smallest responsible skill section or script and rerun the failed evaluation.

- [ ] **Step 10: Run complete deterministic validation**

```bash
bash -n skills/doma-sync-entities-from-database/scripts/generate-entities.sh
python3 -m py_compile \
  skills/doma-sync-entities-from-database/scripts/*.py \
  skills/doma-sync-entities-from-database/scripts/entity_sync/*.py
python3 tests/doma-sync-entities-from-database/run-unit-tests.py -v
bash tests/doma-sync-entities-from-database/run-compile-fixtures.sh
bash tests/doma-sync-entities-from-database/test-install.sh
git diff --check -- README.md skills/doma-sync-entities-from-database \
  tests/doma-sync-entities-from-database
```

- [ ] **Step 11: Commit public Skill content**

```bash
git add -- README.md skills/doma-sync-entities-from-database \
  tests/doma-sync-entities-from-database/test-install.sh
git commit -m "docs: publish Doma entity synchronization skill"
```

### Task 9: Final Review and Release-Readiness Verification

**Files:**
- Read: approved design and this plan
- Read: `README.md`
- Read: `skills/doma-sync-entities-from-database/**`
- Read: `tests/doma-sync-entities-from-database/**`
- Modify only to fix confirmed findings

**Interfaces:**
- Consumes: all implementation commits and evidence from Tasks 1-8.
- Produces: a reviewed, clean, self-contained branch ready for the user's chosen integration path; no automatic push, PR, merge, database mutation, or AWS mutation.

- [ ] **Step 1: Review against the approved design line by line**

Build a temporary checklist mapping every design section to an implementation path and verification command. Required mappings include provider priority, conditional CodeGen registration, metadata SQL types, isolated output, composite-key SAFE behavior, explicit deletion approval, handwritten preservation, AWS modes, four fixture builds, Testcontainers truthfulness, README, and copied installation.

- [ ] **Step 2: Review all scripts for severe defects**

Inspect path validation, symlink handling, atomicity, stale hashes, parser ambiguity, edit overlap, Secret lifetime, error masking, AWS targeting, Proxy resolution, shell quoting, exit-code propagation, Gradle task selection, and DB-operation scope. Fix only confirmed defects and add a failing regression test before each fix.

- [ ] **Step 3: Run the full release gate fresh**

```bash
python3 /home/momose/.codex/skills/.system/skill-creator/scripts/quick_validate.py \
  skills/doma-sync-entities-from-database
bash -n skills/doma-sync-entities-from-database/scripts/generate-entities.sh
python3 -m py_compile \
  skills/doma-sync-entities-from-database/scripts/*.py \
  skills/doma-sync-entities-from-database/scripts/entity_sync/*.py
python3 tests/doma-sync-entities-from-database/run-unit-tests.py -v
bash tests/doma-sync-entities-from-database/run-compile-fixtures.sh
bash tests/doma-sync-entities-from-database/run-testcontainers.sh || test "$?" -eq 77
npx skills add . --list
bash tests/doma-sync-entities-from-database/test-install.sh
! rg -n 'TO[D]O|TB[D]|<skill[-]name>|prisma-skills\.md|doma-project-bundle-[1-4]\.md' \
  README.md skills/doma-sync-entities-from-database
! rg -n 'AKIA[0-9A-Z]{16}|aws_secret_access_key|S3CR3T|jdbc:[^[:space:]]+@|password[[:space:]]*=[[:space:]]*["'"'][^"'"']+' \
  README.md skills/doma-sync-entities-from-database
git diff --check
git status --short --branch
```

Report exact pass counts and an explicit Testcontainers PASS or SKIP. Do not claim a skipped layer passed.

- [ ] **Step 4: Re-run final behavioral evaluations**

Run all approved positive and negative prompts in fresh sessions against the copied installation. Compare with Task 1 RED evidence and record the exact corrected failure classes outside the repository.

- [ ] **Step 5: Commit only confirmed final fixes**

If review produced fixes:

```bash
git add -- README.md skills/doma-sync-entities-from-database \
  tests/doma-sync-entities-from-database
git commit -m "fix: harden Doma entity synchronization skill"
```

If no files changed, do not create an empty commit.

- [ ] **Step 6: Present integration choices without taking them**

Summarize commits, test counts, four fixture builds, Testcontainers status, discovery/copy-install results, remaining review proposals, and any environmental limits. Then use `superpowers:finishing-a-development-branch` to offer keep-local, push/PR, merge, or discard choices. Do not push, open a PR, merge, or delete the branch without the user's selection.
