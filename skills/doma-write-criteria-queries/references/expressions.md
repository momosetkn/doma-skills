# Expressions

- [Where the functions live](#where-the-functions-live)
- [Aggregate functions](#aggregate-functions)
- [Arithmetic](#arithmetic)
- [String functions](#string-functions)
- [Literals](#literals)
- [CASE](#case)
- [Column aliases](#column-aliases)
- [Subquery values](#subquery-values)
- [User-defined expressions](#user-defined-expressions)
- [User-defined operators](#user-defined-operators)

## Where the functions live

- Java: `org.seasar.doma.jdbc.criteria.expression.Expressions`, designed for static import.
- Kotlin: `org.seasar.doma.kotlin.jdbc.criteria.expression.KExpressions`, which wraps the Java class and adapts the lambda types.

Every function returns a `PropertyMetamodel`, so results compose and can be passed anywhere a property is accepted: `select`, `where`, `having`, `orderBy`, and `set`.

## Aggregate functions

`avg`, `avgAsDouble`, `count()`, `count(property)`, `countDistinct(property)`, `max`, `min`, `sum`.

```java
Salary total = dsl.from(e).select(sum(e.salary)).fetchOne();

List<Tuple2<Integer, Long>> perDepartment = dsl
    .from(e)
    .groupBy(e.departmentId)
    .select(e.departmentId, count())
    .fetch();
```

```kotlin
val perDepartment = dsl.from(e).select(e.departmentId, KExpressions.count()).fetch()
```

When `groupBy` is omitted, the grouping is inferred from the select expression, so the two statements above generate the same SQL.

## Arithmetic

`add`, `sub`, `mul`, `div`, `mod`. Each accepts property-and-value, value-and-property, or property-and-property operands.

```java
int count = dsl.update(e)
    .set(c -> c.value(e.version, add(e.version, 10)))
    .where(c -> c.eq(e.employeeId, 1))
    .execute();
```

## String functions

`concat`, `lower`, `upper`, `trim`, `ltrim`, `rtrim`. `concat` takes the same three operand shapes as the arithmetic functions; the rest take a single property.

```java
int count = dsl.update(e)
    .set(c -> c.value(e.employeeName, concat("[", concat(e.employeeName, "]"))))
    .where(c -> c.eq(e.employeeId, 1))
    .execute();
```

## Literals

`literal` has exactly thirteen overloads -- `String`, `boolean`, `byte`, `short`, `int`, `long`, `float`, `double`, `BigDecimal`, `BigInteger`, `LocalDate`, `LocalDateTime`, and `LocalTime` -- and **embeds the value directly in the SQL instead of binding it**. There is no `literal` for a domain type, `java.util.Date`, `java.sql` types, `byte[]`, or `UUID`; compare such values through the binding operators instead (`c.eq(e.salary, new Salary("1000"))`). Use it for constants that must appear in the SQL text, never for values that come from outside the program. `literal(String)` refuses a value containing a single quotation mark with `DomaIllegalArgumentException`, so a quote can never be smuggled into the SQL text.

```java
Employee employee = dsl.from(e).where(c -> c.eq(e.employeeId, literal(1))).fetchOne();
```

```kotlin
val employee = dsl.from(e).where { eq(e.employeeId, KExpressions.literal(1)) }.fetchOneOrNull()
```

## CASE

Java uses `when`; Kotlin cannot, because `when` is a keyword, so `KExpressions` names it `case`. The last argument is the ELSE value. The WHEN declaration carries only `eq`, `ne`, `ge`, `gt`, `le`, `lt` (property-property and property-value forms), `isNull`, and `isNotNull` -- no `like`, `in`, `between`, `exists`, or logical nesting; a condition beyond that surface belongs in a user-defined expression.

```java
List<String> list = dsl
    .from(e)
    .select(
        when(c -> {
          c.eq(e.employeeName, literal("SMITH"), lower(e.employeeName));
          c.eq(e.employeeName, literal("KING"), lower(e.employeeName));
        }, literal("_")))
    .fetch();
```

```kotlin
val list = dsl
    .from(e)
    .select(
        KExpressions.case(
            {
                eq(e.employeeName, Expressions.literal("SMITH"), Expressions.lower(e.employeeName))
                eq(e.employeeName, Expressions.literal("KING"), Expressions.lower(e.employeeName))
            },
            KExpressions.literal("_"),
        ),
    )
    .fetch()
```

Inside the `case` block the receiver is the Java `CaseExpression.Declaration`, so its `eq`, `ne`, `ge`, and related methods take `(left, right, then)` and the operands are built with the Java `Expressions` class even in Kotlin code. The comparison value does not have to be a literal -- a plain value binds as a parameter (`c.eq(e.employeeName, "SMITH", lower(e.employeeName))`). As in WHERE, a null comparison value silently drops that WHEN branch, and a block that ends up adding no branch yields the ELSE value for every row.

## Column aliases

`Expressions.alias(property, "NAME")` adds an alias to a column in the select clause. Doma recommends using it only in the `select` and `orderBy` of the projection family, which is where standard SQL accepts an alias; the alias lets `orderBy` reference a computed column by name:

```java
AliasExpression<Salary> salarySum = Expressions.alias(sum(e.salary), "SALARY_SUM");

List<Tuple2<Integer, Salary>> list = dsl
    .from(e)
    .innerJoin(d, c -> c.eq(e.departmentId, d.departmentId))
    .groupBy(d.departmentId)
    .orderBy(c -> c.asc(salarySum))
    .select(d.departmentId, salarySum)
    .fetch();
```

Do **not** use `alias` to line up a derived-table subquery with its entity -- Doma aliases those columns to the outer entity's column names automatically, and a manual alias suppresses that (see [Select Queries](select-queries.md#subqueries-derived-tables-ctes)). `KExpressions` has no `alias`; Kotlin code calls the Java `Expressions.alias` directly.

## Subquery values

`Expressions.select` / `KExpressions.select` builds a scalar subquery usable as a value, for example on the right-hand side of an assignment:

```java
SelectExpression<Salary> subSelect = select(c ->
    c.from(e2)
     .innerJoin(d, on -> on.eq(e2.departmentId, d.departmentId))
     .where(cc -> cc.eq(e.departmentId, d.departmentId))
     .groupBy(d.departmentId)
     .select(max(e2.salary)));

int count = dsl.update(e)
    .set(c -> c.value(e.salary, subSelect))
    .where(c -> c.eq(e.employeeId, 1))
    .execute();
```

The outer statement's metamodel (`e`) may be referenced inside the subquery, which is how correlated subqueries are expressed.

## User-defined expressions

When a database function has no built-in wrapper, define it once with `Expressions.userDefined` and reuse it. The block appends raw SQL, so treat it as SQL you own: append parameters through `appendParameter`, never by string concatenation.

```java
UserDefinedExpression<String> replace(
    PropertyMetamodel<String> expression,
    PropertyMetamodel<String> from,
    PropertyMetamodel<String> to) {
  return Expressions.userDefined(expression, "replace", from, to, c -> {
    c.appendSql("replace(");
    c.appendExpression(expression);
    c.appendSql(", ");
    c.appendExpression(from);
    c.appendSql(", ");
    c.appendExpression(to);
    c.appendSql(")");
  });
}
```

`KExpressions.userDefined` offers the same feature; its reified overloads take the result type as a type argument instead of a sample property metamodel.

## User-defined operators

To add an operator to WHERE, JOIN, or HAVING, write a class that takes a `UserDefinedCriteriaContext` and use it through `extension`:

```java
record MyExtension(UserDefinedCriteriaContext context) {
  public void regexp(PropertyMetamodel<String> propertyMetamodel, String regexp) {
    context.add(b -> {
      b.appendExpression(propertyMetamodel);
      b.appendSql(" ~ ");
      b.appendParameter(propertyMetamodel, regexp);
    });
  }
}

var list = dsl.from(d)
    .where(c -> c.extension(MyExtension::new, ext -> ext.regexp(d.departmentName, "A")))
    .select()
    .fetch();
```

Kotlin declarations expose the same hook with a constructor reference and a receiver lambda, backed by `KUserDefinedCriteriaContext`:

```kotlin
class MyExtension(private val context: KUserDefinedCriteriaContext) {
    fun regexp(propertyMetamodel: PropertyMetamodel<String>, regexp: String) {
        context.add { b ->
            b.appendExpression(propertyMetamodel)
            b.appendSql(" ~ ")
            b.appendParameter(propertyMetamodel, regexp)
        }
    }
}

val list = dsl.from(d)
    .where { extension(::MyExtension) { regexp(d.departmentName, "A") } }
    .fetch()
```

Operators written this way emit database-specific SQL (`~` is PostgreSQL syntax here), so keep them behind a dialect-aware boundary.

## References

- [Doma 3.14.0: Unified Criteria API, property expressions](https://docs.domaframework.org/en/3.14.0/query-dsl/)
- [`Expressions` javadoc](https://www.javadoc.io/doc/org.seasar.doma/doma-core/latest/org/seasar/doma/jdbc/criteria/expression/Expressions.html)
