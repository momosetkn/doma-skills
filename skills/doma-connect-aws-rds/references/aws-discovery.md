# Read-only AWS discovery

Confirm identity first, then inspect only an explicitly selected existing target. Do not infer the account, region, target kind, identifier, engine, endpoint, IAM setting, Proxy contract, secret, or network configuration from naming conventions.

## Contents

- [Inspection interface](#inspection-interface)
- [Supported engine gate](#supported-engine-gate)
- [Approved operations](#approved-operations)
- [Manual fallback](#manual-fallback)
- [Safe result contract](#safe-result-contract)
- [Official CLI references](#official-cli-references)

## Inspection interface

After the user confirms the expected account, region, target kind, and exact resource id, run the bundled [read-only RDS connection inspector](../scripts/inspect-rds-connection.sh) with this exact interface. Do not execute it while any required targeting fact remains unconfirmed:

```bash
scripts/inspect-rds-connection.sh \
  --expected-account 111122223333 \
  --region ap-northeast-1 \
  --target-kind cluster \
  --target-id app-aurora-pg \
  --profile workloads-dev \
  --secret-id app/database
```

`--expected-account`, `--region`, `--target-kind`, and `--target-id` are mandatory. `--profile` and `--secret-id` are optional. Accept only the documented target kinds for an exact DB instance, DB cluster, or RDS Proxy. Fail before any resource describe call when required targeting input is absent or `sts get-caller-identity` does not match the expected account.

Use a lowercase AWS region made of nonempty alphanumeric segments separated by
single hyphens. Use a 1-63 character instance, cluster, or Proxy identifier that
starts with a letter, contains only letters, digits, and hyphens, and has no
trailing or consecutive hyphen. The inspector validates these inputs before it
calls AWS. It requires Bash and the AWS CLI; it does not require `jq`, Python,
or another JSON parser.

The script emits one JSON record per inspected concern and uses these exit categories:

- `0`: identity matched and every requested inspection completed.
- `64`: an argument is missing, malformed, or unknown; no AWS call is made.
- `65`: the caller account differs from `--expected-account`; only the identity call is made.
- `66`: the selected DB instance, DB cluster, or RDS Proxy is not found after identity confirmation.
- `67`: Proxy target metadata is unsupported, absent, unresolvable, inconsistent, or resolves to an unsupported engine.
- Other nonzero statuses: the AWS CLI or another required local command failed; stop at that failure and do not broaden the inspection.

## Supported engine gate

Proceed only when the resolved RDS `Engine` value is exactly one of:

- `aurora-postgresql`
- `postgres`
- `aurora-mysql`
- `mysql`

Stop before connection-mode selection, dependency guidance, or code changes for every other engine, including MariaDB, Oracle, and SQL Server.

For an RDS Proxy, require its `EngineFamily` to be PostgreSQL or MySQL and
resolve every selected Proxy target through narrowly targeted DB instance or
cluster describes. Resolve `TRACKED_CLUSTER` through its `TrackedClusterId`.
Resolve `RDS_INSTANCE` through its exact `TargetArn`, which
`describe-db-instances` accepts as its identifier. Retain `RdsResourceId` as
reported target metadata, but do not assume it is the immutable `DbiResourceId`;
the service documents it as the target identifier. Treat
`RDS_SERVERLESS_ENDPOINT` and any unknown type as unsupported in this workflow.
Each resolved target must have one of the four allowed `Engine` values above.
Stop if a target cannot be resolved, resolved targets have different `Engine`
values, or any target uses another engine; do not infer support from the Proxy
endpoint, name, or `EngineFamily` alone.

## Approved operations

Allow only the minimum necessary subset of these read-only operations:

- `aws sts get-caller-identity`
- `aws rds describe-db-instances`
- `aws rds describe-db-clusters`
- `aws rds describe-db-proxies`
- `aws rds describe-db-proxy-targets`
- `aws secretsmanager describe-secret`
- narrowly targeted `aws ec2 describe-vpcs`
- narrowly targeted `aws ec2 describe-subnets`
- narrowly targeted `aws ec2 describe-security-groups`

Put the explicit region and narrowest available identifier or filter on every describe call. Inspect only fields needed to decide the connection: engine and version, endpoint and port, immutable resource ID, IAM-authentication setting, Proxy authentication and target metadata, and referenced VPC/subnet/security-group identifiers.

Never invoke resource creation, modification, deletion, attachment, detachment, authorization, revocation, restore, promotion, failover, rotation, deployment, or database-user operations. Never invoke `secretsmanager get-secret-value`. `describe-secret` returns metadata; it is not permission to retrieve, print, parse, or copy the value. Runtime application permissions such as `GetSecretValue` are a separate contract and may be reported without exercising them.

## Manual fallback

Run identity confirmation before RDS inspection:

```bash
aws --profile workloads-dev --region ap-northeast-1 sts get-caller-identity \
  --query '{account:Account,arn:Arn}' --output json --no-cli-pager
```

For an exact Aurora or RDS Multi-AZ cluster:

```bash
aws --profile workloads-dev --region ap-northeast-1 rds describe-db-clusters \
  --db-cluster-identifier app-aurora-pg \
  --query 'DBClusters[0].{identifier:DBClusterIdentifier,resource_id:DbClusterResourceId,engine:Engine,engine_version:EngineVersion,endpoint:Endpoint,reader_endpoint:ReaderEndpoint,port:Port,iam_auth:IAMDatabaseAuthenticationEnabled,subnet_group:DBSubnetGroup,security_group_ids:VpcSecurityGroups[].VpcSecurityGroupId}' \
  --output json --no-cli-pager
```

For an exact DB instance, retain only connection and referenced-network metadata:

```bash
aws --profile workloads-dev --region ap-northeast-1 rds describe-db-instances \
  --db-instance-identifier app-rds-pg \
  --query 'DBInstances[0].{identifier:DBInstanceIdentifier,resource_id:DbiResourceId,engine:Engine,engine_version:EngineVersion,endpoint:Endpoint.Address,port:Endpoint.Port,iam_auth:IAMDatabaseAuthenticationEnabled,vpc_id:DBSubnetGroup.VpcId,security_group_ids:VpcSecurityGroups[].VpcSecurityGroupId}' \
  --output json --no-cli-pager
```

For an exact Proxy, inspect the client endpoint and authentication contract, then its explicitly selected targets:

```bash
aws --profile workloads-dev --region ap-northeast-1 rds describe-db-proxies \
  --db-proxy-name app-proxy \
  --query 'DBProxies[0].{name:DBProxyName,arn:DBProxyArn,endpoint:Endpoint,engine_family:EngineFamily,require_tls:RequireTLS,idle_client_timeout:IdleClientTimeout,default_auth_scheme:DefaultAuthScheme,role_arn:RoleArn,vpc_id:VpcId,subnet_ids:VpcSubnetIds,security_group_ids:VpcSecurityGroupIds,auth:Auth[].{auth_scheme:AuthScheme,username:UserName,client_password_auth_type:ClientPasswordAuthType,iam_auth:IAMAuth,secret_arn:SecretArn}}' \
  --output json --no-cli-pager

aws --profile workloads-dev --region ap-northeast-1 rds describe-db-proxy-targets \
  --db-proxy-name app-proxy \
  --query 'Targets[].{type:Type,resource_id:RdsResourceId,target_arn:TargetArn,tracked_cluster_id:TrackedClusterId,endpoint:Endpoint,port:Port,role:Role,target_health:TargetHealth.State}' \
  --output json --no-cli-pager
```

Then resolve every returned target without enumerating the account. For a
`TRACKED_CLUSTER`, use its exact nonblank `TrackedClusterId`:

```bash
aws --profile workloads-dev --region ap-northeast-1 rds describe-db-clusters \
  --db-cluster-identifier app-aurora-pg \
  --query 'DBClusters[0].{identifier:DBClusterIdentifier,resource_id:DbClusterResourceId,engine:Engine,engine_version:EngineVersion,endpoint:Endpoint,port:Port,iam_auth:IAMDatabaseAuthenticationEnabled}' \
  --output json --no-cli-pager
```

For an `RDS_INSTANCE`, use its exact `TargetArn`:

```bash
aws --profile workloads-dev --region ap-northeast-1 rds describe-db-instances \
  --db-instance-identifier arn:aws:rds:ap-northeast-1:111122223333:db:app-rds-pg \
  --query 'DBInstances[0].{identifier:DBInstanceIdentifier,resource_id:DbiResourceId,engine:Engine,engine_version:EngineVersion,endpoint:Endpoint.Address,port:Endpoint.Port,iam_auth:IAMDatabaseAuthenticationEnabled}' \
  --output json --no-cli-pager
```

Require exactly one resolved resource for each target. Stop nonzero before
reporting Proxy inspection success if a target type is unsupported, a lookup
returns no resource, resolved engines differ, or an engine is outside the
four-engine allowlist.

For Proxy IAM policy analysis, use the `prx-...` resource ID contained in the selected Proxy ARN; do not mistake the full ARN or the friendly Proxy name for that resource ID.

For an optional secret identifier, request metadata only:

```bash
aws --profile workloads-dev --region ap-northeast-1 secretsmanager describe-secret \
  --secret-id app/database \
  --query '{arn:ARN,name:Name,kms_key_id:KmsKeyId,rotation_enabled:RotationEnabled,rotation_rules:RotationRules}' \
  --output json --no-cli-pager
```

Use targeted EC2 describes only after the selected RDS response names the VPC, subnets, or security groups. Do not broaden a failed lookup into account-wide enumeration.

## Safe result contract

Report the confirmed account and region, exact target identifier and kind,
immutable resource ID, engine family/version, endpoint/port,
IAM-authentication flag, Proxy ARN/default authentication/timeout/VPC/auth and
raw plus resolved target metadata when applicable, referenced network IDs, and
non-value secret metadata. Redact error text that could contain credentials.
Never report a password, secret value, IAM token, access key,
credential-bearing URL, environment-file contents, or unrequested account
inventory.

## Official CLI references

- [`sts get-caller-identity`](https://docs.aws.amazon.com/cli/latest/reference/sts/get-caller-identity.html)
- [`rds describe-db-instances`](https://docs.aws.amazon.com/cli/latest/reference/rds/describe-db-instances.html)
- [`rds describe-db-clusters`](https://docs.aws.amazon.com/cli/latest/reference/rds/describe-db-clusters.html)
- [`rds describe-db-proxies`](https://docs.aws.amazon.com/cli/latest/reference/rds/describe-db-proxies.html)
- [`rds describe-db-proxy-targets`](https://docs.aws.amazon.com/cli/latest/reference/rds/describe-db-proxy-targets.html)
- [`secretsmanager describe-secret`](https://docs.aws.amazon.com/cli/latest/reference/secretsmanager/describe-secret.html)
