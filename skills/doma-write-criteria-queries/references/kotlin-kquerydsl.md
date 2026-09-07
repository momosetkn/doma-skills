# Kotlin KQueryDsl

- [Setup](#setup)
- [Shape differences](#shape-differences)
- [Result and fetch differences](#result-and-fetch-differences)
- [Expressions in Kotlin](#expressions-in-kotlin)
- [Naming collisions with Kotlin keywords](#naming-collisions-with-kotlin-keywords)
- [Known gaps](#known-gaps)

`KQueryDsl` wraps the Java `QueryDsl`, so the statement families and generated SQL largely map one-to-one -- but the Kotlin API surface has real gaps (`having` operators, upsert `keys`, scopes; see [Known gaps](#known-gaps)) and different result semantics. Do not assume a Java method exists in Kotlin without checking this file.

## Setup

- Depend on `org.seasar.doma:doma-kotlin`, not `doma-core`. `KQueryDsl` ships in `doma-kotlin`.
- Entities declare the metamodel with the constructor-call form: `@Entity(metamodel = Metamodel())`.
- Create the entry point with `val dsl = KQueryDsl(config)`.
- Immutable Kotlin entities are usually data classes whose association properties are `@Transient` and are filled by `associateWith` returning `copy(...)`.

## Shape differences

| Java | Kotlin |
| --- | --- |
| `dsl.from(e, settings -> settings.setMaxRows(100))` | `dsl.from(e) { maxRows = 100 }` |
| `.where(c -> { c.eq(e.id, 1); })` | `.where { eq(e.id, 1) }` |
| `.innerJoin(d, on -> on.eq(e.deptId, d.id))` | `.innerJoin(d) { eq(e.deptId, d.id) }` |
| `.associate(e, d, (emp, dept) -> emp.setDept(dept))` | `.associate(e, d) { emp, dept -> emp.dept = dept }` |
| `.orderBy(c -> c.asc(e.id))` | `.orderBy { asc(e.id) }` |
| `.set(c -> c.value(e.deptId, 3))` | `.set { value(e.deptId, 3) }` |
| `dsl.with(a, cteQuery)` | `dsl.with(a to cteQuery)` |

Declarations are receiver lambdas: there is no `c` parameter, and every operator is called directly. Settings are assigned as properties (`comment`, `sqlLogType`, `queryTimeout`, `allowEmptyWhere`, `fetchSize`, `maxRows`, `batchSize`, `ignoreVersion`, `suppressOptimisticLockException`, `excludeNull`) instead of through setters.

## Result and fetch differences

| Operation | Java | Kotlin |
| --- | --- | --- |
| Single row that may be absent | `fetchOne()` returns null | `fetchOne()` throws `NoSuchElementException`; use `fetchOneOrNull()` |
| Optional single row | `fetchOptional()` | `fetchOneOrNull()` |
| Set-based statement | `execute()` returns `int` | `execute()` returns `Int` |
| Entity statement | `execute()` returns `Result`/`BatchResult`/`MultiResult` | same types; read `result.count` and `result.entity` |
| `returning()` for one row | `fetchOne()` / `fetchOptional()` | `fetchOne()`, `fetchOneOrNull()`, and `execute()` all return the same single value |
| Projection with `project` / `projectTo` | `fetch()` | `fetch()` |
| Lazy processing of a large result | `mapStream(...)` / `collect(...)` / `openStream()` | `mapSequence { seq -> ... }` / `openStream()` |
| Eager stream or sequence over the fetched list | `stream()` | `sequence()` |

`mapSequence` is the Kotlin counterpart of `mapStream` and gives the block a lazy `Sequence`; there is no `collect`. `sequence()` and Java's `stream()` both build on the already-fetched list, so neither bounds memory.

The `fetchOne()` difference is the most common Kotlin-specific bug: code ported from Java keeps `fetchOne()` and starts throwing instead of returning null.

## Expressions in Kotlin

Use `KExpressions` where Java uses a statically imported `Expressions`. It carries the same catalog: `literal`, `add`, `sub`, `mul`, `div`, `mod`, `concat`, `lower`, `upper`, `trim`, `ltrim`, `rtrim`, `avg`, `avgAsDouble`, `count`, `countDistinct`, `max`, `min`, `sum`, `case`, `select`, `userDefined`. Some nested declarations still expect Java `Expressions` operands; see [Expressions](expressions.md#case).

## Naming collisions with Kotlin keywords

- `in` and `notIn`: call `` `in` `` with backticks.
- `when`: named `case` on `KExpressions`.

## Known gaps

`KHavingDeclaration` carries only the comparison base (`eq`, `ne`, `ge`, `gt`, `le`, `lt`, `isNull`, `isNotNull`, `eqOrIsNull`, `neOrIsNotNull`, `and`, `or`, `not`, `extension`): `between`, `in`, `like`, and `exists` do not exist in a Kotlin `having` block, unlike Java's `HavingDeclaration` and unlike Kotlin's own `where` and join `on`. None of the Kotlin entity upsert statements exposes `keys(...)`.


Generated `@Metamodel(scopes = ...)` methods return Java `Consumer<WhereDeclaration>` and similar types. As of Doma `3.14.0` the Kotlin declarations accept only Kotlin blocks and expose no `Consumer` overload, so scopes cannot be passed into a `KQueryDsl` clause. Express the shared condition as a Kotlin function that applies the block instead:

```kotlin
fun KWhereDeclaration.onlyTokyo(d: Department_) = eq(d.location, "Tokyo")

val list = dsl.from(d).where { onlyTokyo(d) }.fetch()
```

Re-check the current release before assuming this gap still exists.

## References

- [Doma 3.14.0: Kotlin-specific Criteria API](https://docs.domaframework.org/en/3.14.0/kotlin-support/)
- [Doma 3.14.0: Unified Criteria API](https://docs.domaframework.org/en/3.14.0/query-dsl/)
- [kotlin-sample project](https://github.com/domaframework/kotlin-sample)
