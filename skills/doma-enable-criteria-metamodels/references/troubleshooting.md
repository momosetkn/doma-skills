# Metamodel Troubleshooting

- [No metamodel class is generated](#no-metamodel-class-is-generated)
- [The metamodel has the wrong name](#the-metamodel-has-the-wrong-name)
- [Compilation fails with DOMA4455](#compilation-fails-with-doma4455)
- [The IDE reports an error but the build succeeds](#the-ide-reports-an-error-but-the-build-succeeds)
- [Property fields are missing from the metamodel](#property-fields-are-missing-from-the-metamodel)
- [References](#references)

Work through the matching section in order. Never disable `doma.sql.validation` or `doma.version.validation` to make a metamodel appear; neither affects metamodel generation.

## No metamodel class is generated

1. Check whether the annotation processor ran at all. Confirm that some Doma output exists for the same entity, such as `_Employee.java`. If nothing is generated, fix project setup and annotation processing first; nothing in this skill can substitute for a processor that never executes.
2. Confirm the class is an `@Entity` class. Metamodels are generated for entities only.
3. Confirm the opt-in reached the processor:
   - the entity carries `metamodel = @Metamodel` (Java) or `metamodel = Metamodel()` (Kotlin); or
   - `doma.metamodel.enabled=true` is passed by the build tool or set in `doma.compile.config`.
4. For Kotlin, verify the option is in the `kapt` block's `arguments`, not in `compileJava.options.compilerArgs`; javac arguments do not reach the KAPT tasks. Confirm the KAPT tasks actually ran in the build output.
5. Rebuild from clean. An incremental build that did not recompile the entity does not regenerate its metamodel.
6. Search recursively rather than assuming an output directory:
   ```bash
   find build/generated target/generated-sources -type f -name '*_.java' -print 2>/dev/null
   ```

## The metamodel has the wrong name

1. Remember the precedence: non-empty `prefix`/`suffix` elements on `@Metamodel` win over `doma.metamodel.prefix`/`doma.metamodel.suffix`, which apply only when both elements are empty.
2. Check both places before changing either. A project-wide option plus a per-entity element is the usual cause of one entity disagreeing with the rest.
3. After changing a name, clean-build. A previously generated class with the old name can remain in the output directory and hide the change.

## Compilation fails with DOMA4455

```text
[DOMA4455] The combination of the prefix="_" and the suffix="" is not allowed.
```

`prefix = "_"` with an empty suffix collides with the `_Employee` entity meta class Doma generates. Give a non-empty suffix or pick another prefix. `prefix = "Q"` with an empty suffix is accepted, so do not generalize this to all empty suffixes.

## The IDE reports an error but the build succeeds

The command-line build is the source of truth. When `./gradlew clean build` generates the class and the IDE still reports an unresolved metamodel, re-import or refresh the project so the IDE picks up the generated-source directory and the processor options. For Eclipse with Gradle, annotation processor options require the `com.diffplug.eclipse.apt` plugin and a Gradle project refresh; for Maven, use Update Project. Options placed in `doma.compile.config` apply across build tools and IDEs, which makes them the most reliable choice when IDE and build disagree.

## Property fields are missing from the metamodel

1. Only persistent entity properties become property metamodels. A field excluded from persistence, such as one annotated with `@Transient`, has no property metamodel by design.
2. If a property type is a `@Domain` or `@Embeddable` type, confirm that type also compiles cleanly; its processor error surfaces first and stops the metamodel from being complete.
3. Read the first Doma diagnostic in the build output for the entity itself. A metamodel is generated from the same entity metadata as the entity meta class, so an entity-level error is the real cause.

## References

- [Doma 3.14.0: Annotation processing options](https://docs.domaframework.org/en/3.14.0/annotation-processing/)
- [Doma 3.14.0: Entity classes](https://docs.domaframework.org/en/3.14.0/entity/)
- [Doma 3.14.0: Unified Criteria API](https://docs.domaframework.org/en/3.14.0/query-dsl/)
