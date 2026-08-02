# `doma-setup-project` Design

## Goal

Create the repository's first installable Doma skill. Help an agent add Doma to a plain Java project and reach a compiling, minimal database-access example without depending on repository-root research bundles.

Target the bundled Doma `3.14.1-SNAPSHOT` source snapshot as the research baseline. Describe it as a snapshot baseline, not as the latest stable release.

## Trigger Boundary

The skill should trigger for requests such as:

1. "Set up Doma in this Java Gradle project."
2. "Configure Doma annotation processing with Maven and create a minimal DAO."
3. "My first Doma project does not generate the DAO implementation; fix the setup."

It should not trigger for a request such as:

- "Write a complex Doma two-way SQL query with pagination and result mapping."

That nearby workflow belongs in a future DAO or two-way SQL skill.

## Scope

Cover:

- Gradle and Maven dependencies and annotation processor configuration.
- A plain Java setup using a minimal `Config`, entity, DAO, SQL file, and invocation path when all artifacts are necessary to demonstrate successful setup.
- Doma's source/resource path conventions that affect SQL discovery and generated DAO implementations.
- Compile-time verification and recovery from common initial annotation-processing failures.
- A concise decision workflow in `SKILL.md`, with build snippets, the complete example, and troubleshooting details disclosed through references.

Exclude:

- Spring Boot, Quarkus, and other framework-specific integration.
- Kotlin and KSP-specific setup.
- Advanced DAO queries, two-way SQL directives, Criteria API, transactions, migrations, and broad database-dialect guidance.
- Claims that Doma provides schema migration or general ORM behavior beyond the researched public contract.

## Repository Shape

Create:

```text
skills/doma-setup-project/
  SKILL.md
  agents/openai.yaml
  references/
    build-configuration.md
    minimal-java-project.md
    troubleshooting.md
README.md
```

Keep `SKILL.md` procedural and independently useful. Link each reference directly and state when to read it. Do not expose or require `prisma-skills.md` or `doma-project-bundle-*.md` in installed content.

## Evidence Plan

Research only narrow ranges from the bundles. Prefer:

1. `docs/getting-started.md`, `docs/build.md`, and `docs/annotation-processing.md` for intended setup.
2. Public `@Entity`, `@Dao`, `@Select`, `Config`, and related APIs for signatures and defaults.
3. Annotation processor tests for compile-time constraints and diagnostics.
4. Java integration tests for a working artifact layout and generated implementation usage.

Record stable official documentation URLs or upstream source paths in the skill references. Support exact defaults and restrictions with complementary evidence where practical.

## Validation

- Establish baseline behavior for the three positive prompts and one negative prompt before authoring the skill.
- Validate YAML, directory/frontmatter naming, links, placeholders, and source-bundle independence.
- Run `npx skills add . --list`.
- Copy-install `doma-setup-project` into a disposable directory and inspect the installed files.
- Re-run the trigger prompts with the skill and verify correct workflow selection and the negative boundary.
- Trace exact Doma claims and example details back to source notes.

## Future Expansion

Finish and validate this bounded skill before adding another. Expand toward the broader onboarding experience through neighboring skills for entities, DAOs/two-way SQL, selects/modifications, transactions, Criteria API, and framework integration. Change this skill's boundary only when setup users normally require the added guidance; otherwise link to a separate skill.
