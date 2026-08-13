# CodeGen Configuration

## Contents

- [Version and task model](#version-and-task-model)
- [Plan and apply](#plan-and-apply)
- [Provider and output contract](#provider-and-output-contract)
- [Kotlin DSL rendered shape](#kotlin-dsl-rendered-shape)
- [Groovy DSL rendered shape](#groovy-dsl-rendered-shape)
- [Sources](#sources)

## Version and Task Model

The verified implementation baseline is Doma CodeGen Plugin `3.2.2`, plugin ID
`org.domaframework.doma.codegen`, with Gradle 8+ and Java 17+. Preserve an
existing compatible CodeGen version; do not interpret this baseline as
permission to upgrade a project.

Registering the named configuration `domaSync` produces the official
entity-only task `domaCodeGenDomaSyncEntity`. Never invoke an `All`, DAO, SQL,
DTO, SQL-test, build, or migration CodeGen task for synchronization.

CodeGen 3.2.2 validates each registered configuration after project evaluation.
An unconditional environment-backed registration would make ordinary `clean`,
`build`, and IDE import fail without database inputs. The managed block
therefore registers `domaSync` only when a requested task basename starts with
`domaCodeGenDomaSync`.

`domaSyncWriteCodeGenClasspath` is a skill-managed helper, not an official Doma
task. It writes the resolved `domaCodeGen` classpath to
`build/doma-codegen/codegen-classpath.txt` so the bundled JDBC snapshot helper
uses the same driver.

## Plan and Apply

Use an exact project-selected or separately verified driver coordinate. For
PostgreSQL pass `--schema`; for MySQL pass `--catalog`.

```bash
python3 ./scripts/configure-codegen.py plan \
  --project-root . --language java --database postgresql \
  --entity-package com.example.entity --schema public \
  --table-pattern 'tenant_.*' --codegen-version 3.2.2 \
  --driver-coordinate org.postgresql:postgresql:42.7.10 \
  --metamodel true --output-plan build/doma-codegen/configure-plan.json
```

Exit `2` means the deterministic plan contains a build-file change; exit `0`
means no change. Inspect the JSON mutations and reconstruct the proposed build
diff before applying:

```bash
python3 ./scripts/configure-codegen.py apply \
  --project-root . --plan build/doma-codegen/configure-plan.json
```

Apply returns `66` when the build hash is stale and `65` for unsafe project
state. It preserves LF/CRLF and uses atomic replacement. After apply, rerun
`plan` with the same inputs and require the newly generated plan to contain no
mutations; do not re-apply the stale original plan.

The planner owns only marked plugin/driver lines and the managed block. It
stops on multiple declarations, dynamic structures, an ambiguous unmanaged
`domaSync`, symlinks, project-local secrets, or unsupported declared toolchain
minimums.

## Provider and Output Contract

The managed object reads `DOMA_SYNC_JDBC_URL`, `DOMA_SYNC_JDBC_USER`, and
`DOMA_SYNC_JDBC_PASSWORD`, falling back to user Gradle properties
`domaSyncJdbcUrl`, `domaSyncJdbcUser`, and `domaSyncJdbcPassword`. The wrapper
supplies those only to the entity-task child. Do not put the values in the
managed block or a project file.

`sourceDir` is always `build/doma-codegen/generated`, outside all source roots.
Overwrite is enabled only inside that isolated candidate directory. The
configuration emits physical catalog/schema/table/column names and database
comments, disables listener and mapped-superclass file generation, sets Java or
Kotlin explicitly, and preserves the selected Metamodel policy.

## Kotlin DSL Rendered Shape

The configuration planner renders this tested shape (values vary by plan):

```kotlin
tasks.register("domaSyncWriteCodeGenClasspath") {
    doLast {
        file("build/doma-codegen/codegen-classpath.txt").apply {
            parentFile.mkdirs()
            writeText(configurations.getByName("domaCodeGen").asPath)
        }
    }
}
if (gradle.startParameter.taskNames.any { it.substringAfterLast(":").startsWith("domaCodeGenDomaSync") }) {
    domaCodeGen {
        register("domaSync") {
            val domaSyncJdbcUrl = providers.environmentVariable("DOMA_SYNC_JDBC_URL").orElse(providers.gradleProperty("domaSyncJdbcUrl")).map { jdbcUrl ->
                if (Regex("""jdbc:[^\s]+://[^/@\s]+@""", RegexOption.IGNORE_CASE).containsMatchIn(jdbcUrl)) {
                    throw GradleException("Credential-bearing JDBC URL is unsafe")
                }
                jdbcUrl
            }
            url.set(domaSyncJdbcUrl)
            user.set(providers.environmentVariable("DOMA_SYNC_JDBC_USER").orElse(providers.gradleProperty("domaSyncJdbcUser")))
            password.set(providers.environmentVariable("DOMA_SYNC_JDBC_PASSWORD").orElse(providers.gradleProperty("domaSyncJdbcPassword")))
            sourceDir.set(layout.projectDirectory.dir("build/doma-codegen/generated"))
            languageType.set(org.seasar.doma.gradle.codegen.desc.LanguageType.JAVA)
            entity {
                packageName.set("com.example.entity")
                schemaName.set("public")
                tableNamePattern.set("tenant_.*")
                showCatalogName.set(false)
                showSchemaName.set(true)
                showTableName.set(true)
                showColumnName.set(true)
                showDbComment.set(true)
                overwrite.set(true)
                useListener.set(false)
                useMappedSuperclass.set(false)
                useMetamodel.set(true)
            }
        }
    }
}
```

## Groovy DSL Rendered Shape

The Groovy renderer uses the same decisions:

```groovy
tasks.register('domaSyncWriteCodeGenClasspath') {
    doLast {
        file('build/doma-codegen/codegen-classpath.txt').with {
            parentFile.mkdirs()
            text = configurations.getByName('domaCodeGen').asPath
        }
    }
}
if (gradle.startParameter.taskNames.any { it.tokenize(':').last().startsWith('domaCodeGenDomaSync') }) {
    domaCodeGen {
        register('domaSync') {
            def domaSyncJdbcUrl = providers.environmentVariable('DOMA_SYNC_JDBC_URL').orElse(providers.gradleProperty('domaSyncJdbcUrl')).map { jdbcUrl ->
                if (jdbcUrl =~ /(?i)jdbc:[^\s]+:\/\/[^\/@\s]+@/) {
                    throw new GradleException('Credential-bearing JDBC URL is unsafe')
                }
                jdbcUrl
            }
            url.set(domaSyncJdbcUrl)
            user.set(providers.environmentVariable('DOMA_SYNC_JDBC_USER').orElse(providers.gradleProperty('domaSyncJdbcUser')))
            password.set(providers.environmentVariable('DOMA_SYNC_JDBC_PASSWORD').orElse(providers.gradleProperty('domaSyncJdbcPassword')))
            sourceDir.set(layout.projectDirectory.dir('build/doma-codegen/generated'))
            languageType.set(org.seasar.doma.gradle.codegen.desc.LanguageType.KOTLIN)
            entity {
                packageName.set('com.example.entity')
                catalogName.set('app')
                tableNamePattern.set('tenant_.*')
                showCatalogName.set(true)
                showSchemaName.set(false)
                showTableName.set(true)
                showColumnName.set(true)
                showDbComment.set(true)
                overwrite.set(true)
                useListener.set(false)
                useMappedSuperclass.set(false)
                useMetamodel.set(true)
            }
        }
    }
}
```

The planner also adds or repairs the exact plugin declaration and one
`domaCodeGen` driver dependency in the existing `plugins` and `dependencies`
blocks.

## Sources

- [Doma CodeGen documentation](https://docs.domaframework.org/en/stable/codegen/)
- [CodeGen 3.2.2 task registration](https://github.com/domaframework/doma-codegen-plugin/blob/v3.2.2/codegen/src/main/java/org/seasar/doma/gradle/codegen/CodeGenPlugin.java)
- [CodeGen 3.2.2 main configuration](https://github.com/domaframework/doma-codegen-plugin/blob/v3.2.2/codegen/src/main/java/org/seasar/doma/gradle/codegen/extension/CodeGenConfig.java)
- [CodeGen 3.2.2 entity configuration](https://github.com/domaframework/doma-codegen-plugin/blob/v3.2.2/codegen/src/main/java/org/seasar/doma/gradle/codegen/extension/EntityConfig.java)
