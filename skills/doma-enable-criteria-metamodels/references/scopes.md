# Scopes

- [What a scope generates](#what-a-scope-generates)
- [Required shape](#required-shape)
- [Compile-time diagnostics](#compile-time-diagnostics)
- [Kotlin limitation](#kotlin-limitation)
- [References](#references)

## What a scope generates

A scope turns a reusable query condition into a generated method on the metamodel. Declare the condition in a plain class, then list that class in the `scopes` element:

```java
public class DepartmentScope {
  @Scope
  public Consumer<WhereDeclaration> onlyTokyo(Department_ d) {
    return c -> c.eq(d.location, "Tokyo");
  }
}
```

```java
@Entity(metamodel = @Metamodel(scopes = { DepartmentScope.class }))
public class Department { /* ... */ }
```

`Department_` then exposes `onlyTokyo()`, usable wherever the declaration type is accepted:

```java
List<Department> list = queryDsl.from(d).where(d.onlyTokyo()).fetch();
```

Combine a scope with additional conditions using `andThen`:

```java
List<Department> list =
    queryDsl.from(d).where(d.onlyTokyo().andThen(c -> c.gt(d.departmentNo, 50))).fetch();
```

One class may declare several scope methods, and the return type selects the clause they apply to: `Consumer<WhereDeclaration>` for WHERE, `Consumer<OrderByNameDeclaration>` for ORDER BY, and the corresponding declaration type for other clauses.

## Required shape

Every `@Scope` method must:

- be annotated on a method, not a type or field;
- be `public`;
- not be `static`;
- take the entity metamodel as its first parameter.

Additional parameters after the metamodel are allowed and become parameters of the generated method, including varargs, arrays, `List`, bounded wildcards, and generic type parameters.

## Compile-time diagnostics

| Message | Cause | Fix |
| --- | --- | --- |
| `[DOMA4457] You must always receive the EntityMetamodel as the first parameter.` | The scope method has no parameters | Add the metamodel as the first parameter |
| `[DOMA4458] You cannot use static methods.` | The method is `static` | Make it an instance method |
| `[DOMA4459] The method must be public.` | The method is package-private, protected, or private | Make it `public` |

These are annotation processor errors, so the build fails before any query code runs.

## Kotlin limitation

Generated scope methods return `Consumer<WhereDeclaration>` and similar Java declaration consumers. In the bundled `3.14.1-SNAPSHOT` source, `KQueryDsl`'s Kotlin declarations (`KWhereDeclaration`, `KHavingDeclaration`, `KOrderByNameDeclaration`) accept only Kotlin lambda blocks and expose no overload that takes a `Consumer` of the Java declaration, so a scope cannot be passed into a `KQueryDsl` clause directly. Use scopes from Java `QueryDsl` code, or express the shared condition as a Kotlin extension or helper function that applies the block. Re-check the current release notes before relying on scope support in `KQueryDsl`.

## References

- [Doma 3.14.0: Unified Criteria API, scopes](https://docs.domaframework.org/en/3.14.0/query-dsl/)
- [Doma 3.14.0: `@Scope`](https://docs.domaframework.org/en/3.14.0/apidocs/org/seasar/doma/Scope.html)
- [Doma 3.14.0: `@Metamodel`](https://docs.domaframework.org/en/3.14.0/apidocs/org/seasar/doma/Metamodel.html)
