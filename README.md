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

## Installation

```bash
npx skills add momosetkn/doma-skills --list
npx skills add momosetkn/doma-skills
npx skills add momosetkn/doma-skills --skill doma-setup-project
```

## Usage

```text
Use $doma-setup-project to add Doma to this plain Java Gradle project and verify annotation processing.
```

```text
Use $doma-setup-project to diagnose why this Maven build creates no generated DAO implementation.
```

## Doma Baseline

The guidance was researched against the bundled `3.14.1-SNAPSHOT` source, with versioned released Doma `3.14.0` references and examples where applicable. This baseline does not claim that either version is the current or latest stable Doma release.
