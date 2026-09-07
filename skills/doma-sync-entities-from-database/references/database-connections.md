# Database Connections

## Contents

- [Confirm scope before credentials](#confirm-scope-before-credentials)
- [Local and containerized databases](#local-and-containerized-databases)
- [AWS modes](#aws-modes)
- [Run the wrapper](#run-the-wrapper)
- [Read-only contract](#read-only-contract)

## Confirm Scope Before Credentials

Require these non-secret facts before generation:

1. database family: `postgresql` or `mysql`;
2. connection mode: `local`, `aws-secret`, or `aws-iam`;
3. database name, plus PostgreSQL schema or MySQL catalog;
4. explicit table regular expression and entity package;
5. whether `.*` really means every table in scope;
6. a read-only metadata principal.

PostgreSQL table identity uses schema and table. MySQL table identity uses
catalog (the database name) and table. Never silently exchange schema and
catalog or infer a production target from a hostname or project name.

## Local and Containerized Databases

`local` covers a database on the host, Docker Compose, or another locally
managed runtime. The wrapper resolves values in this order:

1. `DOMA_CODEGEN_DB_URL`, `DOMA_CODEGEN_DB_USER`, and
   `DOMA_CODEGEN_DB_PASSWORD` environment variables;
2. `domaCodegenDbUrl`, `domaCodegenDbUser`, and
   `domaCodegenDbPassword` in the user's Gradle properties file.

Do not put these values in project `gradle.properties`, build scripts, shell
commands, plan files, or committed environment files. A JDBC URL must contain
only routing/options, never `user:password@`, `user=`, `password=`, token,
Secret, or access-key parameters. The family prefix must match `--database`.

Example provider setup for a disposable shell (values intentionally omitted):

```bash
export DOMA_CODEGEN_DB_URL='jdbc:postgresql://127.0.0.1:5432/app'
export DOMA_CODEGEN_DB_USER='metadata_reader'
export DOMA_CODEGEN_DB_PASSWORD='...'
```

For MySQL, the database name is derived from a normal
`jdbc:mysql://host:port/database` local URL. Use an account restricted to
metadata and `SELECT` where the engine requires it. The workflow itself never
uses `psql`, `mysql`, DDL, or DML.

## AWS Modes

Both AWS modes require:

- `--expected-account` with the exact 12-digit account;
- `--region`;
- `--target-kind instance|cluster|proxy`;
- exact `--target-id`;
- `--db-name`;
- optional `--profile` when the current AWS environment is not the intended
  identity.

Use `aws-secret` with an exact `--secret-id`. The secret must be a JSON Secret
String with non-empty `username` and `password`. Optional host, port, engine,
and database fields may only agree with the separately confirmed target; they
cannot redirect it.

Use `aws-iam` with exact `--db-user`. The wrapper creates the database-auth
token only after endpoint and engine confirmation and uses it immediately as
the JDBC password. Do not save or reuse it.

For RDS Proxy, select the proxy identifier, not an inferred backing endpoint.
The wrapper confirms the proxy and every reported instance/cluster target,
requires one engine family, and uses the proxy endpoint with the resolved
engine's standard port. See [AWS Security](aws-security.md) for the complete
allowlist and isolation contract.

## Run the Wrapper

Local PostgreSQL:

```bash
./scripts/generate-entities.sh \
  --project-root . --connection local --database postgresql \
  --schema tenant --table-pattern 'tenant_.*'
```

Aurora MySQL with an IAM token:

```bash
./scripts/generate-entities.sh \
  --project-root . --connection aws-iam --database mysql \
  --expected-account 123456789012 --region ap-northeast-1 \
  --target-kind cluster --target-id app-aurora \
  --db-name app --catalog app --table-pattern 'tenant_.*' \
  --db-user metadata_reader
```

Pass the same PostgreSQL `--schema` or MySQL `--catalog` and
`--table-pattern` used by the reviewed configuration plan. PostgreSQL defaults
to `public`, MySQL catalog defaults to the selected database name, and the table
pattern defaults to `.*` only so the frozen basic invocation remains valid;
explicitly confirm those defaults before using them. The wrapper rejects a
schema/catalog family mismatch and a MySQL catalog that differs from the
selected database. Do not continue if the snapshot or generated set differs
from the confirmed scope.

## Read-Only Contract

The snapshot helper uses JDBC `DatabaseMetaData.getTables`, `getColumns`, and
`getPrimaryKeys`. CodeGen may additionally issue documented read-only comment
queries. Therefore promise no DDL or DML, not “no SQL.” Prefer a dedicated
read-only principal and verify its denial of mutation only in a disposable
environment you own.

## Sources

- [Java 17 `DatabaseMetaData`](https://docs.oracle.com/en/java/javase/17/docs/api/java.sql/java/sql/DatabaseMetaData.html)
- [Gradle build environment](https://docs.gradle.org/current/userguide/build_environment.html)
- [Amazon RDS IAM database authentication](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/UsingWithRDS.IAMDBAuth.html)
- [Amazon RDS Proxy](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-proxy.html)
