# Minimal Plain Java Project

This Java 17 example uses Doma `3.14.0`, the released version documented by the
source baseline. Configure either Gradle or Maven exactly as shown in
[Build Configuration](build-configuration.md) before adding these files. Keep
`doma-core` and `doma-processor` on their distinct classpaths and at the same
released Doma version.

## Contents

- [File Layout](#file-layout)
- [Config](#config)
- [Entity](#entity)
- [DAO](#dao)
- [SQL Resource](#sql-resource)
- [Compile and Call the Generated DAO](#compile-and-call-the-generated-dao)
- [References](#references)

## File Layout

```text
build.gradle or pom.xml
src/
  main/
    java/
      example/
        Application.java
        config/
          AppConfig.java
        dao/
          HealthCheckDao.java
        entity/
          HealthCheck.java
    resources/
      META-INF/
        example/
          dao/
            HealthCheckDao/
              selectById.sql
```

Use UTF-8 for the SQL file. Its path follows
`META-INF/<DAO package path>/<DAO simple name>/<DAO method name>.sql` exactly.
The Java package, DAO name, method name, and resource path are case-sensitive
parts of that contract.

## Config

Create `src/main/java/example/config/AppConfig.java`:

```java
package example.config;

import java.util.Objects;
import javax.sql.DataSource;
import org.seasar.doma.jdbc.Config;
import org.seasar.doma.jdbc.dialect.Dialect;

public final class AppConfig implements Config {
    private final DataSource dataSource;
    private final Dialect dialect;

    public AppConfig(DataSource dataSource, Dialect dialect) {
        this.dataSource = Objects.requireNonNull(dataSource);
        this.dialect = Objects.requireNonNull(dialect);
    }

    @Override
    public DataSource getDataSource() {
        return dataSource;
    }

    @Override
    public Dialect getDialect() {
        return dialect;
    }
}
```

Compilation and generated-source inspection do not require a live database.
Execution does: the caller must supply a configured `DataSource`, a Doma
`Dialect` appropriate for that database, and a database containing the table
used by the SQL below. This boundary keeps driver selection, credentials,
connection-pool setup, and schema creation outside the plain Doma setup
example.

## Entity

Create `src/main/java/example/entity/HealthCheck.java`:

```java
package example.entity;

import org.seasar.doma.Entity;

@Entity
public record HealthCheck(int id) {
}
```

Java records annotated with `@Entity` are treated as immutable entities. The
single `id` component maps the query-result column named `id`.

## DAO

Create `src/main/java/example/dao/HealthCheckDao.java`:

```java
package example.dao;

import example.entity.HealthCheck;
import org.seasar.doma.Dao;
import org.seasar.doma.Select;

@Dao
public interface HealthCheckDao {
    @Select
    HealthCheck selectById(int id);
}
```

Use plain `@Select` for an external SELECT SQL template. Doma 3.14's `@Select`
annotation has no `sqlFile` element. Keep the DAO as a top-level interface so
the annotation processor can generate its implementation.

## SQL Resource

Create
`src/main/resources/META-INF/example/dao/HealthCheckDao/selectById.sql`:

```sql
select id
from health_check
where id = /* id */1
```

The bind expression `id` matches the DAO parameter `int id`. The literal `1`
is test data required by Doma's two-way SQL syntax; Doma replaces the directive
and its test data with a bind variable when executing the query.

## Compile and Call the Generated DAO

Compile with the project's configured build tool and search recursively from
the documented generated-source root:

```bash
# Gradle
./gradlew -PdomaVersion=3.14.0 clean compileJava
find build/generated/sources/annotationProcessor -type f -name 'HealthCheckDaoImpl.java' -print

# Maven
mvn clean compile
find target/generated-sources/annotations -type f -name 'HealthCheckDaoImpl.java' -print
```

Run only the pair for the build tool already used by the project. Compilation
generates `example.dao.HealthCheckDaoImpl` and the entity metadata type
`example.entity._HealthCheck`. Do not create either generated source under
`src/main/java`.

To compile a caller of the generated implementation, create
`src/main/java/example/Application.java`:

```java
package example;

import example.config.AppConfig;
import example.dao.HealthCheckDao;
import example.dao.HealthCheckDaoImpl;
import example.entity.HealthCheck;
import javax.sql.DataSource;
import org.seasar.doma.jdbc.Config;
import org.seasar.doma.jdbc.dialect.Dialect;

public final class Application {
    private Application() {
    }

    public static HealthCheck selectHealthCheck(
            DataSource dataSource, Dialect dialect, int id) {
        Config config = new AppConfig(dataSource, dialect);
        HealthCheckDao dao = new HealthCheckDaoImpl(config);
        return dao.selectById(id);
    }
}
```

The handwritten source imports `HealthCheckDaoImpl`, but the Doma annotation
processor creates that class during compilation. Calling
`selectHealthCheck(...)` crosses the runtime boundary and issues the SQL against
the caller's database; finding `HealthCheckDaoImpl.java` only verifies the
compile-time setup.

## References

- [Doma 3.14.0: Building an application](https://docs.domaframework.org/en/3.14.0/build/)
- [Doma 3.14.0: Configuration definition](https://docs.domaframework.org/en/3.14.0/config/#configuration-definition)
- [Doma 3.14.0: Entity classes](https://docs.domaframework.org/en/3.14.0/entity/)
- [Doma 3.14.0: DAO interfaces](https://docs.domaframework.org/en/3.14.0/dao/)
- [Doma 3.14.0: Select queries](https://docs.domaframework.org/en/3.14.0/query/select/)
- [Doma 3.14.0: SQL templates in files](https://docs.domaframework.org/en/3.14.0/sql/#sql-templates-in-files)
- [Doma 3.14.0 FAQ: generated sources](https://docs.domaframework.org/en/3.14.0/faq/)
