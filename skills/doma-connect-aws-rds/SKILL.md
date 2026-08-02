---
name: doma-connect-aws-rds
description: Use when connecting or repairing an existing plain Java or Kotlin Doma application to Amazon RDS or Aurora PostgreSQL/MySQL with direct JDBC, IAM database authentication, Secrets Manager, RDS Proxy, or the AWS Advanced JDBC Wrapper.
---

# Connect Doma to AWS RDS

## Prerequisite

Confirm that Doma annotation processing already works and the existing project compiles far enough to generate its Doma classes. If initial setup fails, stop and use the `doma-setup-project` or `doma-setup-kotlin-project` concern when available, then return here after annotation processing succeeds. Do not require either setup skill as a filesystem dependency.

Apply this workflow only to an existing supported project and an existing RDS, Aurora, or RDS Proxy target. Supported project shapes are Java with Gradle or Maven, and Kotlin/JVM with Gradle Kotlin DSL. Stop and route every other language/build combination—including Kotlin with Maven or Gradle Groovy DSL—without changing files. Inspect facts; do not invent project files, AWS resources, identifiers, versions, authentication state, or successful verification.

## Ordered workflow

Follow every stage in order. At stage 2, read [AWS discovery](references/aws-discovery.md) before describing or inspecting the target. At stage 3, read [connection modes](references/connection-modes.md) before selecting a topology or authentication mode.

1. Inspect the existing project and preserve its build, language, Doma, JDK, Kotlin, pool, and transaction choices.
2. Confirm AWS account, region, target kind, and exact resource id before describing resources. Only after all four are confirmed, run the bundled [read-only RDS connection inspector](scripts/inspect-rds-connection.sh) as routed by [AWS discovery](references/aws-discovery.md).
3. Choose Proxy, direct wrapper, direct IAM, or direct secret-backed JDBC from evidence; never stack topology-owning Proxy and wrapper plugins blindly.
4. Map PostgreSQL targets to `PostgresDialect` and MySQL 8 targets to `MysqlDialect(MysqlDialect.MySqlVersion.V8)`.
5. Build the smallest matching `DataSource` and `Config` without putting credentials in DAO code.
6. Verify compile, DNS/TCP, TLS, authentication, JDBC, then Doma `SELECT 1`; stop at the first failure.
7. Report the selected mode, required runtime IAM actions, changed files, completed gates, and first unresolved gate without secret material.

Stop before code changes when the expected account, region, exact target, engine, runtime, or authentication contract is ambiguous. Preserve compatible project-selected dependency versions and JDKs; current release pins are examples, not an upgrade instruction. Preserve the application's transaction owner. If it uses Doma local transactions, wrap the final connection `DataSource`; otherwise keep the existing pool and transaction strategy.

Never expose or log a password, secret value, IAM token, access key, credential-bearing URL, or copied environment-file contents. Never disable TLS or hostname verification to pass a probe. Generate IAM tokens for new physical connections rather than setting one startup token as a long-lived pool password.

## Scope boundary

Refuse resource provisioning or mutation, deployment, IAM or database-user changes, security-group changes, secret retrieval, and production failover. Route SQL tuning/index work, framework-specific dependency injection or transactions, schema migrations, entity design, and initial Doma setup to their respective concerns. Doma does not create or apply schema migrations as part of this connection workflow.
