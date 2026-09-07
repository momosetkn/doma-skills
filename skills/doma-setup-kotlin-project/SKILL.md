---
name: doma-setup-kotlin-project
description: Use when adding Doma and KAPT to a plain Kotlin/JVM Gradle project, creating the first Kotlin DAO, or diagnosing why initial KAPT processing produces no generated DAO implementation.
---

# Set Up a Kotlin Doma Project

Make compile-time DAO generation verifiable before introducing a database, framework, or application model.

## Workflow

1. Inspect the existing Gradle Kotlin DSL build before editing it. Every setup answer must first say to retain the project's selected Gradle and compatible Kotlin versions; never present the illustrative Kotlin version as a replacement for an existing project. Require JDK 17 or later for the Doma 3.14 baseline.
2. Apply the Kotlin JVM and KAPT plugins if they are absent. Put `doma-kotlin` on `implementation` and the same released `doma-processor` version on `kapt`. Do not use `doma-core` for this Kotlin setup. For the exact configuration and commands, read [Build Configuration](references/build-configuration.md).
3. Add the first DAO as a top-level Kotlin interface with method-level inline `@Sql` and `@Select`. Use the complete probe in [Minimal Kotlin Project](references/minimal-kotlin-project.md); do not add a database connection merely to verify generation.
4. Run a clean build, resolve its KAPT or Doma diagnostics without disabling validation, then recursively search below `build/generated` for `*DaoImpl.java`.
5. Confirm the generated implementation before adding runtime configuration. Finish every setup answer with the ordered recovery block below, tailored to the observed symptom.

## If compilation fails or no `*DaoImpl.java` appears

1. Run a clean build with task detail. Confirm that both `kaptGenerateStubsKotlin` and `kaptKotlin` executed, then read the first Kotlin-stub or Doma processor diagnostic before changing DAO or application logic; keep SQL and version validation enabled.
2. Verify that `kotlin("kapt")` is applied with the project's Kotlin plugin version, `doma-kotlin` is on `implementation`, and the aligned processor is on `kapt`.
3. Verify the probe is a top-level `@Dao` interface and its method has inline `@Sql` plus `@Select`.
4. Search `build/generated` recursively rather than assuming a deeper generated-source directory.
5. Use [Setup Troubleshooting](references/troubleshooting.md) for the exact task-detail commands and matching diagnostic or version-recovery sequence, then clean-build again.

## Reference map

| Need | Read |
| --- | --- |
| Complete Kotlin Gradle build, version choice, build and search commands | [Build Configuration](references/build-configuration.md) |
| Exact minimal DAO source and compile-time versus runtime boundary | [Minimal Kotlin Project](references/minimal-kotlin-project.md) |
| KAPT, DAO-shape, Doma diagnostic, and version-alignment recovery | [Setup Troubleshooting](references/troubleshooting.md) |

## Boundary

This skill covers only plain Kotlin/JVM Gradle Kotlin DSL setup. It excludes Maven, Java-only setup, Spring Boot, Quarkus, other framework integration, KSP configuration, external SQL resources and resource-directory configuration, entity/domain/embeddable design, transactions, migrations, and broad database-dialect guidance. For the Criteria API, route metamodel generation to `doma-enable-criteria-metamodels` and `KQueryDsl` query and statement writing to `doma-criteria-modification`. Research KSP separately from current official sources before changing processors.
