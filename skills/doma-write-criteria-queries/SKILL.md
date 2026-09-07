---
name: doma-write-criteria-queries
description: Use when writing or fixing Doma Criteria API queries and statements with QueryDsl or Kotlin KQueryDsl - selects with joins, associations, projections, tuples, aggregates, subqueries, CTEs, and inserts, updates, deletes, upserts, batch and multi-row statements, returning clauses, optimistic locking, and empty-WHERE or silently-dropped-condition problems.
---

# Write Doma Criteria API Queries and Statements

The Criteria API builds SQL from typed metamodels at runtime. Most defects are not compile errors: a condition silently disappears, a statement skips optimistic locking, or duplicate rows appear. Decide the statement form first, then verify the generated SQL before executing it.

## Prerequisites

1. The entity must already have a generated metamodel (`Employee_`). If it does not, generate it first; instantiating a missing metamodel is a setup problem, not a query problem.
2. Get an entry point:
   - Java: `QueryDsl dsl = new QueryDsl(config);`
   - Java inside a `@Dao` default method: `QueryDsl.of(this)`, which is shorthand for `new QueryDsl(Config.get(this))`.
   - Kotlin: `val dsl = KQueryDsl(config)`, from `org.seasar.doma.kotlin.jdbc.criteria.KQueryDsl` in the `doma-kotlin` artifact. Kotlin projects must depend on `doma-kotlin`, not `doma-core`.
3. Create one metamodel instance per table occurrence in the statement, and reuse that instance for every reference to it. A self-join needs two instances (`Employee_ e = new Employee_(); Employee_ m = new Employee_();`).
4. Ignore `Entityql` and `NativeSql`. Doma documents them as the classic API superseded by the unified `QueryDsl`; use `QueryDsl` / `KQueryDsl` for new code and read [Migrating from Entityql and NativeSql](references/troubleshooting.md#migrating-from-entityql-and-nativesql) when touching existing classic code.

## Choose the statement form

| Goal | Form | Read |
| --- | --- | --- |
| Rows of the `from` entity, optionally filtered and joined | `dsl.from(e)...fetch()` | [Select Queries](references/select-queries.md) |
| A joined entity graph in one round trip | `innerJoin`/`leftJoin` plus `associate` (mutable) or `associateWith` (immutable) | [Select Queries](references/select-queries.md#associations) |
| Specific columns, tuples, rows, or a partly-filled entity | `select`, `selectAsRow`, `selectTo`, `project`, `projectTo` | [Select Queries](references/select-queries.md#projection) |
| Aggregates, arithmetic, string functions, CASE, literals, subquery values | `Expressions` (Java) / `KExpressions` (Kotlin) | [Expressions](references/expressions.md) |
| Insert, update, or delete entity instances you already hold | `insert/update/delete(e).single(entity)`, `.batch(list)`; insert alone adds `.multi(list)` | [Modification Statements](references/modification-statements.md) |
| Set-based insert, update, or delete by condition | `insert(e).values(...)`, `insert(e).select(...)`, `update(e).set(...).where(...)`, `delete(e).where(...)` | [Modification Statements](references/modification-statements.md#set-based-statements) |
| Read back the rows a statement wrote | `.returning()` | [Modification Statements](references/modification-statements.md#returning) |
| Any of the above in Kotlin | `KQueryDsl`, whose shape differs in named ways | [Kotlin KQueryDsl](references/kotlin-kquerydsl.md) |

## Rules that decide correctness

1. **A null right-hand operand removes the condition.** `c.eq(e.departmentId, null)` adds nothing, so the query returns everything instead of nothing. This is by design for dynamic conditions, and it applies to `eq`, `ne`, `gt`, `ge`, `lt`, `le`, `like`, `notLike`, `in`, `notIn`, and to `between` when either bound is null. When null must mean `is null`, use `eqOrIsNull` or `neOrIsNotNull`.
2. **An empty collection is not the same as null, for `notIn` too.** `c.in(e.employeeId, List.of())` generates `in (null)`, which matches no row; `c.notIn(e.employeeId, List.of())` generates `not in (null)`, which **also matches no row** under SQL three-valued logic -- the opposite of the "nothing excluded, keep everything" intuition. A null collection omits the predicate and matches every row. List elements are bound as-is, so a null element inside the list poisons the predicate the same way. Decide which one the caller means before passing a possibly-empty list.
3. **Empty WHERE clauses are rejected by default for the statement forms that protect against them.** A select whose settings set `allowEmptyWhere` to false, and a set-based update or delete with no evaluated condition, throw `EmptyWhereClauseException`. Enable `allowEmptyWhere` deliberately, or use `delete(e).all()` to state that deleting everything is intended.
4. **Entity-based and set-based statements have different semantics.** Entity statements (`single`/`batch`, plus `multi` for insert) run entity listeners and target rows by `@Id`; beyond that the guarantees are per statement kind -- insert initializes `@Version` and populates `@GeneratedValue` ids; update and delete add `@Version` and `@TenantId` to the WHERE clause, increment the version on update, and throw `OptimisticLockException` on a zero count; only a `single` update narrows the SET clause via `@OriginalStates`. `set`/`where` and `values` statements do none of that. Never swap one family for the other to "simplify" a fix.
5. **Duplicate handling differs per projection method.** With no projection method, duplicates are removed. `project` and `projectTo` remove duplicates; `select` and `selectTo` do not. `projectTo` and `selectTo` always include the entity's ID properties even when unlisted.
6. **`associate` requires a join.** Associate only entities that a join expression brought into the statement, and use `AssociationOption.optional()` when the join itself is conditional. Otherwise a dynamically skipped join makes the association fail.
7. **`returning` is dialect-limited.** H2, PostgreSQL, SQL Server, and SQLite only -- the canonical list lives in [Modification Statements](references/modification-statements.md#returning). Do not offer it for MySQL or Oracle.
8. **`like` does not escape wildcards by default.** `c.like(e.employeeName, value)` binds the value with `LikeOption.none()`, so `%` and `_` inside it act as wildcards. Pass `LikeOption.prefix()`, `infix()`, `suffix()`, or `escape()` for caller-supplied text; see [Select Queries](references/select-queries.md#like-options-and-wildcard-escaping).
9. **Kotlin is not a syntax skin.** `fetchOne()` throws `NoSuchElementException` on no rows in Kotlin while Java's returns null; use `fetchOneOrNull()`. Settings are assigned as properties inside a block, declarations take receiver lambdas with no `c ->`, and `KExpressions` replaces `Expressions`.

## Verify before executing

Build the statement, print the SQL, and only then run it:

```java
Listable<Department> stmt = dsl.from(d).where(c -> c.eq(d.departmentName, "SALES"));
Sql<?> sql = stmt.asSql();
System.out.println(sql.getFormattedSql());
```

For selects and set-based statements, `asSql()` builds the SQL without touching the database, so it is the cheapest way to prove a dynamic condition survived. **Entity-based statements are different**: their `asSql()` (and `peek`, which calls it) runs the same prepare pipeline as execution -- the statement's entity listeners fire, and an entity insert additionally initializes `@Version` and fetches a SEQUENCE- or TABLE-generated ID from the database at that moment. Treat entity-statement `asSql()` as a dry run with side effects, not a pure formatter. Confirm in the printed SQL that every condition you intended is present, then execute.

## When results or statements are wrong

Read [Criteria Troubleshooting](references/troubleshooting.md) and match the symptom: too many rows, no rows, missing WHERE, `EmptyWhereClauseException`, `OptimisticLockException`, `UniqueConstraintException`, `NoSuchElementException` in Kotlin, unexpected duplicates, null association properties, or a `returning`/CTE/`forUpdate` failure on a specific database.

## Reference map

| Need | Read |
| --- | --- |
| Fetching, projection, joins, associations, grouping, ordering, paging, locking, unions, derived tables, CTEs, subqueries | [Select Queries](references/select-queries.md) |
| Insert, update, delete, batch, multi-row, upsert, `returning`, settings, optimistic locking | [Modification Statements](references/modification-statements.md) |
| Aggregate, arithmetic, string, literal, CASE, subquery, and user-defined expressions | [Expressions](references/expressions.md) |
| Kotlin API differences, receiver lambdas, result types, and known gaps | [Kotlin KQueryDsl](references/kotlin-kquerydsl.md) |
| Symptom-driven diagnosis and classic-API migration | [Criteria Troubleshooting](references/troubleshooting.md) |

## Boundary

This skill covers writing Criteria API selects and modification statements with `QueryDsl` and `KQueryDsl`. It excludes generating and naming metamodel classes, `@Metamodel(scopes = ...)` definition, entity, domain, and embeddable design, project and annotation-processor setup, two-way SQL templates and `@Select`/`@Insert` DAO methods, aggregate strategies with `@AggregateStrategy` and `@AssociationLinker` (a DAO SQL feature, not a Criteria API one), stored procedures and functions, transaction and `Config` construction, and schema migration. Database-specific behavior is stated only where Doma's own documentation or integration tests establish it.

## Version baseline

This skill targets released Doma `3.14.0`; every API, default, and diagnostic described here is verified against that version. Keep the Doma version the project already selected, and re-check the official documentation for a newer release before relying on these rules there. Two kinds of statement age fastest and should be confirmed against the target database as well: the dialect limits for `returning`, common table expressions, and `forUpdate`, and the `KQueryDsl` gaps noted in [Kotlin KQueryDsl](references/kotlin-kquerydsl.md#known-gaps).

## References

- [Doma 3.14.0: Unified Criteria API](https://docs.domaframework.org/en/3.14.0/query-dsl/)
- [Doma 3.14.0: Classic Criteria API](https://docs.domaframework.org/en/3.14.0/criteria-api/)
- [Doma 3.14.0: Kotlin support](https://docs.domaframework.org/en/3.14.0/kotlin-support/)
- [`WhereDeclaration` javadoc](https://www.javadoc.io/doc/org.seasar.doma/doma-core/latest/org/seasar/doma/jdbc/criteria/declaration/WhereDeclaration.html)
- [`HavingDeclaration` javadoc](https://www.javadoc.io/doc/org.seasar.doma/doma-core/latest/org/seasar/doma/jdbc/criteria/declaration/HavingDeclaration.html)
