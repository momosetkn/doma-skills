# Criteria Troubleshooting

- [Too many rows came back](#too-many-rows-came-back)
- [No rows came back](#no-rows-came-back)
- [EmptyWhereClauseException](#emptywhereclauseexception)
- [OptimisticLockException](#optimisticlockexception)
- [UniqueConstraintException](#uniqueconstraintexception)
- [NoSuchElementException in Kotlin](#nosuchelementexception-in-kotlin)
- [Unexpected duplicate rows](#unexpected-duplicate-rows)
- [Association properties are null or empty](#association-properties-are-null-or-empty)
- [A feature fails on one database only](#a-feature-fails-on-one-database-only)
- [Compilation cannot resolve the metamodel](#compilation-cannot-resolve-the-metamodel)
- [Migrating from Entityql and NativeSql](#migrating-from-entityql-and-nativesql)

Always start by printing the SQL. `stmt.asSql().getFormattedSql()` builds the statement without executing it, and `peek` shows intermediate stages; a missing clause in that output identifies the cause immediately.

## Too many rows came back

1. Print the SQL and compare its WHERE clause with the conditions in the code. A condition that is absent was dropped, not mis-evaluated.
2. The usual cause is a null right-hand operand: `eq`, `ne`, `gt`, `ge`, `lt`, `le`, `like`, `notLike`, `in`, `notIn` add nothing when the value is null, and `between` adds nothing unless both bounds are non-null. Use `eqOrIsNull` or `neOrIsNotNull` when null must mean `is null`, or reject null before building the query.
3. Check for a conditional block that did not run, and for a join whose `on` declaration evaluated no operator and therefore vanished.
4. For a select, confirm no `distinct()` or projection change altered the duplicate-removal behavior described below.

## No rows came back

1. Print the SQL and look for `in (null)`. An empty collection passed to `in` produces `in (null)`, which matches nothing, while a null collection would have dropped the predicate. Guard empty lists explicitly.
2. Check that a joined entity's condition is not filtering the driving table through an inner join where a left join was intended.
3. For tuple results, remember that an entity element is null when all its columns are null; that is an empty left-join match, not a mapping failure.

## EmptyWhereClauseException

The statement evaluated no condition and the form protects against it. Decide which is true:

- The condition was supposed to exist: it was dropped by a null operand or a skipped branch; fix the condition.
- Affecting every row is intended: use `delete(e).all()`, or enable `allowEmptyWhere` in the statement settings. For a select, `allowEmptyWhere` defaults to permitting the empty clause, so an exception there means the code explicitly set it to false.

## OptimisticLockException

Thrown by entity-based `update` and `delete` when the entity has a `@Version` property and the update count is zero, which means another transaction changed or deleted the row.

1. Re-fetch the entity, re-apply the change, and retry, or report the conflict to the caller.
2. Do not "fix" it by switching to a set-based `update(e).set(...).where(...)`. That removes the protection instead of handling the conflict.
3. When a zero count is acceptable, set `suppressOptimisticLockException` and inspect the returned count.
4. `ignoreVersion` drops the version from the WHERE clause entirely; use it only for deliberate administrative overwrites.

## UniqueConstraintException

Raised by insert and update statements that violate a unique constraint. If the intent is upsert semantics, chain `onDuplicateKeyUpdate()` or `onDuplicateKeyIgnore()`, and with `values` supply `keys(...)` so the conflict target is explicit. Verify the generated SQL against the target database, because the emulation differs per dialect.

## NoSuchElementException in Kotlin

`KQueryDsl.fetchOne()` throws when there is no row, unlike Java's `fetchOne()`, which returns null. Use `fetchOneOrNull()`. This is the most frequent defect in code ported from Java.

## Unexpected duplicate rows

Duplicate removal depends on the projection method: no projection method removes duplicates, `project` and `projectTo` remove them, and `select` and `selectTo` do not. Joining a one-to-many relationship and then using `select` returns one row per child. Choose `project`/`projectTo`, add `distinct()`, or aggregate.

## Association properties are null or empty

1. `associate` and `associateWith` require the other entity to be joined in the same statement. Verify the join is present in the printed SQL.
2. With a dynamic join, pass `AssociationOption.optional()`; a mandatory association plus a skipped join cannot be satisfied.
3. Use `associateWith` for immutable entities: `associate` mutates the instance, which an immutable entity cannot do, so the associator must return a copy.
4. Confirm the associator actually assigns both directions when the code later reads the reverse property.

## A feature fails on one database only

| Feature | Established support |
| --- | --- |
| `returning()` | Documented for the H2, PostgreSQL, SQL Server, and SQLite dialects. Doma's integration tests additionally skip MySQL and Oracle. |
| Common table expressions | Doma's integration tests skip the CTE cases on MySQL. |
| `forUpdate()` | Doma's integration test for it skips SQLite. Locking options beyond a plain `for update` are dialect-specific. |
| Upsert (`onDuplicateKeyUpdate` / `onDuplicateKeyIgnore`) | Emulated per dialect; verify the generated SQL. |

Match the `Dialect` configured in `Config` to the actual database, then print the SQL and, when necessary, replace the feature (for example, re-select instead of `returning`).

## Compilation cannot resolve the metamodel

`Employee_` is generated code. If it cannot be resolved, this is a metamodel-generation problem, not a query problem: confirm the entity opts in with `metamodel = @Metamodel` / `Metamodel()` or that `doma.metamodel.enabled=true` reaches the processor, then clean-build. No change to the query code can create the class.

## Migrating from Entityql and NativeSql

Doma documents the `Entityql` and `NativeSql` DSLs as the classic Criteria API superseded by the unified `QueryDsl`, which merges both. When touching classic code:

- Replace `new Entityql(config)` and `new NativeSql(config)` with `new QueryDsl(config)`; `KEntityql` and `KNativeSql` become `KQueryDsl`.
- Entityql entity operations map to `single`, `batch`, and `multi`; NativeSql set operations map to `values`, `select`, `set`, `where`, and `all`. The unified DSL exposes both families from the same entry point, which is why the entity/set-based distinction must now be chosen deliberately.
- Migrate one statement at a time and compare `asSql()` output before and after, so a semantic change such as losing optimistic locking cannot pass unnoticed.
- Do not write new code against the classic DSLs.

## References

- [Doma 3.14.0: Unified Criteria API](https://docs.domaframework.org/en/3.14.0/query-dsl/)
- [Doma 3.14.0: Classic Criteria API](https://docs.domaframework.org/en/3.14.0/criteria-api/)
- [`WhereDeclaration` javadoc](https://www.javadoc.io/doc/org.seasar.doma/doma-core/latest/org/seasar/doma/jdbc/criteria/declaration/WhereDeclaration.html)
