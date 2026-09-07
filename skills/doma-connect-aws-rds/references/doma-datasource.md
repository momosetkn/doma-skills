# Doma DataSource, dialect, and connection probe

Use this reference only after [AWS discovery](aws-discovery.md) has established the
engine, endpoint, port, region, and authentication contract and [connection
modes](connection-modes.md) has selected one connection mode. Add only the
dependencies and `DataSource` path for that mode.

## Contents

- [Preserve the project contract](#preserve-the-project-contract)
- [Choose released dependencies](#choose-released-dependencies)
- [Configure the build](#configure-the-build)
- [Build the selected DataSource](#build-the-selected-datasource)
- [Return it from Doma Config](#return-it-from-doma-config)
- [Preserve transaction ownership](#preserve-transaction-ownership)
- [Compile and run the read-only probe](#compile-and-run-the-read-only-probe)
- [References](#references)

## Preserve the project contract

Inspect the existing language, build, JDK, Doma version, driver, pool, AWS SDK,
wrapper, and transaction owner before editing. Keep compatible project-selected
versions. The pins below are released examples verified on 2026-08-02; re-check
them when working at a later date. Doma `3.14.0` is the released example version.
The source research snapshot `3.14.1-SNAPSHOT` is not a dependency coordinate.

Doma 3.14 requires JDK 17 or later. HikariCP `7.1.0` requires Java 11 or later,
so it is compatible with the examples here. A project that remains on Java 8
must use the deprecated HikariCP `4.0.3` maintenance line if Hikari is required;
do not raise its JDK or replace an established pool merely to copy this example.

## Choose released dependencies

Every supported build needs one aligned Doma runtime/processor pair. Add one
engine driver, one pool only when the project does not already have one, and
only the selected authentication or topology integration. These primary-source
pins and runtime notes were checked on 2026-08-02; compatible versions already
selected by the project take precedence:

| Concern | Coordinate and released example | Primary pin/runtime evidence | Add when |
| --- | --- | --- | --- |
| Java Doma | `org.seasar.doma:doma-core:3.14.0`, `org.seasar.doma:doma-processor:3.14.0` | [Doma 3.14.0 documentation](https://docs.domaframework.org/en/3.14.0/) | Java Gradle or Maven; processor stays off the runtime classpath |
| Kotlin Doma | `org.seasar.doma:doma-kotlin:3.14.0`, `org.seasar.doma:doma-processor:3.14.0` | [Doma 3.14.0 Kotlin support](https://docs.domaframework.org/en/3.14.0/kotlin-support/) | Kotlin/JVM Gradle Kotlin DSL; put the processor on `kapt` |
| PostgreSQL | `org.postgresql:postgresql:42.7.13` | [Maven Central release metadata](https://repo.maven.apache.org/maven2/org/postgresql/postgresql/maven-metadata.xml); [42.7.13 supported PostgreSQL and Java versions](https://github.com/pgjdbc/pgjdbc/blob/REL42.7.13/README.md#supported-postgresql-and-java-versions) | PostgreSQL or Aurora PostgreSQL |
| MySQL | `com.mysql:mysql-connector-j:26.7.0` | [Maven Central release metadata](https://repo.maven.apache.org/maven2/com/mysql/mysql-connector-j/maven-metadata.xml); [immutable 26.7.0 POM](https://repo.maven.apache.org/maven2/com/mysql/mysql-connector-j/26.7.0/mysql-connector-j-26.7.0.pom); [official Java compatibility guide](https://dev.mysql.com/doc/connector-j/en/connector-j-versions.html) | MySQL 8 or Aurora MySQL compatible with this driver |
| HikariCP | `com.zaxxer:HikariCP:7.1.0`; deprecated Java 8 line `4.0.3` | [Maven Central release metadata](https://repo.maven.apache.org/maven2/com/zaxxer/HikariCP/maven-metadata.xml); [7.1.0 Java 11+ and 4.0.3 Java 8 artifact guidance](https://github.com/brettwooldridge/HikariCP/blob/HikariCP-7.1.0/README.md#artifacts); immutable POMs for [7.1.0](https://repo.maven.apache.org/maven2/com/zaxxer/HikariCP/7.1.0/HikariCP-7.1.0.pom) and [4.0.3](https://repo.maven.apache.org/maven2/com/zaxxer/HikariCP/4.0.3/HikariCP-4.0.3.pom) | Retaining or intentionally introducing Hikari; use `7.1.0` on Java 11+ or deprecated `4.0.3` only when the project remains on Java 8 |
| AWS SDK 2.x | BOM `software.amazon.awssdk:bom:2.50.2`, modules `software.amazon.awssdk:rds` and `software.amazon.awssdk:auth` | [BOM release metadata](https://repo.maven.apache.org/maven2/software/amazon/awssdk/bom/maven-metadata.xml); immutable 2.50.2 POMs for [BOM](https://repo.maven.apache.org/maven2/software/amazon/awssdk/bom/2.50.2/bom-2.50.2.pom), [RDS](https://repo.maven.apache.org/maven2/software/amazon/awssdk/rds/2.50.2/rds-2.50.2.pom), and [auth](https://repo.maven.apache.org/maven2/software/amazon/awssdk/auth/2.50.2/auth-2.50.2.pom); [2.50.2 minimum requirements](https://github.com/aws/aws-sdk-java-v2/blob/2.50.2/README.md#minimum-requirements) | Direct or Proxy IAM token generation |
| Secrets Manager JDBC | `com.amazonaws.secretsmanager:aws-secretsmanager-jdbc:2.1.3` | [Maven Central release metadata](https://repo.maven.apache.org/maven2/com/amazonaws/secretsmanager/aws-secretsmanager-jdbc/maven-metadata.xml); [official 2.1.3 release](https://github.com/aws/aws-secretsmanager-jdbc/releases/tag/2.1.3); [immutable 2.1.3 POM](https://repo.maven.apache.org/maven2/com/amazonaws/secretsmanager/aws-secretsmanager-jdbc/2.1.3/aws-secretsmanager-jdbc-2.1.3.pom) | Selected secret-aware JDBC integration; also keep its underlying engine driver |
| Secrets Manager cache | `com.amazonaws.secretsmanager:aws-secretsmanager-caching-java:2.2.0` | [Maven Central release metadata](https://repo.maven.apache.org/maven2/com/amazonaws/secretsmanager/aws-secretsmanager-caching-java/maven-metadata.xml); [official 2.2.0 release](https://github.com/aws/aws-secretsmanager-caching-java/releases/tag/2.2.0); [2.2.0 prerequisites](https://github.com/aws/aws-secretsmanager-caching-java/blob/2.2.0/README.md#required-prerequisites); [immutable 2.2.0 POM](https://repo.maven.apache.org/maven2/com/amazonaws/secretsmanager/aws-secretsmanager-caching-java/2.2.0/aws-secretsmanager-caching-java-2.2.0.pom) | Only when the existing design explicitly uses the standalone cache |
| AWS Advanced JDBC Wrapper | `software.amazon.jdbc:aws-advanced-jdbc-wrapper:4.3.0` | [Maven Central release metadata](https://repo.maven.apache.org/maven2/software/amazon/jdbc/aws-advanced-jdbc-wrapper/maven-metadata.xml); [4.3.0 minimum requirements](https://github.com/aws/aws-advanced-jdbc-wrapper/blob/4.3.0/docs/GettingStarted.md#minimum-requirements); [immutable 4.3.0 POM](https://repo.maven.apache.org/maven2/software/amazon/jdbc/aws-advanced-jdbc-wrapper/4.3.0/aws-advanced-jdbc-wrapper-4.3.0.pom) | Selected compatible wrapper mode; also keep the underlying engine driver |

The AWS SDK BOM is dependency management, not a runtime jar. Keep all selected
SDK modules aligned through it. Add `software.amazon.awssdk:sts` at that BOM
version only when the existing EKS or assume-role credential path requires it.

## Configure the build

These are complete compile shapes for the representative selected modes. Merge
the matching shape into the existing build; do not combine all three dependency
sets.

### Java Gradle: selected PostgreSQL pool mode

```groovy
plugins {
    id 'java'
}

java {
    toolchain {
        languageVersion = JavaLanguageVersion.of(17)
    }
}

repositories {
    mavenCentral()
}

def domaVersion = providers.gradleProperty('domaVersion').getOrElse('3.14.0')

dependencies {
    implementation "org.seasar.doma:doma-core:${domaVersion}"
    annotationProcessor "org.seasar.doma:doma-processor:${domaVersion}"
    implementation 'org.postgresql:postgresql:42.7.13'
    implementation 'com.zaxxer:HikariCP:7.1.0'
}
```

For PostgreSQL IAM, additionally import the AWS BOM with
`implementation platform('software.amazon.awssdk:bom:2.50.2')` and add the
unversioned `software.amazon.awssdk:rds` and `software.amazon.awssdk:auth`
modules. For secret-aware JDBC, add `aws-secretsmanager-jdbc:2.1.3` instead.
For a selected wrapper mode, add `aws-advanced-jdbc-wrapper:4.3.0` instead.

### Java Maven: selected MySQL pool mode

```xml
<properties>
  <maven.compiler.release>17</maven.compiler.release>
  <doma.version>3.14.0</doma.version>
</properties>

<dependencies>
  <dependency>
    <groupId>org.seasar.doma</groupId>
    <artifactId>doma-core</artifactId>
    <version>${doma.version}</version>
  </dependency>
  <dependency>
    <groupId>com.mysql</groupId>
    <artifactId>mysql-connector-j</artifactId>
    <version>26.7.0</version>
  </dependency>
  <dependency>
    <groupId>com.zaxxer</groupId>
    <artifactId>HikariCP</artifactId>
    <version>7.1.0</version>
  </dependency>
</dependencies>

<build>
  <plugins>
    <plugin>
      <artifactId>maven-compiler-plugin</artifactId>
      <version>3.14.1</version>
      <configuration>
        <annotationProcessorPaths>
          <path>
            <groupId>org.seasar.doma</groupId>
            <artifactId>doma-processor</artifactId>
            <version>${doma.version}</version>
          </path>
        </annotationProcessorPaths>
      </configuration>
    </plugin>
  </plugins>
</build>
```

Import the AWS SDK BOM under Maven `dependencyManagement` and omit versions on
its modules when IAM is selected. Add the Secrets Manager JDBC or wrapper
coordinate only for its selected mode.

### Kotlin Gradle Kotlin DSL: selected PostgreSQL IAM mode

Preserve the project's compatible Kotlin version. This complete released
example uses the version exercised by the Doma source baseline:

```kotlin
plugins {
    kotlin("jvm") version "2.3.21"
    kotlin("kapt") version "2.3.21"
}

java {
    toolchain {
        languageVersion = JavaLanguageVersion.of(17)
    }
}

repositories {
    mavenCentral()
}

val domaVersion = providers.gradleProperty("domaVersion").getOrElse("3.14.0")

dependencies {
    implementation("org.seasar.doma:doma-kotlin:$domaVersion")
    kapt("org.seasar.doma:doma-processor:$domaVersion")
    implementation("org.postgresql:postgresql:42.7.13")
    implementation("com.zaxxer:HikariCP:7.1.0")
    implementation(platform("software.amazon.awssdk:bom:2.50.2"))
    implementation("software.amazon.awssdk:rds")
    implementation("software.amazon.awssdk:auth")
}
```

For a non-IAM Kotlin mode, remove the SDK platform/modules and add only that
mode's selected integration coordinate.

## Build the selected DataSource

Supply host, port, database, region, user or secret id, and trust material from
the confirmed runtime configuration. The names below are variables, not example
credentials. Never print them or a credential-bearing JDBC URL.

Place those values at these boundaries:

| Selected mode | Placement |
| --- | --- |
| Direct runtime-delivered secret | Put host, port, database, user, runtime credential, and TLS properties on the engine `DataSource`; region belongs to the approved credential-delivery/discovery path, not plain JDBC |
| Direct IAM | Put host, port, database, user, and TLS on the physical engine `DataSource`; put region and the default-chain provider on `RdsUtilities`; pass only the newly generated token to the driver's physical `getConnection` call |
| Secrets Manager JDBC | Put host, port, database, and TLS in the `jdbc-secretsmanager` URL; put the secret id in the `user` property and region in `AWS_SECRET_JDBC_REGION` or `secretsmanager.properties` |
| RDS Proxy | Use the Proxy host/port everywhere a client endpoint is required; place database/user/TLS as for its selected secret or IAM client flow, and place region on its secret or IAM integration |
| Direct AWS wrapper | Put host, port, database, user, runtime credential, TLS, and wrapper plugins on `AwsWrapperDataSource`/its target properties; keep the inspected region as target evidence because the shown failover-only source has no credential-region input |

### Direct or Proxy, runtime-delivered secret

For PostgreSQL, configure the inspected instance/cluster endpoint for direct
mode or the inspected Proxy endpoint for Proxy mode:

```java
PGSimpleDataSource target = new PGSimpleDataSource();
target.setServerNames(new String[] {endpoint});
target.setPortNumbers(new int[] {port});
target.setDatabaseName(databaseName);
target.setUser(databaseUser);
target.setPassword(runtimeCredential);
target.setSslMode("verify-full");

HikariConfig hikari = new HikariConfig();
hikari.setDataSource(target);
HikariDataSource pool = new HikariDataSource(hikari);
```

For MySQL 8, use the matching driver properties and dialect:

```java
MysqlDataSource target = new MysqlDataSource();
target.setServerName(endpoint);
target.setPortNumber(port);
target.setDatabaseName(databaseName);
target.setUser(databaseUser);
target.setPassword(runtimeCredential);
target.setSslMode("VERIFY_IDENTITY");

HikariConfig hikari = new HikariConfig();
hikari.setDataSource(target);
HikariDataSource pool = new HikariDataSource(hikari);
```

Retrieve `runtimeCredential` only through the application's already-approved
runtime delivery mechanism. The read-only inspector must not call
`GetSecretValue`; a runtime application or Secrets Manager integration may need
narrow `secretsmanager:DescribeSecret` and `secretsmanager:GetSecretValue`
permission. Verify rotation and pool-refresh behavior before claiming rotation
support.

For Proxy, also set pool `maxLifetime` below the non-configurable 24-hour Proxy
client-connection limit. Hikari applies `idleTimeout` only when
`minimumIdle < maximumPoolSize`; only in that elastic configuration can a pool
`idleTimeout` below the inspected Proxy `IdleClientTimeout` make the application
retire idle clients first. A fixed-size configuration with
`minimumIdle >= maximumPoolSize`, including Hikari's default behavior, does not
retire idle connections through `idleTimeout`. Choose pool size and lifetime
settings deliberately; do not copy arbitrary values or infer that Proxy
eliminates the application pool.

### Secrets Manager JDBC integration

Let the selected AWS driver resolve the secret at runtime. Put the secret id,
not its value, in Hikari's user property. Put the confirmed endpoint, port,
database, and hostname-verifying TLS option in the URL:

```java
HikariConfig hikari = new HikariConfig();
hikari.setDriverClassName(
        "com.amazonaws.secretsmanager.sql.AWSSecretsManagerPostgreSQLDriver");
hikari.setJdbcUrl(
        "jdbc-secretsmanager:postgresql://" + endpoint + ":" + port + "/"
                + databaseName + "?sslmode=verify-full");
hikari.setUsername(secretId);
HikariDataSource pool = new HikariDataSource(hikari);
```

Set the confirmed region with `AWS_SECRET_JDBC_REGION` or
`drivers.region=<region>` in `secretsmanager.properties`; do not place it in DAO
code. Use `AWSSecretsManagerMySQLDriver` and `sslMode=VERIFY_IDENTITY` for a
compatible MySQL target. The integration caches credentials and refreshes after
rotation; the standalone cache has different behavior and is not a drop-in
substitute.

### IAM token at physical connection acquisition

Generate a token inside the unpooled driver's `getConnection()` method, then
put that token-generating source behind Hikari. Hikari calls the source when it
creates a new physical connection; borrowing an existing pooled connection does
not generate a new token. This Java PostgreSQL source uses the exact endpoint,
port, region, and case-sensitive database user:

```java
import java.sql.Connection;
import java.sql.SQLException;
import org.postgresql.ds.PGSimpleDataSource;
import software.amazon.awssdk.services.rds.RdsUtilities;
import software.amazon.awssdk.services.rds.model.GenerateAuthenticationTokenRequest;

public final class IamTokenPostgresDataSource extends PGSimpleDataSource {
    private final RdsUtilities utilities;
    private final String endpoint;
    private final int databasePort;
    private final String databaseUser;

    public IamTokenPostgresDataSource(
            RdsUtilities utilities,
            String endpoint,
            int databasePort,
            String databaseName,
            String databaseUser) {
        this.utilities = utilities;
        this.endpoint = endpoint;
        this.databasePort = databasePort;
        this.databaseUser = databaseUser;
        setServerNames(new String[] {endpoint});
        setPortNumbers(new int[] {databasePort});
        setDatabaseName(databaseName);
        setUser(databaseUser);
        setSslMode("verify-full");
    }

    @Override
    public Connection getConnection() throws SQLException {
        var request = GenerateAuthenticationTokenRequest.builder()
                .hostname(endpoint)
                .port(databasePort)
                .username(databaseUser)
                .build();
        String token = utilities.generateAuthenticationToken(request);
        return super.getConnection(databaseUser, token);
    }

    @Override
    public Connection getConnection(String username, String ignoredPassword)
            throws SQLException {
        if (!databaseUser.equals(username)) {
            throw new SQLException("IAM database user does not match configured user");
        }
        return getConnection();
    }
}
```

Create and reuse the SDK credential provider and utilities for the runtime, but
never cache the generated token:

```java
DefaultCredentialsProvider credentials = DefaultCredentialsProvider.builder().build();
RdsUtilities utilities = RdsUtilities.builder()
        .region(Region.of(region))
        .credentialsProvider(credentials)
        .build();

IamTokenPostgresDataSource physical = new IamTokenPostgresDataSource(
        utilities, endpoint, port, databaseName, databaseUser);
HikariConfig hikari = new HikariConfig();
hikari.setDataSource(physical);
HikariDataSource pool = new HikariDataSource(hikari);
```

Close the pool before closing an explicitly created credential provider during
runtime shutdown. A token is valid for 15 minutes to establish a connection;
that limit neither expires an established connection nor dictates Hikari's
`maxLifetime`. Sign the real RDS or Proxy endpoint, never a custom DNS alias.

For MySQL IAM, apply the same acquisition boundary to `MysqlDataSource`, pass
the generated token to `getConnection(databaseUser, token)`, require the
server-side IAM database-user plugin already to be configured, and set
`sslMode=VERIFY_IDENTITY`. Do not create or alter the database user here.

The Kotlin companion has the same lifetime boundary but uses Kotlin overrides:

```kotlin
import java.sql.Connection
import java.sql.SQLException
import org.postgresql.ds.PGSimpleDataSource
import software.amazon.awssdk.services.rds.RdsUtilities
import software.amazon.awssdk.services.rds.model.GenerateAuthenticationTokenRequest

class IamTokenPostgresDataSource(
    private val utilities: RdsUtilities,
    private val endpoint: String,
    private val databasePort: Int,
    databaseName: String,
    private val databaseUser: String,
) : PGSimpleDataSource() {
    init {
        setServerNames(arrayOf(endpoint))
        setPortNumbers(intArrayOf(databasePort))
        setDatabaseName(databaseName)
        setUser(databaseUser)
        setSslMode("verify-full")
    }

    override fun getConnection(): Connection {
        val request = GenerateAuthenticationTokenRequest.builder()
            .hostname(endpoint)
            .port(databasePort)
            .username(databaseUser)
            .build()
        val token = utilities.generateAuthenticationToken(request)
        return super.getConnection(databaseUser, token)
    }

    override fun getConnection(username: String?, ignoredPassword: String?): Connection {
        if (databaseUser != username) {
            throw SQLException("IAM database user does not match configured user")
        }
        return connection
    }
}
```

Initialize the Kotlin resources once per runtime and let the pool call the
token-producing source for each new physical connection. Keep the returned
application-owned holder reachable for the runtime lifetime and close it at
shutdown; it exposes the Doma config while retaining both closeable resources:

```kotlin
import com.zaxxer.hikari.HikariDataSource
import org.seasar.doma.jdbc.dialect.PostgresDialect
import software.amazon.awssdk.auth.credentials.DefaultCredentialsProvider
import software.amazon.awssdk.regions.Region
import software.amazon.awssdk.services.rds.RdsUtilities

class KotlinIamConnectionResources private constructor(
    val config: AwsRdsConfig,
    private val pool: HikariDataSource,
    private val credentials: DefaultCredentialsProvider,
) : AutoCloseable {
    override fun close() {
        try {
            pool.close()
        } finally {
            credentials.close()
        }
    }

    companion object {
        fun create(
            endpoint: String,
            port: Int,
            databaseName: String,
            databaseUser: String,
            region: String,
        ): KotlinIamConnectionResources {
            val credentials = DefaultCredentialsProvider.builder().build()
            val pool = HikariDataSource()
            try {
                val utilities = RdsUtilities.builder()
                    .region(Region.of(region))
                    .credentialsProvider(credentials)
                    .build()
                pool.dataSource = IamTokenPostgresDataSource(
                    utilities, endpoint, port, databaseName, databaseUser)
                val config = AwsRdsConfig(pool, PostgresDialect())
                return KotlinIamConnectionResources(config, pool, credentials)
            } catch (failure: Throwable) {
                try {
                    pool.close()
                } finally {
                    credentials.close()
                }
                throw failure
            }
        }
    }
}
```

### Direct Aurora MySQL with the AWS Advanced JDBC Wrapper

Use topology plugins only when [connection modes](connection-modes.md) selected
a compatible direct Aurora or RDS Multi-AZ cluster. The underlying MySQL driver
still owns TLS and credentials:

```java
AwsWrapperDataSource wrapper = new AwsWrapperDataSource();
wrapper.setJdbcProtocol("jdbc:mysql:");
wrapper.setServerName(endpoint);
wrapper.setServerPort(Integer.toString(port));
wrapper.setDatabase(databaseName);
wrapper.setTargetDataSourceClassName(MysqlDataSource.class.getName());
wrapper.setUser(databaseUser);
wrapper.setPassword(runtimeCredential);

Properties targetProperties = new Properties();
targetProperties.setProperty("sslMode", "VERIFY_IDENTITY");
targetProperties.setProperty("wrapperPlugins", "failover2");
wrapper.setTargetDataSourceProperties(targetProperties);

HikariConfig hikari = new HikariConfig();
hikari.setDataSource(wrapper);
hikari.setExceptionOverrideClassName(HikariCPSQLException.class.getName());
HikariDataSource pool = new HikariDataSource(hikari);
```

Do not claim transaction replay or a specific failover time. When the endpoint
is an RDS Proxy, remove `failover`/`failover2`, `efm`/`efm2`, and
topology-dependent Read/Write Splitting. The Simple R/W Splitting Plugin remains
allowed only under the compatibility ruling in [connection modes](connection-modes.md).

## Return it from Doma Config

Use this framework-independent Java contract unchanged except for an optional
package declaration:

```java
import java.util.Objects;
import javax.sql.DataSource;
import org.seasar.doma.jdbc.Config;
import org.seasar.doma.jdbc.dialect.Dialect;

public final class AwsRdsConfig implements Config {
    private final DataSource dataSource;
    private final Dialect dialect;

    public AwsRdsConfig(DataSource dataSource, Dialect dialect) {
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

Use this Kotlin companion shape:

```kotlin
import javax.sql.DataSource
import org.seasar.doma.jdbc.Config
import org.seasar.doma.jdbc.dialect.Dialect

class AwsRdsConfig(
    private val source: DataSource,
    private val databaseDialect: Dialect,
) : Config {
    override fun getDataSource(): DataSource = source
    override fun getDialect(): Dialect = databaseDialect
}
```

Map the inspected engines explicitly:

```java
Dialect postgres = new PostgresDialect();
Dialect mysql8 = new MysqlDialect(MysqlDialect.MySqlVersion.V8);
```

Return the application-managed pool directly when the application already owns
transactions. Doma receives a `DataSource`; credentials and token generation
remain below that boundary and never enter a DAO.

## Preserve transaction ownership

Wrap the final connection source only when the application already chooses Doma
local transactions:

```java
LocalTransactionDataSource local = new LocalTransactionDataSource(pool);
AwsRdsConfig config = new AwsRdsConfig(local, new PostgresDialect());
```

The original source in this example is the final selected pool, IAM-aware
source, secret-aware source, or wrapper pool. Wire the existing Doma
`LocalTransactionManager` against `local` as the project already does. Do not
introduce a framework transaction manager or change an external transaction
owner in this connection workflow.

## Compile and run the read-only probe

Add this top-level Java DAO exactly, with an optional package declaration:

```java
import org.seasar.doma.Dao;
import org.seasar.doma.Select;
import org.seasar.doma.Sql;
import org.seasar.doma.jdbc.SqlLogType;

@Dao
public interface AwsConnectionProbeDao {
    @Sql("select 1")
    @Select(sqlLog = SqlLogType.RAW, queryTimeout = 5)
    int selectOne();
}
```

The matching top-level Kotlin interface is:

```kotlin
import org.seasar.doma.Dao
import org.seasar.doma.Select
import org.seasar.doma.Sql
import org.seasar.doma.jdbc.SqlLogType

@Dao
interface AwsConnectionProbeDao {
    @Sql("select 1")
    @Select(sqlLog = SqlLogType.RAW, queryTimeout = 5)
    fun selectOne(): Int
}
```

Run the existing build's clean compile and find the generated implementation:

```bash
# Java Gradle
./gradlew clean compileJava
find build/generated/sources/annotationProcessor -type f \
  -name 'AwsConnectionProbeDaoImpl.java' -print

# Java Maven
mvn clean compile
find target/generated-sources/annotations -type f \
  -name 'AwsConnectionProbeDaoImpl.java' -print

# Kotlin Gradle Kotlin DSL
./gradlew clean compileKotlin
find build/generated -type f -name 'AwsConnectionProbeDaoImpl.java' -print
```

Compilation proves Doma annotation processing and DAO generation; it does not
prove DNS, TLS, authentication, or database reachability. Only after the exact
target and live read-only probe are explicitly approved, instantiate
`AwsConnectionProbeDaoImpl` with the selected config and invoke `selectOne()`.
Require the result to equal `1`. The query has no schema dependency, uses RAW SQL
logging so bind values are not formatted into this probe's SQL log, and has a
five-second statement timeout. Do not add a write statement.

## References

- [Doma 3.14.0 configuration](https://docs.domaframework.org/en/3.14.0/config/)
- [Doma 3.14.0 DAO interfaces](https://docs.domaframework.org/en/3.14.0/dao/)
- [Doma 3.14.0 select queries](https://docs.domaframework.org/en/3.14.0/query/select/)
- [Doma `Config`](https://github.com/domaframework/doma/blob/3.14.0/doma-core/src/main/java/org/seasar/doma/jdbc/Config.java)
- [Doma `MysqlDialect`](https://github.com/domaframework/doma/blob/3.14.0/doma-core/src/main/java/org/seasar/doma/jdbc/dialect/MysqlDialect.java)
- [Doma `PostgresDialect`](https://github.com/domaframework/doma/blob/3.14.0/doma-core/src/main/java/org/seasar/doma/jdbc/dialect/PostgresDialect.java)
- [Doma `SqlLogType`](https://github.com/domaframework/doma/blob/3.14.0/doma-core/src/main/java/org/seasar/doma/jdbc/SqlLogType.java)
- [AWS SDK for Java 2.x IAM token example](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/example_rds_GenerateRDSAuthToken_section.html)
- [AWS Secrets Manager JDBC library](https://github.com/aws/aws-secretsmanager-jdbc/tree/2.1.3)
- [AWS Advanced JDBC Wrapper DataSource](https://github.com/aws/aws-advanced-jdbc-wrapper/blob/4.3.0/docs/using-the-jdbc-driver/DataSource.md)
