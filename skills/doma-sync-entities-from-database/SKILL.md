---
name: doma-sync-entities-from-database
description: Use when configuring Doma CodeGen in an existing Java or Kotlin Gradle project to generate entities from PostgreSQL/MySQL, compare them structurally with existing entities, and apply only safe database-authoritative changes without overwriting handwritten code.
---

# Sync Doma Entities from Database

Use this workflow only in an existing Gradle 8+/Java 17+ project that already has a supported Java or Kotlin Doma setup. Generate candidates into `build/doma-codegen/generated`; never configure CodeGen to write into `src/main` or overwrite handwritten entities.

First create and inspect a configuration plan with `scripts/configure-codegen.py plan`. Apply only that reviewed plan with `apply`; it checks build-file hashes before writing. Keep JDBC credentials outside committed Gradle files and supply them through the supported Gradle providers.

This skill does not create or migrate schemas, issue DDL/DML against a supplied database, generate DAOs or SQL, tune queries, provision AWS infrastructure, or automatically delete existing entity properties.
