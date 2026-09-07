# Select Queries

- [Settings](#settings)
- [Fetching](#fetching)
- [Streaming](#streaming)
- [Projection](#projection)
- [Where conditions](#where-conditions)
  - [LIKE options and wildcard escaping](#like-options-and-wildcard-escaping)
  - [Multi-column IN](#multi-column-in)
- [Joins](#joins)
- [Associations](#associations)
- [Grouping and having](#grouping-and-having)
- [Ordering, paging, distinct](#ordering-paging-distinct)
- [Row locking](#row-locking)
- [Unions](#unions)
- [Subqueries, derived tables, CTEs](#subqueries-derived-tables-ctes)

Java examples assume `QueryDsl dsl = new QueryDsl(config);`; Kotlin examples assume `val dsl = KQueryDsl(config)`. Both assume one metamodel instance per table occurrence.

## Settings

Optional per-statement settings: `allowEmptyWhere`, `comment`, `fetchSize`, `maxRows`, `queryTimeout`, `sqlLogType`.

```java
List<Employee> list = dsl.from(e, settings -> {
  settings.setAllowEmptyWhere(false);
  settings.setComment("all employees");
  settings.setFetchSize(100);
  settings.setMaxRows(100);
  settings.setQueryTimeout(1000);
  settings.setSqlLogType(SqlLogType.RAW);
}).fetch();
```

```kotlin
val list = dsl.from(e) {
    allowEmptyWhere = false
    comment = "all employees"
    fetchSize = 100
    maxRows = 100
    queryTimeout = 1000
    sqlLogType = SqlLogType.RAW
}.fetch()
```

Defaults: `allowEmptyWhere` is **true for selects** (a whole-table select is normal), `sqlLogType` is `FORMATTED`, and `fetchSize`, `maxRows`, and `queryTimeout` are 0, which defers to the same-named `Config` settings and ultimately the JDBC driver. `queryTimeout` counts **seconds** -- the examples' 1000 is nearly 17 minutes, not one second. `allowEmptyWhere = false` makes a select with no evaluated condition throw `EmptyWhereClauseException` instead of scanning the table -- a useful guard when every query is expected to be filtered.

## Fetching

| Java | Kotlin | Result |
| --- | --- | --- |
| `fetch()` | `fetch()` | `List` of results |
| `fetchOne()` | `fetchOne()` | Java returns null when there is no row; **Kotlin throws `NoSuchElementException`** |
| `fetchOptional()` | `fetchOneOrNull()` | `Optional` in Java, nullable in Kotlin |
| `stream()` | `sequence()` | eager stream/sequence built from the fetched list -- Kotlin statements have no `stream()` |

```java
Employee employee = dsl.from(e).where(c -> c.eq(e.employeeId, 1)).fetchOne();
Optional<Employee> optional = dsl.from(e).where(c -> c.eq(e.employeeId, 1)).fetchOptional();
```

```kotlin
val employee = dsl.from(e).where { eq(e.employeeId, 1) }.fetchOneOrNull()
```

## Streaming

`mapStream`, `collect`, and `openStream` process large results without materializing a list. A stream from `openStream` must be closed explicitly:

```java
try (Stream<Employee> stream = dsl.from(e).openStream()) {
  stream.forEach(employee -> { /* ... */ });
}

Map<Integer, List<Employee>> map = dsl.from(e).collect(groupingBy(Employee::getDepartmentId));
```

`stream()` is **not** one of these: it is defined as `execute().stream()`, so it fetches the whole result into a list first and only then streams over it. For a result set that should never be fully materialized, use `openStream`, `mapStream`, or `collect`.

Kotlin has its own pair on the same statements:

```kotlin
// mapSequence hands you a lazy Sequence and closes the underlying resources for you.
val map = dsl.from(e).mapSequence { seq -> seq.groupBy { it.departmentId } }

// openStream returns a java.util.stream.Stream that you MUST close.
dsl.from(e).openStream().use { stream ->
    stream.forEach { /* ... */ }
}
```

`sequence()` also exists on Kotlin statements, but like Java's `stream()` it is built from the already-fetched list, so it does not bound memory.

Even the lazy methods cannot bound memory on their own: whether rows actually stream from the server is decided by the JDBC driver and the `fetchSize` setting above, and several drivers buffer the entire result set unless their documented streaming conditions are met. Set `fetchSize` (and any driver-specific options) per your driver's documentation before relying on `openStream`/`mapStream` for very large results.

## Projection

| Method | Result type | Duplicates |
| --- | --- | --- |
| none | the `from` entity | removed |
| `project(d)` | the joined entity `d` | removed |
| `select(d, e)` | `Tuple2<Department, Employee>` | kept |
| `select(e.employeeName)` | single column | kept |
| `select(e.employeeName, e.employeeNo)` | `Tuple2` .. `Tuple9` | kept |
| `selectAsRow(...)` | `Row` (use beyond 9 columns) | kept |
| `projectTo(e, e.employeeName)` | partly-filled entity | removed by entity ID |
| `selectTo(e, e.employeeName)` | partly-filled entity | kept |

`projectTo` and `selectTo` always add the entity's ID properties to the select list, so the returned entities are identifiable. They accept only the entity's own property metamodels: an expression such as `sum(...)` or `concat(...)` is rejected at execution time with DOMA6008. In a tuple, an entity element is null when all of its properties are null, which is the normal outcome of a left join.

Read a tuple with `getItem1()` .. `getItem9()`; Kotlin can also destructure it through `component1()` .. `component9()`. A `Row` is keyed by property metamodel rather than by index, so read it with `row.get(e.employeeName)`, and inspect it with `containsKey`, `keySet`, `values`, and `size`.

```java
List<Tuple2<Department, Employee>> list = dsl
    .from(d)
    .leftJoin(e, on -> on.eq(d.departmentId, e.departmentId))
    .select(d, e)
    .fetch();
```

```kotlin
val list = dsl.from(e).projectTo(e, e.employeeName).fetch()
```

## Where conditions

Operators: `eq`, `ne`, `ge`, `gt`, `le`, `lt`, `isNull`, `isNotNull`, `like`, `notLike`, `between`, `in`, `notIn`, `exists`, `notExists`, plus `eqOrIsNull` and `neOrIsNotNull`. Logical operators: `and`, `or`, `not`. The left operand is always a property metamodel; there is no value-on-the-left overload, so write `c.gt(e.salary, value)`, never the flipped form.

```java
List<Employee> list = dsl
    .from(e)
    .where(c -> {
      c.eq(e.departmentId, 2);
      c.isNotNull(e.managerId);
      c.or(() -> {
        c.gt(e.salary, new Salary("1000"));
        c.lt(e.salary, new Salary("2000"));
      });
    })
    .fetch();
```

```kotlin
val list = dsl
    .from(e)
    .where {
        eq(e.departmentId, 2)
        isNotNull(e.managerId)
        or {
            gt(e.salary, Salary("1000"))
            lt(e.salary, Salary("2000"))
        }
    }
    .fetch()
```

An `@Embeddable` property is reached through its nested metamodel field: `c.eq(e.empInfo.hiredate, date)`. Varying `in`-list lengths defeat prepared-statement caching; `Config.getSqlBuilderSettings().shouldRequireInListPadding()` can pad the list to the next power of two -- a Config-level opt-in outside this skill's scope, noted because it changes the generated `in (...)`. Dynamic conditions need no builder: only the operators actually evaluated appear in the SQL, and a statement with none omits the WHERE clause entirely.

```java
.where(c -> {
  c.eq(e.departmentId, 1);
  if (enableNameCondition) {
    c.like(e.employeeName, name);
  }
})
```

Null and empty-collection semantics decide whether a filter exists at all; see the rules in `SKILL.md`. The property-to-property overloads (`c.eq(e.departmentId, d.departmentId)`) reject null and throw `NullPointerException` instead of dropping the condition.

### LIKE options and wildcard escaping

`like(property, value)` and `notLike(property, value)` bind the value with `LikeOption.none()`, which performs **no escaping**: any `%` or `_` inside the value acts as a wildcard. Search text that came from a caller must therefore pass an explicit option.

| Option | Effect |
| --- | --- |
| `LikeOption.none()` | default; binds the value as-is, no `escape` clause |
| `LikeOption.escape()` / `escape(char)` | escapes wildcards in the value; default escape character is `$` |
| `LikeOption.prefix()` / `prefix(char)` | escapes the value, then appends `%` (starts-with search) |
| `LikeOption.infix()` / `infix(char)` | escapes the value, then wraps it in `%` (contains search) |
| `LikeOption.suffix()` / `suffix(char)` | escapes the value, then prepends `%` (ends-with search) |

Every option other than `none` escapes through the dialect's `ExpressionFunctions` and appends `escape '<char>'` to the SQL.

```java
List<Employee> list = dsl
    .from(e)
    .where(c -> c.like(e.employeeName, userInput, LikeOption.prefix()))
    .fetch();
```

```kotlin
val list = dsl
    .from(e)
    .where { like(e.employeeName, userInput, LikeOption.prefix()) }
    .fetch()
```

Kotlin's `like` and `notLike` declare the option parameter with a default of `LikeOption.none()`, so omitting it is the same unescaped behavior as in Java. Do not hand-build `"%" + input + "%"` and pass it with `none()`; that reintroduces the wildcard injection the options exist to prevent.

### Multi-column IN

`in` and `notIn` also accept a `Tuple2` or `Tuple3` of property metamodels on the left, with a list of value tuples or a matching subquery on the right — the composite-key form of IN:

```java
List<Employee> list = dsl
    .from(e)
    .where(c -> c.in(
        new Tuple2<>(e.employeeId, e.employeeName),
        Arrays.asList(new Tuple2<>(2, "ALLEN"), new Tuple2<>(3, "WARD"))))
    .fetch();
```

```kotlin
val list = dsl
    .from(e)
    .where { `in`(Tuple2(e.employeeId, e.employeeName), listOf(Tuple2(2, "ALLEN"), Tuple2(3, "WARD"))) }
    .fetch()
```

This generates a row-constructor predicate (`where (ID, NAME) in ((?, ?), (?, ?))`), which not every database accepts: Doma's integration tests run the tuple forms only on H2, MySQL, PostgreSQL, SQLite, and Oracle. `KWhereDeclaration` exposes the `Tuple2` form only; the `Tuple3` form is Java-only. As with single-column `in`, a null right-hand list drops the predicate.

## Joins

`innerJoin` and `leftJoin` are the supported join expressions. The `on` declaration shares WHERE's full operator surface in both languages -- the declaration types extend the same `ComparisonDeclaration`, so `ne`, `ge`, `gt`, `le`, `lt`, `isNull`, `isNotNull`, `between`, `in`, `like`, `exists`, and the logical operators are all available, not just the `eq` the documentation showcases (the CTE example below joins on `ge`). It is dynamic in the same way as WHERE: if no operator is evaluated, the join is omitted from the SQL, and a null right-hand value drops that condition.

```java
List<Employee> list = dsl
    .from(e)
    .innerJoin(d, on -> on.eq(e.departmentId, d.departmentId))
    .fetch();
```

```kotlin
val list = dsl
    .from(e)
    .innerJoin(d) { eq(e.departmentId, d.departmentId) }
    .fetch()
```

An omitted join is a common cause of "the association is empty": the join disappeared, so nothing could be associated.

## Associations

Use `associate` for mutable entities and `associateWith` for immutable ones. Both require the second entity to be joined in the same statement.

```java
List<Employee> list = dsl
    .from(e)
    .innerJoin(d, on -> on.eq(e.departmentId, d.departmentId))
    .where(c -> c.eq(d.departmentName, "SALES"))
    .associate(e, d, (employee, department) -> {
      employee.setDepartment(department);
      department.getEmployeeList().add(employee);
    })
    .fetch();
```

```kotlin
val list = dsl
    .from(e)
    .innerJoin(d) { eq(e.departmentId, d.departmentId) }
    .associate(e, d) { employee, department -> employee.department = department }
    .fetch()
```

Immutable entities are associated by returning a copy:

```java
List<Emp> list = dsl
    .from(e)
    .innerJoin(d, on -> on.eq(e.departmentId, d.departmentId))
    .leftJoin(m, on -> on.eq(e.managerId, m.employeeId))
    .associateWith(e, d, Emp::withDept)
    .associateWith(e, m, Emp::withManager)
    .fetch();
```

```kotlin
val list = dsl
    .from(e)
    .innerJoin(d) { eq(e.departmentId, d.departmentId) }
    .leftJoin(m) { eq(e.managerId, m.employeeId) }
    .associateWith(e, d) { emp, dept -> emp.copy(department = dept) }
    .associateWith(e, m) { emp, manager -> emp.copy(manager = manager) }
    .fetch()
```

Associations are mandatory by default. When the join is conditional, pass `AssociationOption.optional()` as the last argument so the statement stays valid in the branch where the join is skipped. Chain several `associate` calls to build a wider graph; a projection method may follow the associations (`.associate(...).projectTo(e, e.employeeName)`).

Association results are always fully buffered: after `associate`/`associateWith` the statement offers only the eager fetch methods (`fetch`, `fetchOne`, `fetchOptional`, and the eager `stream()`/`sequence()`), not `openStream`, `mapStream`, or `collect` -- linking parent and child rows requires the whole result. Do not plan an associated query for a result set that must not be materialized.

## Grouping and having

`groupBy` takes property metamodels. When it is omitted and a **top-level** projection item is an `AggregateFunction` (`count()`, `sum(...)`, ...), Doma uses the remaining top-level items as the group keys. The check is a plain instanceof, so a wrapped aggregate such as `alias(count(), "CNT")` is not detected -- write an explicit `groupBy` whenever an aggregate is aliased or nested. Doma's documentation lists `eq`, `ne`, `ge`, `gt`, `le`, `lt` plus `and`, `or`, `not` for `having`; Java's declaration type shares WHERE's full comparison surface, and it is dynamic like WHERE. Kotlin is narrower: `KHavingDeclaration` adds nothing to the comparison base, so `between`, `in`, `like`, and `exists` are unavailable in a Kotlin `having` block even though Kotlin's `where` and join `on` have them.

Calling `groupBy` or `having` moves the statement into the projection family: the returned type no longer offers `associate`, `associateWith`, `project`, or `projectTo`, while `where`, `orderBy`, `limit`/`offset`, `distinct`, `forUpdate`, the `select` variants, `selectAsRow`, and `selectTo` remain available. Build entity graphs before grouping, or aggregate in a separate query.

```java
List<Tuple2<Long, String>> list = dsl
    .from(e)
    .innerJoin(d, on -> on.eq(e.departmentId, d.departmentId))
    .having(c -> c.gt(count(), 3L))
    .orderBy(c -> c.asc(count()))
    .select(count(), d.departmentName)
    .fetch();
```

```kotlin
val list = dsl
    .from(e)
    .groupBy(e.departmentId)
    .having { gt(KExpressions.count(), 3L) }
    .select(e.departmentId, KExpressions.count())
    .fetch()
```

## Ordering, paging, distinct

`orderBy` supports `asc` and `desc` and is dynamic. `limit` and `offset` accept null, in which case the corresponding clause is omitted, so a nullable page size needs no conditional code. `distinct()` adds `select distinct`, and `distinct(DistinctOption)` takes `DistinctOption.basic()` for the same effect or `DistinctOption.none()` to build the call without emitting `distinct`, which keeps a dynamically chosen option out of the surrounding `if`.

```java
List<Employee> list = dsl.from(e).limit(5).offset(3).orderBy(c -> c.asc(e.employeeNo)).fetch();
```

```kotlin
val list = dsl.from(e).limit(5).offset(3).orderBy { asc(e.employeeNo) }.fetch()
```

## Row locking

`forUpdate()` appends `for update`. `forUpdate(ForUpdateOption)` selects the variant:

| Option | Meaning |
| --- | --- |
| `ForUpdateOption.basic(properties...)` | plain `for update`, optionally `of` the given columns |
| `ForUpdateOption.noWait(properties...)` | fail instead of waiting for the lock |
| `ForUpdateOption.wait(seconds, properties...)` | wait at most the given number of seconds |
| `ForUpdateOption.none()` | build the call without emitting a lock clause |

Locking support and each option are dialect-specific; Doma's integration suite skips the `forUpdate` test on SQLite. Verify against the target database before relying on a wait or no-wait variant, and prefer `@Version` optimistic locking when a pessimistic lock is not required.

## Unions

`union` and `unionAll` are the only set operations in the Criteria API; there is no `intersect` or `except`, and no recursive CTE. They combine set operands whose select lists match. Order a union result by column index:

```java
List<Tuple2<Integer, String>> list = dsl
    .from(e)
    .select(e.employeeId, e.employeeName)
    .union(dsl.from(d).select(d.departmentId, d.departmentName))
    .orderBy(c -> c.asc(2))
    .fetch();
```

## Subqueries, derived tables, CTEs

A scalar or list subquery is written inside the declaration:

```java
List<Employee> list = dsl
    .from(e)
    .where(c -> c.in(e.employeeId, c.from(e2).select(e2.managerId)))
    .orderBy(c -> c.asc(e.employeeId))
    .fetch();
```

```kotlin
val list = dsl
    .from(e)
    .where { `in`(e.employeeId, from(e2).select(e2.managerId)) }
    .fetch()
```

Kotlin needs backticks for `in` because it is a keyword.

`exists` and `notExists` take the same `c.from(...)` subquery, and the outer metamodel may be referenced inside it, which makes the subquery correlated:

```java
List<Employee> list = dsl
    .from(e)
    .where(c -> c.exists(
        c.from(e2).where(c2 -> c2.eq(e.employeeId, e2.managerId)).select(e2.managerId)))
    .fetch();
```

A derived table and a CTE each require an entity class, with a metamodel, whose properties match the subquery's select list. The match is positional and checked at execution time: the subquery must select exactly as many columns as the outer entity has properties (DOMA6011 otherwise), and **Doma aliases each plain select item to the outer entity's actual column name automatically** -- computed columns, literals, and aggregates included. Do not alias them yourself: a manual `AliasExpression` suppresses the automatic alias, and `PropertyMetamodel.getName()` is the Java property name, not the column name, so `alias(expr, t.prop.getName())` breaks the mapping as soon as `@Column(name = ...)` diverges from the property name. Order the select list to match the entity's properties and let Doma name the columns:

```java
NameAndAmount_ t = new NameAndAmount_();
SetOperand<?> subquery = dsl
    .from(e)
    .innerJoin(d, c -> c.eq(e.departmentId, d.departmentId))
    .groupBy(d.departmentName)
    .select(d.departmentName, Expressions.sum(e.salary));

List<NameAndAmount> list = dsl.from(t, subquery).orderBy(c -> c.asc(t.name)).fetch();
```

```java
var a = new AverageSalary_();
var list = dsl
    .with(a, dsl.from(e).select(Expressions.avg(e.salary)))
    .from(e)
    .innerJoin(a, on -> on.ge(e.salary, a.salary))
    .select(e.employeeId, e.employeeName, e.salary)
    .fetch();
```

The derived-table subquery may itself be a union, and Kotlin has the same overload (`dsl.from(t, subquery)` on `KQueryDsl`).

Common table expressions follow these rules:

- The CTE's name is the entity's table name and its column list is the entity's column names, so `AverageSalary` becomes `with AVERAGE_SALARY(SALARY) as (...)`. The CTE entity can be a plain class or a record; it needs a metamodel like any other entity.
- Declare several CTEs by chaining (`dsl.with(a, queryA).with(b, queryB)`), by passing `with(List<WithContext>)` in Java, or with varargs pairs in Kotlin (`dsl.with(a to queryA, b to queryB)`); `KWithQueryDsl` chains the same way.
- To define two CTEs from the same entity class, name the second through the metamodel's table-name constructor: `var second = new DepartmentCount_("secondCte")`.
- Join a CTE's metamodel exactly like a table: `.leftJoin(dcCte, on -> on.eq(e.departmentId, dcCte.departmentId))`.
- `with(...)` returns a DSL whose only statement entry is `from`: **CTEs work with selects only**. There is no `with(...).insert/update/delete`, and no recursive CTE.
- The `from` after `with` keeps the settings and derived-table overloads, so a CTE and a derived table can appear in the same statement, in Kotlin too.

CTE support is dialect-dependent; Doma's integration suite skips the CTE cases on its older MySQL profile while running them on MySQL 8, where `MysqlDialect` should be constructed with `MySqlVersion.V8` (the default flavor is V5).

## References

- [Doma 3.14.0: Unified Criteria API](https://docs.domaframework.org/en/3.14.0/query-dsl/)
- [Doma 3.14.0: Kotlin-specific Criteria API](https://docs.domaframework.org/en/3.14.0/kotlin-support/)
- [`WhereDeclaration` javadoc](https://www.javadoc.io/doc/org.seasar.doma/doma-core/latest/org/seasar/doma/jdbc/criteria/declaration/WhereDeclaration.html)
