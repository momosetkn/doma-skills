# Read-only AWS discovery

Confirm identity first, then inspect only an explicitly selected existing target. Do not infer the account, region, target kind, identifier, engine, endpoint, IAM setting, Proxy contract, secret, or network configuration from naming conventions.

## Contents

- [Inspection interface](#inspection-interface)
- [Approved operations](#approved-operations)
- [Manual fallback](#manual-fallback)
- [Safe result contract](#safe-result-contract)
- [Official CLI references](#official-cli-references)

## Inspection interface

Use this exact interface when the bundled inspection script is available:

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
  --query 'DBClusters[0].{identifier:DBClusterIdentifier,resource_id:DbClusterResourceId,engine:Engine,endpoint:Endpoint,port:Port,iam_auth:IAMDatabaseAuthenticationEnabled,security_group_ids:VpcSecurityGroups[].VpcSecurityGroupId}' \
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
  --query 'DBProxies[0].{name:DBProxyName,arn:DBProxyArn,endpoint:Endpoint,engine_family:EngineFamily,require_tls:RequireTLS,idle_client_timeout:IdleClientTimeout,default_auth_scheme:DefaultAuthScheme,auth:Auth[].{iam_auth:IAMAuth,secret_arn:SecretArn}}' \
  --output json --no-cli-pager

aws --profile workloads-dev --region ap-northeast-1 rds describe-db-proxy-targets \
  --db-proxy-name app-proxy \
  --query 'Targets[].{type:Type,resource_id:RdsResourceId,endpoint:Endpoint,port:Port,target_health:TargetHealth.State}' \
  --output json --no-cli-pager
```

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

Report the confirmed account and region, exact target identifier and kind, engine family/version, endpoint/port, IAM-authentication flag, Proxy auth/target metadata when applicable, referenced network IDs, and non-value secret metadata. Redact error text that could contain credentials. Never report a password, secret value, IAM token, access key, credential-bearing URL, environment-file contents, or unrequested account inventory.

## Official CLI references

- [`sts get-caller-identity`](https://docs.aws.amazon.com/cli/latest/reference/sts/get-caller-identity.html)
- [`rds describe-db-instances`](https://docs.aws.amazon.com/cli/latest/reference/rds/describe-db-instances.html)
- [`rds describe-db-clusters`](https://docs.aws.amazon.com/cli/latest/reference/rds/describe-db-clusters.html)
- [`rds describe-db-proxies`](https://docs.aws.amazon.com/cli/latest/reference/rds/describe-db-proxies.html)
- [`rds describe-db-proxy-targets`](https://docs.aws.amazon.com/cli/latest/reference/rds/describe-db-proxy-targets.html)
- [`secretsmanager describe-secret`](https://docs.aws.amazon.com/cli/latest/reference/secretsmanager/describe-secret.html)
