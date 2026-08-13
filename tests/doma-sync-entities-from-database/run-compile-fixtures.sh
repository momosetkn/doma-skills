#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

readonly GRADLE_VERSION="9.4.1"
readonly GRADLE_SHA256="2ab2958f2a1e51120c326cad6f385153bb11ee93b3c216c5fccebfdfbb7ec6cb"
readonly TEST_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly REPO_ROOT="$(cd -- "$TEST_DIR/../.." && pwd -P)"
readonly CONFIGURATOR="$REPO_ROOT/skills/doma-sync-entities-from-database/scripts/configure-codegen.py"
readonly MERGER="$REPO_ROOT/skills/doma-sync-entities-from-database/scripts/compare-and-merge-entities.py"
readonly FIXTURE_ROOT="$TEST_DIR/fixtures"

work_dir=""

cleanup() {
  if [[ -n "$work_dir" && -d "$work_dir" ]]; then
    rm -rf -- "$work_dir"
  fi
}
trap cleanup EXIT HUP INT TERM

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

path_is_outside_repo() {
  local candidate
  candidate=$(cd -- "$1" 2>/dev/null && pwd -P) || return 1
  [[ "$candidate" != "$REPO_ROOT" && "$candidate" != "$REPO_ROOT/"* ]]
}

select_temp_base() {
  local candidate canonical
  for candidate in "${TMPDIR:-}" /tmp /var/tmp; do
    [[ -n "$candidate" && -d "$candidate" && -w "$candidate" ]] || continue
    canonical=$(cd -- "$candidate" && pwd -P) || continue
    if path_is_outside_repo "$canonical"; then
      printf '%s\n' "$canonical"
      return
    fi
  done
  fail "no writable temporary directory exists outside the repository"
}

create_work_dir() {
  local base created
  base=$(select_temp_base)
  path_is_outside_repo "$base" || fail "temporary base resolved inside the repository"
  path_is_outside_repo "$REPO_ROOT" \
    && fail "temporary containment preflight accepted the repository root"
  path_is_outside_repo "$TEST_DIR" \
    && fail "temporary containment preflight accepted a repository child"
  created=$(mktemp -d --tmpdir="$base" 'doma-sync-compile-fixtures.XXXXXX')
  work_dir=$(cd -- "$created" && pwd -P)
  path_is_outside_repo "$work_dir" || fail "temporary work directory resolved inside the repository"
}

require_file() {
  [[ -f "$1" ]] || fail "required fixture file is missing: ${1#$REPO_ROOT/}"
}

run_plan_command() {
  local expected_changes=$1
  shift
  local status
  set +e
  "$@"
  status=$?
  set -e
  if [[ "$expected_changes" == "yes" ]]; then
    [[ $status -eq 2 ]] || fail "configuration plan did not report changes (exit $status)"
  else
    [[ $status -eq 0 ]] || fail "configuration plan was not idempotent (exit $status)"
  fi
}

run_merge_command() {
  local status
  set +e
  "$@"
  status=$?
  set -e
  [[ $status -eq 0 || $status -eq 2 || $status -eq 3 ]] \
    || fail "entity merge command failed (exit $status)"
}

resolve_gradle() {
  if [[ -n "${GRADLE_CMD:-}" ]]; then
    [[ -x "$GRADLE_CMD" ]] || fail "GRADLE_CMD is not an executable file"
    gradle_command=("$GRADLE_CMD")
    return
  fi

  local archive="$work_dir/gradle-${GRADLE_VERSION}-bin.zip"
  local distribution="$work_dir/gradle-${GRADLE_VERSION}"
  local url="https://services.gradle.org/distributions/gradle-${GRADLE_VERSION}-bin.zip"
  if command -v curl >/dev/null 2>&1; then
    curl --fail --location --silent --show-error --output "$archive" "$url"
  elif command -v wget >/dev/null 2>&1; then
    wget --quiet --output-document="$archive" "$url"
  else
    fail "curl or wget is required to download Gradle"
  fi
  printf '%s  %s\n' "$GRADLE_SHA256" "$archive" | sha256sum --check --status \
    || fail "Gradle distribution checksum mismatch"
  unzip -q "$archive" -d "$work_dir"
  [[ -x "$distribution/bin/gradle" ]] || fail "Gradle distribution extraction failed"
  gradle_command=("$distribution/bin/gradle")
}

assert_handwritten_slices() {
  local project=$1
  python3 - "$project" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
contract = json.loads((root / "fixture/handwritten-slices.json").read_text(encoding="utf-8"))
for item in contract:
    source = (root / item["path"]).read_bytes()
    start = item["start"].encode()
    end = item["end"].encode()
    first = source.find(start)
    last = source.find(end, first + len(start))
    if first < 0 or last < 0:
        raise SystemExit(f"handwritten slice markers missing: {item['path']}")
    finish = last + len(end)
    if source[finish:finish + 2] == b"\r\n":
        finish += 2
    elif source[finish:finish + 1] == b"\n":
        finish += 1
    actual = source[first:finish]
    expected = (root / item["expected"]).read_bytes()
    if actual != expected:
        raise SystemExit(f"handwritten slice changed: {item['path']}")
PY
}

assert_generated_outside_sources() {
  local project=$1
  python3 - "$project" <<'PY'
import pathlib
import sys

root = pathlib.Path(sys.argv[1]).resolve()
generated = (root / "build/doma-codegen/generated").resolve()
for relative in ("src/main/java", "src/main/kotlin"):
    source = (root / relative).resolve()
    if generated == source or source in generated.parents or generated in source.parents:
        raise SystemExit("generated candidates overlap a production source root")
PY
}

assert_plan_findings() {
  local project=$1
  python3 - "$project" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
plan = json.loads((root / "build/doma-codegen/merge-plan.json").read_text())
expected = json.loads((root / "fixture/expected-findings.json").read_text())

def normalize(item):
    return {
        "path": item["path"],
        "table": item["table"],
        "column": item.get("column"),
        "status": item["status"],
        "kind": item["kind"],
        "edit_count": len(item.get("edits", ())),
    }

actual = [normalize(item) for item in plan["findings"]]
if not all(isinstance(item, dict) for item in expected):
    raise SystemExit("expected finding contract must contain normalized objects; actual="
                     + json.dumps(actual, sort_keys=True))
key = lambda item: json.dumps(item, sort_keys=True, separators=(",", ":"))
if sorted(actual, key=key) != sorted(expected, key=key):
    raise SystemExit("merge finding contract mismatch: expected="
                     + json.dumps(expected, sort_keys=True)
                     + " actual=" + json.dumps(actual, sort_keys=True))
PY
}

configure_fixture() {
  local project=$1 language=$2 database=$3 package=$4 metamodel=$5
  local database_args=() driver
  if [[ "$database" == "postgresql" ]]; then
    database_args=(--schema public)
    driver="org.postgresql:postgresql:42.7.10"
  else
    database_args=(--catalog fixture_catalog)
    driver="com.mysql:mysql-connector-j:26.7.0"
  fi
  local command=(
    python3 "$CONFIGURATOR" plan --project-root "$project"
    --language "$language" --database "$database" --entity-package "$package"
    "${database_args[@]}" --table-pattern '.*' --codegen-version 3.2.2
    --driver-coordinate "$driver" --metamodel "$metamodel"
    --output-plan build/doma-codegen/configure-plan.json
  )
  run_plan_command yes "${command[@]}"
  python3 "$CONFIGURATOR" apply --project-root "$project" \
    --language "$language" --database "$database" --entity-package "$package" \
    "${database_args[@]}" --table-pattern '.*' --codegen-version 3.2.2 \
    --driver-coordinate "$driver" --metamodel "$metamodel" \
    --plan build/doma-codegen/configure-plan.json
  run_plan_command no "${command[@]}"
}

run_fixture() {
  local name=$1 language=$2 database=$3 dsl=$4 metamodel=$5
  local fixture="$FIXTURE_ROOT/$name"
  [[ -d "$fixture" ]] || fail "required fixture directory is missing: ${fixture#$REPO_ROOT/}"
  require_file "$fixture/fixture/schema-snapshot.json"
  require_file "$fixture/fixture/handwritten-slices.json"
  require_file "$fixture/fixture/expected-findings.json"
  require_file "$fixture/settings.gradle$dsl"
  require_file "$fixture/build.gradle$dsl"

  local project="$work_dir/$name"
  cp -R "$fixture" "$project"
  mkdir -p "$project/build/doma-codegen"
  cp "$project/fixture/schema-snapshot.json" "$project/build/doma-codegen/schema-snapshot.json"
  cp -R "$project/fixture/generated" "$project/build/doma-codegen/generated"

  git -C "$project" init -q
  git -C "$project" config user.name "Doma Fixture"
  git -C "$project" config user.email "fixture@example.invalid"
  git -C "$project" add -- .
  git -C "$project" commit -qm "fixture baseline"

  configure_fixture "$project" "$language" "$database" "example.entity" "$metamodel"

  git -C "$project" add -- .
  git -C "$project" commit -qm "configured fixture"

  local source_root="src/main/$language"
  run_merge_command python3 "$MERGER" plan --project-root "$project" \
    --schema-snapshot build/doma-codegen/schema-snapshot.json \
    --generated-dir build/doma-codegen/generated --existing-root "$source_root" \
    --language "$language" --output-plan build/doma-codegen/merge-plan.json \
    --output-diff build/doma-codegen/merge.diff
  [[ -s "$project/build/doma-codegen/merge.diff" ]] \
    || fail "$name produced no initial merge diff"
  assert_plan_findings "$project"
  run_merge_command python3 "$MERGER" apply --project-root "$project" \
    --plan "$project/build/doma-codegen/merge-plan.json"

  env -u DOMA_SYNC_JDBC_URL -u DOMA_SYNC_JDBC_USER -u DOMA_SYNC_JDBC_PASSWORD \
    "${gradle_command[@]}" --no-daemon --console=plain -p "$project" clean build
  find "$project/build" -type f -name '*DaoImpl.java' -print -quit | grep -q . \
    || fail "$name did not produce a Doma-generated DAO implementation"

  mkdir -p "$project/build/doma-codegen"
  cp "$project/fixture/schema-snapshot.json" "$project/build/doma-codegen/schema-snapshot.json"
  cp -R "$project/fixture/generated" "$project/build/doma-codegen/generated"
  run_merge_command python3 "$MERGER" plan --project-root "$project" \
    --schema-snapshot build/doma-codegen/schema-snapshot.json \
    --generated-dir build/doma-codegen/generated --existing-root "$source_root" \
    --language "$language" --output-plan build/doma-codegen/merge-plan.json \
    --output-diff build/doma-codegen/merge.diff
  [[ ! -s "$project/build/doma-codegen/merge.diff" ]] \
    || fail "$name produced a non-empty second merge diff"
  assert_handwritten_slices "$project"
  assert_generated_outside_sources "$project"

  env -u DOMA_SYNC_JDBC_URL -u DOMA_SYNC_JDBC_USER -u DOMA_SYNC_JDBC_PASSWORD \
    "${gradle_command[@]}" --no-daemon --console=plain -p "$project" clean build
  printf 'PASS: %s\n' "$name"
}

create_work_dir
if [[ "${DOMA_SYNC_TEMP_PREFLIGHT_ONLY:-0}" == "1" ]]; then
  printf 'PASS: temporary work directory outside repository\n'
  exit 0
fi
resolve_gradle

run_fixture java-kotlin-dsl-postgresql java postgresql .kts true
run_fixture kotlin-kotlin-dsl-postgresql kotlin postgresql .kts true
run_fixture java-groovy-dsl-mysql java mysql '' false
run_fixture kotlin-groovy-dsl-mysql kotlin mysql '' true
