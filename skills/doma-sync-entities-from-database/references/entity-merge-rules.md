# Entity Merge Rules

## Contents

- [Three inputs and their authority](#three-inputs-and-their-authority)
- [Plan](#plan)
- [SAFE](#safe)
- [REVIEW_REQUIRED](#review_required)
- [BLOCKED](#blocked)
- [Apply and result states](#apply-and-result-states)
- [Required report](#required-report)

## Three Inputs and Their Authority

The JDBC snapshot is authoritative for physical catalog/schema/table/column
identity, JDBC and native database type, size/precision/scale, nullability,
default, auto-increment, database remarks, and ordered primary-key membership.
Unknown metadata stays unknown.

The isolated CodeGen candidate is authoritative only for the verified CodeGen
3.2.2 Java/Kotlin source shape and basic type mapping. It is not authoritative
for native SQL type names or application intent.

Existing source is authoritative for application semantics: Domain types,
`@TenantId`, `@Version`, transient/association/embedded mappings, custom
annotations, handwritten methods/accessors/comments, inheritance, interfaces,
records, data classes, constructor properties, Lombok, naming choices, and
references from the rest of the project.

Match tables only by exact catalog/schema/table identity and properties only by
exact physical column identity. Never infer a rename from similar names, file
paths, class names, or types.

## Plan

Create a non-mutating plan and diff:

```bash
python3 ./scripts/compare-and-merge-entities.py plan \
  --project-root . \
  --schema-snapshot build/doma-codegen/schema-snapshot.json \
  --generated-dir build/doma-codegen/generated \
  --existing-root src/main/java --language java \
  --output-plan build/doma-codegen/merge-plan.json \
  --output-diff build/doma-codegen/merge.diff
```

Repeat `--existing-root` for both conventional roots and use `--language auto`
only for a deliberately mixed Java/Kotlin project. The plan binds its format,
language/root request, snapshot hash, every generated/existing/reference source
hash, normalized structures, finding details, edits, and stable finding IDs.
It contains project-relative paths and no timestamp, credential, URL, host,
user, classpath, or raw database exception.

## `SAFE`

The closed automatic set is:

- create a new entity only when the generated package/class/property/file
  identity, exact complete columns, CodeGen basic types, Kotlin
  nullability/defaults, ordered IDs, identity generation, database remarks,
  source root, and collision checks all agree with the complete snapshot;
- add a generated-shaped property when exact identity and required metadata
  are proven;
- add or unambiguously correct an explicit physical `@Column` mapping;
- synchronize all single/composite primary-key `@Id` annotations as one atomic
  finding when every key column and sequence is known;
- add `@GeneratedValue` only when affirmative auto-increment metadata and the
  generated candidate agree;
- widen a supported basic type when no retained project reference makes the
  signature change unsafe;
- apply a database comment only when the candidate payload exactly equals the
  snapshot remark and the existing location is an empty generated placeholder;
- add only a new property or atomic key synchronization around an otherwise
  unsupported handwritten method/custom annotation when every candidate and
  metadata check remains complete and consistent.

No change is SAFE merely because CodeGen emitted it.

## `REVIEW_REQUIRED`

Executable review proposals are limited to concrete generated-shaped changes:

- remove a generated property absent from the snapshot, only when no
  handwritten/project reference is found;
- narrow a supported basic type without a retained reference;
- change Kotlin nullability; or
- change Kotlin type and nullability together as one atomic declaration.

Each proposal includes database facts, existing and candidate excerpts,
impact/manual action, an exact unified diff, and a stable finding ID. Show that
complete proposal before requesting approval. Approval is the exact ID, not an
intent such as “accept removals,” and IDs are not reusable after any input
changes.

Property deletion is never automatic. Entity deletion is never an executable
review proposal.

## `BLOCKED`

Blocked findings contain no edit. Causes include:

- missing/removed entity, rename inference, identity mismatch, source/FQCN
  collision, duplicate/embedded mapping, parser error, or ambiguous annotation;
- Domain/basic uncertainty, `@TenantId`, `@Version`, association/transient/
  embedded semantics, inheritance/interfaces, record, Lombok, data class,
  primary-constructor property, custom template, or unsupported source shape;
- incomplete/unknown metadata needed for the proposed physical change;
- candidate/snapshot type, nullability, default, ID, generated-value, identity,
  or database-comment disagreement;
- any retained Java/Kotlin direct, accessor, callable, receiver-scope, factory,
  or inferred Entity reference affected by removal or signature change;
- dirty target, path/symlink escape, stale hash, tampered plan, unknown approval,
  or inability to reconstruct the exact canonical plan.

Do not hand-edit around a blocker. Report it with the needed manual decision or
source evidence.

## Apply and Result States

Apply SAFE changes only:

```bash
python3 ./scripts/compare-and-merge-entities.py apply \
  --project-root . --plan build/doma-codegen/merge-plan.json
```

After the user approves one displayed proposal:

```bash
python3 ./scripts/compare-and-merge-entities.py apply \
  --project-root . --plan build/doma-codegen/merge-plan.json \
  --approve REVIEW-EXACT-ID
```

Repeat `--approve` for independently approved IDs. Apply rechecks every input,
canonical plan, path, symlink, collision, and relevant Git state before its
first write. It prepares same-filesystem temporary files and atomically
replaces targets while preserving untouched bytes, UTF-8 BOM, line endings,
final newline, and permissions.

| State / exit | Meaning |
| --- | --- |
| `SUCCESS` / 0 | No unapproved review or blocked finding remains |
| `PENDING_REVIEW` / 2 | At least one executable review proposal is unapproved |
| `BLOCKED` / 3 | At least one fail-closed finding remains |
| 64 | Invalid input |
| 65 | Unsafe project state |
| 66 | Stale plan/input |
| 1 | Sanitized operational failure |

A plan can apply independent SAFE edits and still finish
`PENDING_REVIEW`/`BLOCKED`; report remaining findings. A clean build failure is
`FAILED`, never success.

## Required Report

Report, in order:

1. result state and selected project/language/root;
2. snapshot scope and candidate path;
3. every applied SAFE ID with path/table/column/kind;
4. every approved review ID and its exact applied impact;
5. every pending proposal with exact ID and diff location;
6. every blocked finding and required manual decision;
7. complete Git diff summary;
8. clean-build and Doma annotation-processing evidence;
9. second-generation/replan idempotence result;
10. pre-existing dirty files and credential provider names only.

## Sources

- [Doma entities](https://docs.domaframework.org/en/3.14.0/entity/)
- [Doma domain classes](https://docs.domaframework.org/en/3.14.0/domain/)
- [Doma CodeGen documentation](https://docs.domaframework.org/en/stable/codegen/)
