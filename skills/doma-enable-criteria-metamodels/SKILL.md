---
name: doma-enable-criteria-metamodels
description: Use when the Criteria API needs generated Doma metamodel classes such as Employee_, when @Metamodel or the doma.metamodel.enabled option must be configured in a Java or Kotlin build, when metamodel class names need a prefix or suffix, or when a build produces no *_ metamodel class or fails with DOMA4455.
---

# Enable Doma Criteria Metamodels

The Criteria API (`QueryDsl`, `KQueryDsl`) can only reference entity properties through generated metamodel classes. Metamodel generation is opt-in: without it, every `new Employee_()` is an unresolved symbol, not a Criteria API bug.

## Workflow

1. Confirm the Doma annotation processor already runs in this project. Look for existing generated Doma output (an entity meta class such as `_Employee.java`, or a `*DaoImpl.java`) under `build/generated` or `target/generated-sources`. If nothing is generated, the problem is project setup, not metamodels; fix the build wiring first and only then return here.
2. Choose the enablement scope, then apply it:
   - **Per entity (default choice).** Add the `metamodel` element to the entity's `@Entity` annotation. Prefer this when only some entities are queried through the Criteria API, and when the project must not depend on a build-tool option.
     ```java
     @Entity(metamodel = @Metamodel)
     public class Employee { /* @Id, properties, getters and setters */ }
     ```
     ```kotlin
     @Entity(metamodel = Metamodel())
     class Employee { /* @Id and properties */ }
     ```
     Kotlin uses the constructor-call form `Metamodel()`; the Java annotation form `@Metamodel` does not compile there.
   - **All entities at once.** Set the annotation processor option `doma.metamodel.enabled=true`. It generates metamodels for every entity class even when the entity has no `metamodel = @Metamodel` element. Read [Build Configuration](references/build-configuration.md) for the exact Gradle, KAPT, Maven, and `doma.compile.config` wiring.
   The two paths combine safely: the option is a project-wide default and the annotation stays valid.
3. Only if the default names are unacceptable, customize them. Defaults produce `Employee` -> `Employee_`. Names come from the annotation elements first, and from the `doma.metamodel.prefix` / `doma.metamodel.suffix` options when both annotation elements are empty. Read [Metamodel Naming](references/metamodel-naming.md) before setting either, because `prefix = "_"` with an empty suffix is a compile error (DOMA4455).
4. Rebuild from clean and verify that the class exists in generated sources, not just that the build passed:
   ```bash
   ./gradlew clean build
   find build/generated -type f -name 'Employee_.java' -print
   ```
   Use `target/generated-sources` for Maven, and the customized name when a prefix or suffix is configured. KAPT emits the metamodel as Java source, so search for `*_.java` in Kotlin projects too.
5. Reference the generated class from the query code only after step 4 succeeds: metamodels are generated into the entity's own package, and are instantiated per query (`Employee_ e = new Employee_();` / `val e = Employee_()`).
6. If generation or compilation fails, work through [Metamodel Troubleshooting](references/troubleshooting.md) in order instead of disabling validation options.

## What the generated class contains

A metamodel is a plain class in the entity's package implementing `EntityMetamodel<ENTITY>`:

- one `public final PropertyMetamodel<T>` field per persistent property, named after the **property**, not the column;
- a no-arg constructor, plus a constructor taking a qualified table name that overrides the entity's default table for that instance;
- `asType()` and `allPropertyMetamodels()`;
- any methods generated from the `scopes` element.

An `@Embeddable` property becomes a field of the embeddable's own nested metamodel type (generated as `_EmpInfo.Metamodel`), named after the property; its members are the embeddable's property metamodels, so query code reaches them by dot chain (`e.empInfo.hiredate`), and nested embeddables nest further. A `@Domain` property is a single `PropertyMetamodel<Name>` compared against whole domain values. `Optional<T>`, `OptionalInt`, `OptionalLong`, and `OptionalDouble` properties surface as the element type (`PropertyMetamodel<String>`, `PropertyMetamodel<Integer>`, ...), not as the optional wrapper. Non-persistent members have no property metamodel, so an association field or a `@Transient` field is absent by design. Immutable entities, Kotlin data classes, and Java records all support metamodels; the annotation goes on the entity declaration in every case (`@Entity(immutable = true, metamodel = @Metamodel)`, `@Entity(metamodel = @Metamodel) public record AverageSalary(Salary salary) {}`).

Instances are cheap and are created per query; two instances of the same metamodel represent two occurrences of the table, which is how a self-join is expressed.

## Reusable query conditions

`@Metamodel(scopes = { DepartmentScope.class })` adds generated condition methods to the metamodel. The scope class shape is checked at compile time (DOMA4457, DOMA4458, DOMA4459). Read [Scopes](references/scopes.md) when defining one.

## Reference map

| Need | Read |
| --- | --- |
| `doma.metamodel.enabled` wiring for Gradle, KAPT, Maven, `doma.compile.config`, plus verification commands | [Build Configuration](references/build-configuration.md) |
| Prefix and suffix precedence, default names, DOMA4455 | [Metamodel Naming](references/metamodel-naming.md) |
| Defining `@Scope` classes for the `scopes` element | [Scopes](references/scopes.md) |
| No metamodel generated, wrong name, stale generated sources, IDE-only failures | [Metamodel Troubleshooting](references/troubleshooting.md) |

## Boundary

This skill covers only making metamodel classes exist and be named as intended. It excludes writing Criteria API queries and statements, entity, domain, and embeddable design, initial project and annotation-processor setup, DAO and two-way SQL generation, KSP, aggregate strategies and `@AssociationLinker`, and runtime `Config` construction. Choosing whether newly generated entity candidates carry the `metamodel` element -- the Doma CodeGen `useMetamodel` setting -- belongs to database-driven entity generation, not here; this skill works on entities that already exist in the project. Metamodels are generated for `@Entity` classes only; `@Domain` and `@Embeddable` classes never get one.

## Version baseline

This skill targets released Doma `3.14.0`. The option names, the `prefix`/`suffix` precedence, the DOMA4455 rule, and the scope diagnostics are verified against that version. Keep the Doma version the project already selected, and re-check the official documentation for a newer release before relying on these rules there. `3.14.0` names the behavior this guidance describes; it is not a claim about the latest stable release.

## References

- [Doma 3.14.0: Annotation processing options](https://docs.domaframework.org/en/3.14.0/annotation-processing/)
- [Doma 3.14.0: Unified Criteria API](https://docs.domaframework.org/en/3.14.0/query-dsl/)
- [Doma 3.14.0: Kotlin support](https://docs.domaframework.org/en/3.14.0/kotlin-support/)
- [Doma 3.14.0: `@Metamodel`](https://docs.domaframework.org/en/3.14.0/apidocs/org/seasar/doma/Metamodel.html)
