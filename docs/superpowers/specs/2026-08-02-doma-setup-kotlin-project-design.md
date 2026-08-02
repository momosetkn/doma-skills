# `doma-setup-kotlin-project` Design

## Goal

Create an installable Doma skill that helps an agent add Doma to a plain Kotlin
Gradle project, configure KAPT, create a minimal DAO, and verify that Doma
generates the DAO implementation.

Use the bundled Doma `3.14.1-SNAPSHOT` source as the research baseline. Describe
that version as a snapshot baseline, not as the latest stable release or a
dependency coordinate.

## Trigger Boundary

The skill should trigger for requests such as:

1. "Set up Doma and KAPT in this Kotlin Gradle project."
2. "Create the first Doma DAO in Kotlin and verify that its implementation is generated."
3. "KAPT runs, but my Kotlin Doma project does not generate `*DaoImpl`; diagnose it."

It should not trigger for a request such as:

- "Write a complex query with Doma's Kotlin-specific Criteria API in an already configured project."

That nearby workflow belongs in a future Kotlin Criteria API skill.

## Scope

Cover:

- A plain Kotlin/JVM project using Gradle Kotlin DSL.
- The Kotlin JVM and KAPT plugins.
- `doma-kotlin` on the implementation classpath and `doma-processor` on the
  KAPT processor path, using the same released Doma version.
- A minimal top-level Kotlin `@Dao` interface with an inline `@Sql` SELECT that
  exercises annotation processing without requiring a database or external SQL
  resource configuration.
- A clean build, recursive generated-source inspection, and recovery from
  common initial KAPT and Doma processor failures.
- The distinction between compile-time generation and runtime database access.

Exclude:

- Maven, Java-only setup, Spring Boot, Quarkus, and other framework integration.
- KSP configuration. The source baseline documents and exercises KAPT but does
  not establish a KSP workflow; the skill must not claim that KSP is supported
  or unsupported without separate current-version research.
- External SQL resources and `doma.resources.dir` configuration.
- Kotlin entity modeling, domain and embeddable design, Criteria API usage,
  transactions, migrations, and broad database-dialect guidance.

## Repository Shape

Create a structure parallel to the Java setup skill:

```text
skills/doma-setup-kotlin-project/
  SKILL.md
  agents/openai.yaml
  references/
    build-configuration.md
    minimal-kotlin-project.md
    troubleshooting.md
README.md
```

Keep `SKILL.md` procedural and independently useful. Put exact Gradle snippets,
the complete minimal example, and the diagnostic catalog in the three direct
references. Do not copy Java-specific instructions mechanically, and do not
make installed content depend on repository-root research bundles.

## Workflow and Failure Handling

The skill should direct an agent to inspect the existing Gradle Kotlin DSL
project before editing it, preserve its selected Kotlin and Gradle versions,
add KAPT and aligned Doma dependencies, add one minimal DAO, run a clean build,
and inspect generated sources recursively.

If compilation fails or no DAO implementation appears, diagnose plugin
application, dependency scopes and versions, whether KAPT actually ran, Kotlin
stub or processor diagnostics, the DAO's top-level interface shape, and the
generated-source search location before changing application logic. Do not hide
processor errors by disabling validation.

## Evidence Plan

Research only narrow bundle ranges. Prefer:

1. `docs/kotlin-support.md` for the public KAPT and `doma-kotlin` workflow.
2. `integration-test-kotlin/build.gradle.kts` for executable dependency and
   plugin wiring.
3. `docs/annotation-processing.md`, public annotations, and processor tests for
   generated DAO names, defaults, restrictions, and diagnostics.
4. Kotlin integration-test entities only for Kotlin behavior needed by this
   setup boundary.

Record stable official documentation URLs or upstream source pointers in the
skill references. Support important exact claims with complementary evidence
where practical.

## Validation

- Run the three positive trigger prompts and the negative prompt without the
  skill first, recording concrete omissions or wrong assumptions.
- Validate the directory/frontmatter name match, YAML, links, placeholders,
  and independence from root bundles.
- Run `npx skills add . --list`.
- Copy-install only `doma-setup-kotlin-project` into a disposable directory and
  inspect the copied contents.
- Re-run the trigger prompts with the skill and verify the KAPT workflow, the
  recovery path, and the negative Criteria API boundary.
- Compile a representative disposable Kotlin Gradle project when the available
  toolchain and dependency resolution permit it; otherwise report that limit
  separately from structural validation.
- Leave only the new skill directory and its README catalog update staged at
  handoff. Do not stage root research inputs or unrelated user files.

