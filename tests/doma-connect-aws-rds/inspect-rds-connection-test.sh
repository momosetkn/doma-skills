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

assert_line_count() {
  local actual
  actual=$(wc -l < "$1")
  if [[ $actual -ne $2 ]]; then
    printf 'expected %s lines in %s, got %s\n' "$2" "$1" "$actual" >&2
    return 1
  fi
}

assert_first_call_is_identity() {
  local first_call
  first_call=$(sed -n '1p' "$call_log")
  if [[ $first_call != sts\ get-caller-identity\ * ]]; then
    printf 'expected identity first, got: %s\n' "$first_call" >&2
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
  assert_empty "$stdout_file" || return 1
  assert_empty "$call_log"
}

test_account_mismatch_stops_after_identity() {
  capture_inspector aurora-postgresql \
    --expected-account 999900001111 --region ap-northeast-1 \
    --target-kind cluster --target-id app-aurora-pg
  assert_status 65 || return 1
  assert_contains "$stderr_file" 'AWS account mismatch: expected 999900001111, got 111122223333' || return 1
  assert_empty "$stdout_file" || return 1
  assert_line_count "$call_log" 1 || return 1
  assert_contains "$call_log" 'sts get-caller-identity' || return 1
  assert_first_call_is_identity || return 1
  assert_not_contains "$call_log" 'rds' || return 1
  assert_every_call_has '--region ap-northeast-1' || return 1
  assert_every_call_has '--no-cli-pager' || return 1
  assert_safe_call_log
}

test_aurora_postgresql_cluster_projection() {
  capture_inspector aurora-postgresql \
    --expected-account 111122223333 --region ap-northeast-1 \
    --target-kind cluster --target-id app-aurora-pg
  assert_status 0 || return 1
  assert_empty "$stderr_file" || return 1
  assert_contains "$stdout_file" '"record_type":"db_cluster"' || return 1
  assert_contains "$stdout_file" '"engine":"aurora-postgresql"' || return 1
  assert_contains "$stdout_file" '"port":5432' || return 1
  assert_contains "$call_log" 'rds describe-db-clusters --db-cluster-identifier app-aurora-pg' || return 1
  assert_first_call_is_identity || return 1
  assert_every_call_has '--region ap-northeast-1' || return 1
  assert_every_call_has '--no-cli-pager' || return 1
  assert_safe_call_log
}

test_rds_postgresql_instance_projection() {
  capture_inspector rds-postgresql \
    --expected-account 111122223333 --region ap-northeast-1 \
    --target-kind instance --target-id app-rds-pg
  assert_status 0 || return 1
  assert_empty "$stderr_file" || return 1
  assert_contains "$stdout_file" '"record_type":"db_instance"' || return 1
  assert_contains "$stdout_file" '"engine":"postgres"' || return 1
  assert_contains "$stdout_file" '"port":5432' || return 1
  assert_contains "$call_log" 'rds describe-db-instances --db-instance-identifier app-rds-pg' || return 1
  assert_first_call_is_identity || return 1
  assert_every_call_has '--region ap-northeast-1' || return 1
  assert_every_call_has '--no-cli-pager' || return 1
  assert_safe_call_log
}

test_aurora_mysql_cluster_projection() {
  capture_inspector aurora-mysql \
    --expected-account 111122223333 --region ap-northeast-1 \
    --target-kind cluster --target-id app-aurora-mysql
  assert_status 0 || return 1
  assert_empty "$stderr_file" || return 1
  assert_contains "$stdout_file" '"record_type":"db_cluster"' || return 1
  assert_contains "$stdout_file" '"engine":"aurora-mysql"' || return 1
  assert_contains "$stdout_file" '"port":3306' || return 1
  assert_contains "$call_log" 'rds describe-db-clusters --db-cluster-identifier app-aurora-mysql' || return 1
  assert_first_call_is_identity || return 1
  assert_every_call_has '--region ap-northeast-1' || return 1
  assert_every_call_has '--no-cli-pager' || return 1
  assert_safe_call_log
}

test_rds_mysql_instance_projection() {
  capture_inspector rds-mysql \
    --expected-account 111122223333 --region ap-northeast-1 \
    --target-kind instance --target-id app-rds-mysql
  assert_status 0 || return 1
  assert_empty "$stderr_file" || return 1
  assert_contains "$stdout_file" '"record_type":"db_instance"' || return 1
  assert_contains "$stdout_file" '"engine":"mysql"' || return 1
  assert_contains "$stdout_file" '"port":3306' || return 1
  assert_contains "$call_log" 'rds describe-db-instances --db-instance-identifier app-rds-mysql' || return 1
  assert_first_call_is_identity || return 1
  assert_every_call_has '--region ap-northeast-1' || return 1
  assert_every_call_has '--no-cli-pager' || return 1
  assert_safe_call_log
}

test_proxy_emits_proxy_and_target_records() {
  capture_inspector postgresql-proxy \
    --expected-account 111122223333 --region ap-northeast-1 \
    --target-kind proxy --target-id app-proxy
  assert_status 0 || return 1
  assert_empty "$stderr_file" || return 1
  assert_contains "$stdout_file" '"record_type":"db_proxy"' || return 1
  assert_contains "$stdout_file" '"engine_family":"POSTGRESQL"' || return 1
  assert_contains "$stdout_file" '"record_type":"db_proxy_targets"' || return 1
  assert_contains "$stdout_file" '"port":5432' || return 1
  assert_line_count "$call_log" 3 || return 1
  assert_contains "$call_log" 'rds describe-db-proxies --db-proxy-name app-proxy' || return 1
  assert_contains "$call_log" 'rds describe-db-proxy-targets --db-proxy-name app-proxy' || return 1
  assert_first_call_is_identity || return 1
  assert_every_call_has '--region ap-northeast-1' || return 1
  assert_every_call_has '--no-cli-pager' || return 1
  assert_safe_call_log
}

test_secret_inspection_is_metadata_only_and_propagates_profile() {
  capture_inspector rds-postgresql \
    --expected-account 111122223333 --region ap-northeast-1 \
    --target-kind instance --target-id app-rds-pg \
    --profile workloads-dev --secret-id app/database
  assert_status 0 || return 1
  assert_empty "$stderr_file" || return 1
  assert_contains "$stdout_file" '"record_type":"secret_metadata"' || return 1
  assert_contains "$stdout_file" '"name":"app/database"' || return 1
  assert_not_contains "$stdout_file" 'password' || return 1
  assert_not_contains "$stdout_file" 'secret_value' || return 1
  assert_contains "$call_log" 'secretsmanager describe-secret --secret-id app/database' || return 1
  assert_first_call_is_identity || return 1
  assert_not_contains "$call_log" 'get-secret-value' || return 1
  assert_every_call_has '--profile workloads-dev' || return 1
  assert_every_call_has '--region ap-northeast-1' || return 1
  assert_every_call_has '--no-cli-pager' || return 1
  assert_safe_call_log
}

test_unknown_argument_makes_no_aws_call() {
  capture_inspector aurora-postgresql \
    --expected-account 111122223333 --region ap-northeast-1 \
    --target-kind cluster --target-id app-aurora-pg --write-anything
  assert_status 64 || return 1
  assert_contains "$stderr_file" 'unknown argument: --write-anything' || return 1
  assert_empty "$stdout_file" || return 1
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
    assert_empty "$stdout_file" || return 1
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
    assert_empty "$stdout_file" || return 1
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
    assert_empty "$stdout_file" || return 1
    assert_empty "$call_log" || return 1
  done
}

test_not_found_cluster_exits_66_after_identity() {
  capture_inspector not-found \
    --expected-account 111122223333 --region ap-northeast-1 \
    --target-kind cluster --target-id missing-cluster
  assert_status 66 || return 1
  assert_contains "$stderr_file" 'DB cluster not found' || return 1
  assert_contains "$stdout_file" '"record_type":"identity"' || return 1
  assert_not_contains "$stdout_file" '"record_type":"db_cluster"' || return 1
  assert_line_count "$call_log" 2 || return 1
  assert_first_call_is_identity || return 1
  assert_safe_call_log
}

run_test 'missing expected account makes no AWS call' test_missing_expected_account_makes_no_aws_call
run_test 'account mismatch stops after identity' test_account_mismatch_stops_after_identity
run_test 'Aurora PostgreSQL cluster emits engine and port' test_aurora_postgresql_cluster_projection
run_test 'RDS PostgreSQL instance emits engine and port' test_rds_postgresql_instance_projection
run_test 'Aurora MySQL cluster emits engine and port' test_aurora_mysql_cluster_projection
run_test 'RDS MySQL instance emits engine and port' test_rds_mysql_instance_projection
run_test 'Proxy emits proxy and target records' test_proxy_emits_proxy_and_target_records
run_test 'secret inspection is metadata-only and propagates profile' test_secret_inspection_is_metadata_only_and_propagates_profile
run_test 'unknown argument makes no AWS call' test_unknown_argument_makes_no_aws_call
run_test 'empty option values are rejected' test_empty_option_values_are_rejected
run_test 'option tokens are rejected as missing values' test_option_tokens_are_not_consumed_as_values
run_test 'unknown option-looking values are rejected' test_unknown_option_looking_values_are_rejected
run_test 'not-found cluster exits 66 after identity' test_not_found_cluster_exits_66_after_identity
printf '1..%s\n' "$tests_run"
