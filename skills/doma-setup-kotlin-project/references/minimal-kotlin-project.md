# Minimal Kotlin Project

Create `src/main/kotlin/example/dao/HealthCheckDao.kt` with this source:

```kotlin
package example.dao

import org.seasar.doma.Dao
import org.seasar.doma.Select
import org.seasar.doma.Sql

@Dao
interface HealthCheckDao {
    @Sql("select 1")
    @Select
    fun selectOne(): Int
}
```

Compilation should generate `example.dao.HealthCheckDaoImpl`. No database connection is needed to prove that annotation processing generated it. Executing `selectOne()` does require a runtime `Config`, a `DataSource`, an appropriate dialect, and a reachable database.

Keep this first probe small: do not add an entity, external SQL file, handwritten generated class, or runtime bootstrap.

## References

- [Doma 3.14.0: Kotlin DAO interfaces](https://docs.domaframework.org/en/3.14.0/kotlin-support/)
- [Doma 3.14.0: DAO interfaces](https://docs.domaframework.org/en/3.14.0/dao/)
- [Doma 3.14.0: `@Sql`](https://docs.domaframework.org/en/3.14.0/apidocs/org/seasar/doma/Sql.html)
- [Doma 3.14.0: `@Select`](https://docs.domaframework.org/en/3.14.0/apidocs/org/seasar/doma/Select.html)
