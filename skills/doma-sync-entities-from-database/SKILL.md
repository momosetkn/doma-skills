---
name: doma-sync-entities-from-database
description: Use when configuring Doma CodeGen in an existing Java or Kotlin Gradle project to generate entities from PostgreSQL/MySQL, compare them structurally with existing entities, and apply only safe database-authoritative changes without overwriting handwritten code.
---

# Sync Doma Entities from Database

Synchronize database physical facts through an isolated generated candidate, never by pointing CodeGen at application sources. Preserve Domains, custom annotations, methods, inheritance, associations, and every other application semantic the database cannot establish.

## Workflow

1. Inspect the existing project and run its annotation-processing build before editing. Require Gradle 8+, Java 17+, a supported `build.gradle.kts` or `build.gradle`, and conventional Java/Kotlin source roots. Stop if Doma processing is already broken. Read [Supported Projects](references/supported-projects.md).
2. Inspect Git status. Require the selected build file and every existing target entity to be tracked and clean; stop for dirty, untracked, or ignored targets. Never stage, reset, restore, or discard the project's changes.
3. Confirm PostgreSQL schema or MySQL catalog, an explicit table regex, entity package/language, and connection mode. Require explicit confirmation before using `.*`. Read [Database Connections](references/database-connections.md); for RDS, Aurora, or RDS Proxy also read [AWS Security](references/aws-security.md).
4. Run the [CodeGen configuration planner](scripts/configure-codegen.py) with `plan`. Inspect its JSON and build-file diff, then run `apply`. Preserve compatible project-selected versions; do not silently upgrade Gradle, Java, Kotlin, Doma, CodeGen, or the JDBC driver. Read [CodeGen Configuration](references/codegen-configuration.md).
5. Run the [generation wrapper](scripts/generate-entities.sh). It uses the [JDBC snapshot helper](scripts/schema-snapshot.java), invokes only official `domaCodeGenDomaSyncEntity`, and writes candidates below `build/doma-codegen/generated`. It must not write to a source root.
6. Run the [structural merge tool](scripts/compare-and-merge-entities.py) with `plan`. Inspect `schema-snapshot.json`, `merge-plan.json`, and `merge.diff`. Use [Entity Merge Rules](references/entity-merge-rules.md) plus [Java Entity Merge](references/java-entity-merge.md) or [Kotlin Entity Merge](references/kotlin-entity-merge.md) to interpret every `SAFE`, `REVIEW_REQUIRED`, and `BLOCKED` finding.
7. Run merge `apply` without approvals to apply only `SAFE` edits. A destructive or narrowing proposal is eligible only after showing its exact diff and receiving explicit approval for its exact finding ID; pass that ID with a repeated `--approve`. Never infer blanket approval. A `BLOCKED` finding has no executable edit.
8. Show the complete Git diff. Run the project's clean build, verify Doma-generated DAO implementations or equivalent processor output, regenerate and replan, and require an empty second diff. If any layer fails, stop at that layer and read [Troubleshooting](references/troubleshooting.md).

## Final Report

Report the selected project/module, language and Gradle DSL, database family and non-secret target identity, schema/catalog and table regex, versions preserved, configuration changes, generated/snapshot paths, applied `SAFE` IDs, approved review IDs, pending proposals, blocked findings, build/annotation-processing result, idempotence result, pre-existing dirty files, and credential source by provider name only. Never report a JDBC URL, host, user, password/token, Secret value, classpath, or raw credential-bearing error.

## Response Contract

Every synchronization response—even when required inputs are missing—must state the whole intended shape: inspect the existing AP build and Git boundary; confirm non-secret scope/provider inputs; plan and review permanent configuration; use the credential-free JDBC snapshot and official `domaCodeGenDomaSyncEntity` task to generate only under `build/doma-codegen/generated`; structurally plan `SAFE`/`REVIEW_REQUIRED`/`BLOCKED` findings; apply SAFE changes separately and require exact displayed proposal IDs for destructive/review changes; then show Git diff, clean-build/AP evidence, an empty second plan, pending/blocked findings, and provider names without secret values. Ask only for missing non-secret inputs.

## Boundary

This skill does not support Maven; create or migrate schemas; run DDL or DML against a supplied database; generate or modify DAOs, two-way SQL, migrations, or business queries; tune SQL or indexes; provision or mutate AWS resources; infer renames or business semantics; delete entities; or delete properties without an exact approved proposal. For an excluded request, respond only with a brief boundary and route to the owning workflow: do not solicit its implementation inputs and take no project, database, or AWS action here. The property-deletion exception is only to offer a non-mutating structural plan; never apply without the exact displayed proposal ID.
