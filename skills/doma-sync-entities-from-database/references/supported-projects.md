# Supported Projects

## Accept the Project Only After Inspection

Select one Gradle project or subproject whose build and entity source roots are
unambiguous. Record:

- the selected project root and `build.gradle.kts` or `build.gradle`;
- Gradle wrapper, Java toolchain, Kotlin, Doma, processor, CodeGen, and JDBC
  driver versions;
- Java `annotationProcessor` or Kotlin KAPT wiring and the existing clean-build
  command;
- entity language, package, conventional source root, `@Table` identities,
  Domain declarations, custom annotations, and Metamodel policy;
- any existing `org.domaframework.doma.codegen` plugin, `domaCodeGen`
  dependency, or named CodeGen configuration.

Run the current compile/annotation-processing gate before configuration. Stop
if it fails or no expected generated DAO implementation appears. Synchronizing
entities must not disguise an existing Doma setup problem.

## Supported Matrix

| Concern | Supported |
| --- | --- |
| Build | Gradle Kotlin DSL (`build.gradle.kts`) or Groovy DSL (`build.gradle`) |
| Minimums for CodeGen 3.2.2 | Gradle 8+, Java 17+ |
| Entity source | Java under `src/main/java`; Kotlin under `src/main/kotlin` |
| Language selection | `java`, `kotlin`, or merge-only `auto` for both conventional roots |
| Database | PostgreSQL or MySQL |
| Doma processing | Existing Java annotation processing or Kotlin KAPT that already builds |
| Project layout | One explicitly selected root; a selected subproject is treated as its own root |

The source research baseline is Doma `3.14.1-SNAPSHOT`; released compile
fixtures use Doma `3.14.0`. These are evidence baselines, not instructions to
replace a target project's compatible released Doma version.

For a multi-project build, identify the one subproject containing the build file
and conventional entity roots, then pass that directory as `--project-root`.
Do not run the configuration planner at the aggregate root when the actual
plugin/dependencies/entities live in a child project. Do not span multiple
subprojects in one plan.

## Cleanliness Gate

Inspect Git status before planning and again before apply.

- A dirty selected build file blocks configuration apply.
- A dirty entity that could be edited blocks the complete merge apply before
  the first write.
- Unrelated dirty files may remain, but identify them as pre-existing in the
  final report.
- Never stage, commit, reset, restore, stash, or discard project changes for
  this workflow.

The scripts also reject stale hashes, symlinked inputs or targets, path escape,
source collisions, and ambiguous Gradle structures. Treat those stops as
safety results, not invitations to hand-edit around the checks.

## Fail-Closed Shapes

Stop or narrow the task when any of these is present:

- Maven or both `build.gradle.kts` and `build.gradle` in the selected root;
- Gradle below 8, Java below 17, a non-conventional source root, or a custom
  generated-source layout;
- broken Java processor/KAPT setup;
- dynamically constructed plugin/dependency blocks that cannot be edited
  locally and deterministically;
- an unmanaged `domaSync` CodeGen configuration whose ownership is ambiguous;
- custom CodeGen templates or naming rules not proven by the candidate model;
- mixed entity languages when the requested scope/root cannot be expressed by
  one exact `java`, `kotlin`, or `auto` merge request.

Do not migrate Maven to Gradle, KSP to KAPT, Java to Kotlin, or upgrade Gradle,
Java, Kotlin, Doma, CodeGen, or the JDBC driver as an implicit prerequisite.
Report the unsupported shape and request a separate explicit decision.

## Sources

- [Doma 3.14.0: Building an application](https://docs.domaframework.org/en/3.14.0/build/)
- [Doma 3.14.0: Annotation processing](https://docs.domaframework.org/en/3.14.0/annotation-processing/)
- [Doma CodeGen Plugin prerequisites](https://docs.domaframework.org/en/stable/codegen/)
- [Doma CodeGen Plugin 3.2.2](https://plugins.gradle.org/plugin/org.domaframework.doma.codegen/3.2.2)
