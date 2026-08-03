# Doma Database-to-Entity Synchronization Skill Design

## Goal

Create an installable `doma-sync-entities-from-database` skill that adds a permanent Doma CodeGen configuration to an existing Gradle-based Doma project, generates Java or Kotlin entities from a selected PostgreSQL or MySQL schema into an ignored build directory, compares the candidates structurally with existing entities, and applies only changes that satisfy explicit safety gates.

The database is authoritative for physical schema facts. The skill must still preserve application semantics that the database cannot express, such as Doma Domain types, handwritten methods, associations, inheritance, and custom annotations.

The skill covers:

- Gradle Kotlin DSL and Gradle Groovy DSL;
- Java and Kotlin Doma entities;
- local PostgreSQL and MySQL;
- PostgreSQL and MySQL started by Docker Compose or an equivalent local runtime;
- Amazon RDS for PostgreSQL and MySQL;
- Amazon Aurora PostgreSQL and MySQL;
- direct RDS/Aurora endpoints and RDS Proxy endpoints.

Maven, database schema mutation, DAO or SQL generation, database provisioning, and performance tuning remain outside this skill.

## User Outcomes

The skill should let an agent:

1. inspect an existing Doma project, its Gradle DSL, language, Doma version, annotation-processing setup, and entity layout;
2. select a local, containerized, RDS, Aurora, or RDS Proxy database and an explicit schema and table scope;
3. add or repair an idempotent, permanent Doma CodeGen configuration without storing credentials in the project;
4. generate only entity candidates into `build/doma-codegen/generated` by using the official entity-only CodeGen task;
5. compare generated and existing entities through normalized Java/Kotlin structure instead of text alone;
6. apply safe physical-schema synchronization automatically;
7. produce concrete database-authoritative patches for destructive or review-sensitive changes and apply them only after explicit proposal approval;
8. preserve application-level constructs that cannot be derived from database metadata;
9. verify the final diff, clean build, Doma annotation processing, and absence of leaked secrets.

## Trigger Boundary

Positive trigger examples:

```text
Connect to my local PostgreSQL database, generate Doma entities, and merge missing columns into the existing entities.
```

```text
Compare the existing Kotlin Doma entities with our Aurora MySQL schema and apply only safe changes.
```

```text
Configure Doma CodeGen in this Gradle project and synchronize the entities with the selected database tables.
```

```text
Generate entities from the tenant_* tables in RDS PostgreSQL without overwriting handwritten code.
```

Nearby prompts that must not trigger this skill as their primary authority:

```text
Create a new database schema.
```

```text
Write a Liquibase migration.
```

```text
Optimize this slow SQL query.
```

```text
Generate a DAO and two-way SQL.
```

```text
Provision a new Aurora cluster.
```

```text
Delete Entity properties that no longer exist in the database without asking me.
```

The last prompt is outside the automatic-merge boundary. The skill may generate a database-authoritative removal proposal, but it must not apply that proposal without explicit approval.

## Responsibility Boundaries

### `doma-setup-project`

`doma-setup-project` owns initial plain Java Doma setup and annotation processing. This synchronization skill assumes the existing Java project can already run Doma annotation processing. If that prerequisite is broken, stop and route the initial setup problem before returning to synchronization.

### `doma-setup-kotlin-project`

`doma-setup-kotlin-project` owns initial Kotlin/JVM, Gradle Kotlin DSL, and KAPT setup. This synchronization skill supports both Gradle DSLs but does not replace or migrate KAPT, KSP, Kotlin, or Doma versions.

### `doma-connect-aws-rds`

`doma-connect-aws-rds` owns application runtime `DataSource`, Doma `Config`, dialect, pooling, and general AWS connection topology. This synchronization skill owns the temporary CodeGen connection used to read schema metadata. It reuses the connection skill's safety concepts but has no filesystem dependency on that skill and remains independently installable.

### Explicit Exclusions

The skill does not:

- create, alter, migrate, truncate, or drop database objects;
- execute application DML;
- delete entities automatically;
- generate or modify DAOs, two-way SQL, migrations, or business queries;
- tune SQL or indexes;
- provision or modify AWS resources, IAM policies, database users, networks, or secrets;
- infer business semantics such as `@TenantId`, Domain adoption, associations, inheritance, or class naming changes;
- convert Maven projects or upgrade Gradle, Java, Kotlin, Doma, CodeGen, or JDBC dependencies without a separate explicit decision.

## Evidence Baseline

The repository Doma research baseline is the bundled `3.14.1-SNAPSHOT`. It is not a latest-stable claim. The target project's selected Doma version must be preserved.

On 2026-08-03, official sources established these CodeGen facts:

- the released Doma CodeGen Plugin version is `3.2.2`;
- the plugin ID is `org.domaframework.doma.codegen`;
- the plugin requires Gradle 8 or newer and Java 17 or newer;
- a named configuration creates `domaCodeGenXxxEntity` as the entity-only task;
- `url`, `user`, and `password` are Gradle `Property<String>` values;
- `sourceDir` is a `DirectoryProperty` and can target a build directory;
- entity overwrite defaults to `true`, so isolation from source directories is mandatory;
- entity generation may also emit listeners and mapped superclasses when those options remain enabled.

The implementation baseline is CodeGen Plugin `3.2.2`, not the repository's `3.2.3-SNAPSHOT` development branch. Preserve an existing compatible CodeGen version when present. If the target project cannot meet the verified plugin prerequisites, report the incompatibility and stop rather than upgrading the project automatically.

JDBC driver coordinates and versions must be taken from a compatible dependency already selected by the project when possible. If no driver is selected, verify a current official PostgreSQL or MySQL driver coordinate during implementation and require it as an explicit non-secret configuration input. Do not guess or silently upgrade it.

## Chosen Architecture

Use one public orchestration skill, focused references, three deterministic implementation scripts, and repository-level tests and fixtures.

```text
skills/doma-sync-entities-from-database/
  SKILL.md
  agents/
    openai.yaml
  references/
    supported-projects.md
    database-connections.md
    codegen-configuration.md
    entity-merge-rules.md
    java-entity-merge.md
    kotlin-entity-merge.md
    aws-security.md
    troubleshooting.md
  scripts/
    configure-codegen.py
    generate-entities.sh
    compare-and-merge-entities.py

tests/doma-sync-entities-from-database/
  test-configure-codegen.py
  test-entity-merge.py
  test-security.py
  test-generate-wrapper.py
  test-install.sh
  fixtures/
    java-kotlin-dsl-postgresql/
    kotlin-kotlin-dsl-postgresql/
    java-groovy-dsl-mysql/
    kotlin-groovy-dsl-mysql/
    generated-candidates/
    aws-stubs/
    secret-redaction/
```

Repository-level tests are authoring assets and are not installed with the skill. Every runtime resource remains inside the skill directory so a copied individual installation is self-contained.

### Component Responsibilities

- `SKILL.md`: Defines triggers, prerequisites, ordered execution, approval boundaries, verification gates, exclusions, reference routing, and final reporting.
- `references/supported-projects.md`: Defines supported Java/Kotlin and Gradle shapes, source-layout discovery, CodeGen compatibility gates, and unsupported-project behavior.
- `references/database-connections.md`: Defines local, Docker Compose, direct RDS/Aurora, and RDS Proxy connection inputs without embedding credentials.
- `references/codegen-configuration.md`: Documents the verified plugin/task model, Kotlin and Groovy DSL provider-backed configurations, temporary output, language selection, table filters, and idempotent managed-block behavior.
- `references/entity-merge-rules.md`: Defines the normalized model, database-authoritative boundary, `SAFE`, `REVIEW_REQUIRED`, and `BLOCKED` classifications, proposal approvals, and plan integrity.
- `references/java-entity-merge.md`: Covers Java fields, accessors, comments, imports, classes, Domain types, annotations, inheritance, records, Lombok, and fail-closed cases.
- `references/kotlin-entity-merge.md`: Covers body properties, nullability, imports, KDoc, classes, primary constructors, data classes, Domain types, and fail-closed cases.
- `references/aws-security.md`: Defines exact-target AWS inspection, Secrets Manager and IAM-token handling, RDS Proxy differences, command allowlists, masking, and non-mutation guarantees.
- `references/troubleshooting.md`: Maps project, configuration, AWS, network, JDBC metadata, generation, parsing, merge, annotation-processing, and build failures to safe next actions.
- `scripts/configure-codegen.py`: Inspects and idempotently modifies `build.gradle` or `build.gradle.kts` with token-aware balanced-block handling. It never handles secret values.
- `scripts/generate-entities.sh`: Resolves connection inputs, performs approved read-only AWS operations, retrieves a secret or creates an IAM token just in time when required, masks output, and runs only the official entity generation task with `--no-daemon`.
- `scripts/compare-and-merge-entities.py`: Tokenizes Java/Kotlin, creates normalized models, writes a deterministic plan and diff, applies `SAFE` changes, and applies `REVIEW_REQUIRED` changes only by approved proposal ID.

## Ordered Workflow

### 1. Inspect the Existing Project

Identify and record:

- repository and Gradle root;
- clean/dirty worktree state;
- `build.gradle` or `build.gradle.kts` and any relevant subproject;
- Java or Kotlin entity language;
- Java, Kotlin, Gradle, Doma, annotation processor, and CodeGen versions;
- KAPT or Java annotation-processing configuration;
- existing CodeGen plugin, dependency, and named configurations;
- existing entity source roots, packages, `@Table` mappings, Domain declarations, Metamodel style, and custom templates;
- database family, location, schema, and explicit table include/exclude scope.

Run the existing compile or annotation-processing gate before editing. If initial Doma processing is broken, stop without adding CodeGen configuration.

### 2. Establish a Clean Change Boundary

Inspect `git status` before configuration or entity changes.

- A dirty build file that must be edited is a global blocker.
- A dirty target entity is never changed. Report it and stop the apply stage before writing any entity.
- Unrelated dirty files may remain when they do not overlap, but the final report must list that pre-existing state separately.
- Never stage, commit, reset, restore, or discard a target project's changes as part of this skill.

### 3. Confirm Database Scope and Connection Mode

Require an explicit database family, schema or catalog semantics, and table pattern. An all-table pattern is allowed only after explicit confirmation. Do not infer a production target from names.

For local or containerized databases, accept only credential-free JDBC URLs and external user/password providers.

For AWS, require:

- expected AWS account;
- explicit region;
- target kind: DB instance, DB cluster, or RDS Proxy;
- exact target identifier;
- direct or Proxy endpoint choice;
- Secrets Manager or IAM database authentication mode;
- exact secret identifier when Secrets Manager is selected;
- database name and database user where they cannot be derived safely.

### 4. Add or Repair Permanent CodeGen Configuration

`configure-codegen.py` uses a token-aware Gradle scanner that understands strings, comments, and balanced blocks for the supported DSLs. It does not attempt to become a general Gradle parser.

The script:

1. preserves an existing compatible CodeGen plugin declaration;
2. adds the verified plugin declaration when absent;
3. reuses an existing compatible JDBC driver version or accepts an explicitly verified coordinate;
4. adds exactly one `domaCodeGen` dependency;
5. creates or repairs a named `domaSync` configuration;
6. surrounds only script-owned content with stable managed markers;
7. refuses ambiguous or dynamically constructed Gradle structures rather than rewriting them;
8. produces no diff when run twice with the same inputs.

If a compatible unmanaged `domaCodeGen` container already exists, add the dedicated named configuration without changing unrelated named configurations. If an unmanaged `domaSync` configuration exists, adopt it only when every required edit can be proven local and non-destructive; otherwise stop with a configuration conflict.

The permanent configuration must:

- use provider-backed URL, user, and password values;
- register the `domaSync` named configuration only when a requested task name starts with `domaCodeGenDomaSync`;
- set `sourceDir` to `layout.buildDirectory.dir("doma-codegen/generated")` or the DSL-equivalent;
- set `languageType` from the inspected entity language;
- set entity package and explicit table/schema filters;
- generate entities only;
- set entity overwrite to `true` only because the output is isolated;
- disable listener and mapped-superclass file generation for the synchronization candidate unless a verified custom generation contract requires them;
- preserve the existing project's Metamodel policy in generated candidates;
- avoid adding the generated directory to a production source set.

The task-name guard is required by CodeGen Plugin `3.2.2`: each registered `CodeGenConfig` validates its `DataSource` and dialect during Gradle's `afterEvaluate` phase. Registering an absent environment-backed URL unconditionally would make ordinary `clean`, `build`, IDE import, and unrelated Gradle tasks fail when CodeGen credentials are not present. Keep the plugin and configuration code permanent, but create the named object only for an explicitly requested `domaCodeGenDomaSync...` task. The generation wrapper performs its own missing-input check before Gradle starts. Test both generation-task registration and a credential-free ordinary clean build.

The resulting official task for `register("domaSync")` is:

```bash
./gradlew --no-daemon domaCodeGenDomaSyncEntity
```

Generation and merge remain separate operations. Do not register a Gradle `Exec` merge task whose command depends on a particular skill installation path.

### 5. Generate into the Isolated Directory

`generate-entities.sh` validates that the resolved output is inside the current Gradle build directory before cleaning only that exact generated directory. It must never resolve to a source root, repository root, home directory, or an unresolved variable.

The wrapper invokes only `domaCodeGenDomaSyncEntity`. It does not invoke `All`, DAO, SQL, DTO, SQL-test, build, migration, `psql`, or `mysql` commands.

Doma CodeGen may use JDBC `DatabaseMetaData` and dialect-specific read-only comment queries. The skill therefore promises no DDL or DML, not an inaccurate guarantee that no SQL `SELECT` is issued. Recommend a read-only database user and validate that the selected user cannot mutate schema or data when a disposable integration environment is available.

### 6. Build a Deterministic Merge Plan

The comparison script has separate `plan` and `apply` commands. `plan` never changes an entity.

It records:

- input and configuration schema version;
- sorted table/entity identities;
- SHA-256 of every existing and generated source file;
- normalized database and source structures;
- ordered `SAFE`, `REVIEW_REQUIRED`, and `BLOCKED` findings;
- an ordered unified diff;
- stable proposal IDs derived from change kind and entity identity, not timestamps;
- no secret values or credential-bearing URLs.

### 7. Apply Approved Changes

Before writing, `apply` rechecks:

- plan schema version;
- project root and target paths;
- hashes of every input;
- Git status of all target entities and build files;
- generated directory location;
- proposal approval IDs.

Any stale or mismatched input stops the complete apply stage before the first write.

Write changed files through same-filesystem temporary files followed by atomic replacement. Preserve encoding, line endings, final newline, file permissions, source slices that are not part of a planned edit, and deterministic import placement.

Apply `SAFE` changes by default. Apply a `REVIEW_REQUIRED` proposal only when its exact ID is supplied through a repeated `--approve` option after its diff has been shown. Do not provide a silent blanket approval mode in the initial version.

### 8. Verify

After application:

1. show the complete Git diff for changed build and entity files;
2. run the project's clean build;
3. confirm Doma-generated classes or equivalent annotation-processing output;
4. rerun generation and planning to prove idempotence;
5. report every remaining proposal and blocked decision.

A build failure is `FAILED`, never success. Leave the agent-owned Git diff visible for diagnosis; do not run destructive Git rollback commands. Because the target files were clean before apply, the report can identify precisely which changes belong to the synchronization run.

## Connection and Secret Contract

### Provider Priority

Resolve database connection inputs in this explicit order:

1. environment variables;
2. user-home `~/.gradle/gradle.properties`;
3. AWS profile or execution-role credentials.

Use these public names unless the target project has an established equivalent:

```text
DOMA_CODEGEN_DB_URL
DOMA_CODEGEN_DB_USER
DOMA_CODEGEN_DB_PASSWORD
DOMA_CODEGEN_DB_SCHEMA
DOMA_CODEGEN_TABLE_PATTERN
AWS_PROFILE
AWS_REGION
RDS_IDENTIFIER
RDS_TARGET_KIND
RDS_SECRET_ID
DB_NAME
DB_USER
```

The Gradle configuration uses `ProviderFactory.environmentVariable` followed by `ProviderFactory.gradleProperty`. Before Gradle runs, scan the Gradle build tree's project-local `gradle.properties` files and stop if they contain CodeGen password, Secret, token, access-key, or credential-bearing URL keys. Never recommend `-Ppassword=...` or another command-line secret.

Map or validate the URL provider without interpolating its value into an error. Reject URL user-info, password parameters, access keys, tokens, or other embedded credentials.

### AWS Resolution

The wrapper uses an explicit allowlist:

- `aws sts get-caller-identity`;
- one exact `rds describe-db-instances`, `describe-db-clusters`, or `describe-db-proxies` request;
- `rds describe-db-proxy-targets` and exact target resolution for a selected Proxy;
- `secretsmanager describe-secret` for the explicit secret;
- `secretsmanager get-secret-value` only for the same explicit secret and only immediately before generation;
- `rds generate-db-auth-token` only for the confirmed endpoint, port, region, and DB user.

Every AWS call uses the explicit region and profile when supplied. Confirm the account before RDS or Secret retrieval. Reject unsupported engines, inconsistent Proxy targets, target-not-found results, and account mismatch.

When a Secret contains host, port, engine, database name, username, and password fields, continue to use the endpoint, port, and engine from the explicitly confirmed RDS/Aurora/Proxy target. Accept only the required username/password fields and an explicitly selected database name from the Secret; reject inconsistent routing metadata rather than allowing a Secret value to redirect the connection silently.

Do not call AWS create, modify, delete, attach, detach, authorize, revoke, rotate, restore, promote, failover, deploy, or database-user operations.

### Secret Lifetime and Redaction

- Run the wrapper with shell tracing disabled.
- Capture Secret JSON and IAM tokens without printing them.
- Parse only required connection fields in memory.
- Pass the resolved password/token only in the environment of the non-daemon Gradle child process.
- Do not write secret-bearing temporary files, environment files, Gradle files, plan files, reports, logs, or responses.
- Clear shell variables after the child process exits.
- Do not use Gradle `--info`, `--debug`, or unredacted stack traces.
- Redact sentinel values, URL user-info, password/token query parameters, and known AWS credential shapes from stdout, stderr, and exception summaries.

Environment delivery is the requested interface, but it is not described as protection from a privileged local process inspector. Limit exposure to the one child process and its lifetime.

## Structural Comparison Model

Use a deterministic lexical scanner and small language-aware parsers implemented with the Python standard library. Do not depend on regular expressions alone, and do not claim compiler-complete AST coverage.

Normalize at least:

- package, imports, language, class kind, and class name;
- `@Entity` values and Metamodel settings;
- catalog, schema, and table identity;
- property name, column name, source range, type, and nullability;
- `@Id` and `@GeneratedValue`;
- `@Version` and `@TenantId`;
- `@Transient` and `@Association`;
- Domain type declarations and uses;
- `@Embeddable` and `@Embedded`;
- constructors and handwritten methods;
- superclass and implemented interfaces;
- custom annotations;
- Javadoc, KDoc, and database comments;
- recognized generated Java accessor methods;
- Kotlin body properties and primary-constructor properties.

Match entities by normalized physical table identity, not by file or class name alone. Match properties by normalized physical column identity. A missing or ambiguous physical identity is not sufficient evidence for a rename.

Preserve exact source slices outside planned edits. Add imports according to the existing grouping and ordering style. Do not run an unrelated whole-project formatter.

## Database-Authoritative Change Policy

### Physical Facts Versus Application Semantics

Treat these database facts as authoritative:

- table and column existence;
- SQL type and width/precision;
- nullability;
- primary-key membership and sequence;
- physical catalog, schema, table, and column names;
- database comments.

The database does not settle:

- Java/Kotlin class or property names;
- Domain adoption or removal;
- `@Transient`, `@Association`, or `@TenantId` intent;
- handwritten methods;
- inheritance and interfaces;
- custom annotations;
- constructor/equality/serialization compatibility;
- whether a name-pattern match should mean `@Version` in an established model.

### `SAFE`

Apply automatically only when every relevant parser, identity, Git, and source-location gate succeeds.

`SAFE` may include:

- creating an entity for a new table when the package and target source root are unambiguous and no path collision exists;
- adding a new body property for a new column when no property/column collision exists and the type mapping is supported;
- adding or correcting `@Column(name = "...")` when entity and property physical identities are unique;
- adding database comments as Javadoc or KDoc without replacing handwritten documentation;
- adding required imports without removing unrelated imports;
- a predefined non-narrowing Java/Kotlin basic-type correction in an entity proven to contain only recognized generated code;
- nullability on a newly added property;
- synchronizing single or composite `@Id` membership with the complete database primary key;
- preserving existing Metamodel settings, custom annotations, handwritten methods, inheritance, interfaces, and formatting.

Primary-key synchronization is atomic across the complete key. It is `SAFE` only when:

- the table identity is exact;
- JDBC metadata returns the complete key and sequence;
- every key column maps to exactly one existing or safely addable property;
- no property rename, type replacement, Domain replacement, embedded mapping, transient mapping, association, or constructor rewrite is required;
- the parser fully understands the entity;
- only `@Id` membership changes.

Removing `@Id` from a property that remains a database column is allowed under the same gates. Never delete the property as part of that operation. Do not infer `@GeneratedValue` merely from primary-key membership; require explicit, unambiguous database auto-generation metadata and a compatible CodeGen candidate.

An existing Kotlin property's nullable/non-null change is not `SAFE` in the initial version. Java project-specific nullability annotations are not invented.

### `REVIEW_REQUIRED`

Generate a concrete database-authoritative patch and stable proposal ID, but do not apply it without explicit approval, for changes such as:

- deleting a property for a column removed from the database;
- deleting recognized generated accessors associated only with that property;
- a compatible but source-sensitive existing-property nullability change;
- a basic-type change outside the strict `SAFE` widening table;
- adding a property that requires a source-compatible but behavior-sensitive constructor change;
- a clearly mapped physical table/schema name correction that may affect application assumptions.

A removal proposal is executable only when the parser proves the property and any removed accessors are generated-shaped and no handwritten method or initializer refers to them. Otherwise show an advisory diff and classify the decision as `BLOCKED`.

### `BLOCKED`

Do not create an executable patch when database metadata cannot determine the application-level decision. Report database facts, existing code, generated candidate, reason, affected references when detectable, and concrete options.

`BLOCKED` includes:

- Domain-to-basic or basic-to-Domain replacement;
- property or entity rename inference;
- deletion or replacement of `@Transient`, `@Association`, `@Embedded`, or custom annotations;
- handwritten method deletion;
- inheritance or interface changes;
- `@Version` or `@TenantId` inference;
- unsupported or ambiguous composite/embedded property mapping;
- Java records, Lombok-dependent shapes, complex custom templates, or other syntax the parser cannot edit safely;
- Kotlin primary-constructor or data-class changes that affect constructor, equality, copy, or serialization semantics;
- column-type narrowing when compatibility cannot be proven;
- duplicate property-to-column mappings;
- class/table/schema identity ambiguity.

No state writes Git conflict markers. `REVIEW_REQUIRED` means an unapplied concrete proposal; `BLOCKED` means a manual application decision is still required.

## Plan and Result States

Use these high-level outcomes:

- `SUCCESS`: all selected and approved changes were applied, clean build and Doma processing succeeded, and no selected unresolved proposal remains;
- `PENDING_REVIEW`: safe changes may be applied and verified, but one or more proposal IDs await approval;
- `BLOCKED`: at least one required application-level decision has no executable safe proposal;
- `FAILED`: project inspection, security, AWS, generation, stale-plan, write, clean-build, or annotation-processing verification failed.

Conflict-free files may be updated while another file is pending review or blocked, but never partially edit a single file that contains interacting unsafe findings. If one finding makes a file's edit ranges or imports ambiguous, skip every planned edit for that file.

## Error and Failure Handling

Classify failures into:

1. project shape or annotation-processing prerequisite;
2. Git/change-boundary violation;
3. CodeGen/Gradle compatibility or configuration mutation;
4. connection-input or credential policy;
5. AWS identity, target, Secret, or IAM token resolution;
6. network, TLS, JDBC, metadata, or permission failure;
7. CodeGen generation or generated-output validation;
8. Java/Kotlin parsing or entity identity ambiguity;
9. stale plan or atomic write failure;
10. clean build or Doma annotation-processing failure.

At failure, report what was proven, the first failing layer, a redacted summary, whether any files changed, and the next safe action. Do not skip to a later layer or broaden resource inspection after a narrow lookup fails.

## Output Contract

Every run reports:

```text
Connection:
  Type:
  AWS account/region/target:
  Schema:
  Tables:

Project:
  Language:
  Gradle DSL:
  Doma version:
  CodeGen plugin version:
  Generated directory:

Changes:
  New entities:
  Safe changes:
  Review-required proposals:
  Blocked decisions:
  Modified files:

Verification:
  Clean build:
  Doma annotation processing:
  Remaining issues:
  Secrets saved or displayed: NO
```

Each proposal or blocked decision includes:

- target file;
- database definition;
- existing source;
- generated candidate;
- proposed diff when deterministic;
- reason automatic application stopped;
- impact and required action;
- stable approval ID for executable review proposals.

Never include a password, Secret value, IAM token, access key, credential-bearing URL, environment-file contents, or unredacted credential-bearing error.

## Validation Strategy

### Gradle Configuration Tests

Using temporary copies of fixtures, test:

- insertion into Kotlin DSL;
- insertion into Groovy DSL;
- safe repair of an existing CodeGen configuration;
- preservation of unrelated named configurations;
- plugin and dependency reuse;
- byte-identical output on a second run;
- safe stop when a required Secret input is absent;
- an ordinary clean build and IDE-style model task without CodeGen credentials;
- registration of `domaSync` when `domaCodeGenDomaSyncEntity` is explicitly requested;
- rejection of a project-local Secret property;
- rejection of ambiguous dynamic Gradle code;
- no credential value in the resulting build or Gradle files.

### Entity Merge Tests

Test at least:

- new Java and Kotlin entity creation;
- new body property insertion;
- `@Column` addition and correction;
- compatible basic-type update;
- single and composite `@Id` synchronization;
- preservation of handwritten methods;
- preservation of custom annotations and Metamodel settings;
- Domain/basic-type blocking;
- existing Kotlin nullability review;
- removed-column review proposal;
- refusal to remove a property without its approval ID;
- composite-key ambiguity blocking;
- Kotlin primary-constructor blocking;
- import and comment handling;
- generated-only versus handwritten classification;
- stale-plan rejection;
- no change when the same generated and existing inputs are compared again;
- deterministic plan JSON, proposal IDs, and unified diff.

### Security Tests

Place stub `aws` and `gradlew` executables first on `PATH` and verify:

- password, Secret JSON, IAM token, and credential-bearing URL sentinels never appear in stdout or stderr;
- credential-bearing JDBC URLs are rejected and masked;
- no project-local Gradle property receives a Secret;
- every AWS command belongs to the exact allowlist;
- identity mismatch stops before RDS or Secret retrieval;
- Secret retrieval is limited to the explicitly described Secret;
- IAM token generation uses the confirmed endpoint, port, region, and user;
- direct RDS/Aurora and RDS Proxy target resolution are both covered;
- no AWS mutation command is invoked;
- no database CLI or DDL/DML command is invoked;
- Gradle always runs with `--no-daemon`;
- missing environment, user-home, and AWS inputs stop without prompting for or echoing a Secret.

### Compile Fixtures

Maintain these four representative Gradle fixtures:

- Java + Gradle Kotlin DSL + PostgreSQL;
- Kotlin + Gradle Kotlin DSL + PostgreSQL;
- Java + Gradle Groovy DSL + MySQL;
- Kotlin + Gradle Groovy DSL + MySQL.

For each fixture:

1. apply CodeGen configuration;
2. place a deterministic generated candidate set;
3. plan and apply safe changes;
4. verify handwritten code remains byte-equivalent outside edit ranges;
5. run the fixture's clean build;
6. prove Doma annotation-generated classes exist;
7. rerun and prove no diff.

All four clean-build fixtures are a release gate.

### Testcontainers Integration

When Docker is available, run PostgreSQL and MySQL integration tests using Testcontainers:

- initialize fixture schema with a disposable administrator;
- run CodeGen with a separate read-only metadata user;
- execute the actual `domaCodeGenDomaSyncEntity` task;
- validate comments, nullability, types, single and composite primary keys;
- prove the CodeGen user cannot execute DDL or DML;
- merge and compile Java/Kotlin candidates;
- require no AWS credentials.

If Docker is unavailable, mark this layer explicitly skipped. Never describe a skipped integration test as passed. The deterministic tests and four compile fixtures remain mandatory.

### Skill Structure and Installation

- Parse frontmatter and confirm directory/frontmatter names match.
- Validate `agents/openai.yaml` against existing repository conventions.
- Resolve every linked reference and script.
- Run `bash -n` and `python3 -m py_compile`.
- Run every deterministic unit and fixture test.
- Verify `npx skills add . --list` discovers the new and existing skills.
- Copy-install only `doma-sync-entities-from-database` in a disposable directory.
- Prove the installed directory contains no reference to root bundles, `prisma-skills.md`, another skill directory, or repository-only tests.

### Behavioral Evaluation

Run fresh-session evaluations for the four positive trigger prompts and negative evaluations for:

- schema creation or migration;
- slow-query and index work;
- DAO and two-way SQL generation;
- Aurora/RDS provisioning;
- unapproved entity-property deletion.

The skill passes only when it selects synchronization for the positive prompts, refuses the excluded workflow as primary authority, produces database-authoritative proposals, never overwrites source with CodeGen, and keeps credentials out of artifacts and responses.

## README Contract

Update the root README with:

- `doma-sync-entities-from-database` name and trigger scope;
- Java/Kotlin and both Gradle DSLs;
- PostgreSQL/MySQL and local/Docker/RDS/Aurora/RDS Proxy coverage;
- temporary generation and structural safe-merge summary;
- environment, user-home Gradle, Secrets Manager, and IAM-token secret handling;
- list, install-all, and single-skill installation commands;
- local PostgreSQL and Aurora MySQL usage examples;
- targeted Doma source baseline and verified CodeGen Plugin baseline.

## Official Sources

The implementation must recheck mutable details against current official sources before writing examples. This design used:

- [Doma CodeGen Plugin documentation](https://docs.domaframework.org/en/stable/codegen/)
- [Doma CodeGen Plugin Portal entry](https://plugins.gradle.org/plugin/org.domaframework.doma.codegen)
- [Doma CodeGen Plugin `v3.2.2` task registration](https://github.com/domaframework/doma-codegen-plugin/blob/v3.2.2/codegen/src/main/java/org/seasar/doma/gradle/codegen/CodeGenPlugin.java)
- [Doma CodeGen Plugin `v3.2.2` main configuration](https://github.com/domaframework/doma-codegen-plugin/blob/v3.2.2/codegen/src/main/java/org/seasar/doma/gradle/codegen/extension/CodeGenConfig.java)
- [Doma CodeGen Plugin `v3.2.2` entity configuration](https://github.com/domaframework/doma-codegen-plugin/blob/v3.2.2/codegen/src/main/java/org/seasar/doma/gradle/codegen/extension/EntityConfig.java)
- [Gradle build environment and Provider guidance](https://docs.gradle.org/current/userguide/build_environment.html)
- [Gradle `ProviderFactory`](https://docs.gradle.org/current/javadoc/org/gradle/api/provider/ProviderFactory.html)
- [AWS CLI `get-caller-identity`](https://docs.aws.amazon.com/cli/latest/reference/sts/get-caller-identity.html)
- [AWS CLI `describe-db-instances`](https://docs.aws.amazon.com/cli/latest/reference/rds/describe-db-instances.html)
- [AWS CLI `describe-db-clusters`](https://docs.aws.amazon.com/cli/latest/reference/rds/describe-db-clusters.html)
- [AWS CLI `describe-db-proxies`](https://docs.aws.amazon.com/cli/latest/reference/rds/describe-db-proxies.html)
- [AWS CLI `describe-db-proxy-targets`](https://docs.aws.amazon.com/cli/latest/reference/rds/describe-db-proxy-targets.html)
- [AWS CLI `get-secret-value`](https://docs.aws.amazon.com/cli/latest/reference/secretsmanager/get-secret-value.html)
- [AWS CLI `generate-db-auth-token`](https://docs.aws.amazon.com/cli/latest/reference/rds/generate-db-auth-token.html)
- [Amazon RDS IAM database authentication](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/UsingWithRDS.IAMDBAuth.html)
- [Amazon RDS Proxy](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-proxy.html)

Do not silently mix this versioned CodeGen baseline with the plugin repository's later snapshot branch. Record any newly verified release and compatibility change explicitly during implementation.
