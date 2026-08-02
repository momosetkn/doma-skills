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
      case "$2" in
        ''|--expected-account|--region|--target-kind|--target-id|--profile|--secret-id)
          printf 'missing value for %s\n' "$option" >&2
          exit 64
          ;;
      esac
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

aws_args=(--region "$region" --no-cli-pager)
[[ -z $profile ]] || aws_args=(--profile "$profile" "${aws_args[@]}")
aws_call() { AWS_PAGER= aws "$@" "${aws_args[@]}"; }

emit_record() {
  local record_type=$1
  local projected_json=$2
  printf '{"record_type":"%s","data":%s}\n' "$record_type" "$projected_json"
}

actual_account=$(aws_call sts get-caller-identity --query Account --output text)
[[ $actual_account == "$expected_account" ]] || {
  printf 'AWS account mismatch: expected %s, got %s\n' "$expected_account" "$actual_account" >&2
  exit 65
}
printf '{"record_type":"identity","account":"%s","region":"%s"}\n' "$actual_account" "$region"

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

if [[ -n $secret_id ]]; then
  secret_json=$(aws_call secretsmanager describe-secret \
    --secret-id "$secret_id" \
    --query '{name:Name,arn:ARN,rotation_enabled:RotationEnabled,kms_key_id:KmsKeyId}' \
    --output json)
  emit_record secret_metadata "$secret_json"
fi
