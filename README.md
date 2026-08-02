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

### `doma-connect-aws-rds`

Use this skill when an existing plain Java or Kotlin Doma application must connect to, or repair a connection to, an existing Amazon RDS PostgreSQL, Aurora PostgreSQL, RDS MySQL, or Aurora MySQL target.

It covers Direct JDBC, IAM database authentication, Secrets Manager integration, existing RDS Proxy connections, the AWS Advanced JDBC Wrapper, Doma dialect and `DataSource` selection, layered connection verification, and narrowly targeted read-only AWS discovery.

AWS inspection is read-only and never retrieves or prints a secret value. The skill does not provision or mutate cloud resources. It excludes framework wiring and transactions, deployment, schema migrations, entity or business-DAO design, and slow-query or index tuning.

## Installation

```bash
npx skills add momosetkn/doma-skills --list
npx skills add momosetkn/doma-skills
npx skills add momosetkn/doma-skills --skill doma-setup-project
npx skills add momosetkn/doma-skills --skill doma-setup-kotlin-project
npx skills add momosetkn/doma-skills --skill doma-connect-aws-rds
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
Use $doma-connect-aws-rds to inspect the existing Aurora PostgreSQL target in ap-northeast-1 and connect this Kotlin Doma Lambda through its existing RDS Proxy with IAM authentication.
```

## Doma Baseline

The guidance was researched against the bundled `3.14.1-SNAPSHOT` source, with versioned released Doma `3.14.0` references and examples where applicable. This baseline does not claim that either version is the current or latest stable Doma release.
