# Runtime and lifetime guidance

Apply this reference after selecting a mode and building the matching
`DataSource`. Preserve the application's deployment and shutdown model. Do not
deploy, change IAM, provision a Proxy, or mutate a database as part of this
connection workflow.

## Contents

- [Runtime decision table](#runtime-decision-table)
- [Credential identity and permissions](#credential-identity-and-permissions)
- [Pool, token, and Proxy lifetimes](#pool-token-and-proxy-lifetimes)
- [Runtime-specific guidance](#runtime-specific-guidance)
- [TLS and configuration delivery](#tls-and-configuration-delivery)
- [Connection observability baseline](#connection-observability-baseline)
- [Shutdown and reporting](#shutdown-and-reporting)
- [References](#references)

## Runtime decision table

| Runtime | Credential source | Pool/lifetime focus | Proxy decision |
| --- | --- | --- | --- |
| EC2 | Instance profile/default chain | Bound pool and refresh auth before expiry | Evaluate for shared scale/failover needs |
| ECS | Task role/default chain | Size per task count; avoid embedding node credentials | Evaluate for burst or aggregate connection pressure |
| EKS | Pod Identity or IRSA/default chain | Confirm pod identity rather than node role | Evaluate from aggregate pod concurrency |
| Lambda | Execution role/default chain | Reuse initialized clients; bound connections across concurrency | Prefer evaluation for frequent short connections or bursts |

The table is a starting point, not a reason to change runtime architecture.
Confirm the actual credential source and connection concurrency from the
existing application. Use only an existing explicitly selected Proxy.

## Credential identity and permissions

Let the AWS SDK default credential provider chain obtain short-lived workload
credentials. Do not embed access keys, copy a developer profile into a runtime,
or fall back from a pod/task role to a node/instance role silently.

Map runtime permission to the selected mode:

| Selected mode | Runtime permission contract |
| --- | --- |
| Direct IAM | `rds-db:connect` for the exact DB instance or cluster resource ID and case-sensitive database user |
| Proxy IAM, client to Proxy | For both standard and end-to-end IAM, the application/runtime role has `rds-db:connect` on the Proxy DB-user ARN. Its resource segment uses the Proxy's `prx-*` resource ID and the exact case-sensitive database user, not the backend DB resource ID. |
| Proxy IAM, standard backend | RDS Proxy connects to the database with the matching password from Secrets Manager. Inspect the Proxy service role's existing secret/KMS access; this leg does not use the application's `rds-db:connect` permission. |
| Proxy IAM, end-to-end backend | RDS Proxy connects to the database with IAM. Inspect the Proxy service role's `rds-db:connect` permission on the backend DB instance or cluster DB-user ARN; do not substitute the application's role or the Proxy `prx-*` resource ID on this leg. |
| Secrets Manager JDBC or application secret retrieval | Narrow `secretsmanager:DescribeSecret` and `secretsmanager:GetSecretValue` for the selected secret, plus KMS permission only when the secret's key contract requires it |
| Runtime-delivered secret | Preserve the platform's existing delivery contract; do not add an SDK client when the runtime already supplies rotated credentials safely |

Treat the two Proxy legs as separate identity checks. Inspect and report the
existing application role, Proxy service role, authentication mode, and exact
resource ARN. This skill does not create or change either role or policy.

The read-only discovery workflow may inspect secret metadata with
`DescribeSecret`, but it must never retrieve the value. A runtime library's
need for `GetSecretValue` is a separate least-privilege application contract.
Never exercise that permission merely to author or inspect the connection.

## Pool, token, and Proxy lifetimes

Keep these independent clocks separate:

- An IAM database authentication token is valid for 15 minutes to establish a
  new connection. Generate a fresh token at every new physical connection
  acquisition. Expiry does not terminate an already established connection.
- RDS Proxy has a non-configurable 24-hour maximum client-connection lifetime.
  When Hikari remains in front of Proxy, set `maxLifetime` below 24 hours so the
  application retires connections first.
- RDS Proxy's `IdleClientTimeout` is configurable and must be read from the
  selected Proxy. Hikari applies `idleTimeout` only when
  `minimumIdle < maximumPoolSize`. For that elastic configuration, set
  `idleTimeout` below the inspected Proxy value if the application must retire
  idle clients first. A fixed-size configuration with
  `minimumIdle >= maximumPoolSize`—including Hikari's default behavior—does not
  retire idle connections through `idleTimeout`; choose pool size and this
  relationship intentionally.
- Hikari `connectionTimeout`, a driver login/connect/socket timeout, Proxy
  `ConnectionBorrowTimeout`, and Doma's statement query timeout guard different
  waits. Configure each deliberately; none substitutes for another.
- Secret rotation, SDK credential refresh, IAM token validity, Hikari
  `maxLifetime`, and database/Proxy connection lifetime are separate. Verify the
  actual integration's refresh boundary rather than choosing one universal
  duration.

Proxy still requires an application-side pool decision. Bound both pool size
and lifetime from the application's concurrency, database capacity, number of
runtime replicas, and observed Proxy configuration. Performance sizing and
tuning remain outside this skill.

## Runtime-specific guidance

### EC2

Use the instance profile through the default chain. Confirm the process is not
selecting a local shared-credentials file left on the host. Reuse the AWS SDK
credential provider and IAM utilities, generate tokens only when the pool opens
a physical connection, and close pool resources on process shutdown.

Account for the product of pool size and instance count. Evaluate an existing
Proxy when many services share the database or when its connection-management
and failover behavior is required; do not create one here.

### ECS

Use the ECS task role, not the container-instance role or baked-in
credentials. Keep the metadata credential path reachable and size connections
across desired task count, deployment overlap, and autoscaling bursts. A task
restart must rebuild SDK clients and the pool from runtime configuration rather
than reuse a serialized token or secret value.

Evaluate the selected Proxy when aggregate task concurrency or bursts create
connection pressure. Continue to bound each task's pool even behind Proxy.

### EKS

Use EKS Pod Identity or IRSA as selected by the cluster. Confirm the pod's
effective caller identity and service-account binding rather than accepting the
node role. Keep `software.amazon.awssdk:sts` aligned with the AWS SDK BOM when
the selected IRSA/assume-role path requires it. The Secrets Manager JDBC library
also documents STS v2 as the remedy when EKS otherwise selects node credentials.

Calculate aggregate connections across replicas, rollout surge, horizontal
autoscaling, and side-by-side versions. Do not change service accounts, trust
policies, or Kubernetes manifests in this workflow; report the exact identity
gap to the platform owner.

### Lambda

Use the Lambda execution role/default chain. Initialize and reuse SDK credential
providers, `RdsUtilities`, and an intentionally bounded `DataSource` outside the
handler when the runtime is reused. Do not generate one IAM token during cold
start and store it as the pool password. The token-producing physical
`DataSource` must generate again whenever the pool opens a connection.

Bound connections against reserved/provisioned concurrency and concurrent
execution environments. Reuse does not guarantee that one pool or connection
serves every invocation, and frozen environments may retain idle clients. AWS
recommends evaluating RDS Proxy for Lambda workloads that make frequent short
connections or have high concurrency. Use only an existing confirmed Proxy and
retain application-side limits.

## TLS and configuration delivery

Use the real inspected RDS or Proxy endpoint for both token signing and TLS
hostname validation. Do not sign a custom DNS alias. Require PostgreSQL
`sslmode=verify-full` or MySQL `sslMode=VERIFY_IDENTITY` when supported by the
project-selected driver. Install and rotate the appropriate Amazon RDS CA trust
material through the runtime's established mechanism; never disable TLS or
hostname verification to make a probe pass.

Deliver non-secret settings—account context, region, endpoint, port, database,
user or secret id, and trust path—through the application's existing
configuration mechanism. Treat the endpoint and secret id as sensitive
operational metadata even though they are not passwords. Never print passwords,
secret values, IAM tokens, access keys, credential-bearing URLs, environment
file contents, or SDK request debug bodies.

## Connection observability baseline

Keep observability limited to connection verification:

- Compile the top-level probe and confirm its generated DAO implementation.
- Use the probe's `SqlLogType.RAW`, which keeps bind placeholders rather than
  formatting bind values into that query log. It does not globally change
  Doma's exception SQL formatting.
- Keep the probe's finite five-second Doma statement timeout. Preserve separate
  driver, pool, and Proxy timeouts.
- If the project already uses SLF4J, retain its configured Doma JDBC logger and
  redact surrounding connection metadata. Never log connection properties or
  URLs that can contain credentials.
- Report connection acquisition latency/error category only at the existing
  metrics boundary; avoid high-cardinality endpoint, user, SQL, or token labels.

Doma's statistic collection is disabled by default. The default
`DefaultStatisticManager` retains entries keyed by raw SQL without a built-in
retention bound while enabled. Leave it disabled for connection setup. If the
application deliberately enables it, clear it periodically or replace it with
a bounded implementation before production use.

Route database log export, Database Insights, slow-query analysis, `EXPLAIN` or
`EXPLAIN ANALYZE`, SQL rewrites, and index design to a future performance skill.
Do not run or recommend those operations as connection verification.

## Shutdown and reporting

Close resources from the outer layer inward: stop new application work, close
the application pool, then close any explicitly created AWS SDK credential
provider/client resources. In Lambda, allow the execution environment to reuse
initialized resources between invocations and do not close them at the end of
each handler call unless the existing application lifecycle requires it.

Report the runtime, effective credential source, selected endpoint kind, pool
owner, token/secret refresh boundary, relevant Proxy lifetime relationship,
completed verification gates, and first failure. Redact all secret material.

## References

- [AWS SDK for Java 2.x default credential provider chain](https://docs.aws.amazon.com/sdk-for-java/latest/developer-guide/credentials-chain.html)
- [EC2 IAM roles](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/iam-roles-for-amazon-ec2.html)
- [ECS task IAM roles](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-iam-roles.html)
- [EKS Pod Identity](https://docs.aws.amazon.com/eks/latest/userguide/pod-identities.html)
- [IAM roles for EKS service accounts](https://docs.aws.amazon.com/eks/latest/userguide/iam-roles-for-service-accounts.html)
- [Lambda execution role](https://docs.aws.amazon.com/lambda/latest/dg/lambda-intro-execution-role.html)
- [Lambda with RDS](https://docs.aws.amazon.com/lambda/latest/dg/services-rds.html)
- [Connecting to RDS Proxy with standard or end-to-end IAM](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-proxy-connecting.html)
- [Configuring RDS Proxy IAM authentication](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-proxy-iam-setup.html)
- [RDS Proxy connection considerations](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-proxy-connections.html)
- [IAM database authentication connections](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/UsingWithRDS.IAMDBAuth.Connecting.html)
- [RDS certificate authority rotation](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/UsingWithRDS.SSL-certificate-rotation.html)
- [Doma 3.14.0 configuration and statistics](https://docs.domaframework.org/en/3.14.0/config/)
- [Doma `DefaultStatisticManager`](https://github.com/domaframework/doma/blob/3.14.0/doma-core/src/main/java/org/seasar/doma/jdbc/statistic/DefaultStatisticManager.java)
