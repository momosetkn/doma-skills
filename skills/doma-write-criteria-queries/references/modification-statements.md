# Modification Statements

- [Two families of statements](#two-families-of-statements)
  - [What only entity-based statements do](#what-only-entity-based-statements-do)
- [Insert](#insert)
- [Upsert](#upsert)
- [Update](#update)
- [Delete](#delete)
- [Set-based statements](#set-based-statements)
- [Returning](#returning)
- [Settings](#settings)
- [Very large batches](#very-large-batches)

Java examples assume `QueryDsl dsl = new QueryDsl(config);`; Kotlin examples assume `val dsl = KQueryDsl(config)`.

## Two families of statements

| | Entity-based (`single`, `batch`, `multi`) | Set-based (`values`, `select`, `set`, `where`, `all`) |
| --- | --- | --- |
| Identifies rows by | the entity's `@Id` | the WHERE condition you write |
| `@Version` | included in WHERE and incremented | untouched unless you set it yourself |
| Failure on lost update | `OptimisticLockException` when the update count is 0 | none |
| Java result | `Result<ENTITY>`, `BatchResult<ENTITY>`, `MultiResult<ENTITY>` | `int` affected rows |
| Kotlin result | same result objects via `execute()` | `Int` via `execute()` |

Choose the family from the caller's intent, not from convenience. Replacing an entity update with a set-based update silently removes optimistic locking.

### What only entity-based statements do

Entity statements run through Doma's auto queries, so they carry entity semantics that set-based statements never apply:

- **Entity listeners.** `preInsert`, `preUpdate`, and `preDelete` hooks on the entity's listener run, and a listener may replace the entity instance. `values`/`set`/`where` statements invoke no listener.
- **`@OriginalStates`.** When the entity holds original states, only the properties that actually changed appear in the SET clause. If nothing changed, no UPDATE statement is issued at all and the count is zero, which is not an error.
- **`@GeneratedValue`.** Insert prepares id generation and populates the generated id on the returned entity (`result.getEntity()`).
- **`@TenantId`.** The tenant column is added to the WHERE clause of entity updates and deletes and is excluded from the SET clause. A set-based update or delete filters by the tenant only if you write that condition yourself, so a multi-tenant application must add it explicitly.
- **`@Id` validation.** The statement fails when a required id property is absent.

When a fix moves work from one family to the other, re-check every item above.

## Insert

```java
Result<Department> result = dsl.insert(d).single(department).execute();
BatchResult<Department> batch = dsl.insert(d).batch(departments).execute();
MultiResult<Department> multi = dsl.insert(d).multi(departments).execute();
```

```kotlin
val result = dsl.insert(d).single(department).execute()
val batch = dsl.insert(d).batch(departments).execute()
val multi = dsl.insert(d).multi(departments).execute()
```

`batch` sends one statement per entity in a JDBC batch; `multi` sends a single `values (...), (...)` statement. A unique constraint violation raises `UniqueConstraintException` unless an upsert clause handles it.

When the entity's id generator cannot retrieve generated keys in a JDBC batch, Doma executes the statements one by one instead so the ids can still be read; the call looks batched but performs one round trip per entity. Set `ignoreGeneratedKeys` when the generated ids are not needed and real batching matters more.

## Upsert

`onDuplicateKeyUpdate()` and `onDuplicateKeyIgnore()` are available after `single`, `batch`, `multi`, and after `values`:

```java
Result<Department> result = dsl.insert(d).single(department).onDuplicateKeyUpdate().execute();
```

With `values`, the conflict target and the assignments can be stated explicitly, and `c.excluded(...)` refers to the proposed row:

```java
int count = dsl
    .insert(d)
    .values(c -> {
      c.value(d.departmentId, 1);
      c.value(d.departmentNo, 60);
      c.value(d.departmentName, "DEVELOPMENT");
      c.value(d.location, "KYOTO");
      c.value(d.version, 2);
    })
    .onDuplicateKeyUpdate()
    .keys(d.departmentId)
    .set(c -> {
      c.value(d.departmentName, c.excluded(d.departmentName));
      c.value(d.location, "KYOTO");
      c.value(d.version, 3);
    })
    .execute();
```

Emulation of `INSERT ... ON CONFLICT` differs per database, so verify the generated SQL with `asSql()` against the target dialect.

## Update

```java
Employee employee = dsl.from(e).where(c -> c.eq(e.employeeId, 5)).fetchOne();
employee.setEmployeeName("aaa");
Result<Employee> result = dsl.update(e).single(employee).execute();
```

```kotlin
val employee = dsl.from(e).where { eq(e.employeeId, 5) }.fetchOneOrNull() ?: return
employee.employeeName = "aaa"
val result = dsl.update(e).single(employee).execute()
```

The generated SQL includes `VERSION = ? + 1` in SET and `VERSION = ?` in WHERE for a versioned entity. When zero rows match, Doma throws `OptimisticLockException`; set `suppressOptimisticLockException` when a zero-count result is acceptable, and read `result.getCount()` (`result.count` in Kotlin) to detect it. `ignoreVersion` removes the version from WHERE and stops the increment behavior from protecting the row.

## Delete

```java
Result<Employee> result = dsl.delete(e).single(employee).execute();
BatchResult<Employee> batch = dsl.delete(e).batch(employees).execute();
```

Entity deletes are subject to the same optimistic-locking rules as updates.

## Set-based statements

```java
int updated = dsl
    .update(e)
    .set(c -> c.value(e.departmentId, 3))
    .where(c -> {
      c.isNotNull(e.managerId);
      c.ge(e.salary, new Salary("2000"));
    })
    .execute();

int deleted = dsl.delete(e).where(c -> c.ge(e.salary, new Salary("2000"))).execute();
int all = dsl.delete(e).all().execute();
```

```kotlin
val updated = dsl.update(e).set { value(e.departmentId, 3) }.where { isNotNull(e.managerId) }.execute()
val deleted = dsl.delete(e).where { ge(e.salary, Salary("2000")) }.execute()
val all = dsl.delete(e).all().execute()
```

A set-based update or delete whose WHERE declaration evaluates no operator throws `EmptyWhereClauseException`. Enable the `allowEmptyWhere` setting only when the caller really means every row, and prefer `all()` because it states that intent in the code.

INSERT SELECT copies rows between structurally identical tables, which pairs with the metamodel table-name constructor:

```java
Department_ da = new Department_("DEPARTMENT_ARCHIVE");
int count = dsl.insert(da).select(c -> c.from(d).where(cc -> cc.in(d.departmentId, List.of(1, 2)))).execute();
```

A table name passed to a metamodel constructor is validated: quotes, semicolons, double hyphens, and comment sequences raise `DomaIllegalArgumentException`. Never build it from user input.

## Returning

`returning()` executes the statement and reads the affected rows back in one round trip:

```java
Department inserted = dsl.insert(d).single(department).returning().fetchOne();
Department updated = dsl.update(d).single(department).returning().fetchOne();
Department deleted = dsl.delete(d).single(department).returning().fetchOne();
List<Department> many = dsl.insert(d).multi(departmentList).returning().fetch();
```

```kotlin
val inserted = dsl.insert(d).single(department).returning().fetchOne()
val updated = dsl.update(e).single(employee).returning().fetchOne()
val many = dsl.insert(d).multi(departments).returning().fetch()
```

- `returning` is an entity-statement feature: it is available after `single` and `multi` for insert, and after `single` for update and delete. There is no returning form for `batch(...)`, nor for the set-based `values`, `select`, `set`, `where`, and `all` statements; use `multi` or re-select the rows.
- Pass property metamodels to `returning(...)` to narrow the returned columns.
- Java offers `fetchOptional()` and Kotlin `fetchOneOrNull()`; in Kotlin `fetchOne()`, `fetchOneOrNull()`, and `execute()` all return the same single result for these statements.
- Doma documents support only for the H2, PostgreSQL, SQL Server, and SQLite dialects. Doma's integration tests additionally skip MySQL and Oracle. Do not propose `returning` for MySQL or Oracle; fetch the row again instead.

## Settings

| Setting | insert | update | delete | Effect |
| --- | --- | --- | --- | --- |
| `comment` / `queryTimeout` / `sqlLogType` | yes | yes | yes | SQL comment, JDBC timeout, log format |
| `batchSize` | yes | yes | yes | rows per `executeBatch()` flush |
| `excludeNull` | yes | yes | no | omits null properties from the statement |
| `include` / `exclude` | yes | yes | no | restricts the affected properties |
| `ignoreGeneratedKeys` | yes | no | no | skips retrieving generated keys |
| `allowEmptyWhere` | no | yes | yes | permits a statement with no condition |
| `ignoreVersion` | no | yes | yes | drops `@Version` from the WHERE clause |
| `suppressOptimisticLockException` | no | yes | yes | returns count 0 instead of throwing |

Each row is a JavaBean-style property on the settings object: booleans and values use `setXxx` (`settings.setExcludeNull(true)`, `settings.setIgnoreVersion(true)`), while `include` and `exclude` are varargs methods without the `set` prefix. Doma's documentation shows `settings.excludeNull(true)` in one example; that form does not exist on the settings classes, so use `setExcludeNull`.

```java
Result<Department> result = dsl.insert(d, settings -> settings.exclude(d.departmentName, d.location))
    .single(department)
    .execute();
```

```kotlin
val result = dsl.update(e) { suppressOptimisticLockException = true }.single(employee).execute()
```

## Very large batches

`batchSize` bounds how many rows are flushed per `executeBatch()` call, not how many `PreparedSql` objects exist at once, so hundreds of thousands of entities can exhaust the heap even with a small batch size. Doma documents an opt-in fix: override `Config.getQueryImplementors()` to return the chunked `AutoBatchInsertQuery`, `AutoBatchUpdateQuery`, and `AutoBatchDeleteQuery` implementations, which build SQL one entity at a time. Nothing changes unless the `QueryImplementors` are swapped.

## References

- [Doma 3.14.0: Unified Criteria API, insert, update, delete](https://docs.domaframework.org/en/3.14.0/query-dsl/)
- [Doma 3.14.0: Config query implementors](https://docs.domaframework.org/en/3.14.0/config/)
- [Doma 3.14.0: Kotlin-specific Criteria API](https://docs.domaframework.org/en/3.14.0/kotlin-support/)
