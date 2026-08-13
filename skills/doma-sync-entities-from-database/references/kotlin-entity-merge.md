# Kotlin Entity Merge

## Generated Shape the Parser Can Prove

The verified CodeGen 3.2.2 Kotlin shape is a plain top-level class with body
`var` properties. The parser preserves annotations and raw arguments, imports,
KDoc/comments, native `T?` nullability, declaration/default spans, methods,
line endings, BOM, final newline, and permissions.

Before entity parsing, collect project annotation and Domain declarations from
both conventional source roots. This makes same-package/wildcard annotation
and Domain resolution fail closed instead of guessing.

Kotlin nullability comes from the generated declaration and must agree with the
snapshot. CodeGen primitive defaults are part of the proven declaration shape:
non-null generated primitives use their verified sentinel defaults, while
nullable properties use `null`. Do not independently rewrite only `?` when the
initializer must change too.

## Eligible Edits

For a generated-only body-property entity with complete snapshot/candidate
agreement, the planner may:

- create the exact generated entity at its package-relative `.kt` path;
- add a complete generated body property;
- add/correct explicit physical `@Column` identity;
- synchronize the complete single/composite `@Id` set atomically;
- add a proven identity `@GeneratedValue`;
- widen a supported basic property declaration;
- add an exact authoritative database KDoc/comment.

Around a tested handwritten method or custom class annotation, only a
non-overlapping new body property or atomic key synchronization can remain
SAFE, and only when no candidate inconsistency or incomplete metadata exists.
All handwritten slices stay byte-identical.

## Review-Only Edits

These generated-shaped changes require an exact proposal ID:

- remove a property absent from the snapshot when no reference remains;
- narrow a basic type when no reference remains;
- change nullability; or
- change type and nullability together.

A simultaneous type/nullability change is one atomic
`kotlin-type-nullability` proposal. Its edit replaces the complete generated
declaration, including initializer and required imports. Approving an obsolete
type-only or nullability-only ID is invalid.

Reference analysis includes Kotlin direct/safe/non-null calls, callable
references, inferred Entity assignments, Entity-returning factories,
qualified/parenthesized receivers, common generic collection extraction through
`get(index)`, indexing, `first`, and `filter` chains, extension functions,
labeled receiver
scopes, and `with`, `apply`, `run`, `let`, or `also`; it also includes Java JVM
getter/setter references. Any affected use makes removal or signature change
`BLOCKED`.

## Fail-Closed Kotlin Constructs

Do not automatically edit an affected structure containing:

- a primary-constructor property, data class, secondary/complex constructor,
  delegated/destructuring property, custom accessor, initializer block, nested
  class/object, generic/non-template modifier, or unmatched/bodyless boundary;
- Domain type, tenant/version/association/embedded/transient semantics,
  inheritance/interfaces, custom/type-use annotation, or unsupported Doma
  annotation expression;
- duplicate/nonliteral column identity or non-default implicit naming;
- candidate/snapshot disagreement about type, nullable state, default,
  database comment, ID, generated value, class/package/file identity, or
  complete table columns;
- project-wide Java/Kotlin reference to a property being removed or whose JVM
  signature changes.

Entity deletion and inferred renames remain blocked. `data class` and
primary-constructor properties are never converted to the body-property CodeGen
shape automatically.

## Review Checklist

For every Kotlin proposal, verify:

1. exact physical table/column identity and complete metadata;
2. candidate `type`, `?`, and initializer as one coherent declaration;
3. ordered single/composite IDs and identity generation;
4. imports and source spans do not overlap handwritten KDoc, annotations, or
   methods;
5. cross-language reference findings are empty;
6. the displayed atomic diff exactly matches the approval ID.

After apply, run KAPT/Doma processing, inspect the generated DAO implementation,
then regenerate/replan and require an empty diff.

## Sources

- [Doma 3.14.0 Kotlin support](https://docs.domaframework.org/en/3.14.0/kotlin-support/)
- [Doma 3.14.0 entities](https://docs.domaframework.org/en/3.14.0/entity/)
- [CodeGen 3.2.2 Kotlin entity template](https://github.com/domaframework/doma-codegen-plugin/blob/v3.2.2/codegen/src/main/resources/org/seasar/doma/gradle/codegen/template/kotlin/entity.ftl)
