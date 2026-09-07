---
name: doma-setup-project
description: Use when adding Doma to a plain Java Gradle or Maven project, creating the first Config, entity, DAO, or SQL resource, or diagnosing missing generated DAO implementations during initial annotation processing.
---

# Set Up a Plain Java Doma Project

## Core Principle

Make annotation processing and resource paths verifiable before adding application complexity.

## Boundary

Use this skill only for initial setup in a plain Java Gradle or Maven project. Route Spring Boot, Quarkus, other framework integration, Kotlin with KAPT or KSP, advanced DAO or two-way SQL design, transaction configuration, and database migrations to guidance dedicated to those concerns, and do not imply that this setup workflow covers them. For the Criteria API, route metamodel generation to `doma-enable-criteria-metamodels` and query and statement writing to `doma-write-criteria-queries`.

## Workflow

1. Inspect the existing project before editing it. Identify the build tool, Java version, selected released Doma version, source/resource layout, and any current annotation-processor configuration. Keep the project's build tool and require Java 17 or later for Doma 3.14.
2. Configure `doma-core` on the compile/runtime classpath and `doma-processor` only on the annotation-processor path. Give both artifacts the same released Doma version. For exact Gradle or Maven wiring and `doma.resources.dir`, read [Build Configuration](references/build-configuration.md).
3. Add one matching minimal set of artifacts: a top-level `@Dao` interface, its query method, and the exact SQL resource when using external SQL. Add `Config` and an entity only when the requested example or runtime boundary needs them. For a coherent file-by-file example, read [Minimal Plain Java Project](references/minimal-java-project.md).
4. Run a clean compile with the project's build tool. Treat compiler diagnostics as the primary result; do not disable SQL or version validation to hide setup errors.
5. Inspect generated sources recursively. Search below `build/generated/sources/annotationProcessor` for Gradle or `target/generated-sources/annotations` for Maven; do not assume one deeper leaf path.
6. End every setup answer with an `If compilation fails or no *DaoImpl.java appears` recovery block. Fill it with the applicable verification sequence from [Setup Troubleshooting](references/troubleshooting.md) before changing application logic.

## Quick Reference

| Need | Read |
| --- | --- |
| Gradle or Maven dependencies, processor scope, resource option, compile command | [Build Configuration](references/build-configuration.md) |
| Complete `Config`, entity, DAO, SQL resource, and generated-DAO example | [Minimal Plain Java Project](references/minimal-java-project.md) |
| Missing generated DAO, compile failure, or `DOMA` diagnostic | [Setup Troubleshooting](references/troubleshooting.md) |

## Common Mistakes

- Copying the research baseline `3.14.1-SNAPSHOT` as though it were a released dependency coordinate; choose a released version instead.
- Putting `doma-processor` on the normal runtime or implementation classpath instead of Gradle `annotationProcessor` or Maven `annotationProcessorPaths`.
- Writing `@Select(sqlFile = true)`; Doma 3.14 uses plain `@Select` for an external SELECT SQL file.
- Placing SQL anywhere other than the exact UTF-8 `META-INF/<DAO package path>/<DAO simple name>/<DAO method name>.sql` resource path, or pointing `doma.resources.dir` elsewhere.
- Declaring generation failed before compiling and searching recursively under the documented generated-source root.
- Giving `doma-core` and `doma-processor` different versions; align them and clean-compile to remove stale generated output.
