# Doma AWS RDS Connection Skill Design

## Goal

Create an installable `doma-connect-aws-rds` skill that connects an existing plain Java or Kotlin Doma project to an existing Amazon RDS or Amazon Aurora database safely and verifiably.

The skill covers these database targets:

- Amazon Aurora PostgreSQL
- Amazon RDS for PostgreSQL
- Amazon Aurora MySQL
- Amazon RDS for MySQL

It remains framework-independent and supports applications running on EC2, ECS, EKS, or Lambda. A later, separate `doma-diagnose-aws-rds-performance` skill will handle CloudWatch Database Insights, slow-query diagnosis, execution plans, and tuning.

## User Outcomes

The skill should let an agent:

1. inspect an existing Doma project and the explicitly selected AWS database safely;
2. choose among direct JDBC, IAM database authentication, Secrets Manager, RDS Proxy, and the AWS Advanced JDBC Wrapper;
3. add or repair the matching JDBC dependencies, `DataSource`, Doma `Config`, and dialect;
4. verify compilation, network reachability, authentication, JDBC connectivity, and a read-only Doma DAO probe in order;
5. leave the application ready for later performance investigation without expanding into query tuning.

## Trigger Boundary

Positive trigger examples:

```text
Connect this Kotlin Doma Lambda function to Aurora PostgreSQL through RDS Proxy with IAM authentication.
```

```text
Configure this plain Java Doma service on ECS to use an existing RDS MySQL database whose credentials are managed by Secrets Manager.
```

```text
Our Doma application cannot connect to Aurora MySQL after failover. Check whether direct JDBC, RDS Proxy, or the AWS Advanced JDBC Wrapper is appropriate.
```

Nearby prompts that must not trigger this skill as their primary authority:

```text
Provision a new production Aurora PostgreSQL cluster and security groups.
```

```text
Find and optimize the slowest SQL query in this Doma application.
```

```text
Configure Spring Boot transaction management for Doma.
```

The skill assumes Doma annotation processing already works. If it does not, diagnose project setup first using the appropriate Java or Kotlin setup guidance, then return to the AWS connection workflow.

## Chosen Architecture

Use one public skill for all four database targets. Keep the decision workflow in `SKILL.md`, move exact engine and runtime details into direct references, and provide one deterministic read-only AWS inspection script.

```text
skills/doma-connect-aws-rds/
  SKILL.md
  agents/
    openai.yaml
  references/
    connection-modes.md
    aws-discovery.md
    doma-datasource.md
    runtime-guidance.md
    troubleshooting.md
  scripts/
    inspect-rds-connection.sh
```

### Component Responsibilities

- `SKILL.md`: Defines triggers, prerequisites, the ordered decision workflow, verification gates, failure behavior, exclusions, and reference routing.
- `references/connection-modes.md`: Compares direct JDBC, IAM authentication, Secrets Manager, RDS Proxy, and AWS Advanced JDBC Wrapper combinations. It records incompatible or redundant combinations, especially features that RDS Proxy already owns.
- `references/aws-discovery.md`: Defines identity confirmation and narrowly scoped read-only AWS CLI inspection. It explains which metadata is safe to collect and how to avoid exposing credentials, tokens, or credential-bearing URLs.
- `references/doma-datasource.md`: Provides PostgreSQL and MySQL dependency choices, Doma dialect mapping, pooled or wrapped `DataSource` construction, and `Config` examples. Java is the primary example; matching Kotlin examples are included where syntax or lifetime handling differs. Existing build tools and versions are preserved.
- `references/runtime-guidance.md`: Covers credential-provider and connection-lifetime decisions for EC2, ECS, EKS, and Lambda without adding framework-specific DI or transaction configuration.
- `references/troubleshooting.md`: Maps symptoms to the first failing layer and the next safe diagnostic action.
- `scripts/inspect-rds-connection.sh`: Accepts an explicit AWS profile or credential context, region, target kind, and exact resource identifier. It calls only an allowlisted set of read-only AWS APIs and emits a redacted machine-readable summary.

## Supported Project Shapes

The skill adapts to an existing project rather than replacing its build or language versions.

- Plain Java with Gradle or Maven
- Plain Kotlin/JVM with Gradle Kotlin DSL
- Existing Doma `Config` implementation or a new framework-independent implementation
- Existing application-managed or Doma local transaction boundary

The skill does not repeat initial Doma annotation-processor setup. It adds only the cloud/JDBC dependencies and code needed for the selected connection mode.

## Decision Workflow

### 1. Inspect the Project

Identify:

- Java or Kotlin;
- Gradle or Maven;
- selected Doma version;
- current JDBC driver and connection-pool dependencies;
- current `Config`, `DataSource`, dialect, transaction manager, and DAO construction;
- EC2, ECS, EKS, Lambda, or an explicitly described equivalent runtime.

Preserve compatible project choices. Do not replace the build system, Doma version, JDK, Kotlin version, connection pool, or transaction strategy merely to follow an example.

### 2. Confirm AWS Identity and Target

Before inspection, require:

- the intended AWS account to be confirmed against `aws sts get-caller-identity`;
- an explicit region;
- an exact DB instance, DB cluster, or RDS Proxy identifier.

Inspect only the selected resources. Retrieve engine, endpoint, port, IAM-authentication setting, proxy target and authentication metadata, and the minimum referenced network metadata needed for diagnosis.

Do not call `secretsmanager:GetSecretValue`. Secret values must be resolved by the application at runtime or supplied through the user's established secret-delivery mechanism.

### 3. Choose a Connection Mode

Use this order:

1. If an existing RDS Proxy is explicitly selected, use its endpoint and authentication contract.
2. For Lambda or highly bursty connection workloads, recommend evaluating RDS Proxy, but do not create it.
3. For direct Aurora or supported RDS Multi-AZ cluster connections that require faster failover, evaluate the AWS Advanced JDBC Wrapper.
4. Choose IAM database authentication when the runtime identity and DB user are already prepared for it.
5. Otherwise, use password authentication through the user's existing Secrets Manager delivery path.

Do not combine RDS Proxy with AWS JDBC Wrapper failover, host-monitoring, or read/write-splitting behavior that depends on direct cluster topology. A wrapper may still be useful for a specifically supported authentication path, but the skill must verify current compatibility before recommending it.

### 4. Map the Engine to Doma

| AWS target | JDBC family | Doma dialect |
| --- | --- | --- |
| Aurora PostgreSQL | PostgreSQL | `PostgresDialect` |
| RDS PostgreSQL | PostgreSQL | `PostgresDialect` |
| Aurora MySQL | MySQL | `MysqlDialect`, configured for MySQL 8 when applicable |
| RDS MySQL | MySQL | `MysqlDialect`, configured for MySQL 8 when applicable |

Return the selected or constructed `DataSource` from Doma `Config`. Keep authentication-token refresh, secret rotation, pool lifetime, and wrapper configuration outside DAO code.

### 5. Build the Connection

Produce only the artifacts required by the selected project:

- JDBC driver or AWS wrapper dependencies;
- AWS SDK or Secrets Manager integration dependencies only when used;
- connection-pool configuration when the project owns a pool;
- environment-variable or runtime configuration names without secret values;
- Java or Kotlin `DataSource` construction;
- Doma `Config` with the matching dialect;
- a read-only DAO probe when no existing health check is suitable.

Never place a password, IAM authentication token, full credential-bearing JDBC URL, access key, or secret value in source, build files, logs, or the final response.

### 6. Verify in Layers

Verify in this order and stop at the first failing layer:

1. project compilation;
2. DNS and TCP reachability;
3. TLS negotiation and hostname validation;
4. IAM or password/secret authentication;
5. raw JDBC connection acquisition;
6. read-only Doma DAO `SELECT 1` execution.

Do not disable TLS, certificate validation, Doma validation, or authentication safeguards to make a probe pass.

### 7. Leave an Observability Baseline

The connection skill may:

- configure Doma or SLF4J SQL logging to use raw SQL in production-oriented examples;
- set explicit connection and query timeout guidance;
- explain optional `StatisticManager` enablement and its retention risk;
- identify which DAO method owns the connection probe.

It must not enable database slow-query logging, modify parameter groups, query CloudWatch Database Insights for tuning, run broad `EXPLAIN` analysis, create indexes, or rewrite business SQL. Those belong to `doma-diagnose-aws-rds-performance`.

## Read-Only AWS Command Contract

The inspection script may use only the minimum required subset of:

- `aws sts get-caller-identity`
- `aws rds describe-db-instances`
- `aws rds describe-db-clusters`
- `aws rds describe-db-proxies`
- `aws rds describe-db-proxy-targets`
- `aws secretsmanager describe-secret`
- narrowly targeted `aws ec2 describe-vpcs`
- narrowly targeted `aws ec2 describe-subnets`
- narrowly targeted `aws ec2 describe-security-groups`

Every describe call must include the explicit region and the narrowest available identifier or filter. The script must reject missing account confirmation, region, target kind, or resource identifier.

The script must never invoke create, modify, delete, attach, detach, authorize, revoke, restore, promote, failover, rotate, or secret-value retrieval operations.

## Output Contract

Every completed workflow reports:

- confirmed AWS account and region in a non-secret form;
- selected DB target and engine family;
- runtime type;
- selected connection and authentication mode with rationale;
- Doma dialect and `DataSource` strategy;
- project files changed;
- IAM actions the runtime requires;
- verification result for each completed layer;
- the first unresolved layer and next safe diagnostic when incomplete;
- operational limitations for RDS Proxy, IAM authentication, Secrets Manager rotation, or the AWS JDBC Wrapper.

The response must not contain secret values, IAM tokens, credential-bearing URLs, or copied environment-file contents.

## Error Handling

Classify failures into these layers:

1. AWS identity or authorization;
2. RDS, Aurora, or Proxy resource configuration;
3. VPC, DNS, security group, subnet, or port reachability;
4. TLS, IAM, or password/Secrets Manager authentication;
5. JDBC driver, wrapper, or pool behavior;
6. Doma `Config`, dialect, transaction, or DAO behavior.

For a failure, report what was proven, the first failing operation, a redacted error summary, the next safe action, and whether the owner is application code or AWS administration. Do not jump to a later layer or change connection modes without evidence.

Stop without modifying code when the AWS account, region, target resource, engine, runtime, or authentication contract is ambiguous.

## Exclusions

The skill does not:

- provision, modify, fail over, restore, or delete AWS resources;
- change IAM roles, policies, security groups, subnets, route tables, parameter groups, or secrets;
- deploy an application;
- configure Spring Boot, Quarkus, or another framework;
- establish initial Doma annotation processing;
- create schemas or run migrations;
- design entities or business DAOs;
- tune SQL, create indexes, or perform broad production performance analysis;
- cover non-AWS managed databases or other cloud providers.

## Validation Strategy

### Skill Structure

- Parse frontmatter and confirm directory/frontmatter names match.
- Resolve every linked reference and script.
- Run the repository skill validator.
- Verify `npx skills add . --list` discovery.
- Copy-install the skill in a disposable directory and prove it has no dependency on root source bundles or `prisma-skills.md`.

### Script Safety and Behavior

- Run `bash -n` and ShellCheck when available.
- Place a stub `aws` executable first on `PATH` and capture every requested service, operation, region, identifier, and query.
- Provide sanitized AWS CLI response fixtures for all four target database types and representative Proxy, IAM, Secret metadata, access-denied, not-found, and identity-mismatch cases.
- Assert that only allowlisted read commands execute.
- Assert that missing required targeting inputs fail before any resource describe call.
- Seed fixtures with sentinel passwords, tokens, and credential-bearing URLs and assert that none appear in output.
- Scan the script for forbidden mutating operations and `get-secret-value`.

### Compile and Connection Examples

- Compile representative Java Gradle, Java Maven, and Kotlin Gradle Kotlin DSL examples.
- Exercise both PostgreSQL and MySQL Doma dialect construction.
- Compile direct JDBC, RDS Proxy endpoint, IAM-authentication, Secrets Manager delivery, and AWS JDBC Wrapper examples independently where their APIs differ.
- Do not require live AWS credentials for repository validation.
- When an explicitly approved disposable AWS target is available, run only the read-only inspection and `SELECT 1` connection probe; make this optional evidence, not a release prerequisite.

### Behavioral Evaluation

Run fresh-session evaluations for at least:

- Aurora PostgreSQL + Lambda + RDS Proxy + IAM authentication;
- RDS PostgreSQL + ECS + Secrets Manager;
- Aurora MySQL + EC2 + AWS Advanced JDBC Wrapper;
- RDS MySQL + EKS + IAM authentication or Secrets Manager.

Run negative-boundary evaluations for:

- provisioning a new RDS or Aurora database;
- Spring Boot-specific configuration;
- schema migration;
- slow-query diagnosis and index creation.

The skill passes only when it selects the correct connection workflow, preserves the project shape, keeps AWS operations read-only, emits no secret material, and refuses the excluded workflows.

## Evidence Strategy

Doma claims must follow the repository source precedence and target the bundled `3.14.1-SNAPSHOT` research baseline, using released versioned upstream references for examples. Important connection and logging claims should use Doma documentation plus public APIs or integration tests where practical.

AWS claims must be verified against current official AWS documentation during implementation. The initial design research used the following sources on 2026-08-02:

- [Amazon RDS Proxy](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-proxy.html)
- [RDS Proxy connection considerations](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-proxy-connections.html)
- [IAM database authentication with the AWS SDK for Java](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/UsingWithRDS.IAMDBAuth.Connecting.Java.html)
- [AWS Secrets Manager JDBC connections](https://docs.aws.amazon.com/secretsmanager/latest/userguide/retrieving-secrets_jdbc.html)
- [AWS Advanced JDBC Wrapper](https://github.com/aws/aws-advanced-jdbc-wrapper)
- [Using AWS Lambda with Amazon RDS](https://docs.aws.amazon.com/lambda/latest/dg/services-rds.html)

Do not copy mutable command syntax or dependency versions from this design without re-verifying the official source during skill implementation.

## Follow-On Skill

After this skill is implemented, validated, and reviewed, design `doma-diagnose-aws-rds-performance` separately. It will consume the connection and observability baseline conceptually but remain independently installable and self-contained.

Its future scope includes Doma `StatisticManager`, SLF4J SQL-to-DAO correlation, CloudWatch Database Insights, DB load and wait analysis, engine-specific execution plans, slow-query remediation proposals, and before/after verification. It will not be implemented as part of this design.
