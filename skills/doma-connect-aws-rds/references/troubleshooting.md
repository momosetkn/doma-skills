# Ordered connection troubleshooting

Diagnose one gate at a time in this exact order:

```text
compile → AWS identity/target → network → TLS/auth → JDBC/pool/wrapper → Doma
```

Stop at the first failure. Later failures are not interpretable until the first
one is resolved. Do not mutate AWS, IAM, security groups, database users,
secrets, deployments, or schema while diagnosing this connection workflow.

## Contents

- [Gate table](#gate-table)
- [Run the gates in order](#run-the-gates-in-order)
- [Authentication branch checks](#authentication-branch-checks)
- [Pool and wrapper checks](#pool-and-wrapper-checks)
- [Doma checks](#doma-checks)
- [Required failure report](#required-failure-report)
- [References](#references)

## Gate table

Compilation is the prerequisite gate; the following six rows are the ordered
runtime recovery layers.

| Layer | Representative symptom | Inspect | Recover |
| --- | --- | --- | --- |
| Compile | Missing annotation, processor diagnostic, or no generated probe DAO | JDK/build, aligned released Doma runtime and processor, processor configuration, first compiler diagnostic | Correct only the first compile or generation failure; do not attempt a database connection |
| AWS identity/authorization | `AccessDenied` or wrong account | STS identity and exact denied action/resource | Select the intended profile/role or request the narrow permission |
| RDS/Aurora/Proxy | Target not found or wrong engine | Exact region/id, engine, Proxy target/auth | Correct targeting; do not create or mutate resources |
| Network | Unknown host, connect timeout, refused port | Endpoint, DNS, VPC path, SG relationship, port | Escalate exact network gap; never disable TLS |
| TLS/auth | Certificate, password, PAM/IAM failure | Hostname, CA/trust, IAM-enabled DB user, token region/host/user | Fix the failing contract and retry only that gate |
| JDBC/pool/wrapper | No suitable driver, stale credentials, reconnect loop | Driver/wrapper/plugin versions and pool lifetime | Align verified dependencies and per-connection auth refresh |
| Doma | Wrong dialect, `Config`, transaction, or DAO result | `getDataSource`, `getDialect`, generated DAO, first Doma error | Correct the Doma boundary after JDBC succeeds |

## Run the gates in order

### 1. Compile without connecting

Run the project's existing clean compile and inspect the first error:

```bash
# Java Gradle
./gradlew clean compileJava

# Java Maven
mvn clean compile

# Kotlin Gradle Kotlin DSL
./gradlew clean compileKotlin
```

Run only the matching command. Confirm `AwsConnectionProbeDaoImpl.java` exists
under the build tool's generated-source tree. Compilation needs no database or
VPC connection, endpoint, secret value, or IAM token. A clean build may still
need network access to the configured artifact repositories while resolving
dependencies. A missing implementation is a processor/build failure, not an
RDS failure.

### 2. Confirm AWS identity and the exact target

Require the expected account, explicit region, target kind, and exact resource
id. Run the bundled read-only inspector as described in [AWS discovery](aws-discovery.md).
Stop on account mismatch, denied action, absent target, unsupported engine,
unresolved Proxy target, or conflicting Proxy metadata. Do not broaden an exact
lookup into account-wide enumeration.

Record the exact denied action and redacted resource. A read-only inspector may
request `DescribeSecret`; it must never request `GetSecretValue`. A runtime
application/library permission to retrieve one selected secret is a separate
contract.

### 3. Prove network reachability from the runtime path

Test DNS resolution and TCP reachability to the inspected endpoint and port
from the same VPC/network path as the application. A developer laptop result
does not prove ECS, EKS, EC2, or Lambda reachability. Compare the runtime VPC,
subnets, routes, name resolution, and source-to-destination security-group
relationship against the narrow identifiers returned by discovery.

Classify the first failure precisely:

- Unknown host: endpoint spelling, region, DNS resolver, or VPC DNS path.
- Timeout: route, subnet/NACL, security-group relationship, unreachable target,
  or wrong port.
- Refused: endpoint/port mismatch or target listener/health contract.

Report the gap to the AWS/network owner. Do not authorize ingress, edit a
security group, deploy a test pod/function, or switch to a public endpoint.

### 4. Prove TLS, then authentication

Validate the certificate chain and hostname against the real inspected RDS or
Proxy endpoint before sending credentials. Use the runtime's configured Amazon
RDS CA trust material and the driver equivalent of PostgreSQL
`sslmode=verify-full` or MySQL `sslMode=VERIFY_IDENTITY`.

Only after the TLS handshake and hostname succeed, attempt the selected
authentication path from the approved runtime identity. Never paste a secret or
token into a command that will enter shell history, process listings, CI logs,
or a report. Never set `trust`, `require`, `VERIFY_CA`, or disabled hostname
verification as a diagnostic shortcut.

### 5. Prove raw JDBC, pool, and wrapper

Acquire a connection through the selected unpooled `DataSource` and execute the
read-only scalar `select 1` with a finite statement timeout before involving
Hikari, wrapper plugins, or Doma. Then add layers back one at a time:

1. Engine driver and TLS/auth-aware physical `DataSource`.
2. AWS authentication integration or wrapper, when selected.
3. Hikari or the existing application pool.
4. Proxy-specific lifetime settings, when selected.

If the unpooled source succeeds and the pooled source fails, inspect physical
connection creation, stale credentials, pool exhaustion, exception handling,
and lifetime relationships. If adding the wrapper causes failure, inspect the
underlying driver, wrapper release, selected plugins, and endpoint topology.

### 6. Prove Doma

After raw JDBC succeeds, instantiate the generated
`AwsConnectionProbeDaoImpl` with `AwsRdsConfig` and the engine-matched dialect.
Invoke `selectOne()` only against the explicitly approved target. Require the
result to be `1`.

If this is the first failing gate, inspect the first Doma exception, returned
`DataSource`, selected dialect, generated implementation/runtime version match,
query timeout, and transaction ownership. Do not change SQL, add a table, or
replace the transaction manager merely to make the probe pass.

## Authentication branch checks

### IAM database authentication

Verify all of these facts without printing the token:

- IAM database authentication is enabled on the direct target, or the selected
  Proxy's authentication metadata explicitly supports the chosen client flow.
- The exact case-sensitive database user already exists and is IAM-enabled.
- For direct IAM, the runtime identity has `rds-db:connect` on the backend DB
  instance or cluster DB-user ARN. For Proxy IAM, the application/runtime role
  instead targets the Proxy DB-user ARN with its `prx-*` resource ID for the
  client-to-Proxy leg.
- For standard Proxy IAM, confirm that the Proxy service role reads the matching
  Secrets Manager password. For end-to-end Proxy IAM, confirm that the Proxy
  service role has `rds-db:connect` on the backend DB instance or cluster
  DB-user ARN. Do not confuse either backend contract with the application role.
- Token generation uses the real target endpoint, port, confirmed region, and
  exact database user—not a custom DNS alias.
- The physical `DataSource` generates a new token when it opens each physical
  connection. No startup token is stored as a long-lived pool password.
- TLS and hostname verification are enabled.

A 15-minute token validity only governs connection establishment. Do not
destroy a healthy established connection at 15 minutes or misdiagnose its age
as an expired-token failure.

### Secret/password authentication

Confirm the selected secret id and metadata, the runtime retrieval/delivery
contract, JSON field compatibility where the integration requires it, region,
rotation state, and pool refresh boundary. The inspector cannot retrieve the
value. If the approved runtime application must call `GetSecretValue`, keep the
value in memory only and redact library errors that could include it.

An old pooled physical connection may continue to use an established session;
a new physical connection can fail after rotation if the pool or integration
still supplies stale credentials. Recycle only through the application's safe
pool lifecycle after correcting the refresh contract.

### RDS Proxy authentication

Use the Proxy endpoint for both connection and IAM token signing. Branch on the
inspected `DefaultAuthScheme` and `Auth[].IAMAuth`:

- Standard IAM uses IAM from client to Proxy and a Secrets Manager password
  from Proxy to database.
- End-to-end IAM uses IAM on both legs and does not use a database secret for
  the backend credential.

Do not merge those flows or assume that enabling IAM on one leg proves the
other. IAM-authenticated Proxy clients require TLS.

## Pool and wrapper checks

For Hikari behind Proxy, verify `maxLifetime` is below the non-configurable
24-hour Proxy client maximum. If `minimumIdle < maximumPoolSize`, verify
`idleTimeout` is below the inspected `IdleClientTimeout` when the application is
intended to retire idle clients first. If
`minimumIdle >= maximumPoolSize`, including Hikari's default behavior,
`idleTimeout` does not retire idle connections; confirm that the fixed-size
choice is intentional. Check that the pool opens physical connections through
the token-refreshing source. Do not rotate a Hikari password field on a timer
and call that per-connection IAM authentication.

For the AWS Advanced JDBC Wrapper, verify the wrapper, base driver, JDK, pool,
engine, and endpoint together. Direct compatible Aurora or RDS Multi-AZ cluster
topology may use `failover2`; do not claim transaction replay or a fixed
failover duration. Behind Proxy, remove `failover`/`failover2`, `efm`/`efm2`,
and topology-dependent Read/Write Splitting. Simple R/W Splitting is supported
with Proxy only on a verified compatible wrapper release under the ruling in
[connection modes](connection-modes.md).

## Doma checks

Map `postgres` and `aurora-postgresql` to `PostgresDialect`. Map confirmed MySQL
8-compatible `mysql` and `aurora-mysql` targets to
`MysqlDialect(MysqlDialect.MySqlVersion.V8)`; the zero-argument constructor has
MySQL 5 behavior and is not the MySQL 8 recipe.

Confirm `AwsRdsConfig#getDataSource()` returns the final selected source and
`getDialect()` returns the matching dialect. Wrap the source in
`LocalTransactionDataSource` only when the application already uses Doma local
transactions. Keep any other established transaction owner unchanged.

Treat the first Doma diagnostic or exception as evidence. Do not infer Doma is
at fault from a lower-level SQL exception when raw JDBC did not pass first.

## Required failure report

End every diagnosis with this exact information shape:

```text
Proven gates: <ordered gates that passed>
First failure: <gate, operation, redacted error category>
Redacted evidence: <account/region/target kind and id, engine, endpoint kind,
  dependency/API facts, no secret material>
Next safe action: <one read-only retry or exact gap to correct>
Owner: <application owner or AWS/platform/database owner>
```

Do not report a later speculative failure. Never include a password, secret
value, IAM token, access key, credential-bearing URL, environment-file contents,
or fabricated successful gate.

## References

- [Read-only AWS discovery](aws-discovery.md)
- [Doma DataSource and probe](doma-datasource.md)
- [RDS IAM database authentication troubleshooting](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/UsingWithRDS.IAMDBAuth.Troubleshooting.html)
- [RDS SSL/TLS certificates](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/UsingWithRDS.SSL.html)
- [RDS Proxy troubleshooting](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-proxy.troubleshooting.html)
- [AWS Advanced JDBC Wrapper compatibility](https://github.com/aws/aws-advanced-jdbc-wrapper/blob/4.3.0/docs/using-the-jdbc-driver/Compatibility.md)
- [Doma 3.14.0 configuration](https://docs.domaframework.org/en/3.14.0/config/)
- [Doma 3.14.0 FAQ](https://docs.domaframework.org/en/3.14.0/faq/)
