# Connection modes

Choose from inspected project, runtime, engine, endpoint, Proxy authentication, and credential-delivery evidence. No mode is universally best, and a Lambda or connection burst is only a reason to evaluate an existing RDS Proxy—not permission to create one.

| Mode | Prefer when | Avoid or verify |
| --- | --- | --- |
| Direct JDBC + runtime-delivered secret | Long-lived service, existing secret delivery, no Proxy requirement | Rotation behavior, pool credential refresh, TLS |
| Direct JDBC + IAM authentication | Runtime role and DB user are IAM-ready | Per-connection token generation, TLS, pool integration |
| RDS Proxy + secret-backed database auth | Bursty clients or shared connection management | VPC reachability, Proxy pool/client lifetime, pinning |
| RDS Proxy + IAM client auth | Runtime identity should authenticate to Proxy | Standard versus end-to-end IAM, exact `rds-db:connect` resource |
| AWS Advanced JDBC Wrapper direct | Aurora or supported Multi-AZ topology-aware failover/auth plugins are needed | Current engine/plugin compatibility and base driver |
| AWS Wrapper with RDS Proxy | A documented authentication workflow or Simple R/W Splitting use case requires it | Verify a compatible wrapper release; do not enable topology failover, host monitoring, or topology-dependent Read/Write Splitting |

## Decide in order

1. Use an explicitly selected existing Proxy endpoint and its inspected authentication contract when Proxy is required.
2. Evaluate Proxy for short-lived, highly concurrent, or bursty clients. Do not provision it in this workflow.
3. For a direct Aurora or supported RDS Multi-AZ cluster that needs topology-aware failover, evaluate the AWS Advanced JDBC Wrapper.
4. Use IAM authentication only when the runtime role and exact, case-sensitive database user are already prepared.
5. Otherwise, retain the application's established runtime secret-delivery path.

## Direct secret-backed JDBC

Keep the secret outside source code, DAO parameters, JDBC URLs, logs, and reports. An application or Secrets Manager JDBC integration may legitimately need runtime `secretsmanager:DescribeSecret` and `secretsmanager:GetSecretValue`; the inspection workflow must never retrieve the value. Verify how the existing pool receives refreshed credentials before claiming rotation support. The AWS Secrets Manager JDBC integration caches credentials and refreshes on rotation; a standalone client cache has different refresh and invalidation behavior, so do not substitute one blindly.

Require TLS hostname verification: for example, use PostgreSQL `sslmode=verify-full` or MySQL `sslMode=VERIFY_IDENTITY` where supported by the project-selected driver. Preserve a compatible existing driver and pool rather than forcing current example versions.

## Direct IAM authentication

Confirm that IAM DB authentication is enabled, the database user is prepared, and the runtime identity has least-privilege `rds-db:connect` for the exact resource:

```text
arn:aws:rds-db:<region>:<account-id>:dbuser:<db-or-cluster-resource-id>/<db-user>
```

Generate an unlogged token for the exact RDS endpoint, port, region, and case-sensitive username for every new physical connection. With AWS SDK for Java 2.x, use `RdsClient.utilities()` / `RdsUtilities`, `GenerateAuthenticationTokenRequest`, and `generateAuthenticationToken`. A token is valid for 15 minutes for establishing a connection; its expiry does not impose a 15-minute lifetime on an established connection. Do not use a custom DNS alias for signing, and do not place one startup token into a long-lived pool password field.

## RDS Proxy

Use the Proxy endpoint, never the cluster or instance endpoint, for client connection and IAM token signing. Inspect `DefaultAuthScheme` and `Auth[].IAMAuth` before deciding between:

- standard IAM: client to Proxy uses IAM; Proxy to database uses a Secrets Manager password;
- end-to-end IAM: both legs use IAM and no database secret supplies the backend credential.

The current RDS Proxy connection page documents both flows, but a later tip on that page still says Proxy always uses Secrets Manager password authentication. Treat that tip narrowly as legacy standard-IAM text. Do not merge the statements or guess: branch on the selected Proxy's inspected authentication metadata and derive the exact Proxy or database resource ID required by that contract. IAM-authenticated Proxy clients must use TLS.

When the application retains its own pool in front of Proxy, keep its maximum connection lifetime below Proxy's non-configurable 24-hour client-connection limit and its idle timeout below the inspected `IdleClientTimeout`. Inspect pinning behavior and do not copy arbitrary lifetime values.

## AWS Advanced JDBC Wrapper

Use topology-aware wrapper behavior only for direct Aurora or currently supported RDS Multi-AZ DB clusters. Verify the inspected engine, project JDK, wrapper release, underlying PostgreSQL/MySQL driver, pool, and selected plugins together. The current wrapper uses `failover2` for Failover Plugin v2 and enables it by default when `wrapperPlugins` is absent; do not assume transaction replay or measured failover timing.

RDS Proxy owns topology target routing. Behind Proxy, disable `failover`/`failover2`, Enhanced Host Monitoring (`efm`/`efm2`), and topology-dependent Read/Write Splitting. Authentication workflows remain supported when their plugin and credentials match the inspected Proxy contract.

The **Simple R/W Splitting Plugin** is supported with RDS Proxy starting with wrapper 3.0.0 according to the [official RDS Proxy compatibility section](https://github.com/aws/aws-advanced-jdbc-wrapper#rds-proxy). Allow it only after verifying that the project uses a compatible wrapper release and the Simple plugin rather than topology-dependent Read/Write Splitting. Otherwise, use the base driver or another currently documented compatible wrapper configuration.

## Official references

- [Amazon RDS Proxy](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-proxy.html)
- [Connecting through RDS Proxy](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-proxy-connecting.html)
- [RDS Proxy connection considerations](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-proxy-connections.html)
- [IAM database account setup](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/UsingWithRDS.IAMDBAuth.DBAccounts.html)
- [IAM database access policies](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/UsingWithRDS.IAMDBAuth.IAMPolicy.html)
- [IAM database authentication connections](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/UsingWithRDS.IAMDBAuth.Connecting.html)
- [IAM authentication with the AWS SDK for Java](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/UsingWithRDS.IAMDBAuth.Connecting.Java.html)
- [Secrets Manager JDBC connections](https://docs.aws.amazon.com/secretsmanager/latest/userguide/retrieving-secrets_jdbc.html)
- [Secrets Manager Java client-side caching](https://docs.aws.amazon.com/secretsmanager/latest/userguide/retrieving-secrets_cache-java.html)
- [AWS Advanced JDBC Wrapper](https://github.com/aws/aws-advanced-jdbc-wrapper)
- [AWS Advanced JDBC Wrapper with RDS Proxy](https://github.com/aws/aws-advanced-jdbc-wrapper#rds-proxy)
