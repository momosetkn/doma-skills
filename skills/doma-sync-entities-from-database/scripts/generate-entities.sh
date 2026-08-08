#!/usr/bin/env bash
set -euo pipefail
set +x

connection=""
database=""
project_root_input=""
expected_account=""
region=""
target_kind=""
target_id=""
profile=""
secret_id=""
db_name=""
db_user_option=""
db_url=""
db_user=""
db_password=""
iam_token=""
secret_response=""
secret_parsed=""

cleanup_secrets() {
  unset db_password iam_token secret_response secret_parsed
  unset DOMA_CODEGEN_DB_PASSWORD DOMA_SYNC_JDBC_PASSWORD
  unset DOMA_REDACT_PASSWORD DOMA_REDACT_TOKEN
}
trap cleanup_secrets EXIT
trap 'cleanup_secrets; trap - EXIT; exit 130' HUP INT TERM

die() {
  printf '%s\n' "$1" >&2
  exit "${2:-64}"
}

require_value() {
  [[ $# -ge 2 && -n "$2" ]] || die "$1 requires a value"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-root) require_value "$@"; project_root_input=$2; shift 2 ;;
    --connection) require_value "$@"; connection=$2; shift 2 ;;
    --database) require_value "$@"; database=$2; shift 2 ;;
    --expected-account) require_value "$@"; expected_account=$2; shift 2 ;;
    --region) require_value "$@"; region=$2; shift 2 ;;
    --target-kind) require_value "$@"; target_kind=$2; shift 2 ;;
    --target-id) require_value "$@"; target_id=$2; shift 2 ;;
    --profile) require_value "$@"; profile=$2; shift 2 ;;
    --secret-id) require_value "$@"; secret_id=$2; shift 2 ;;
    --db-name) require_value "$@"; db_name=$2; shift 2 ;;
    --db-user) require_value "$@"; db_user_option=$2; shift 2 ;;
    --password|--db-password|--token|--access-key|--secret-value|--jdbc-url|--url)
      die "$1 is forbidden; pass credentials only through the documented environment"
      ;;
    --password=*|--db-password=*|--token=*|--access-key=*|--secret-value=*|--jdbc-url=*|--url=*)
      die "credential-bearing command-line options are forbidden"
      ;;
    *) die "unsupported option: $1" ;;
  esac
done

[[ -n "$project_root_input" ]] || die "--project-root is required"
[[ "$connection" == "local" || "$connection" == "aws-secret" || "$connection" == "aws-iam" ]] \
  || die "--connection must be local, aws-secret, or aws-iam"
[[ "$database" == "postgresql" || "$database" == "mysql" ]] \
  || die "--database must be postgresql or mysql"
[[ -d "$project_root_input" ]] || die "project root must be a directory"
project_root=$(cd -- "$project_root_input" && pwd -P)
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)

output_root="$project_root/build/doma-codegen"
classpath_file="$output_root/codegen-classpath.txt"
snapshot_file="$output_root/schema-snapshot.json"
generated_dir="$output_root/generated"

validate_output_paths() {
  python3 - "$project_root" "$output_root" "$classpath_file" "$snapshot_file" "$generated_dir" <<'PY'
import pathlib
import sys

project = pathlib.Path(sys.argv[1]).resolve()
build = (project / "build").resolve()
try:
    build.relative_to(project)
except ValueError:
    raise SystemExit(1)
for raw in sys.argv[2:]:
    path = pathlib.Path(raw)
    resolved = path.resolve()
    try:
        resolved.relative_to(build)
    except ValueError:
        raise SystemExit(1)
    if path.is_symlink():
        raise SystemExit(1)
PY
}
validate_output_paths || die "output path must remain inside the project build directory" 65

scan_generated_outputs() {
  DOMA_SCAN_PASSWORD="$db_password" DOMA_SCAN_TOKEN="$iam_token" python3 - "$snapshot_file" "$generated_dir" <<'PY'
import os
import pathlib
import re
import sys

needles = [value.encode() for value in (os.environ.get("DOMA_SCAN_PASSWORD", ""), os.environ.get("DOMA_SCAN_TOKEN", "")) if value]
patterns = (
    re.compile(rb"(?i)jdbc:[^\s]+://[^/@\s]+@"),
    re.compile(rb"(?:AKIA|ASIA)[0-9A-Z]{16}"),
    re.compile(rb"(?i)(?:password|secret|token)\s*[:=]\s*[\"'][^\"']+[\"']"),
)
paths = [pathlib.Path(sys.argv[1])]
generated = pathlib.Path(sys.argv[2])
if generated.exists():
    paths.extend(path for path in generated.rglob("*") if path.is_file() and not path.is_symlink())
for path in paths:
    if not path.is_file() or path.is_symlink():
        continue
    data = path.read_bytes()
    if any(needle in data for needle in needles) or any(pattern.search(data) for pattern in patterns):
        raise SystemExit(1)
PY
}

scan_or_remove_unsafe_outputs() {
  validate_output_paths || die "output path must remain inside the project build directory" 65
  if ! scan_generated_outputs; then
    validate_output_paths || die "output path must remain inside the project build directory" 65
    rm -rf -- "$generated_dir"
    rm -f -- "$snapshot_file"
    die "generated output failed credential scan; candidate outputs were removed" 65
  fi
}

unsafe_field=$(python3 - "$project_root" <<'PY'
import pathlib
import re
import sys

root = pathlib.Path(sys.argv[1])
property_name = re.compile(r"^\s*([^#!\s:=]+)\s*[:=]")
sensitive = re.compile(r"(?:password|token|secret|access.?key)", re.I)
connection_url = re.compile(r"jdbc:[^\s'\"]+://[^/@\s'\"]+@", re.I)
connection_property = re.compile(
    r"jdbc:[^\s'\"]*[?&;](?:user(?:name)?|password|token|secret|access.?key)=",
    re.I,
)
for path in sorted(root.rglob("*")):
    relative = path.relative_to(root)
    if any(part in {"build", ".gradle", ".git"} for part in relative.parts):
        continue
    if path.name != "gradle.properties" and not path.name.endswith((".gradle", ".gradle.kts")):
        continue
    if path.is_symlink():
        print("Gradle build tree symlink")
        raise SystemExit(0)
    if not path.is_file():
        continue
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise SystemExit(65)
    for line in text.splitlines():
        match = property_name.match(line)
        if path.name == "gradle.properties" and match and sensitive.search(match.group(1)):
            print(match.group(1))
            raise SystemExit(0)
        if connection_url.search(line) or connection_property.search(line):
            print("credential-bearing JDBC URL")
            raise SystemExit(0)
    literal = re.search(
        r"\b([A-Za-z_][A-Za-z0-9_.-]*(?:password|token|secret|access.?key)[A-Za-z0-9_.-]*)\b(?:\s*:\s*[^=]+\s*=|\s*=|\.set\s*\()\s*['\"]",
        text, re.I,
    )
    if literal:
        print(literal.group(1))
        raise SystemExit(0)
    indexed = re.search(
        r"['\"]([^'\"]*(?:password|token|secret|access.?key)[^'\"]*)['\"]\s*\]\s*=\s*['\"]",
        text, re.I,
    )
    if indexed:
        print(indexed.group(1))
        raise SystemExit(0)
PY
) || die "could not safely scan the Gradle build tree" 65
[[ -z "$unsafe_field" ]] || die "project-local secret field is unsafe: $unsafe_field" 65

validate_scalar() {
  local field=$1 value=$2
  [[ -n "$value" ]] || die "$field is required"
  [[ "$value" != *$'\n'* && "$value" != *$'\r'* ]] || die "$field contains a forbidden control character"
}

read_user_property() {
  local wanted=$1 properties_file=$2
  [[ -f "$properties_file" && ! -L "$properties_file" ]] || return 0
  python3 - "$wanted" "$properties_file" <<'PY'
import pathlib
import sys

wanted, raw = sys.argv[1], pathlib.Path(sys.argv[2]).read_bytes()
if b"\0" in raw:
    raise SystemExit(65)
for line in raw.decode("utf-8").splitlines():
    stripped = line.lstrip()
    if not stripped or stripped[0] in "#!":
        continue
    import re
    match = re.match(r"^\s*" + re.escape(wanted) + r"(?:\s*[:=]\s*|\s+)(.*)$", line)
    if match:
        value = match.group(1)
        if any(character in value for character in "\r\n\0"):
            raise SystemExit(65)
        print(value.strip())
        raise SystemExit(0)
PY
}

url_is_credential_free() {
  python3 -c '
import sys
from urllib.parse import parse_qsl, urlsplit
raw = sys.stdin.read()
try:
    parsed = urlsplit(raw[5:] if raw.lower().startswith("jdbc:") else raw)
except ValueError:
    raise SystemExit(1)
if "@" in parsed.netloc:
    raise SystemExit(1)
sensitive = {"user", "username", "password", "token", "secret", "accesskey", "access_key"}
keys = {key.lower() for key, _ in parse_qsl(parsed.query, keep_blank_values=True)}
for segment in raw.split(";")[1:]:
    keys.add(segment.split("=", 1)[0].strip().lower())
raise SystemExit(1 if keys & sensitive else 0)
'
}

if [[ "$connection" == "local" ]]; then
  user_properties="${GRADLE_USER_HOME:-${HOME:?HOME is required}/.gradle}/gradle.properties"
  db_url=${DOMA_CODEGEN_DB_URL-}
  db_user=${DOMA_CODEGEN_DB_USER-}
  db_password=${DOMA_CODEGEN_DB_PASSWORD-}
  [[ -n "$db_url" ]] || db_url=$(read_user_property domaCodegenDbUrl "$user_properties") \
    || die "could not safely read domaCodegenDbUrl"
  [[ -n "$db_user" ]] || db_user=$(read_user_property domaCodegenDbUser "$user_properties") \
    || die "could not safely read domaCodegenDbUser"
  [[ -n "$db_password" ]] || db_password=$(read_user_property domaCodegenDbPassword "$user_properties") \
    || die "could not safely read domaCodegenDbPassword"
  missing_local=()
  [[ -n "$db_url" ]] || missing_local+=(DOMA_CODEGEN_DB_URL)
  [[ -n "$db_user" ]] || missing_local+=(DOMA_CODEGEN_DB_USER)
  [[ -n "$db_password" ]] || missing_local+=(DOMA_CODEGEN_DB_PASSWORD)
  [[ ${#missing_local[@]} -eq 0 ]] || die "local credentials are incomplete: ${missing_local[*]}"
  validate_scalar DOMA_CODEGEN_DB_URL "$db_url"
  validate_scalar DOMA_CODEGEN_DB_USER "$db_user"
  validate_scalar DOMA_CODEGEN_DB_PASSWORD "$db_password"
  printf '%s' "$db_url" | url_is_credential_free \
    || die "DOMA_CODEGEN_DB_URL must not contain embedded credentials" 65
  expected_prefix="jdbc:$database:"
  [[ "$db_url" == "$expected_prefix"* ]] || die "DOMA_CODEGEN_DB_URL does not match --database"
  if [[ "$database" == "mysql" && -z "$db_name" ]]; then
    db_name=${db_url#jdbc:mysql://*/}
    db_name=${db_name%%\?*}
  fi
else
  [[ "$expected_account" =~ ^[0-9]{12}$ ]] || die "--expected-account must be 12 digits"
  [[ "$region" =~ ^[a-z]{2}(-[a-z0-9]+)+-[0-9]+$ ]] || die "--region is invalid"
  [[ "$target_kind" == "instance" || "$target_kind" == "cluster" || "$target_kind" == "proxy" ]] \
    || die "--target-kind must be instance, cluster, or proxy"
  [[ "$target_id" =~ ^[A-Za-z][A-Za-z0-9-]{0,62}$ ]] || die "--target-id is invalid"
  [[ "$db_name" =~ ^[A-Za-z0-9_.\$-]+$ ]] || die "--db-name is invalid"
  [[ -z "$profile" || "$profile" =~ ^[A-Za-z0-9_+=,.@-]+$ ]] || die "--profile is invalid"
  if [[ "$connection" == "aws-secret" ]]; then
    [[ "$secret_id" =~ ^[A-Za-z0-9_+=,.@:/-]+$ ]] || die "--secret-id is required and must be valid"
    [[ -z "$db_user_option" ]] || die "--db-user is only valid with aws-iam"
  else
    [[ -z "$secret_id" ]] || die "--secret-id is only valid with aws-secret"
    [[ "$db_user_option" =~ ^[A-Za-z0-9_.$-]+$ ]] || die "--db-user is required and must be valid"
  fi
fi

if [[ -x "$project_root/gradlew" && ! -L "$project_root/gradlew" ]]; then
  gradle_command=("$project_root/gradlew")
elif [[ -n "${GRADLE_CMD-}" ]]; then
  [[ "$GRADLE_CMD" =~ ^[A-Za-z0-9_./+-]+$ ]] || die "GRADLE_CMD contains unsafe shell characters" 65
  resolved_gradle=$(command -v -- "$GRADLE_CMD" 2>/dev/null || true)
  [[ -n "$resolved_gradle" && -x "$resolved_gradle" ]] || die "GRADLE_CMD is not executable"
  gradle_command=("$resolved_gradle")
else
  resolved_gradle=$(command -v gradle 2>/dev/null || true)
  [[ -n "$resolved_gradle" && -x "$resolved_gradle" ]] || die "no safe Gradle command was found"
  gradle_command=("$resolved_gradle")
fi

redact_stream() {
  DOMA_REDACT_PASSWORD="$db_password" DOMA_REDACT_TOKEN="$iam_token" python3 -c '
import os, sys
values = [v.encode() for v in (os.environ.get("DOMA_REDACT_PASSWORD", ""), os.environ.get("DOMA_REDACT_TOKEN", "")) if v]
for data in sys.stdin.buffer:
    for value in values: data = data.replace(value, b"[REDACTED]")
    sys.stdout.buffer.write(data); sys.stdout.buffer.flush()
'
}

run_redacted() {
  local status
  set +e
  "$@" > >(redact_stream) 2> >(redact_stream >&2)
  status=$?
  wait
  set -e
  return "$status"
}

aws_command=()
aws_call() {
  local service=$1 operation=$2
  shift 2
  case "$service $operation" in
    "sts get-caller-identity"|"rds describe-db-instances"|"rds describe-db-clusters"|\
    "rds describe-db-proxies"|"rds describe-db-proxy-targets"|\
    "secretsmanager describe-secret"|"secretsmanager get-secret-value"|\
    "rds generate-db-auth-token") ;;
    *) die "internal AWS operation is not allowlisted" 65 ;;
  esac
  "${aws_command[@]}" "$service" "$operation" "$@"
}

parse_target() {
  local kind=$1 identifier=$2
  python3 -c '
import json, sys
kind, expected = sys.argv[1:3]
data = json.load(sys.stdin)
if kind == "instance":
    values = data.get("DBInstances")
    key, host = "DBInstanceIdentifier", lambda item: item.get("Endpoint", {}).get("Address")
    port = lambda item: item.get("Endpoint", {}).get("Port")
elif kind == "cluster":
    values = data.get("DBClusters")
    key, host, port = "DBClusterIdentifier", lambda item: item.get("Endpoint"), lambda item: item.get("Port")
else:
    values = data.get("DBProxies")
    key, host, port = "DBProxyName", lambda item: item.get("Endpoint"), lambda item: ""
if not isinstance(values, list) or len(values) != 1 or values[0].get(key) != expected:
    raise SystemExit(1)
item = values[0]
engine = item.get("Engine") if kind != "proxy" else item.get("EngineFamily")
parts = (host(item), port(item), engine)
if any(value is None or isinstance(value, (dict, list)) for value in parts):
    raise SystemExit(1)
print("\x1f".join(map(str, parts)))
' "$kind" "$identifier"
}

engine_family() {
  case "${1,,}" in
    postgres|aurora-postgresql|postgresql) printf 'postgresql\n' ;;
    mysql|aurora-mysql) printf 'mysql\n' ;;
    *) return 1 ;;
  esac
}

if [[ "$connection" != "local" ]]; then
  resolved_aws=$(command -v aws 2>/dev/null || true)
  [[ -n "$resolved_aws" && -x "$resolved_aws" ]] || die "AWS CLI is required"
  aws_command=("$resolved_aws")
  [[ -z "$profile" ]] || aws_command+=(--profile "$profile")
  identity=$(aws_call sts get-caller-identity --output json) || die "AWS identity lookup failed" 70
  actual_account=$(python3 -c 'import json,sys; value=json.load(sys.stdin).get("Account"); print(value if isinstance(value,str) else "")' \
    <<< "$identity" 2>/dev/null) || die "AWS identity response is invalid" 70
  [[ "$actual_account" == "$expected_account" ]] || die "AWS account does not match --expected-account" 65

  case "$target_kind" in
    instance)
      target_json=$(aws_call rds describe-db-instances --db-instance-identifier "$target_id" --region "$region" --output json) \
        || die "exact RDS instance lookup failed" 70
      target_fields=$(parse_target instance "$target_id" <<< "$target_json" 2>/dev/null) \
        || die "exact RDS instance response is invalid" 70
      IFS=$'\x1f' read -r endpoint port engine <<< "$target_fields"
      ;;
    cluster)
      target_json=$(aws_call rds describe-db-clusters --db-cluster-identifier "$target_id" --region "$region" --output json) \
        || die "exact RDS cluster lookup failed" 70
      target_fields=$(parse_target cluster "$target_id" <<< "$target_json" 2>/dev/null) \
        || die "exact RDS cluster response is invalid" 70
      IFS=$'\x1f' read -r endpoint port engine <<< "$target_fields"
      ;;
    proxy)
      proxy_json=$(aws_call rds describe-db-proxies --db-proxy-name "$target_id" --region "$region" --output json) \
        || die "exact RDS proxy lookup failed" 70
      proxy_fields=$(parse_target proxy "$target_id" <<< "$proxy_json" 2>/dev/null) \
        || die "exact RDS proxy response is invalid" 70
      IFS=$'\x1f' read -r endpoint _ proxy_engine <<< "$proxy_fields"
      targets_json=$(aws_call rds describe-db-proxy-targets --db-proxy-name "$target_id" --region "$region" --output json) \
        || die "exact RDS proxy target lookup failed" 70
      proxy_target_lines=$(python3 -c '
import json, sys
targets = json.load(sys.stdin).get("Targets")
if not isinstance(targets, list) or not targets: raise SystemExit(1)
for target in targets:
    kind, identifier = target.get("Type"), target.get("RdsResourceId")
    if kind not in {"RDS_INSTANCE", "RDS_CLUSTER", "TRACKED_CLUSTER"} or not isinstance(identifier, str): raise SystemExit(1)
    print(kind + "\t" + identifier)
' <<< "$targets_json" 2>/dev/null) || die "RDS proxy target response is invalid" 70
      [[ -n "$proxy_target_lines" ]] || die "RDS proxy has no supported exact targets" 70
      mapfile -t proxy_targets <<< "$proxy_target_lines"
      [[ ${#proxy_targets[@]} -gt 0 ]] || die "RDS proxy has no supported exact targets" 70
      resolved_family=""
      for proxy_target in "${proxy_targets[@]}"; do
        IFS=$'\t' read -r proxy_target_kind proxy_target_id <<< "$proxy_target"
        if [[ "$proxy_target_kind" == "RDS_INSTANCE" ]]; then
          resolved_json=$(aws_call rds describe-db-instances --db-instance-identifier "$proxy_target_id" --region "$region" --output json) \
            || die "RDS proxy instance target lookup failed" 70
          resolved_fields=$(parse_target instance "$proxy_target_id" <<< "$resolved_json" 2>/dev/null) \
            || die "RDS proxy instance target response is invalid" 70
        else
          resolved_json=$(aws_call rds describe-db-clusters --db-cluster-identifier "$proxy_target_id" --region "$region" --output json) \
            || die "RDS proxy cluster target lookup failed" 70
          resolved_fields=$(parse_target cluster "$proxy_target_id" <<< "$resolved_json" 2>/dev/null) \
            || die "RDS proxy cluster target response is invalid" 70
        fi
        IFS=$'\x1f' read -r _ resolved_port resolved_engine <<< "$resolved_fields"
        family=$(engine_family "$resolved_engine") || die "RDS proxy target engine is unsupported" 65
        [[ -z "$resolved_family" || "$family" == "$resolved_family" ]] \
          || die "RDS proxy targets do not share one engine family" 65
        resolved_family=$family
      done
      [[ "$(engine_family "$proxy_engine")" == "$resolved_family" ]] \
        || die "RDS proxy engine family conflicts with its targets" 65
      engine=$resolved_family
      port=$([[ "$resolved_family" == "postgresql" ]] && printf 5432 || printf 3306)
      ;;
  esac
  [[ "$endpoint" =~ ^[A-Za-z0-9.-]+$ && "$port" =~ ^[0-9]+$ && "$port" -ge 1 && "$port" -le 65535 ]] \
    || die "confirmed RDS endpoint is invalid" 70
  family=$(engine_family "$engine") || die "confirmed RDS engine is unsupported" 65
  [[ "$family" == "$database" ]] || die "confirmed RDS engine does not match --database" 65
  if [[ "$database" == "postgresql" ]]; then
    db_url="jdbc:postgresql://$endpoint:$port/$db_name?sslmode=verify-full"
  else
    db_url="jdbc:mysql://$endpoint:$port/$db_name?sslMode=VERIFY_IDENTITY"
  fi
fi

set +e
(
  cd -- "$project_root"
  unset DOMA_CODEGEN_DB_URL DOMA_CODEGEN_DB_USER DOMA_CODEGEN_DB_PASSWORD
  unset DOMA_SYNC_JDBC_URL DOMA_SYNC_JDBC_USER DOMA_SYNC_JDBC_PASSWORD
  run_redacted "${gradle_command[@]}" --no-daemon domaSyncWriteCodeGenClasspath
)
classpath_status=$?
set -e
if [[ $classpath_status -ne 0 ]]; then
  printf 'Gradle CodeGen classpath task failed\n' >&2
  exit "$classpath_status"
fi
validate_output_paths || die "output path must remain inside the project build directory" 65
[[ -f "$classpath_file" && ! -L "$classpath_file" ]] || die "Gradle did not write a safe CodeGen classpath" 70
IFS= read -r codegen_classpath < "$classpath_file" || true
[[ -n "$codegen_classpath" && "$codegen_classpath" != *$'\n'* && "$codegen_classpath" != *$'\r'* ]] \
  || die "CodeGen classpath output is invalid" 70

if [[ "$connection" == "aws-secret" ]]; then
  description=$(aws_call secretsmanager describe-secret --secret-id "$secret_id" --region "$region" --output json) \
    || die "Secret description failed" 70
  python3 -c '
import json, sys
data=json.load(sys.stdin); arn=data.get("ARN", "")
expected_region, expected_account = sys.argv[1:3]
parts=arn.split(":")
raise SystemExit(0 if len(parts) > 5 and parts[3] == expected_region and parts[4] == expected_account else 1)
' "$region" "$expected_account" <<< "$description" 2>/dev/null \
    || die "Secret identity does not match the confirmed region and account" 65
  secret_response=$(aws_call secretsmanager get-secret-value --secret-id "$secret_id" --region "$region" --output json) \
    || die "Secret retrieval failed" 70
  secret_parsed=$(python3 -c '
import json, sys
outer=json.load(sys.stdin)
if "SecretBinary" in outer or not isinstance(outer.get("SecretString"), str): raise SystemExit(1)
value=json.loads(outer["SecretString"])
if not isinstance(value, dict): raise SystemExit(1)
fields=[value.get(name, "") for name in ("username", "password", "host", "port", "engine", "dbname")]
if not isinstance(fields[0], str) or not fields[0] or not isinstance(fields[1], str) or not fields[1]: raise SystemExit(1)
for field in fields:
    if not isinstance(field, (str, int)) or any(ord(c) < 32 for c in str(field)): raise SystemExit(1)
print("\x1f".join(map(str, fields)))
' <<< "$secret_response" 2>/dev/null) || die "Secret value has an unsafe format" 65
  unset secret_response
  IFS=$'\x1f' read -r db_user db_password secret_host secret_port secret_engine secret_dbname <<< "$secret_parsed"
  unset secret_parsed
  [[ -z "$secret_host" || "$secret_host" == "$endpoint" ]] || die "Secret routing fields conflict with the confirmed RDS target" 65
  [[ -z "$secret_port" || "$secret_port" == "$port" ]] || die "Secret routing fields conflict with the confirmed RDS target" 65
  [[ -z "$secret_engine" || "$(engine_family "$secret_engine" 2>/dev/null || true)" == "$database" ]] \
    || die "Secret routing fields conflict with the confirmed RDS target" 65
  [[ -z "$secret_dbname" || "$secret_dbname" == "$db_name" ]] || die "Secret database name conflicts with --db-name" 65
elif [[ "$connection" == "aws-iam" ]]; then
  db_user=$db_user_option
  iam_token=$(aws_call rds generate-db-auth-token --hostname "$endpoint" --port "$port" --username "$db_user" --region "$region") \
    || die "IAM database authentication token generation failed" 70
  validate_scalar "IAM database authentication token" "$iam_token"
  db_password=$iam_token
fi

schema=""
catalog=""
if [[ "$database" == "postgresql" ]]; then
  schema=public
else
  validate_scalar "database name" "$db_name"
  catalog=$db_name
fi

set +e
(
  cd -- "$project_root"
  unset DOMA_SYNC_JDBC_URL DOMA_SYNC_JDBC_USER DOMA_SYNC_JDBC_PASSWORD
  export DOMA_CODEGEN_DB_URL="$db_url" DOMA_CODEGEN_DB_USER="$db_user" DOMA_CODEGEN_DB_PASSWORD="$db_password"
  export DOMA_CODEGEN_DB_KIND="$database" DOMA_CODEGEN_DB_SCHEMA="$schema" DOMA_CODEGEN_DB_CATALOG="$catalog"
  export DOMA_CODEGEN_TABLE_PATTERN='.*' DOMA_CODEGEN_SCHEMA_SNAPSHOT="$snapshot_file" DOMA_CODEGEN_PROJECT_ROOT="$project_root"
  run_redacted java --class-path "$codegen_classpath" "$script_dir/schema-snapshot.java"
)
snapshot_status=$?
set -e
scan_or_remove_unsafe_outputs
if [[ $snapshot_status -ne 0 ]]; then
  printf 'schema snapshot failed\n' >&2
  exit "$snapshot_status"
fi
[[ -f "$snapshot_file" && ! -L "$snapshot_file" ]] || die "schema snapshot output is missing or unsafe" 70

validate_output_paths || die "output path must remain inside the project build directory" 65
set +e
(
  cd -- "$project_root"
  unset DOMA_CODEGEN_DB_URL DOMA_CODEGEN_DB_USER DOMA_CODEGEN_DB_PASSWORD
  export DOMA_SYNC_JDBC_URL="$db_url" DOMA_SYNC_JDBC_USER="$db_user" DOMA_SYNC_JDBC_PASSWORD="$db_password"
  run_redacted "${gradle_command[@]}" --no-daemon domaCodeGenDomaSyncEntity
)
entity_status=$?
set -e
scan_or_remove_unsafe_outputs
if [[ $entity_status -ne 0 ]]; then
  printf 'Doma entity generation failed\n' >&2
  exit "$entity_status"
fi

printf 'Generated candidate entities under build/doma-codegen/generated.\n'
