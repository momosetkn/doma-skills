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
        ''|--*)
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

valid_rds_identifier() {
  local identifier=$1
  ((${#identifier} >= 1 && ${#identifier} <= 63)) || return 1
  [[ $identifier =~ ^[A-Za-z][A-Za-z0-9-]*$ ]] || return 1
  [[ $identifier != *--* && $identifier != *- ]]
}

json_quote() {
  local value=$1
  value=${value//\\/\\\\}
  value=${value//\"/\\\"}
  value=${value//$'\n'/\\n}
  value=${value//$'\r'/\\r}
  value=${value//$'\t'/\\t}
  printf '"%s"' "$value"
}

json_nullable_string() {
  if [[ $1 == - ]]; then
    printf 'null'
  else
    json_quote "$1"
  fi
}

normalize_boolean() {
  case "$1" in
    True|true) printf 'true' ;;
    False|false) printf 'false' ;;
    *) return 1 ;;
  esac
}

is_supported_engine() {
  case "$1" in
    aurora-postgresql|postgres|aurora-mysql|mysql) return 0 ;;
    *) return 1 ;;
  esac
}

fail_proxy() {
  printf '%s\n' "$1" >&2
  exit 67
}

[[ $expected_account =~ ^[0-9]{12}$ ]] || { printf 'expected account must be 12 digits\n' >&2; exit 64; }
[[ $region =~ ^[a-z0-9]+(-[a-z0-9]+)+$ ]] || {
  printf 'region must contain lowercase alphanumeric segments separated by single hyphens\n' >&2
  exit 64
}
case "$target_kind" in
  instance|cluster|proxy) ;;
  *) printf 'target kind must be instance, cluster, or proxy\n' >&2; exit 64 ;;
esac
valid_rds_identifier "$target_id" || {
  printf '%s identifier must be 1-63 letters, digits, or hyphens; start with a letter; and contain no trailing or consecutive hyphen\n' "$target_kind" >&2
  exit 64
}

aws_args=(--region "$region" --no-cli-pager)
[[ -z $profile ]] || aws_args=(--profile "$profile" "${aws_args[@]}")
aws_call() { AWS_PAGER= aws "$@" "${aws_args[@]}"; }

emit_record() {
  local record_type=$1
  local projected_json=$2
  projected_json=${projected_json//$'\n'/}
  projected_json=${projected_json//$'\r'/}
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
      --query 'DBInstances[0].{identifier:DBInstanceIdentifier,resource_id:DbiResourceId,engine:Engine,engine_version:EngineVersion,endpoint:Endpoint.Address,port:Endpoint.Port,iam_auth:IAMDatabaseAuthenticationEnabled,vpc_id:DBSubnetGroup.VpcId,security_group_ids:VpcSecurityGroups[].VpcSecurityGroupId}' \
      --output json)
    [[ $target_json != null && -n $target_json ]] || { printf 'DB instance not found\n' >&2; exit 66; }
    emit_record db_instance "$target_json"
    ;;
  cluster)
    target_json=$(aws_call rds describe-db-clusters \
      --db-cluster-identifier "$target_id" \
      --query 'DBClusters[0].{identifier:DBClusterIdentifier,resource_id:DbClusterResourceId,engine:Engine,engine_version:EngineVersion,endpoint:Endpoint,reader_endpoint:ReaderEndpoint,port:Port,iam_auth:IAMDatabaseAuthenticationEnabled,subnet_group:DBSubnetGroup,security_group_ids:VpcSecurityGroups[].VpcSecurityGroupId}' \
      --output json)
    [[ $target_json != null && -n $target_json ]] || { printf 'DB cluster not found\n' >&2; exit 66; }
    emit_record db_cluster "$target_json"
    ;;
  proxy)
    proxy_json=$(aws_call rds describe-db-proxies \
      --db-proxy-name "$target_id" \
      --query 'DBProxies[0].{name:DBProxyName,arn:DBProxyArn,engine_family:EngineFamily,endpoint:Endpoint,require_tls:RequireTLS,idle_client_timeout:IdleClientTimeout,default_auth_scheme:DefaultAuthScheme,role_arn:RoleArn,vpc_id:VpcId,subnet_ids:VpcSubnetIds,security_group_ids:VpcSecurityGroupIds,auth:Auth[].{auth_scheme:AuthScheme,username:UserName,client_password_auth_type:ClientPasswordAuthType,iam_auth:IAMAuth,secret_arn:SecretArn}}' \
      --output json)
    [[ $proxy_json != null && -n $proxy_json ]] || { printf 'RDS Proxy not found\n' >&2; exit 66; }

    target_rows=$(aws_call rds describe-db-proxy-targets \
      --db-proxy-name "$target_id" \
      --query 'Targets[].[Type,RdsResourceId,not_null(TargetArn, `-`),not_null(TrackedClusterId, `-`),Endpoint,Port,not_null(Role, `UNKNOWN`),TargetHealth.State]' \
      --output text)
    [[ -n $target_rows && $target_rows != None ]] || fail_proxy 'RDS Proxy has no resolvable targets'

    target_items=
    resolved_items=
    first_engine=
    while IFS=$'\t' read -r target_type target_resource_id target_arn tracked_cluster_id target_endpoint target_port target_role target_health; do
      [[ -n $target_type && -n $target_resource_id && -n $target_endpoint && $target_port =~ ^[0-9]+$ ]] || \
        fail_proxy 'RDS Proxy returned malformed target metadata'

      case "$target_type" in
        TRACKED_CLUSTER)
          [[ $tracked_cluster_id != - ]] || fail_proxy 'RDS Proxy tracked-cluster target omitted TrackedClusterId'
          resolution_row=$(aws_call rds describe-db-clusters \
            --db-cluster-identifier "$tracked_cluster_id" \
            --query 'DBClusters[0].[DBClusterIdentifier,DbClusterResourceId,Engine,EngineVersion,Endpoint,Port,IAMDatabaseAuthenticationEnabled]' \
            --output text)
          resolved_kind=cluster
          ;;
        RDS_INSTANCE)
          [[ $target_arn != - ]] || fail_proxy 'RDS Proxy instance target omitted TargetArn'
          resolution_row=$(aws_call rds describe-db-instances \
            --db-instance-identifier "$target_arn" \
            --query 'DBInstances[0].[DBInstanceIdentifier,DbiResourceId,Engine,EngineVersion,Endpoint.Address,Endpoint.Port,IAMDatabaseAuthenticationEnabled]' \
            --output text)
          resolved_kind=instance
          ;;
        *) fail_proxy "unsupported RDS Proxy target type: $target_type" ;;
      esac

      [[ -n $resolution_row && $resolution_row != None ]] || \
        fail_proxy "RDS Proxy target could not be resolved: $target_type $target_resource_id"
      IFS=$'\t' read -r resolved_identifier resolved_resource_id resolved_engine resolved_engine_version resolved_endpoint resolved_port resolved_iam_auth <<< "$resolution_row"
      [[ -n $resolved_identifier && -n $resolved_resource_id && -n $resolved_engine && -n $resolved_engine_version && -n $resolved_endpoint && $resolved_port =~ ^[0-9]+$ ]] || \
        fail_proxy "RDS Proxy target could not be resolved: $target_type $target_resource_id"
      resolved_iam_auth_json=$(normalize_boolean "$resolved_iam_auth") || \
        fail_proxy "RDS Proxy target returned invalid IAM-authentication metadata: $target_type $target_resource_id"
      is_supported_engine "$resolved_engine" || fail_proxy "unsupported RDS Proxy target engine: $resolved_engine"
      if [[ -n $first_engine && $resolved_engine != "$first_engine" ]]; then
        fail_proxy "RDS Proxy targets disagree on engine: $first_engine and $resolved_engine"
      fi
      first_engine=$resolved_engine

      target_arn_json=$(json_nullable_string "$target_arn")
      tracked_cluster_id_json=$(json_nullable_string "$tracked_cluster_id")
      target_object=$(printf '{"type":%s,"rds_resource_id":%s,"target_arn":%s,"tracked_cluster_id":%s,"endpoint":%s,"port":%s,"role":%s,"target_health":%s}' \
        "$(json_quote "$target_type")" \
        "$(json_quote "$target_resource_id")" \
        "$target_arn_json" \
        "$tracked_cluster_id_json" \
        "$(json_quote "$target_endpoint")" \
        "$target_port" \
        "$(json_quote "$target_role")" \
        "$(json_quote "$target_health")")
      target_items="${target_items}${target_items:+,}${target_object}"

      resolved_object=$(printf '{"target_type":%s,"target_resource_id":%s,"tracked_cluster_id":%s,"kind":%s,"identifier":%s,"resource_id":%s,"engine":%s,"engine_version":%s,"endpoint":%s,"port":%s,"iam_auth":%s}' \
        "$(json_quote "$target_type")" \
        "$(json_quote "$target_resource_id")" \
        "$tracked_cluster_id_json" \
        "$(json_quote "$resolved_kind")" \
        "$(json_quote "$resolved_identifier")" \
        "$(json_quote "$resolved_resource_id")" \
        "$(json_quote "$resolved_engine")" \
        "$(json_quote "$resolved_engine_version")" \
        "$(json_quote "$resolved_endpoint")" \
        "$resolved_port" \
        "$resolved_iam_auth_json")
      resolved_items="${resolved_items}${resolved_items:+,}${resolved_object}"
    done <<< "$target_rows"

    emit_record db_proxy "$proxy_json"
    emit_record db_proxy_targets "[$target_items]"
    emit_record db_proxy_resolved_targets "[$resolved_items]"
    ;;
esac

if [[ -n $secret_id ]]; then
  secret_json=$(aws_call secretsmanager describe-secret \
    --secret-id "$secret_id" \
    --query '{name:Name,arn:ARN,rotation_enabled:RotationEnabled,kms_key_id:KmsKeyId}' \
    --output json)
  emit_record secret_metadata "$secret_json"
fi
