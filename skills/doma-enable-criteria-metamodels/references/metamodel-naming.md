# Metamodel Naming

- [Default names](#default-names)
- [Precedence](#precedence)
- [DOMA4455: the reserved `_` prefix](#doma4455-the-reserved--prefix)
- [Renaming an established project](#renaming-an-established-project)
- [References](#references)

## Default names

The metamodel prefix defaults to an empty string and the suffix defaults to `_`, so `Employee` produces `Employee_` in the entity's own package.

## Precedence

1. The `prefix` and `suffix` elements of `@Metamodel` on that entity, when either is non-empty.
2. The `doma.metamodel.prefix` and `doma.metamodel.suffix` annotation processor options, used when both annotation elements are empty.
3. The defaults above.

So an entity-level name wins over the project-wide options, and the options apply to every entity that does not name itself:

```java
@Entity(metamodel = @Metamodel(prefix = "My", suffix = "Metamodel"))
public class Employee { /* ... */ }
```

The class above is generated as `MyEmployeeMetamodel`. With `-Adoma.metamodel.prefix=Q -Adoma.metamodel.suffix=Metamodel` and a plain `@Metamodel`, the same entity produces `QEmployeeMetamodel`.

## DOMA4455: the reserved `_` prefix

`prefix = "_"` combined with an empty suffix is rejected at compile time:

```text
[DOMA4455] The combination of the prefix="_" and the suffix="" is not allowed.
```

`_` with an empty suffix would collide with `_Employee`, the entity meta class Doma already generates. Fix it by giving a non-empty suffix, or by choosing a different prefix. Note that `prefix = "Q"` with an empty suffix is accepted, so the rule is specific to `_`, not to empty suffixes in general.

## Renaming an established project

Changing a prefix or suffix renames every generated metamodel and breaks all call sites at once. Change the name only together with the query code that instantiates it, then clean-build so that the previously generated class does not linger in the output directory and mask the rename.

## References

- [Doma 3.14.0: `@Metamodel`](https://docs.domaframework.org/en/3.14.0/apidocs/org/seasar/doma/Metamodel.html)
- [Doma 3.14.0: Annotation processing options](https://docs.domaframework.org/en/3.14.0/annotation-processing/)
- [Doma 3.14.0: Unified Criteria API, metamodel classes](https://docs.domaframework.org/en/3.14.0/query-dsl/)
