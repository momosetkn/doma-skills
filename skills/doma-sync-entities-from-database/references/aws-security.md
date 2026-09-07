# AWS Security

## Contents

- [Confirm identity and exact target](#confirm-identity-and-exact-target)
- [AWS command allowlist](#aws-command-allowlist)
- [Secrets Manager](#secrets-manager)
- [IAM database authentication](#iam-database-authentication)
- [Child-process isolation](#child-process-isolation)
- [Database non-mutation](#database-non-mutation)
- [Failure rules](#failure-rules)

## Confirm Identity and Exact Target

Before retrieving a Secret or generating a database token, require and confirm:

- expected 12-digit account from `sts get-caller-identity`;
- explicit region;
- target kind: DB instance, DB cluster, or RDS Proxy;
- exact target identifier;
- expected `postgresql` or `mysql` family;
- database name;
- `aws-secret` plus exact Secret identifier, or `aws-iam` plus exact database
  user;
- direct or Proxy endpoint choice.

Never discover by broad list, tag, partial name, “prod,” or first match. The
endpoint, port, and engine come only from the exact confirmed RDS response. For
a Proxy, resolve every reported `RDS_INSTANCE`, `RDS_CLUSTER`, or
`TRACKED_CLUSTER` target and require one engine family before using the Proxy
endpoint.

## AWS Command Allowlist

The wrapper permits only:

```text
sts get-caller-identity
rds describe-db-instances
rds describe-db-clusters
rds describe-db-proxies
rds describe-db-proxy-targets
secretsmanager describe-secret
secretsmanager get-secret-value
rds generate-db-auth-token
```

All RDS and Secret calls include the explicit region and exact identifier.
There is no create, modify, delete, failover, restore, rotate, IAM-policy, or
network operation. Do not add one to complete entity synchronization.

## Secrets Manager

First describe the exact Secret and require its ARN account and region to match
the confirmed identity. Then retrieve it just in time. Accept only a JSON
Secret String with non-empty `username` and `password`; reject binary or
malformed values. Optional host, port, engine, and database fields can confirm
the RDS target but cannot redirect it.

Do not place a Secret value in CLI arguments, a JDBC URL, a plan, a project
file, a response, or a log. Unset the raw AWS response and parsed secret as soon
as the child environment is prepared.

## IAM Database Authentication

Generate the token only after account, region, target, endpoint, port, engine,
database, and user are confirmed. Treat it as a short-lived password: pass it
only to the metadata/CodeGen child environment, never save or reuse it. IAM
database authentication does not by itself prove the database user is
read-only; use a metadata principal with database-side restrictions.

PostgreSQL direct/Proxy URLs use `sslmode=verify-full`. MySQL URLs use
`sslMode=VERIFY_IDENTITY`. A Secret cannot override these routing and TLS
choices.

## Child-Process Isolation

- Every Gradle invocation uses `--no-daemon` and a fresh mode-0700 Gradle user
  home so caller properties cannot be loaded.
- AWS credential/profile/web-identity/shared-file/container variables are
  available only to AWS CLI calls. They are removed from Python, Java, Gradle,
  redaction, and cleanup children.
- Database URL/user/password or token enter only the specific Java snapshot and
  entity-task child environments.
- The streaming redactor masks the actual password/token on stdout and stderr
  while preserving the real child exit status.
- The snapshot and generated tree are scanned for the actual credential and
  credential-like patterns. Unsafe candidate outputs are removed only after
  their canonical paths are revalidated below the project build directory.
- Never enable shell tracing. Never report raw driver/AWS exceptions, URL,
  host, user, token, Secret value, or classpath.

## Database Non-Mutation

The wrapper invokes no database CLI, DDL, or DML. The snapshot helper uses JDBC
metadata only; CodeGen may use read-only comment queries. Test mutation denial
only against a disposable database you own, with a separate administrator used
solely to initialize that fixture. Never reuse those probes against a supplied
local, RDS, Aurora, or Proxy target.

## Failure Rules

Stop before connection on account/region/identifier mismatch, ambiguous Proxy
targets, engine mismatch, unsafe endpoint, Secret identity or routing conflict,
credential-bearing URL, project-local secret, missing input, or output-path
escape. Report only the field/category that failed. Do not retry against a
different target or credential source automatically.

## Sources

- [AWS CLI `get-caller-identity`](https://docs.aws.amazon.com/cli/latest/reference/sts/get-caller-identity.html)
- [AWS CLI RDS commands](https://docs.aws.amazon.com/cli/latest/reference/rds/)
- [AWS CLI `get-secret-value`](https://docs.aws.amazon.com/cli/latest/reference/secretsmanager/get-secret-value.html)
- [RDS IAM database authentication](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/UsingWithRDS.IAMDBAuth.html)
- [RDS Proxy](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-proxy.html)
