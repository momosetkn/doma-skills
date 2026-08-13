# Doma Skills

Installable [Agent Skills](https://agentskills.io/) for developers using Doma, the compile-time database access framework for Java and Kotlin.

## Available Skills

### `doma-setup-project`

Use this skill when:

- adding Doma and annotation processing to a plain Java Gradle project;
- configuring a plain Java Maven project and creating its first compilable DAO; or
- diagnosing why an initial build produced no generated DAO implementation.

It covers Java 17-or-later build wiring, matching `doma-core` and `doma-processor` versions, the first `Config`, entity, DAO, and SQL resource, clean compilation, recursive generated-source inspection, and setup diagnostics.

It excludes Spring Boot, Quarkus, other framework integrations, Kotlin with KAPT or KSP, advanced DAO and two-way SQL design, Criteria API, transactions, and database migrations.

### `doma-setup-kotlin-project`

Use this skill when:

- adding Doma and KAPT to a plain Kotlin/JVM Gradle Kotlin DSL project;
- creating the first Kotlin DAO that proves annotation processing works; or
- diagnosing why KAPT produced no generated DAO implementation.

It covers JDK 17-or-later setup, aligned `doma-kotlin` and `doma-processor`
dependencies, an inline-SQL top-level DAO probe, a clean Gradle build,
recursive generated-source inspection, and initial setup diagnostics.

It excludes Maven, Java-only setup, Spring Boot, Quarkus, other framework
integrations, KSP configuration, external SQL resources, entity/domain/embeddable
design, Criteria API and KQueryDsl, transactions, migrations, and broad
database-dialect guidance.

### `doma-sync-entities-from-database`

Use this skill when an existing Doma Gradle project must configure Doma CodeGen,
generate Java or Kotlin entity candidates from selected PostgreSQL or MySQL
tables, compare them structurally with existing entities, and apply only proven
database-authoritative changes without overwriting handwritten code.

It supports Gradle Kotlin and Groovy DSL projects, local or Docker-hosted
databases, RDS and Aurora instances or clusters, and RDS Proxy. It creates a
credential-free JDBC metadata snapshot and temporary candidates under
`build/doma-codegen`, applies `SAFE` edits separately, and requires explicit
approval of each exact `REVIEW_REQUIRED` proposal. Domains, custom annotations,
methods, associations, inheritance, and ambiguous source shapes fail closed.

Local credentials come from `DOMA_CODEGEN_DB_URL`, `DOMA_CODEGEN_DB_USER`, and
`DOMA_CODEGEN_DB_PASSWORD`, falling back to the matching user-home Gradle
properties; project-local secrets are rejected. AWS connections use exact
account/region/target confirmation with Secrets Manager or a just-in-time IAM
database-authentication token. Credentials are passed only to isolated child
processes, redacted from output, and never stored in generated artifacts.

It excludes Maven, schema or migration changes, DAO/two-way-SQL generation,
query tuning, AWS provisioning, inferred renames, entity deletion, and
unapproved property deletion.

## Installation

```bash
npx skills add momosetkn/doma-skills --list
npx skills add momosetkn/doma-skills
npx skills add momosetkn/doma-skills --skill doma-setup-project
npx skills add momosetkn/doma-skills --skill doma-setup-kotlin-project
npx skills add momosetkn/doma-skills --skill doma-sync-entities-from-database
```

## Usage

```text
Use $doma-setup-project to add Doma to this plain Java Gradle project and verify annotation processing.
```

```text
Use $doma-setup-project to diagnose why this Maven build creates no generated DAO implementation.
```

```text
Use $doma-setup-kotlin-project to add Doma and KAPT to this Kotlin/JVM Gradle project and verify DAO generation.
```

```text
Use $doma-sync-entities-from-database to connect to my local PostgreSQL database, generate Doma entities for the tenant tables, and merge only safe changes.
```

```text
Use $doma-sync-entities-from-database to compare our Kotlin entities with an Aurora MySQL schema through RDS Proxy without overwriting handwritten code.
```

## Doma Baseline

The guidance was researched against the bundled `3.14.1-SNAPSHOT` source, with versioned released Doma `3.14.0` references and examples where applicable. Entity synchronization uses the verified Doma CodeGen Plugin `3.2.2` baseline while preserving a compatible version already selected by the target project. These baselines do not claim that any version is the current or latest stable release.
