#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)
fixture_dir="$repo_root/tests/doma-connect-aws-rds/fixtures"
inspector=${INSPECTOR_PATH:-"$repo_root/skills/doma-connect-aws-rds/scripts/inspect-rds-connection.sh"}
fake_bin=$(mktemp -d)
ln -s "$repo_root/tests/doma-connect-aws-rds/fake-aws" "$fake_bin/aws"
call_log="$fake_bin/aws-calls.log"
stdout_file="$fake_bin/stdout"
stderr_file="$fake_bin/stderr"
status=0
tests_run=0
trap 'rm -rf -- "$fake_bin"' EXIT

run_inspector() {
  PATH="$fake_bin:$PATH" \
  AWS_CALL_LOG="$call_log" \
  FIXTURE_DIR="$fixture_dir" \
  FAKE_SCENARIO="$1" \
  "$inspector" "${@:2}"
}

capture_inspector() {
  : > "$call_log"
  : > "$stdout_file"
  : > "$stderr_file"
  set +e
  run_inspector "$@" >"$stdout_file" 2>"$stderr_file"
  status=$?
  set -e
}

assert_contains() {
  if ! rg -F -- "$2" "$1" >/dev/null; then
    printf 'expected %s to contain: %s\n' "$1" "$2" >&2
    return 1
  fi
}

assert_not_contains() {
  if rg -F -- "$2" "$1" >/dev/null; then
    printf 'expected %s not to contain: %s\n' "$1" "$2" >&2
    return 1
  fi
}

assert_empty() {
  if [[ -s $1 ]]; then
    printf 'expected %s to be empty; got:\n' "$1" >&2
    sed -n '1,20p' "$1" >&2
    return 1
  fi
}

assert_status() {
  if [[ $status -ne $1 ]]; then
    printf 'expected exit %s, got %s; stderr:\n' "$1" "$status" >&2
    sed -n '1,20p' "$stderr_file" >&2
    return 1
  fi
}

assert_json_records() {
  local expected_types=$1
  local expected_fields=$2
  python3 - "$stdout_file" "$expected_types" "$expected_fields" <<'PY'
import json
import pathlib
import sys

output_path = pathlib.Path(sys.argv[1])
expected_types = json.loads(sys.argv[2])
expected_fields = json.loads(sys.argv[3])
records = []
for line_number, line in enumerate(output_path.read_text().splitlines(), 1):
    try:
        record = json.loads(line)
    except json.JSONDecodeError as error:
        raise AssertionError(f"line {line_number} is not JSON: {error}") from error
    if not isinstance(record, dict):
        raise AssertionError(f"line {line_number} is not a JSON object")
    records.append(record)

actual_types = [record.get("record_type") for record in records]
if actual_types != expected_types:
    raise AssertionError(f"record types: expected {expected_types!r}, got {actual_types!r}")

def assert_subset(actual, expected, path):
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            raise AssertionError(f"{path}: expected object, got {actual!r}")
        for key, value in expected.items():
            if key not in actual:
                raise AssertionError(f"{path}: missing key {key!r}")
            assert_subset(actual[key], value, f"{path}.{key}")
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            raise AssertionError(f"{path}: expected {len(expected)} items, got {actual!r}")
        for index, value in enumerate(expected):
            assert_subset(actual[index], value, f"{path}[{index}]")
    elif actual != expected:
        raise AssertionError(f"{path}: expected {expected!r}, got {actual!r}")

records_by_type = {record["record_type"]: record for record in records}
for record_type, fields in expected_fields.items():
    if record_type not in records_by_type:
        raise AssertionError(f"missing expected record {record_type!r}")
    assert_subset(records_by_type[record_type], fields, record_type)
PY
}

assert_call_operations() {
  local expected=$1
  local actual
  actual=$(awk '{print $1 " " $2}' "$call_log")
  if [[ $actual != "$expected" ]]; then
    printf 'expected AWS operation order:\n%s\ngot:\n%s\n' "$expected" "$actual" >&2
    return 1
  fi
}

assert_every_call_has() {
  local expected=$1
  local line
  while IFS= read -r line; do
    if [[ $line != *"$expected"* ]]; then
      printf 'AWS call omitted %s: %s\n' "$expected" "$line" >&2
      return 1
    fi
  done < "$call_log"
}

assert_safe_call_log() {
  local forbidden
  for forbidden in create modify delete failover restore authorize revoke rotate get-secret-value; do
    assert_not_contains "$call_log" "$forbidden" || return 1
  done
}

assert_common_call_contract() {
  assert_every_call_has '--region ap-northeast-1' || return 1
  assert_every_call_has '--no-cli-pager' || return 1
  assert_safe_call_log
}

run_test() {
  local name=$1
  shift
  if "$@"; then
    tests_run=$((tests_run + 1))
    printf 'ok %s - %s\n' "$tests_run" "$name"
  else
    printf 'not ok - %s\n' "$name" >&2
    exit 1
  fi
}

test_missing_expected_account_makes_no_aws_call() {
  capture_inspector aurora-postgresql \
    --region ap-northeast-1 --target-kind cluster --target-id app-aurora-pg
  assert_status 64 || return 1
  assert_contains "$stderr_file" 'expected account must be 12 digits' || return 1
  assert_json_records '[]' '{}' || return 1
  assert_empty "$call_log"
}

test_account_mismatch_stops_after_identity() {
  capture_inspector aurora-postgresql \
    --expected-account 999900001111 --region ap-northeast-1 \
    --target-kind cluster --target-id app-aurora-pg
  assert_status 65 || return 1
  assert_contains "$stderr_file" 'AWS account mismatch: expected 999900001111, got 111122223333' || return 1
  assert_json_records '[]' '{}' || return 1
  assert_call_operations 'sts get-caller-identity' || return 1
  assert_common_call_contract
}

test_aurora_postgresql_cluster_projection() {
  capture_inspector aurora-postgresql \
    --expected-account 111122223333 --region ap-northeast-1 \
    --target-kind cluster --target-id app-aurora-pg
  assert_status 0 || return 1
  assert_empty "$stderr_file" || return 1
  assert_json_records '["identity","db_cluster"]' \
    '{"identity":{"account":"111122223333","region":"ap-northeast-1"},"db_cluster":{"data":{"identifier":"app-aurora-pg","resource_id":"cluster-ABCDEFGHIJKLMNOPQRSTU","engine":"aurora-postgresql","engine_version":"15.4","port":5432}}}' || return 1
  assert_call_operations $'sts get-caller-identity\nrds describe-db-clusters' || return 1
  assert_common_call_contract
}

test_rds_postgresql_instance_projection() {
  capture_inspector rds-postgresql \
    --expected-account 111122223333 --region ap-northeast-1 \
    --target-kind instance --target-id app-rds-pg
  assert_status 0 || return 1
  assert_empty "$stderr_file" || return 1
  assert_json_records '["identity","db_instance"]' \
    '{"identity":{"account":"111122223333"},"db_instance":{"data":{"identifier":"app-rds-pg","resource_id":"db-ABCDEFGHIJKLMNOPQRSTU","engine":"postgres","engine_version":"16.3","port":5432}}}' || return 1
  assert_call_operations $'sts get-caller-identity\nrds describe-db-instances' || return 1
  assert_common_call_contract
}

test_aurora_mysql_cluster_projection() {
  capture_inspector aurora-mysql \
    --expected-account 111122223333 --region ap-northeast-1 \
    --target-kind cluster --target-id app-aurora-mysql
  assert_status 0 || return 1
  assert_empty "$stderr_file" || return 1
  assert_json_records '["identity","db_cluster"]' \
    '{"db_cluster":{"data":{"identifier":"app-aurora-mysql","resource_id":"cluster-BCDEFGHIJKLMNOPQRSTUV","engine":"aurora-mysql","engine_version":"8.0.mysql_aurora.3.07.1","port":3306}}}' || return 1
  assert_call_operations $'sts get-caller-identity\nrds describe-db-clusters' || return 1
  assert_common_call_contract
}

test_rds_mysql_instance_projection() {
  capture_inspector rds-mysql \
    --expected-account 111122223333 --region ap-northeast-1 \
    --target-kind instance --target-id app-rds-mysql
  assert_status 0 || return 1
  assert_empty "$stderr_file" || return 1
  assert_json_records '["identity","db_instance"]' \
    '{"db_instance":{"data":{"identifier":"app-rds-mysql","resource_id":"db-BCDEFGHIJKLMNOPQRSTUV","engine":"mysql","engine_version":"8.0.39","port":3306}}}' || return 1
  assert_call_operations $'sts get-caller-identity\nrds describe-db-instances' || return 1
  assert_common_call_contract
}

test_proxy_resolves_tracked_cluster_and_emits_complete_metadata() {
  capture_inspector postgresql-proxy \
    --expected-account 111122223333 --region ap-northeast-1 \
    --target-kind proxy --target-id app-proxy
  assert_status 0 || return 1
  assert_empty "$stderr_file" || return 1
  assert_json_records '["identity","db_proxy","db_proxy_targets","db_proxy_resolved_targets"]' \
    '{"db_proxy":{"data":{"name":"app-proxy","arn":"arn:aws:rds:ap-northeast-1:111122223333:db-proxy:prx-ABCDEFGHIJKLMNOPQRSTU","engine_family":"POSTGRESQL","idle_client_timeout":1800,"default_auth_scheme":"NONE","vpc_id":"vpc-0123456789abcdef0","subnet_ids":["subnet-0123456789abcdef0","subnet-0123456789abcdef1"],"auth":[{"auth_scheme":"SECRETS","username":"app_user","client_password_auth_type":"POSTGRES_SCRAM_SHA_256","iam_auth":"REQUIRED","secret_arn":"arn:aws:secretsmanager:ap-northeast-1:111122223333:secret:app/database-example"}]}},"db_proxy_targets":{"data":[{"type":"TRACKED_CLUSTER","rds_resource_id":"cluster-ABCDEFGHIJKLMNOPQRSTU","target_arn":"arn:aws:rds:ap-northeast-1:111122223333:cluster:app-aurora-pg","tracked_cluster_id":"app-aurora-pg","port":5432}]},"db_proxy_resolved_targets":{"data":[{"target_type":"TRACKED_CLUSTER","target_resource_id":"cluster-ABCDEFGHIJKLMNOPQRSTU","kind":"cluster","identifier":"app-aurora-pg","resource_id":"cluster-ABCDEFGHIJKLMNOPQRSTU","engine":"aurora-postgresql","engine_version":"15.4","port":5432}]}}' || return 1
  assert_call_operations $'sts get-caller-identity\nrds describe-db-proxies\nrds describe-db-proxy-targets\nrds describe-db-clusters' || return 1
  assert_common_call_contract
}

test_proxy_resolves_instance_by_exact_target_arn() {
  capture_inspector postgresql-instance-proxy \
    --expected-account 111122223333 --region ap-northeast-1 \
    --target-kind proxy --target-id app-proxy
  assert_status 0 || return 1
  assert_empty "$stderr_file" || return 1
  assert_json_records '["identity","db_proxy","db_proxy_targets","db_proxy_resolved_targets"]' \
    '{"db_proxy_targets":{"data":[{"type":"RDS_INSTANCE","rds_resource_id":"app-rds-pg","target_arn":"arn:aws:rds:ap-northeast-1:111122223333:db:app-rds-pg","tracked_cluster_id":null}]},"db_proxy_resolved_targets":{"data":[{"target_type":"RDS_INSTANCE","target_resource_id":"app-rds-pg","kind":"instance","identifier":"app-rds-pg","resource_id":"db-ABCDEFGHIJKLMNOPQRSTU","engine":"postgres","engine_version":"16.3"}]}}' || return 1
  assert_call_operations $'sts get-caller-identity\nrds describe-db-proxies\nrds describe-db-proxy-targets\nrds describe-db-instances' || return 1
  assert_common_call_contract
}

test_proxy_rejects_unsupported_target_type_before_success() {
  capture_inspector proxy-unsupported-type \
    --expected-account 111122223333 --region ap-northeast-1 \
    --target-kind proxy --target-id app-proxy
  assert_status 67 || return 1
  assert_contains "$stderr_file" 'unsupported RDS Proxy target type: RDS_SERVERLESS_ENDPOINT' || return 1
  assert_json_records '["identity"]' '{"identity":{"account":"111122223333"}}' || return 1
  assert_call_operations $'sts get-caller-identity\nrds describe-db-proxies\nrds describe-db-proxy-targets' || return 1
  assert_common_call_contract
}

test_proxy_rejects_unresolvable_target_before_success() {
  capture_inspector proxy-unresolvable \
    --expected-account 111122223333 --region ap-northeast-1 \
    --target-kind proxy --target-id app-proxy
  assert_status 67 || return 1
  assert_contains "$stderr_file" 'RDS Proxy target could not be resolved: RDS_INSTANCE missing' || return 1
  assert_json_records '["identity"]' '{"identity":{"account":"111122223333"}}' || return 1
  assert_call_operations $'sts get-caller-identity\nrds describe-db-proxies\nrds describe-db-proxy-targets\nrds describe-db-instances' || return 1
  assert_common_call_contract
}

test_proxy_rejects_targets_that_disagree_on_engine() {
  capture_inspector proxy-mixed-engines \
    --expected-account 111122223333 --region ap-northeast-1 \
    --target-kind proxy --target-id app-proxy
  assert_status 67 || return 1
  assert_contains "$stderr_file" 'RDS Proxy targets disagree on engine: aurora-postgresql and postgres' || return 1
  assert_json_records '["identity"]' '{"identity":{"account":"111122223333"}}' || return 1
  assert_call_operations $'sts get-caller-identity\nrds describe-db-proxies\nrds describe-db-proxy-targets\nrds describe-db-clusters\nrds describe-db-instances' || return 1
  assert_common_call_contract
}

test_proxy_rejects_unsupported_resolved_engine() {
  capture_inspector proxy-unsupported-engine \
    --expected-account 111122223333 --region ap-northeast-1 \
    --target-kind proxy --target-id app-proxy
  assert_status 67 || return 1
  assert_contains "$stderr_file" 'unsupported RDS Proxy target engine: mariadb' || return 1
  assert_json_records '["identity"]' '{"identity":{"account":"111122223333"}}' || return 1
  assert_call_operations $'sts get-caller-identity\nrds describe-db-proxies\nrds describe-db-proxy-targets\nrds describe-db-instances' || return 1
  assert_common_call_contract
}

test_secret_inspection_is_metadata_only_and_propagates_profile() {
  capture_inspector rds-postgresql \
    --expected-account 111122223333 --region ap-northeast-1 \
    --target-kind instance --target-id app-rds-pg \
    --profile workloads-dev --secret-id app/database
  assert_status 0 || return 1
  assert_empty "$stderr_file" || return 1
  assert_json_records '["identity","db_instance","secret_metadata"]' \
    '{"secret_metadata":{"data":{"name":"app/database","rotation_enabled":true}}}' || return 1
  assert_not_contains "$stdout_file" 'password' || return 1
  assert_not_contains "$stdout_file" 'secret_value' || return 1
  assert_call_operations $'sts get-caller-identity\nrds describe-db-instances\nsecretsmanager describe-secret' || return 1
  assert_not_contains "$call_log" 'get-secret-value' || return 1
  assert_every_call_has '--profile workloads-dev' || return 1
  assert_common_call_contract
}

test_unknown_argument_makes_no_aws_call() {
  capture_inspector aurora-postgresql \
    --expected-account 111122223333 --region ap-northeast-1 \
    --target-kind cluster --target-id app-aurora-pg --write-anything
  assert_status 64 || return 1
  assert_contains "$stderr_file" 'unknown argument: --write-anything' || return 1
  assert_json_records '[]' '{}' || return 1
  assert_empty "$call_log"
}

test_option_tokens_are_not_consumed_as_values() {
  local option
  local next_option
  while IFS=: read -r option next_option; do
    capture_inspector aurora-postgresql \
      --expected-account 111122223333 --region ap-northeast-1 \
      --target-kind cluster --target-id app-aurora-pg \
      "$option" "$next_option"
    assert_status 64 || return 1
    assert_contains "$stderr_file" "missing value for $option" || return 1
    assert_json_records '[]' '{}' || return 1
    assert_empty "$call_log" || return 1
  done <<'CASES'
--expected-account:--region
--region:--profile
--target-kind:--profile
--target-id:--profile
--profile:--secret-id
--secret-id:--profile
CASES
}

test_unknown_option_looking_values_are_rejected() {
  local option
  for option in --target-id --expected-account --region --target-kind --profile --secret-id; do
    capture_inspector aurora-postgresql \
      --expected-account 111122223333 --region ap-northeast-1 \
      --target-kind cluster --target-id app-aurora-pg \
      "$option" --write-anything
    assert_status 64 || return 1
    assert_contains "$stderr_file" "missing value for $option" || return 1
    assert_json_records '[]' '{}' || return 1
    assert_empty "$call_log" || return 1
  done
}

test_empty_option_values_are_rejected() {
  local option
  for option in --expected-account --region --target-kind --target-id --profile --secret-id; do
    capture_inspector aurora-postgresql \
      --expected-account 111122223333 --region ap-northeast-1 \
      --target-kind cluster --target-id app-aurora-pg \
      "$option" ''
    assert_status 64 || return 1
    assert_contains "$stderr_file" "missing value for $option" || return 1
    assert_json_records '[]' '{}' || return 1
    assert_empty "$call_log" || return 1
  done
}

test_malformed_regions_make_no_aws_call() {
  local invalid_region
  for invalid_region in - -us-east-1 us-east-1- us--east-1 us-east--1 us_east_1; do
    capture_inspector aurora-postgresql \
      --expected-account 111122223333 --region "$invalid_region" \
      --target-kind cluster --target-id app-aurora-pg
    assert_status 64 || return 1
    assert_contains "$stderr_file" 'region must contain lowercase alphanumeric segments separated by single hyphens' || return 1
    assert_json_records '[]' '{}' || return 1
    assert_empty "$call_log" || return 1
  done
}

test_malformed_identifiers_make_no_aws_call_by_kind() {
  local target_kind
  local invalid_id
  while IFS=: read -r target_kind invalid_id; do
    capture_inspector aurora-postgresql \
      --expected-account 111122223333 --region ap-northeast-1 \
      --target-kind "$target_kind" --target-id "$invalid_id"
    assert_status 64 || return 1
    assert_contains "$stderr_file" "$target_kind identifier must be 1-63 letters, digits, or hyphens; start with a letter; and contain no trailing or consecutive hyphen" || return 1
    assert_json_records '[]' '{}' || return 1
    assert_empty "$call_log" || return 1
  done <<'CASES'
instance:1app
instance:app-
instance:app--db
instance:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
cluster:1app
cluster:app-
cluster:app--db
cluster:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
proxy:1app
proxy:app-
proxy:app--db
proxy:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
CASES
}

test_not_found_cluster_exits_66_after_identity() {
  capture_inspector not-found \
    --expected-account 111122223333 --region ap-northeast-1 \
    --target-kind cluster --target-id missing-cluster
  assert_status 66 || return 1
  assert_contains "$stderr_file" 'DB cluster not found' || return 1
  assert_json_records '["identity"]' '{"identity":{"account":"111122223333"}}' || return 1
  assert_call_operations $'sts get-caller-identity\nrds describe-db-clusters' || return 1
  assert_common_call_contract
}

run_test 'missing expected account makes no AWS call' test_missing_expected_account_makes_no_aws_call
run_test 'account mismatch stops after identity' test_account_mismatch_stops_after_identity
run_test 'Aurora PostgreSQL cluster emits immutable id and engine version' test_aurora_postgresql_cluster_projection
run_test 'RDS PostgreSQL instance emits immutable id and engine version' test_rds_postgresql_instance_projection
run_test 'Aurora MySQL cluster emits immutable id and engine version' test_aurora_mysql_cluster_projection
run_test 'RDS MySQL instance emits immutable id and engine version' test_rds_mysql_instance_projection
run_test 'Proxy resolves tracked cluster and emits complete metadata' test_proxy_resolves_tracked_cluster_and_emits_complete_metadata
run_test 'Proxy resolves instance by exact target ARN' test_proxy_resolves_instance_by_exact_target_arn
run_test 'Proxy rejects unsupported target type before success' test_proxy_rejects_unsupported_target_type_before_success
run_test 'Proxy rejects unresolvable target before success' test_proxy_rejects_unresolvable_target_before_success
run_test 'Proxy rejects targets that disagree on engine' test_proxy_rejects_targets_that_disagree_on_engine
run_test 'Proxy rejects unsupported resolved engine' test_proxy_rejects_unsupported_resolved_engine
run_test 'secret inspection is metadata-only and propagates profile' test_secret_inspection_is_metadata_only_and_propagates_profile
run_test 'unknown argument makes no AWS call' test_unknown_argument_makes_no_aws_call
run_test 'empty option values are rejected' test_empty_option_values_are_rejected
run_test 'option tokens are rejected as missing values' test_option_tokens_are_not_consumed_as_values
run_test 'unknown option-looking values are rejected' test_unknown_option_looking_values_are_rejected
run_test 'malformed regions make no AWS call' test_malformed_regions_make_no_aws_call
run_test 'malformed identifiers make no AWS call by kind' test_malformed_identifiers_make_no_aws_call_by_kind
run_test 'not-found cluster exits 66 after identity' test_not_found_cluster_exits_66_after_identity
printf '1..%s\n' "$tests_run"
