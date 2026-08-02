# Doma AWS RDS Connection Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an installable `doma-connect-aws-rds` skill that safely inspects and connects an existing plain Java or Kotlin Doma application to an existing Aurora PostgreSQL, RDS PostgreSQL, Aurora MySQL, or RDS MySQL target.

**Architecture:** Keep the ordered project/AWS/connection decision workflow in `SKILL.md`, place connection-mode, AWS-discovery, Doma `DataSource`, runtime, and troubleshooting details in five direct references, and ship one allowlisted read-only AWS CLI inspection script. Test the script with a fake AWS CLI and sanitized fixtures, compile representative Java and Kotlin connection examples, and keep slow-query diagnosis in a separate future skill.

**Tech Stack:** Agent Skills Markdown/YAML, Bash, AWS CLI v2, JDBC, Doma `3.14.1-SNAPSHOT` research baseline, released Doma `3.14.0` example baseline, PostgreSQL JDBC, MySQL Connector/J, HikariCP where the application owns a pool, AWS SDK for Java 2.x, AWS Secrets Manager integrations, AWS Advanced JDBC Wrapper, Gradle, Maven, Kotlin/JVM, `npx skills`.

## Global Constraints

- Target only existing Aurora PostgreSQL, RDS PostgreSQL, Aurora MySQL, and RDS MySQL resources.
- Support plain Java with Gradle or Maven and plain Kotlin/JVM with Gradle Kotlin DSL; preserve compatible project-selected versions and build tools.
- Remain framework-independent; exclude Spring Boot, Quarkus, and framework-owned DI or transaction configuration.
- Confirm the intended AWS account, explicit region, exact target kind, and exact resource identifier before resource inspection.
- Restrict the inspection script to allowlisted read-only `sts`, `rds`, `secretsmanager`, and narrowly targeted `ec2 describe-*` calls.
- Never call `secretsmanager get-secret-value`, print a password or IAM token, or emit a credential-bearing JDBC URL.
- Never create, modify, fail over, restore, authorize, revoke, rotate, attach, detach, or delete an AWS resource.
- Use Java as the primary example and include matching Kotlin guidance when syntax or object lifetime differs.
- Use raw SQL rather than formatted SQL for production-oriented logging examples so bind values are not intentionally expanded into logs.
- Treat Doma `3.14.1-SNAPSHOT` only as the bundled research baseline and use released, versioned artifacts in compile examples.
- Verify mutable AWS command syntax, library APIs, compatibility, and dependency releases against current official sources during implementation.
- Exclude application deployment, schema migration, entity/business-DAO design, broad performance analysis, SQL tuning, and index creation.
- Keep the installed skill self-contained; never require root `doma-project-bundle-*.md` or `prisma-skills.md` files.

---

## File Map

- Create `skills/doma-connect-aws-rds/SKILL.md`: triggers, prerequisites, ordered workflow, verification gates, failure behavior, exclusions, and resource routing.
- Create `skills/doma-connect-aws-rds/agents/openai.yaml`: Codex UI metadata generated through the skill initializer.
- Create `skills/doma-connect-aws-rds/references/connection-modes.md`: direct JDBC, IAM, Secrets Manager, RDS Proxy, and AWS JDBC Wrapper decision matrix.
- Create `skills/doma-connect-aws-rds/references/aws-discovery.md`: exact read-only inspection inputs, commands, redaction rules, and interpretation.
- Create `skills/doma-connect-aws-rds/references/doma-datasource.md`: Java-first and Kotlin companion `DataSource`, Doma `Config`, dialect, dependency, timeout, and logging guidance.
- Create `skills/doma-connect-aws-rds/references/runtime-guidance.md`: EC2, ECS, EKS, and Lambda credential/pool/lifetime guidance.
- Create `skills/doma-connect-aws-rds/references/troubleshooting.md`: six-layer symptom-to-check-to-recovery table.
- Create `skills/doma-connect-aws-rds/scripts/inspect-rds-connection.sh`: argument-validated, allowlisted, read-only AWS metadata inspector emitting JSON records.
- Create `tests/doma-connect-aws-rds/fake-aws`: deterministic AWS CLI test double and call logger.
- Create `tests/doma-connect-aws-rds/inspect-rds-connection-test.sh`: executable shell regression tests.
- Create `tests/doma-connect-aws-rds/fixtures/identity.txt`: expected account response.
- Create `tests/doma-connect-aws-rds/fixtures/aurora-postgresql-cluster.json`: projected Aurora PostgreSQL metadata.
- Create `tests/doma-connect-aws-rds/fixtures/rds-postgresql-instance.json`: projected RDS PostgreSQL metadata.
- Create `tests/doma-connect-aws-rds/fixtures/aurora-mysql-cluster.json`: projected Aurora MySQL metadata.
- Create `tests/doma-connect-aws-rds/fixtures/rds-mysql-instance.json`: projected RDS MySQL metadata.
- Create `tests/doma-connect-aws-rds/fixtures/postgresql-proxy.json`: projected RDS Proxy metadata.
- Create `tests/doma-connect-aws-rds/fixtures/proxy-targets.json`: projected Proxy target metadata.
- Create `tests/doma-connect-aws-rds/fixtures/secret-metadata.json`: projected secret metadata without a secret value.
- Modify `README.md`: catalog triggers, supported targets/modes, safety boundary, installation command, and invocation example.

### Task 1: Establish RED Behavior and Freeze Evidence

**Files:**
- Read: `docs/superpowers/specs/2026-08-02-doma-connect-aws-rds-design.md`
- Read: `skills/doma-setup-project/SKILL.md`
- Read: `skills/doma-setup-kotlin-project/SKILL.md`
- Read narrow ranges from: `doma-project-bundle-1.md`, `doma-project-bundle-2.md`, `doma-project-bundle-3.md`
- Temporary output: fresh `mktemp -d` directories outside the repository
- SDD report output: Task 1 report with a `Source Notes` table and `Version/API Matrix`

**Interfaces:**
- Consumes: the approved design and repository-wide `AGENTS.md` evidence/source-precedence rules.
- Produces: exact RED failures, Doma source pointers, current official AWS compatibility findings, and verified dependency/API names passed in the controller brief to Tasks 2-5.

- [ ] **Step 1: Confirm the repository boundary**

Run:

```bash
git status --short
git diff --cached --name-only
```

Expected: root research inputs may be untracked; no implementation path for `doma-connect-aws-rds` exists or is staged.

- [ ] **Step 2: Run four positive prompts without the new skill**

Use fresh sessions with only each exact prompt and save raw responses outside the repository:

```text
Connect this plain Kotlin Doma Lambda function to an existing Aurora PostgreSQL database through an existing RDS Proxy with IAM authentication. Inspect the AWS target safely and show how to verify the connection.
```

```text
Configure this plain Java Gradle Doma service on ECS to connect to an existing RDS PostgreSQL instance using credentials managed by AWS Secrets Manager. Do not expose the secret.
```

```text
This plain Java Maven Doma service connects directly to Aurora MySQL and reconnects too slowly after failover. Decide whether to use RDS Proxy or the AWS Advanced JDBC Wrapper and show the Doma DataSource wiring.
```

```text
Connect this plain Kotlin Doma service on EKS to an existing RDS MySQL instance using IAM database authentication, then diagnose a failed TLS or authentication probe in order.
```

Expected RED evidence: at least one response guesses the AWS account or region, exposes or requests a secret value, conflates Proxy and wrapper failover behavior, uses the wrong Doma dialect, gives a stale IAM-token/pool pattern, or mixes network/auth/JDBC/Doma diagnostics without an ordered gate.

- [ ] **Step 3: Run negative-boundary prompts without the new skill**

Use fresh sessions and record whether generic guidance expands into unsafe or unrelated work:

```text
Provision a new production Aurora PostgreSQL cluster, security groups, IAM policies, and Secrets Manager secret for this application.
```

```text
Find the slowest SQL in this Doma application, run EXPLAIN ANALYZE, and create the best index in production.
```

```text
Configure Spring Boot transaction management and dependency injection for Doma with RDS.
```

```text
Create and apply the database migration needed by this Doma entity change.
```

The finished connection skill must refuse or route these workflows instead of claiming them.

- [ ] **Step 4: Gather narrow Doma source notes**

Locate headings, then read only through the next heading:

```bash
rg -n '^## docs/config\.md$|^## doma-core/src/main/java/org/seasar/doma/jdbc/(Config|SimpleDataSource|SqlLogType)\.java$' doma-project-bundle-1.md
rg -n '^## doma-core/src/main/java/org/seasar/doma/jdbc/statistic/(DefaultStatisticManager|Statistic|StatisticManager)\.java$' doma-project-bundle-2.md
rg -n '^## doma-slf4j/src/main/java/org/seasar/doma/slf4j/Slf4jJdbcLogger\.java$|^## integration-test-common/src/main/java/org/seasar/doma/it/AppConfig\.java$' doma-project-bundle-3.md
rg -n '^## doma-core/src/main/java/org/seasar/doma/jdbc/dialect/(PostgresDialect|MysqlDialect)\.java$' doma-project-bundle-1.md doma-project-bundle-2.md
```

Record the bundled path, symbol/section, exact claim, and why the evidence supports it. Required claims include `Config#getDataSource`, `Config#getDialect`, PostgreSQL/MySQL dialect selection, local transaction wrapping, raw/formatted SQL log behavior, `Slf4jJdbcLogger`, query timeouts, and `StatisticManager` being disabled by default with unbounded retention in the default implementation.

- [ ] **Step 5: Verify current official AWS behavior**

Use only official AWS documentation and the official AWS JDBC Wrapper repository. Record the accessed URL, access date, exact command/API/plugin name, and compatibility decision for:

```text
https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-proxy.html
https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-proxy-connections.html
https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/rds-proxy-connecting.html
https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/UsingWithRDS.IAMDBAuth.Connecting.Java.html
https://docs.aws.amazon.com/secretsmanager/latest/userguide/retrieving-secrets_jdbc.html
https://docs.aws.amazon.com/lambda/latest/dg/services-rds.html
https://github.com/aws/aws-advanced-jdbc-wrapper
```

Resolve and record:

- RDS Proxy standard and end-to-end IAM flows;
- TLS requirements for IAM authentication;
- client pool maximum lifetime/idle guidance with Proxy;
- direct Aurora/RDS Multi-AZ wrapper failover support;
- wrapper plugins incompatible with Proxy topology ownership;
- AWS SDK for Java 2.x IAM token API names;
- Secrets Manager JDBC/caching library coordinates and rotation behavior;
- current released example versions for PostgreSQL JDBC, MySQL Connector/J, HikariCP, AWS SDK BOM/modules, Secrets Manager integration, and AWS Advanced JDBC Wrapper.

- [ ] **Step 6: Write the Task 1 report**

The report must contain these exact tables:

```markdown
| Prompt | Retrieval failure | Application failure | Boundary failure |
| --- | --- | --- | --- |

| Claim | Doma bundle/public source | AWS official source | Implementation consequence |
| --- | --- | --- | --- |

| Component | Maven coordinate | Verified release | Required class/plugin/API |
| --- | --- | --- | --- |
```

Do not edit repository files or commit Task 1 artifacts. The controller must pass the complete tables to every later task that uses current AWS APIs or dependency versions.

### Task 2: Initialize the Skill and Author the Connection Decision Core

**Files:**
- Create: `skills/doma-connect-aws-rds/SKILL.md`
- Create: `skills/doma-connect-aws-rds/agents/openai.yaml`
- Create: `skills/doma-connect-aws-rds/references/connection-modes.md`
- Create: `skills/doma-connect-aws-rds/references/aws-discovery.md`

**Interfaces:**
- Consumes: Task 1 RED classifications, Doma source notes, and current AWS compatibility/version matrix.
- Produces: public skill identity, ordered workflow, connection-mode decision contract, and manual read-only discovery contract used by Tasks 3-5.

- [ ] **Step 1: Read the authoring contracts completely**

Read:

```text
/home/momose/.codex/skills/.system/skill-creator/SKILL.md
/home/momose/.codex/skills/.system/skill-creator/references/openai_yaml.md
/home/momose/.codex/plugins/cache/openai-curated-remote/superpowers/6.2.0/skills/writing-skills/SKILL.md
/home/momose/.codex/plugins/cache/openai-curated-remote/superpowers/6.2.0/skills/test-driven-development/SKILL.md
```

- [ ] **Step 2: Initialize the skill exactly once**

Run from the repository root:

```bash
python /home/momose/.codex/skills/.system/skill-creator/scripts/init_skill.py \
  doma-connect-aws-rds \
  --path skills \
  --resources references,scripts \
  --interface 'display_name=Connect Doma to AWS RDS' \
  --interface 'short_description=Connect Java and Kotlin Doma apps to RDS and Aurora' \
  --interface 'default_prompt=Use $doma-connect-aws-rds to inspect this existing AWS database connection and configure the Doma DataSource safely.'
```

Expected: the skill directory, `SKILL.md`, `agents/openai.yaml`, empty `references/`, and empty `scripts/` exist. Do not run the initializer again.

- [ ] **Step 3: Replace the template frontmatter and define the boundary**

Use this exact frontmatter:

```yaml
---
name: doma-connect-aws-rds
description: Use when connecting or repairing an existing plain Java or Kotlin Doma application to Amazon RDS or Aurora PostgreSQL/MySQL with direct JDBC, IAM database authentication, Secrets Manager, RDS Proxy, or the AWS Advanced JDBC Wrapper.
---
```

The body must start with a prerequisite that Doma annotation processing already works, then route failed initial setup to the Java/Kotlin setup concern without making either installed skill a required filesystem dependency.

- [ ] **Step 4: Write the ordered workflow in `SKILL.md`**

Use these exact decision stages and stop conditions:

```markdown
1. Inspect the existing project and preserve its build, language, Doma, JDK, Kotlin, pool, and transaction choices.
2. Confirm AWS account, region, target kind, and exact resource id before describing resources.
3. Choose Proxy, direct wrapper, direct IAM, or direct secret-backed JDBC from evidence; never stack topology-owning Proxy and wrapper plugins blindly.
4. Map PostgreSQL targets to `PostgresDialect` and MySQL 8 targets to `MysqlDialect(MysqlDialect.MySqlVersion.V8)`.
5. Build the smallest matching `DataSource` and `Config` without putting credentials in DAO code.
6. Verify compile, DNS/TCP, TLS, authentication, JDBC, then Doma `SELECT 1`; stop at the first failure.
7. Report the selected mode, required runtime IAM actions, changed files, completed gates, and first unresolved gate without secret material.
```

At this task boundary, link only the two references created in this task. Task 3 adds the script link and Task 4 adds the remaining reference map.

- [ ] **Step 5: Author `references/connection-modes.md`**

Include this decision table, expanding each row with Task 1 evidence and current official limitations:

```markdown
| Mode | Prefer when | Avoid or verify |
| --- | --- | --- |
| Direct JDBC + runtime-delivered secret | Long-lived service, existing secret delivery, no Proxy requirement | Rotation behavior, pool credential refresh, TLS |
| Direct JDBC + IAM authentication | Runtime role and DB user are IAM-ready | Per-connection token generation, TLS, pool integration |
| RDS Proxy + secret-backed database auth | Bursty clients or shared connection management | VPC reachability, Proxy pool/client lifetime, pinning |
| RDS Proxy + IAM client auth | Runtime identity should authenticate to Proxy | Standard versus end-to-end IAM, exact `rds-db:connect` resource |
| AWS Advanced JDBC Wrapper direct | Aurora or supported Multi-AZ topology-aware failover/auth plugins are needed | Current engine/plugin compatibility and base driver |
| AWS Wrapper with RDS Proxy | A currently documented authentication-only use case requires it | Do not enable incompatible failover, host monitoring, or read/write splitting |
```

Do not claim that one mode is universally best. Make Lambda/connection bursts a reason to evaluate Proxy, not permission to create it.

- [ ] **Step 6: Author `references/aws-discovery.md`**

Document the future script interface exactly:

```bash
scripts/inspect-rds-connection.sh \
  --expected-account 111122223333 \
  --region ap-northeast-1 \
  --target-kind cluster \
  --target-id app-aurora-pg \
  --profile workloads-dev \
  --secret-id app/database
```

State that `--profile` and `--secret-id` are optional, while account, region, target kind, and target id are mandatory. List the approved operations from the design and explicitly forbid resource mutations and `get-secret-value`.

Provide manual fallback commands with projections that exclude secret values, for example:

```bash
aws --profile workloads-dev --region ap-northeast-1 sts get-caller-identity \
  --query '{account:Account,arn:Arn}' --output json --no-cli-pager

aws --profile workloads-dev --region ap-northeast-1 rds describe-db-clusters \
  --db-cluster-identifier app-aurora-pg \
  --query 'DBClusters[0].{identifier:DBClusterIdentifier,engine:Engine,endpoint:Endpoint,port:Port,iam_auth:IAMDatabaseAuthenticationEnabled,security_group_ids:VpcSecurityGroups[].VpcSecurityGroupId}' \
  --output json --no-cli-pager
```

- [ ] **Step 7: Validate the core skill**

Run:

```bash
python /home/momose/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/doma-connect-aws-rds
! rg -n 'TO[D]O|TB[D]|<skill[-]name>|prisma-skills\.md|doma-project-bundle-[1-4]\.md' skills/doma-connect-aws-rds
git diff --check -- skills/doma-connect-aws-rds
```

Expected: validation passes and the new files contain no template residue or root-input dependency.

- [ ] **Step 8: Commit the decision core**

```bash
git add -- skills/doma-connect-aws-rds/SKILL.md \
  skills/doma-connect-aws-rds/agents/openai.yaml \
  skills/doma-connect-aws-rds/references/connection-modes.md \
  skills/doma-connect-aws-rds/references/aws-discovery.md
git commit -m "feat: add Doma AWS RDS connection workflow"
```

### Task 3: Build the Read-Only AWS Inspector with TDD

**Files:**
- Create: `skills/doma-connect-aws-rds/scripts/inspect-rds-connection.sh`
- Modify: `skills/doma-connect-aws-rds/SKILL.md`
- Modify: `skills/doma-connect-aws-rds/references/aws-discovery.md`
- Create: `tests/doma-connect-aws-rds/fake-aws`
- Create: `tests/doma-connect-aws-rds/inspect-rds-connection-test.sh`
- Create: `tests/doma-connect-aws-rds/fixtures/identity.txt`
- Create: `tests/doma-connect-aws-rds/fixtures/aurora-postgresql-cluster.json`
- Create: `tests/doma-connect-aws-rds/fixtures/rds-postgresql-instance.json`
- Create: `tests/doma-connect-aws-rds/fixtures/aurora-mysql-cluster.json`
- Create: `tests/doma-connect-aws-rds/fixtures/rds-mysql-instance.json`
- Create: `tests/doma-connect-aws-rds/fixtures/postgresql-proxy.json`
- Create: `tests/doma-connect-aws-rds/fixtures/proxy-targets.json`
- Create: `tests/doma-connect-aws-rds/fixtures/secret-metadata.json`

**Interfaces:**
- Consumes: Task 2 script CLI contract and AWS operation allowlist.
- Produces: executable `inspect-rds-connection.sh` accepting `--expected-account`, `--region`, `--target-kind`, `--target-id`, optional `--profile`, and optional `--secret-id`; emits one JSON record per inspected concern and exits nonzero before resource calls on invalid identity/arguments.

- [ ] **Step 1: Write sanitized projected fixtures**

Use fake identifiers only. The four target fixtures must follow this shape with their corresponding engine and port:

```json
{
  "identifier": "app-aurora-pg",
  "engine": "aurora-postgresql",
  "endpoint": "app-aurora-pg.cluster-example.ap-northeast-1.rds.amazonaws.com",
  "port": 5432,
  "iam_auth": true,
  "security_group_ids": ["sg-0123456789abcdef0"]
}
```

Use `postgres`, `mysql`, or `aurora-mysql` as appropriate, port `3306` for MySQL, distinct target ids, and no password/token fields. `identity.txt` contains exactly `111122223333` plus a trailing newline. `secret-metadata.json` contains only `name`, `arn`, `rotation_enabled`, and `kms_key_id` with synthetic values.

- [ ] **Step 2: Write `tests/doma-connect-aws-rds/fake-aws`**

Implement an exact service/operation switch and append shell-escaped arguments to `AWS_CALL_LOG`:

```bash
#!/usr/bin/env bash
set -euo pipefail
: "${AWS_CALL_LOG:?AWS_CALL_LOG is required}"
: "${FIXTURE_DIR:?FIXTURE_DIR is required}"
: "${FAKE_SCENARIO:?FAKE_SCENARIO is required}"
printf '%q ' "$@" >> "$AWS_CALL_LOG"
printf '\n' >> "$AWS_CALL_LOG"

service=${1-}
operation=${2-}
case "$service:$operation:$FAKE_SCENARIO" in
  sts:get-caller-identity:*) file=identity.txt ;;
  rds:describe-db-clusters:aurora-postgresql) file=aurora-postgresql-cluster.json ;;
  rds:describe-db-instances:rds-postgresql) file=rds-postgresql-instance.json ;;
  rds:describe-db-clusters:aurora-mysql) file=aurora-mysql-cluster.json ;;
  rds:describe-db-instances:rds-mysql) file=rds-mysql-instance.json ;;
  rds:describe-db-proxies:postgresql-proxy) file=postgresql-proxy.json ;;
  rds:describe-db-proxy-targets:postgresql-proxy) file=proxy-targets.json ;;
  secretsmanager:describe-secret:*) file=secret-metadata.json ;;
  *) printf 'unexpected operation: %s:%s for %s\n' "$service" "$operation" "$FAKE_SCENARIO" >&2; exit 90 ;;
esac
sed -n '1,$p' "$FIXTURE_DIR/$file"
```

- [ ] **Step 3: Write failing regression tests**

The test runner must create a disposable directory with `mktemp -d`, place the committed fake `aws` first on `PATH`, and include assertions equivalent to:

```bash
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)
fixture_dir="$repo_root/tests/doma-connect-aws-rds/fixtures"
inspector=${INSPECTOR_PATH:-"$repo_root/skills/doma-connect-aws-rds/scripts/inspect-rds-connection.sh"}
fake_bin=$(mktemp -d)
ln -s "$repo_root/tests/doma-connect-aws-rds/fake-aws" "$fake_bin/aws"
call_log="$fake_bin/aws-calls.log"

run_inspector() {
  PATH="$fake_bin:$PATH" \
  AWS_CALL_LOG="$call_log" \
  FIXTURE_DIR="$fixture_dir" \
  FAKE_SCENARIO="$1" \
  "$inspector" "${@:2}"
}

assert_contains() { rg -F -- "$2" "$1" >/dev/null; }
assert_not_contains() { ! rg -F -- "$2" "$1" >/dev/null; }
```

Cover:

- missing `--expected-account` fails before any AWS call;
- account mismatch calls only STS and never calls RDS;
- each of the four target kinds/scenarios emits the expected engine and port;
- Proxy emits Proxy and target records;
- optional secret inspection calls only `describe-secret` and emits no secret value;
- every AWS call contains the explicit region and optional profile when supplied;
- call logs contain none of `create`, `modify`, `delete`, `failover`, `restore`, `authorize`, `revoke`, `rotate`, or `get-secret-value` operations.

- [ ] **Step 4: Run tests to verify RED**

Run:

```bash
chmod +x tests/doma-connect-aws-rds/fake-aws \
  tests/doma-connect-aws-rds/inspect-rds-connection-test.sh
bash tests/doma-connect-aws-rds/inspect-rds-connection-test.sh
```

Expected: FAIL because `skills/doma-connect-aws-rds/scripts/inspect-rds-connection.sh` does not exist.

- [ ] **Step 5: Implement strict argument parsing**

Start the inspector with:

```bash
#!/usr/bin/env bash
set -euo pipefail

expected_account=
region=
target_kind=
target_id=
profile=
secret_id=

while (($#)); do
  case "$1" in
    --expected-account|--region|--target-kind|--target-id|--profile|--secret-id)
      option=$1
      (($# >= 2)) || { printf 'missing value for %s\n' "$option" >&2; exit 64; }
      value=$2
      case "$option" in
        --expected-account) expected_account=$value ;;
        --region) region=$value ;;
        --target-kind) target_kind=$value ;;
        --target-id) target_id=$value ;;
        --profile) profile=$value ;;
        --secret-id) secret_id=$value ;;
      esac
      shift 2
      ;;
    *) printf 'unknown argument: %s\n' "$1" >&2; exit 64 ;;
  esac
done

[[ $expected_account =~ ^[0-9]{12}$ ]] || { printf 'expected account must be 12 digits\n' >&2; exit 64; }
[[ $region =~ ^[a-z0-9-]+$ ]] || { printf 'region is required and may contain lowercase letters, digits, and hyphens\n' >&2; exit 64; }
[[ $target_id =~ ^[A-Za-z0-9-]+$ ]] || { printf 'target id is required and may contain letters, digits, and hyphens\n' >&2; exit 64; }
case "$target_kind" in instance|cluster|proxy) ;; *) printf 'target kind must be instance, cluster, or proxy\n' >&2; exit 64 ;; esac
```

Build AWS arguments as arrays, set `AWS_PAGER` to an empty value for each call, and quote every user-supplied value.

- [ ] **Step 6: Implement identity and target inspection**

Use one identity call before all resource calls:

```bash
aws_args=(--region "$region" --no-cli-pager)
[[ -z $profile ]] || aws_args=(--profile "$profile" "${aws_args[@]}")
aws_call() { AWS_PAGER= aws "$@" "${aws_args[@]}"; }
actual_account=$(aws_call sts get-caller-identity --query Account --output text)
[[ $actual_account == "$expected_account" ]] || {
  printf 'AWS account mismatch: expected %s, got %s\n' "$expected_account" "$actual_account" >&2
  exit 65
}
printf '{"record_type":"identity","account":"%s","region":"%s"}\n' "$actual_account" "$region"
```

For `instance`, `cluster`, and `proxy`, call only the matching describe operations with the exact identifier and a JMESPath projection that omits credential material. Treat empty or `null` JSON as not found and exit nonzero. Wrap each projected object with this helper without logging raw AWS responses:

```bash
emit_record() {
  local record_type=$1
  local projected_json=$2
  printf '{"record_type":"%s","data":%s}\n' "$record_type" "$projected_json"
}
```

Use this exact target switch and projections:

```bash
case "$target_kind" in
  instance)
    target_json=$(aws_call rds describe-db-instances \
      --db-instance-identifier "$target_id" \
      --query 'DBInstances[0].{identifier:DBInstanceIdentifier,engine:Engine,endpoint:Endpoint.Address,port:Endpoint.Port,iam_auth:IAMDatabaseAuthenticationEnabled,security_group_ids:VpcSecurityGroups[].VpcSecurityGroupId}' \
      --output json)
    [[ $target_json != null && -n $target_json ]] || { printf 'DB instance not found\n' >&2; exit 66; }
    emit_record db_instance "$target_json"
    ;;
  cluster)
    target_json=$(aws_call rds describe-db-clusters \
      --db-cluster-identifier "$target_id" \
      --query 'DBClusters[0].{identifier:DBClusterIdentifier,engine:Engine,endpoint:Endpoint,reader_endpoint:ReaderEndpoint,port:Port,iam_auth:IAMDatabaseAuthenticationEnabled,security_group_ids:VpcSecurityGroups[].VpcSecurityGroupId}' \
      --output json)
    [[ $target_json != null && -n $target_json ]] || { printf 'DB cluster not found\n' >&2; exit 66; }
    emit_record db_cluster "$target_json"
    ;;
  proxy)
    proxy_json=$(aws_call rds describe-db-proxies \
      --db-proxy-name "$target_id" \
      --query 'DBProxies[0].{name:DBProxyName,engine_family:EngineFamily,endpoint:Endpoint,require_tls:RequireTLS,role_arn:RoleArn,security_group_ids:VpcSecurityGroupIds,auth:Auth[].{auth_scheme:AuthScheme,iam_auth:IAMAuth,secret_arn:SecretArn}}' \
      --output json)
    [[ $proxy_json != null && -n $proxy_json ]] || { printf 'RDS Proxy not found\n' >&2; exit 66; }
    target_json=$(aws_call rds describe-db-proxy-targets \
      --db-proxy-name "$target_id" \
      --query 'Targets[].{endpoint:Endpoint,port:Port,type:Type,target_arn:TargetArn,rds_resource_id:RdsResourceId,target_health:TargetHealth.State}' \
      --output json)
    emit_record db_proxy "$proxy_json"
    emit_record db_proxy_targets "$target_json"
    ;;
esac
```

- [ ] **Step 7: Implement optional secret metadata inspection**

Use only:

```bash
aws_call secretsmanager describe-secret \
  --secret-id "$secret_id" \
  --query '{name:Name,arn:ARN,rotation_enabled:RotationEnabled,kms_key_id:KmsKeyId}' \
  --output json
```

Never call secret-value retrieval. Emit the projected metadata as a separate `secret_metadata` record.

- [ ] **Step 8: Run GREEN script verification**

Run:

```bash
chmod +x skills/doma-connect-aws-rds/scripts/inspect-rds-connection.sh
bash -n skills/doma-connect-aws-rds/scripts/inspect-rds-connection.sh
bash -n tests/doma-connect-aws-rds/fake-aws
bash -n tests/doma-connect-aws-rds/inspect-rds-connection-test.sh
bash tests/doma-connect-aws-rds/inspect-rds-connection-test.sh
if command -v shellcheck >/dev/null; then
  shellcheck skills/doma-connect-aws-rds/scripts/inspect-rds-connection.sh \
    tests/doma-connect-aws-rds/fake-aws \
    tests/doma-connect-aws-rds/inspect-rds-connection-test.sh
fi
```

Expected: all tests pass; ShellCheck passes when installed.

- [ ] **Step 9: Route the script from the skill**

Add a direct link from `SKILL.md` and `aws-discovery.md`, say when to run it, document each exit category, and include the exact example command from Task 2. Do not make the agent execute it until identity, region, kind, and resource id are confirmed.

- [ ] **Step 10: Commit the inspector and tests**

```bash
git add -- skills/doma-connect-aws-rds/SKILL.md \
  skills/doma-connect-aws-rds/references/aws-discovery.md \
  skills/doma-connect-aws-rds/scripts/inspect-rds-connection.sh \
  tests/doma-connect-aws-rds
git commit -m "feat: add safe AWS RDS connection inspector"
```

### Task 4: Author Doma DataSource, Runtime, and Troubleshooting Guidance

**Files:**
- Modify: `skills/doma-connect-aws-rds/SKILL.md`
- Create: `skills/doma-connect-aws-rds/references/doma-datasource.md`
- Create: `skills/doma-connect-aws-rds/references/runtime-guidance.md`
- Create: `skills/doma-connect-aws-rds/references/troubleshooting.md`
- Temporary compile fixtures: fresh directories from `mktemp -d`, outside the repository

**Interfaces:**
- Consumes: Task 1 verified dependency/API matrix, Task 2 connection-mode contract, and Task 3 inspector output fields.
- Produces: complete self-contained skill guidance for Java/Kotlin, PostgreSQL/MySQL, EC2/ECS/EKS/Lambda, verification, observability baseline, and six-layer recovery.

- [ ] **Step 1: Add the complete reference map to `SKILL.md`**

Use this routing table:

```markdown
| Need | Read or run |
| --- | --- |
| Choose direct, IAM, secret, Proxy, or wrapper mode | [Connection Modes](references/connection-modes.md) |
| Confirm the exact AWS target without secret retrieval | [AWS Discovery](references/aws-discovery.md) and `scripts/inspect-rds-connection.sh` |
| Add JDBC dependencies, `DataSource`, Doma `Config`, dialect, and probe | [Doma DataSource](references/doma-datasource.md) |
| Adjust credential and pool lifetime for EC2, ECS, EKS, or Lambda | [Runtime Guidance](references/runtime-guidance.md) |
| Recover from the first failed verification layer | [Troubleshooting](references/troubleshooting.md) |
```

- [ ] **Step 2: Author the Doma configuration core**

Use this Java contract as the primary framework-independent shape:

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

Explain when an application-managed pool can be returned directly and when Doma local transactions require wrapping the original source in `LocalTransactionDataSource`. Do not invent a framework transaction manager.

- [ ] **Step 3: Author engine and dependency recipes**

For Java Gradle, Java Maven, and Kotlin Gradle Kotlin DSL, give exact coordinates from Task 1 for only the selected mode. Keep these engine invariants explicit:

```java
Dialect postgres = new PostgresDialect();
Dialect mysql8 = new MysqlDialect(MysqlDialect.MySqlVersion.V8);
```

Do not present the source snapshot as a dependency version. State that existing compatible driver, AWS SDK BOM, and pool versions win over illustrative versions.

For each mode, show where connection host, port, database name, user/secret id, region, and TLS settings enter the `DataSource` or wrapper. Never include a password or literal IAM token. IAM examples must generate or refresh authentication at connection acquisition according to the verified official API/plugin instead of storing one generated token as a long-lived pool password.

- [ ] **Step 4: Add the read-only Doma probe**

Use this Java probe:

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

Use this matching top-level Kotlin interface:

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

Explain that compilation proves DAO generation, while invoking `selectOne()` proves the live connection and requires the explicitly approved target/auth context. Do not add a write statement or schema dependency.

- [ ] **Step 5: Author `references/runtime-guidance.md`**

Include this runtime decision table and expand it with Task 1 official evidence:

```markdown
| Runtime | Credential source | Pool/lifetime focus | Proxy decision |
| --- | --- | --- | --- |
| EC2 | Instance profile/default chain | Bound pool and refresh auth before expiry | Evaluate for shared scale/failover needs |
| ECS | Task role/default chain | Size per task count; avoid embedding node credentials | Evaluate for burst or aggregate connection pressure |
| EKS | Pod Identity or IRSA/default chain | Confirm pod identity rather than node role | Evaluate from aggregate pod concurrency |
| Lambda | Execution role/default chain | Reuse initialized clients; bound connections across concurrency | Prefer evaluation for frequent short connections or bursts |
```

State current RDS Proxy client maximum-lifetime and idle-time relationships exactly as verified in Task 1. Do not claim that Proxy removes all need for application-side pool decisions.

- [ ] **Step 6: Author the six-layer troubleshooting table**

Cover at least:

```markdown
| Layer | Representative symptom | Inspect | Recover |
| --- | --- | --- | --- |
| AWS identity/authorization | AccessDenied or wrong account | STS identity and exact denied action/resource | Select the intended profile/role or request the narrow permission |
| RDS/Aurora/Proxy | Target not found or wrong engine | Exact region/id, engine, Proxy target/auth | Correct targeting; do not create or mutate resources |
| Network | Unknown host, connect timeout, refused port | Endpoint, DNS, VPC path, SG relationship, port | Escalate exact network gap; never disable TLS |
| TLS/auth | Certificate, password, PAM/IAM failure | Hostname, CA/trust, IAM-enabled DB user, token region/host/user | Fix the failing contract and retry only that gate |
| JDBC/pool/wrapper | No suitable driver, stale credentials, reconnect loop | Driver/wrapper/plugin versions and pool lifetime | Align verified dependencies and per-connection auth refresh |
| Doma | Wrong dialect, `Config`, transaction, or DAO result | `getDataSource`, `getDialect`, generated DAO, first Doma error | Correct the Doma boundary after JDBC succeeds |
```

End with the required report shape: proven gates, first failure, redacted evidence, next safe action, and application-versus-AWS owner.

- [ ] **Step 7: Add the observability baseline without performance scope creep**

Document raw SQL logging, a finite query timeout, and optional `StatisticManager`. State that the default statistic implementation retains entries while enabled and must be cleared periodically or replaced with a bounded implementation. Explicitly route DB log export, Database Insights, `EXPLAIN`, SQL rewrites, and indexes to the future performance skill.

- [ ] **Step 8: Compile representative examples from the finished reference**

Create disposable fixtures from the exact published dependency and code snippets using `apply_patch`. Cover:

```text
Java Gradle: PostgreSQL + HikariCP + PostgresDialect + Doma probe
Java Maven: MySQL 8 + HikariCP + MysqlDialect + Doma probe
Kotlin Gradle Kotlin DSL: PostgreSQL IAM or Proxy recipe + Kotlin Config/probe
Java Gradle: AWS Advanced JDBC Wrapper direct Aurora MySQL recipe
```

Use released Doma `3.14.0`, JDK 17 or later, the verified Task 1 dependency versions, and no live database connection. Run `clean compileJava` or `clean compileKotlin` and verify generated probe DAO implementations where annotation processing is included. If a current AWS API differs from the planned snippet, fix the reference and recompile rather than weakening the claim.

- [ ] **Step 9: Validate and commit the completed content**

Run:

```bash
python /home/momose/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/doma-connect-aws-rds
! rg -n 'TO[D]O|TB[D]|<skill[-]name>|3\.14\.1-SNAPSHOT.*(implementation|annotationProcessor|kapt)' \
  skills/doma-connect-aws-rds
! rg -n 'AKIA[0-9A-Z]{16}|aws_secret_access_key[[:space:]]*=|password[[:space:]]*=[[:space:]]*"[A-Za-z0-9]' \
  skills/doma-connect-aws-rds
git diff --check -- skills/doma-connect-aws-rds
```

Then commit:

```bash
git add -- skills/doma-connect-aws-rds/SKILL.md \
  skills/doma-connect-aws-rds/references/doma-datasource.md \
  skills/doma-connect-aws-rds/references/runtime-guidance.md \
  skills/doma-connect-aws-rds/references/troubleshooting.md
git commit -m "docs: add Doma AWS RDS connection recipes"
```

### Task 5: Prove GREEN Behavior and Publish Discovery

**Files:**
- Modify: `README.md`
- Modify only when evaluations reveal a concrete gap: `skills/doma-connect-aws-rds/SKILL.md`
- Modify only when evaluations reveal a concrete gap: `skills/doma-connect-aws-rds/references/*.md`
- Modify only when script tests reveal a concrete gap: `skills/doma-connect-aws-rds/scripts/inspect-rds-connection.sh`
- Modify only when script tests reveal a concrete gap: `tests/doma-connect-aws-rds/**`
- Temporary evaluation output: fresh `mktemp -d` outside the repository

**Interfaces:**
- Consumes: the complete skill, passing script tests, compiled snippets, and Task 1 RED prompts.
- Produces: README catalog/discovery and fresh-session evidence that the skill corrects observed failures without claiming excluded workflows.

- [ ] **Step 1: Run the four positive prompts with the installed skill path**

Use the exact Task 1 prompts in fresh sessions. Each response must:

- confirm account, region, kind, and id before AWS describes;
- use only read-only metadata inspection and never request/print a secret value;
- select the correct PostgreSQL/MySQL Doma dialect;
- distinguish Proxy topology ownership from direct wrapper failover;
- place IAM-token/secret rotation outside DAO code and avoid a stale long-lived pool password;
- verify compile, network, TLS, auth, JDBC, then Doma in order;
- report the first unresolved gate and stay inside the connection boundary.

Save raw outputs only outside the repository.

- [ ] **Step 2: Run all negative-boundary prompts with the skill catalog available**

Use the exact Task 1 negative prompts. Expected:

- provisioning is refused or routed to dedicated infrastructure work;
- slow-query/index work is routed to the future performance concern without pretending that skill exists in the current catalog;
- Spring Boot framework wiring is excluded;
- migration work is excluded.

- [ ] **Step 3: Refactor only observed gaps**

Classify each failure as retrieval, application, or boundary failure. Patch the smallest responsible section or script behavior, rerun the affected prompt/test, and preserve the approved scope. Do not add generic discipline prose unrelated to an observed failure.

- [ ] **Step 4: Add the README catalog entry**

Add `doma-connect-aws-rds` under `Available Skills` with:

- triggers for existing plain Java/Kotlin Doma applications connecting to the four supported AWS database targets;
- Direct JDBC, IAM, Secrets Manager, RDS Proxy, wrapper, dialect, DataSource, layered verification, and safe discovery scope;
- explicit read-only/no-secret/no-provisioning boundary;
- exclusions for frameworks, deployment, migrations, entities/business DAOs, and slow-query tuning;
- exact install command:

```bash
npx skills add momosetkn/doma-skills --skill doma-connect-aws-rds
```

- exact invocation example:

```text
Use $doma-connect-aws-rds to inspect the existing Aurora PostgreSQL target in ap-northeast-1 and connect this Kotlin Doma Lambda through its existing RDS Proxy with IAM authentication.
```

Preserve the existing Java/Kotlin setup entries and Doma baseline statement.

- [ ] **Step 5: Run local discovery and copied-install checks**

Run:

```bash
python /home/momose/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/doma-connect-aws-rds
npx skills add . --list
repo_root=$(pwd -P)
copy_root=$(mktemp -d)
(cd "$copy_root" && npx skills add "$repo_root" --skill doma-connect-aws-rds --agent codex --copy -y)
installed_skill=$(find "$copy_root" -path '*/doma-connect-aws-rds/SKILL.md' -print -quit)
test -n "$installed_skill"
installed_dir=$(dirname "$installed_skill")
test -x "$installed_dir/scripts/inspect-rds-connection.sh"
! rg -n 'prisma-skills\.md|doma-project-bundle-[1-4]\.md' "$installed_dir"
```

Expected: three public skills are listed; the copied inspector remains executable and every direct resource resolves.

- [ ] **Step 6: Re-run the script test suite from the installed copy**

Point the committed test harness at the copied inspector through its `INSPECTOR_PATH` override and run all fixtures.

Run:

```bash
INSPECTOR_PATH="$installed_dir/scripts/inspect-rds-connection.sh" \
  bash tests/doma-connect-aws-rds/inspect-rds-connection-test.sh
```

Expected: all safety and output tests pass against the copied artifact.

- [ ] **Step 7: Run final content checks**

Run:

```bash
! rg -n 'TO[D]O|TB[D]|<skill[-]name>|prisma-skills\.md|doma-project-bundle-[1-4]\.md' \
  README.md skills/doma-connect-aws-rds
! rg -n 'get-secret-value|create-db-|modify-db-|delete-db-|failover-db-|authorize-security-group|revoke-security-group' \
  skills/doma-connect-aws-rds/scripts/inspect-rds-connection.sh
git diff --check -- README.md skills/doma-connect-aws-rds tests/doma-connect-aws-rds
```

Trace every exact AWS command, API/plugin name, lifetime value, dependency version, and compatibility claim to Task 1 notes and current official sources.

- [ ] **Step 8: Commit the public catalog and evaluation fixes**

Stage only changed deliverable/test paths:

```bash
git add -- README.md skills/doma-connect-aws-rds tests/doma-connect-aws-rds
git commit -m "docs: publish Doma AWS RDS connection skill"
```

### Task 6: Final Review and Release-Readiness Verification

**Files:**
- Read: `docs/superpowers/specs/2026-08-02-doma-connect-aws-rds-design.md`
- Read: `README.md`
- Read: `skills/doma-connect-aws-rds/**`
- Read: `tests/doma-connect-aws-rds/**`
- Modify only to address confirmed review or verification findings.

**Interfaces:**
- Consumes: all implementation commits and validation evidence from Tasks 1-5.
- Produces: a reviewed, self-contained branch ready for the user's chosen integration path; no automatic push, PR, merge, AWS mutation, or production connection.

- [ ] **Step 1: Run the complete local verification set fresh**

Run:

```bash
bash -n skills/doma-connect-aws-rds/scripts/inspect-rds-connection.sh
bash -n tests/doma-connect-aws-rds/fake-aws
bash -n tests/doma-connect-aws-rds/inspect-rds-connection-test.sh
bash tests/doma-connect-aws-rds/inspect-rds-connection-test.sh
python /home/momose/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/doma-connect-aws-rds
npx skills add . --list
base_ref=$(git merge-base HEAD main)
git diff --check "$base_ref"..HEAD
```

Also recreate and rerun the four Task 4 compile fixtures from the published snippets. Do not reuse only old build output.

- [ ] **Step 2: Verify safety invariants manually and mechanically**

Confirm:

- no secret-value API or mutating AWS command appears in the inspector;
- account mismatch stops before resource describes;
- every resource describe is region- and identifier-scoped;
- output contains no password, access key, session token, IAM DB token, or credential-bearing URL;
- Proxy and wrapper compatibility guidance matches current official sources;
- IAM authentication is refreshed at connection acquisition rather than treated as a static long-lived pool password;
- JDBC success is required before changing Doma `Config` or DAO behavior;
- slow-query analysis stays excluded.

- [ ] **Step 3: Request code review**

Use `superpowers:requesting-code-review` with the design, plan, commit range, script tests, compile evidence, behavior-evaluation paths, and copied-install evidence. Resolve every confirmed Critical or Important finding through the smallest change and rerun the affected verification.

- [ ] **Step 4: Prove repository boundaries**

Run:

```bash
git status --short
git diff --name-only "$(git merge-base HEAD main)"..HEAD
```

Expected changed paths are limited to the design/plan history already committed, `README.md`, `skills/doma-connect-aws-rds/`, and `tests/doma-connect-aws-rds/`. Root research bundles, `prisma-skills.md`, installed copies, evaluation outputs, connection logs, and secrets are absent from commits.

- [ ] **Step 5: Hand off integration choice**

Use `superpowers:finishing-a-development-branch`. Present the allowed local merge, push/PR, or keep-branch choices for the detected environment. Do not push, merge, delete the branch, or remove a worktree without the user's selected option and the finishing skill's required confirmation.
