#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

readonly TEST_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly REPO_ROOT="$(cd -- "$TEST_DIR/../.." && pwd -P)"
readonly SKILL_NAME="doma-sync-entities-from-database"
readonly SOURCE_SKILL="$REPO_ROOT/skills/$SKILL_NAME"

work_dir=""
temp_base=""

cleanup() {
  if [[ -n "$work_dir" && -n "$temp_base" && -d "$work_dir" &&
        "$work_dir" == "$temp_base/doma-sync-install."* &&
        "$work_dir" != "$REPO_ROOT" && "$work_dir" != "$SOURCE_SKILL" ]]; then
    rm -rf -- "$work_dir"
  fi
}
trap cleanup EXIT HUP INT TERM

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

for candidate in /tmp /var/tmp; do
  [[ -d "$candidate" && -w "$candidate" ]] || continue
  candidate=$(cd -- "$candidate" && pwd -P)
  if [[ "$candidate" != "$REPO_ROOT" && "$candidate" != "$REPO_ROOT/"* &&
        "$REPO_ROOT" != "$candidate"/* ]]; then
    temp_base=$candidate
    break
  fi
done
[[ -n "$temp_base" ]] || fail "no safe external temporary base is available"
work_dir=$(mktemp -d "$temp_base/doma-sync-install.XXXXXX")
work_dir=$(cd -- "$work_dir" && pwd -P)
[[ "$work_dir" == "$temp_base/doma-sync-install."* && "$work_dir" != "$REPO_ROOT"* ]] \
  || fail "temporary directory is not safely outside the repository"

python3 - "$SOURCE_SKILL" <<'PY'
import pathlib
import re
import sys

import yaml

root = pathlib.Path(sys.argv[1])
required = {
    "SKILL.md",
    "agents/openai.yaml",
    "references/supported-projects.md",
    "references/database-connections.md",
    "references/codegen-configuration.md",
    "references/entity-merge-rules.md",
    "references/java-entity-merge.md",
    "references/kotlin-entity-merge.md",
    "references/aws-security.md",
    "references/troubleshooting.md",
    "scripts/configure-codegen.py",
    "scripts/generate-entities.sh",
    "scripts/schema-snapshot.java",
    "scripts/compare-and-merge-entities.py",
    "scripts/entity_sync/__init__.py",
    "scripts/entity_sync/applier.py",
    "scripts/entity_sync/java_parser.py",
    "scripts/entity_sync/kotlin_parser.py",
    "scripts/entity_sync/lexer.py",
    "scripts/entity_sync/model.py",
    "scripts/entity_sync/planner.py",
}
missing = sorted(path for path in required if not (root / path).is_file())
if missing:
    raise SystemExit("missing required skill files: " + ", ".join(missing))

skill_text = (root / "SKILL.md").read_text(encoding="utf-8")
frontmatter_match = re.match(r"\A---\n(.*?)\n---\n", skill_text, re.DOTALL)
if frontmatter_match is None:
    raise SystemExit("SKILL.md frontmatter is missing")
frontmatter = yaml.safe_load(frontmatter_match.group(1))
if set(frontmatter) != {"name", "description"}:
    raise SystemExit("SKILL.md frontmatter must contain only name and description")
if frontmatter["name"] != root.name:
    raise SystemExit("directory and frontmatter names differ")
if not str(frontmatter["description"]).startswith("Use when "):
    raise SystemExit("description must start with 'Use when '")

metadata = yaml.safe_load((root / "agents/openai.yaml").read_text(encoding="utf-8"))
expected_interface = {
    "display_name": "Sync Doma Entities from Database",
    "short_description": "Generate and safely merge Java or Kotlin Doma entities",
    "default_prompt": (
        "Use $doma-sync-entities-from-database to generate Doma entity candidates "
        "from this database and apply only structurally safe changes."
    ),
}
if metadata != {"interface": expected_interface}:
    raise SystemExit("agents/openai.yaml does not match the published interface")

links = re.findall(r"\[[^]]+\]\(([^)]+)\)", skill_text)
local_links = {link.split("#", 1)[0] for link in links if not re.match(r"[a-z]+://", link)}
required_links = required - {"SKILL.md", "agents/openai.yaml", "scripts/entity_sync/__init__.py",
                             "scripts/entity_sync/applier.py", "scripts/entity_sync/java_parser.py",
                             "scripts/entity_sync/kotlin_parser.py", "scripts/entity_sync/lexer.py",
                             "scripts/entity_sync/model.py", "scripts/entity_sync/planner.py"}
unlinked = sorted(required_links - local_links)
if unlinked:
    raise SystemExit("SKILL.md does not link required resources: " + ", ".join(unlinked))
for link in local_links:
    if not (root / link).is_file():
        raise SystemExit(f"broken local link in SKILL.md: {link}")
PY

[[ -x "$SOURCE_SKILL/scripts/generate-entities.sh" ]] \
  || fail "generate-entities.sh is not executable"
[[ -x "$SOURCE_SKILL/scripts/compare-and-merge-entities.py" ]] \
  || fail "compare-and-merge-entities.py is not executable"

(
  cd -- "$work_dir"
  npx skills add "$REPO_ROOT" --skill "$SKILL_NAME" --agent codex --copy -y
)

installed_skill=$(find "$work_dir" -path "*/$SKILL_NAME/SKILL.md" -print -quit)
[[ -n "$installed_skill" ]] || fail "copied installation was not found"
installed_dir=$(cd -- "$(dirname -- "$installed_skill")" && pwd -P)
[[ "$installed_dir" == "$work_dir/"* ]] || fail "installed skill resolved outside the disposable directory"

python3 - "$installed_dir" <<'PY'
import pathlib
import re
import sys

root = pathlib.Path(sys.argv[1])
for markdown in root.rglob("*.md"):
    text = markdown.read_text(encoding="utf-8")
    for link in re.findall(r"\[[^]]+\]\(([^)]+)\)", text):
        target = link.split("#", 1)[0]
        if not target or re.match(r"[a-z]+://", target):
            continue
        if not (markdown.parent / target).resolve().is_file():
            raise SystemExit(f"broken installed link: {markdown.relative_to(root)} -> {target}")
PY

[[ -x "$installed_dir/scripts/generate-entities.sh" ]] \
  || fail "copied generate-entities.sh lost its executable mode"
[[ -x "$installed_dir/scripts/compare-and-merge-entities.py" ]] \
  || fail "copied compare-and-merge-entities.py lost its executable mode"

bash -n "$installed_dir/scripts/generate-entities.sh"
PYTHONPYCACHEPREFIX="$work_dir/pycache" python3 -m py_compile \
  "$installed_dir/scripts/configure-codegen.py" \
  "$installed_dir/scripts/compare-and-merge-entities.py" \
  "$installed_dir"/scripts/entity_sync/*.py
mkdir -p "$work_dir/classes"
javac -Xlint:all -d "$work_dir/classes" "$installed_dir/scripts/schema-snapshot.java"

if rg -n \
  'prisma-skills\.md|doma-project-bundle-[1-4]\.md|tests/doma-sync-entities-from-database|skills/doma-[^/ )]+/|/home/[^/]+/|\.\./doma-' \
  "$installed_dir"; then
  fail "installed skill depends on a repository-only input, fixture, other skill path, or authoring path"
fi

if find "$installed_dir" -type f \( -name '*.pyc' -o -name '*.class' \) -print -quit | grep -q .; then
  fail "installed skill contains generated syntax-check artifacts"
fi

printf 'PASS: copied %s installation is self-contained\n' "$SKILL_NAME"
