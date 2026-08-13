# Java Entity Merge

## Generated Shape the Parser Can Prove

The conservative parser recognizes the verified CodeGen 3.2.2 Java entity
shape: one top-level `@Entity`/`@Embeddable` class, explicit Doma table/column
annotations, fields, and either generated public fields or exact generated
getter/setter bodies. It preserves imports, annotations and arguments, types,
field/accessor spans, methods, comments, line endings, BOM, final newline, and
source permissions.

Before parsing entities, collect top-level project annotation and Domain
declarations across the conventional Java/Kotlin roots. Same-package
annotations can make wildcard Doma annotations ambiguous; exact Doma imports
and fully qualified annotations remain distinct.

The parser is deliberately narrower than Java or Doma. A source file can
compile correctly and still be ineligible for automatic edits.

## Eligible Edits

For a generated-only class with complete snapshot/candidate agreement, the
planner may:

- create the exact generated entity at its package-relative `.java` path;
- insert a generated field plus exact getter/setter pair;
- add/correct an explicit `@Column` mapping;
- add/remove `@Id` annotations as one atomic single/composite-key edit;
- add a proven identity `@GeneratedValue` annotation;
- widen a supported basic field/accessor type;
- insert an exact database comment into an empty generated comment slot.

A handwritten method or custom class annotation normally makes the file
non-generated-only. The planner may still localize only `add-property` and
atomic primary-key synchronization when the tested spans are independent and
all metadata/candidate checks remain complete. It must preserve the
handwritten slice byte-for-byte.

## Review-Only Edits

A generated-shaped property removal or basic-type narrowing may produce a
concrete `REVIEW_REQUIRED` proposal only when project-wide reference analysis
finds no use. The proposal includes the real field and accessor source and its
exact diff. It applies only with that finding ID.

Reference analysis includes Java direct fields/getters/setters and Kotlin calls
or callable references to the generated JVM accessors, including qualified,
parenthesized, factory-returned, inferred Entity, and common generic collection
extraction chains such as `get(index)`, `subList(...).get(index)`, and
`iterator().next()` Entity receivers. It scans the selected production roots
plus conventional compiled `src/test`, `src/integrationTest`,
`src/functionalTest`, and `src/testFixtures` Java/Kotlin roots when present.
It recognizes exact imports, qualified names, casts, and direct generic Entity
arguments (for example `Map<String, Employee>`); uncertain receiver typing is
not proof that an API-changing edit is safe. A direct generic Entity wrapper
is conservatively treated as an Entity receiver after one terminal unwrap
method/property (such as `Optional<Employee>.orElseThrow()`). A proven use
makes the finding `BLOCKED` and editless.

## Fail-Closed Java Constructs

Do not automatically edit a file when the affected structure includes:

- a record, Lombok-generated accessors, nested/anonymous type, multiple or
  ambiguous entities, unmatched lexical/body region, or non-template generic or
  interleaved modifiers;
- Domain-typed property, `@TenantId`, `@Version`, association, embedded,
  transient, inheritance, interface, custom/type-use annotation, initializer,
  handwritten method, or non-generated accessor;
- getter/setter clauses or comments between `)` and `{`, even if the body looks
  generated;
- duplicate/nonliteral physical column names, non-default implicit naming, or
  unsupported Doma annotation arguments/expressions;
- a property/type removal or signature change referenced anywhere in the
  analyzed project.

Entity deletion is always blocked. Similar class, property, or column names do
not prove a rename.

## Review Checklist

For every Java proposal, verify:

1. exact catalog/schema/table and physical column identity;
2. snapshot native/JDBC facts and complete key sequence;
3. candidate shape and basic type agree with those facts;
4. field and both accessors change together where applicable;
5. imports are deterministic and no custom annotation/method slice changes;
6. project-wide Java and Kotlin reference findings are empty;
7. the displayed diff is identical to the finding bound to the approval ID.

After apply, compile and verify Doma-generated sources, then regenerate/replan
and require an empty diff.

## Sources

- [Doma 3.14.0 entities](https://docs.domaframework.org/en/3.14.0/entity/)
- [Doma 3.14.0 domain classes](https://docs.domaframework.org/en/3.14.0/domain/)
- [CodeGen 3.2.2 Java entity template](https://github.com/domaframework/doma-codegen-plugin/blob/v3.2.2/codegen/src/main/resources/org/seasar/doma/gradle/codegen/template/java/entity.ftl)
