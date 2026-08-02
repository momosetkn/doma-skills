# Doma Kotlin Project Setup Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an installable `doma-setup-kotlin-project` skill that configures a plain Gradle Kotlin DSL project with KAPT and verifies generation of a minimal Doma DAO implementation.

**Architecture:** Mirror the existing Java setup skill's discoverable layout while replacing its build and example guidance with a Kotlin/JVM and KAPT-specific workflow. Keep decisions and recovery order in `SKILL.md`; place exact Gradle configuration, a complete minimal inline-SQL DAO, and detailed diagnostics in three direct references. Update the root catalog and validate both skill behavior and copied installation independence.

**Tech Stack:** Agent Skills Markdown/YAML, Gradle Kotlin DSL, Kotlin/JVM, KAPT, Doma `3.14.1-SNAPSHOT` source baseline, released Doma `3.14.0` example coordinates, `npx skills`, shell validation.

## Global Constraints

- Target the bundled Doma `3.14.1-SNAPSHOT` source as a research baseline, not as the latest stable release or a published coordinate.
- Scope setup to plain Kotlin/JVM projects using Gradle Kotlin DSL and KAPT.
- Use `doma-kotlin` on `implementation` and the same released version of `doma-processor` on `kapt`.
- Use an inline `@Sql` SELECT in the minimal example; do not add external SQL resources or `doma.resources.dir` guidance.
- Do not claim that KSP is supported or unsupported; state only that the baseline establishes KAPT.
- Exclude Maven, Java-only setup, Spring Boot, Quarkus, entity modeling, Kotlin Criteria API, transactions, migrations, and dialect guidance.
- Keep root bundle files and `prisma-skills.md` read-only, untracked, and absent from installed skill content.
- Do not commit implementation changes. At handoff, stage only `README.md` and `skills/doma-setup-kotlin-project/`.

---

## File Map

- Create `skills/doma-setup-kotlin-project/SKILL.md`: trigger boundary, setup sequence, recovery sequence, and reference routing.
- Create `skills/doma-setup-kotlin-project/agents/openai.yaml`: Codex display metadata derived from the finished skill.
- Create `skills/doma-setup-kotlin-project/references/build-configuration.md`: Gradle Kotlin DSL, Kotlin/JVM and KAPT plugins, aligned Doma dependencies, build and generated-source inspection.
- Create `skills/doma-setup-kotlin-project/references/minimal-kotlin-project.md`: complete minimal source layout and inline-SQL Kotlin DAO.
- Create `skills/doma-setup-kotlin-project/references/troubleshooting.md`: symptom-to-diagnosis-to-recovery table for KAPT and Doma processor failures.
- Modify `README.md`: add the skill's triggers, scope, exclusions, installation command, and invocation examples.
- Do not add committed evaluation logs, copied installations, lockfiles, or root-bundle-derived artifacts.

### Task 1: Establish RED Behavior and Evidence Notes

**Files:**
- Read: `docs/superpowers/specs/2026-08-02-doma-setup-kotlin-project-design.md`
- Read: `skills/doma-setup-project/SKILL.md`
- Read: `skills/doma-setup-project/references/build-configuration.md`
- Read: `doma-project-bundle-1.md` narrow ranges for `docs/kotlin-support.md`, `docs/annotation-processing.md`, `docs/dao.md`, and public annotations
- Read: `doma-project-bundle-3.md` narrow ranges for processor tests and `gradle/libs.versions.toml`
- Read: `doma-project-bundle-4.md` narrow ranges for `integration-test-kotlin/build.gradle.kts`
- Temporary evaluation output: a directory created by `mktemp -d`, never a repository path

**Interfaces:**
- Consumes: the approved design and repository-wide `AGENTS.md` evidence rules.
- Produces: concrete baseline failures and source notes used to author only evidence-backed guidance.

- [ ] **Step 1: Confirm the working tree boundary**

Run:

```bash
git status --short
git diff --cached --name-only
```

Expected: root research inputs may be untracked; no unrelated path is staged.

- [ ] **Step 2: Run the three positive scenarios without the new skill**

Dispatch fresh subagents without exposing the intended solution or future skill content. Use these exact prompts:

```text
In a plain Kotlin/JVM Gradle project using build.gradle.kts, add Doma and annotation processing, then explain how you would verify that a DAO implementation was generated.
```

```text
Create the smallest Kotlin Doma DAO setup that proves code generation works without connecting to a database. Include the required Gradle Kotlin DSL configuration.
```

```text
A Kotlin Doma project compiles Kotlin sources but no *DaoImpl is found. Diagnose the initial setup and give an ordered recovery procedure.
```

Record raw responses in the temporary directory. Expected RED evidence: at least one response omits or misplaces KAPT, uses `doma-core` without explaining `doma-kotlin`, assumes a Java generated-source path, expands into external SQL unnecessarily, or gives an unordered diagnostic list.

- [ ] **Step 3: Run the negative boundary scenario without the new skill**

Use this exact fresh-session prompt:

```text
In an already configured Kotlin Doma project, write a complex KQueryDsl join with nested conditions.
```

Record whether an agent incorrectly treats this as initial setup. The finished skill must not claim this Criteria API task.

- [ ] **Step 4: Gather narrow source notes**

Locate headings first, then read only through the next heading:

```bash
rg -n '^## docs/(kotlin-support|annotation-processing|dao)\.md$' doma-project-bundle-1.md
rg -n '^## integration-test-kotlin/build\.gradle\.kts$' doma-project-bundle-4.md
rg -n '^## gradle/libs\.versions\.toml$' doma-project-bundle-3.md
rg -n 'DOMA4005|DOMA4014|DOMA4017|dao\.suffix' doma-project-bundle-1.md doma-project-bundle-2.md doma-project-bundle-3.md
```

For each rule, record the bundled path, symbol or section, and what it proves. Required evidence includes:

- `docs/kotlin-support.md`: Kotlin uses `doma-kotlin` and KAPT with `doma-processor`.
- `integration-test-kotlin/build.gradle.kts`: the project applies Kotlin JVM and KAPT and uses `kapt(project(":doma-processor"))` with `implementation(project(":doma-kotlin"))`.
- `docs/annotation-processing.md`: generated DAO suffix defaults to `Impl` and validation defaults remain enabled.
- public DAO/query annotations and processor tests: top-level interface and query-annotation restrictions plus exact diagnostics used in troubleshooting.

- [ ] **Step 5: Review RED findings before authoring**

Classify each failure as retrieval, application, or boundary failure. Author only guidance that closes observed failures or is required by the approved design; do not add speculative KSP, framework, external SQL, or Criteria API content.

### Task 2: Initialize and Author the Minimal Skill

**Files:**
- Create: `skills/doma-setup-kotlin-project/SKILL.md`
- Create: `skills/doma-setup-kotlin-project/agents/openai.yaml`
- Create: `skills/doma-setup-kotlin-project/references/build-configuration.md`
- Create: `skills/doma-setup-kotlin-project/references/minimal-kotlin-project.md`
- Create: `skills/doma-setup-kotlin-project/references/troubleshooting.md`

**Interfaces:**
- Consumes: Task 1 baseline failures and source notes.
- Produces: a self-contained Agent Skill whose direct references cover configuration, a minimal example, and diagnostics.

- [ ] **Step 1: Load the authoring contracts**

Read these completely before creating files:

```text
/home/momose/.codex/skills/.system/skill-creator/SKILL.md
/home/momose/.codex/skills/.system/skill-creator/references/openai_yaml.md
/home/momose/.codex/plugins/cache/openai-curated-remote/superpowers/6.2.0/skills/writing-skills/SKILL.md
/home/momose/.codex/plugins/cache/openai-curated-remote/superpowers/6.2.0/skills/test-driven-development/SKILL.md
```

- [ ] **Step 2: Initialize the skill with deterministic UI metadata**

Run the required initializer once from the repository root:

```bash
python /home/momose/.codex/skills/.system/skill-creator/scripts/init_skill.py \
  doma-setup-kotlin-project \
  --path skills \
  --resources references \
  --interface 'display_name=Set Up a Kotlin Doma Project' \
  --interface 'short_description=Configure Doma with KAPT in Kotlin Gradle projects' \
  --interface 'default_prompt=Use $doma-setup-kotlin-project to add Doma and KAPT to this plain Kotlin Gradle project and verify DAO generation.'
```

Expected: the directory, `SKILL.md`, `agents/openai.yaml`, and empty `references/` directory exist. Remove no user file and add no example placeholder resource.

- [ ] **Step 3: Write `SKILL.md` as the decision workflow**

Use exactly this frontmatter boundary:

```yaml
---
name: doma-setup-kotlin-project
description: Use when adding Doma and KAPT to a plain Kotlin/JVM Gradle project, creating the first Kotlin DAO, or diagnosing why initial KAPT processing produces no generated DAO implementation.
---
```

The body must:

1. inspect the existing Gradle Kotlin DSL project and preserve its Kotlin/Gradle versions;
2. require JDK 17 or later for the Doma 3.14 baseline;
3. place `doma-kotlin` on `implementation` and aligned `doma-processor` on `kapt`;
4. create a top-level minimal DAO using inline `@Sql` and `@Select`;
5. run a clean build and recursively search below `build/generated` for `*DaoImpl.java`;
6. finish setup answers with an ordered failure-recovery block;
7. route exact configuration, example, and diagnostics to the three direct references;
8. state the exclusions from Global Constraints without claiming a future skill already exists.

- [ ] **Step 4: Write `references/build-configuration.md`**

Include one complete `build.gradle.kts` example shaped as follows:

```kotlin
plugins {
    kotlin("jvm") version "2.3.21"
    kotlin("kapt") version "2.3.21"
}

java {
    toolchain {
        languageVersion = JavaLanguageVersion.of(17)
    }
}

repositories {
    mavenCentral()
}

val domaVersion = providers.gradleProperty("domaVersion").getOrElse("3.14.0")

dependencies {
    implementation("org.seasar.doma:doma-kotlin:$domaVersion")
    kapt("org.seasar.doma:doma-processor:$domaVersion")
}
```

Explain that `2.3.21` is the Kotlin version exercised by the source snapshot and should not replace a compatible version already selected by a project. Explain that `3.14.0` is the released example version documented by the baseline and may be replaced with the project's one selected release while keeping both Doma artifacts aligned.

Use these verification commands:

```bash
./gradlew -PdomaVersion=3.14.0 clean build
find build/generated -type f -name '*DaoImpl.java' -print
```

Do not promise a deeper KAPT output directory as a Doma API contract.

- [ ] **Step 5: Write `references/minimal-kotlin-project.md`**

Use this complete minimal source:

```kotlin
package example.dao

import org.seasar.doma.Dao
import org.seasar.doma.Select
import org.seasar.doma.Sql

@Dao
interface HealthCheckDao {
    @Sql("select 1")
    @Select
    fun selectOne(): Int
}
```

Place it at `src/main/kotlin/example/dao/HealthCheckDao.kt`. Explain that compilation should generate `example.dao.HealthCheckDaoImpl`, that no database connection is needed to prove generation, and that executing `selectOne()` requires a runtime `Config`, a `DataSource`, an appropriate dialect, and a reachable database. Do not add an entity, external SQL file, handwritten generated class, or runtime bootstrap.

- [ ] **Step 6: Write `references/troubleshooting.md`**

Create a symptom/inspect/recovery table covering at least:

- unresolved Doma annotations: inspect `doma-kotlin` and repository/version selection;
- `kapt` configuration unavailable: apply `kotlin("kapt")` with the Kotlin plugin version;
- Kotlin compilation succeeds but KAPT does not process Doma: move `doma-processor` from `implementation` or `annotationProcessor` to `kapt`;
- no `*DaoImpl.java`: run a clean build, inspect KAPT diagnostics, and search `build/generated` recursively;
- `DOMA4005`: add the query annotation, `@Select` in the minimal example;
- `DOMA4014`: annotate an interface rather than a class;
- `DOMA4017`: move a nested DAO to a top-level interface;
- runtime version validation failure: align the runtime Doma artifact and processor version, then regenerate;
- KSP request: explain that this baseline verifies KAPT only and requires separate current official research before changing processors.

- [ ] **Step 7: Validate the new skill structure before forward testing**

Run:

```bash
python /home/momose/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/doma-setup-kotlin-project
test "$(find skills/doma-setup-kotlin-project -type f | sort | wc -l)" -eq 5
! rg -n 'TODO|TBD|<skill-name>|prisma-skills\.md|doma-project-bundle-[1-4]\.md' skills/doma-setup-kotlin-project
```

Expected: validation succeeds, exactly five files exist, and the forbidden-content scan returns no matches.

### Task 3: Update Discovery and Prove GREEN Behavior

**Files:**
- Modify: `README.md`
- Read: `skills/doma-setup-kotlin-project/SKILL.md`
- Read: `skills/doma-setup-kotlin-project/references/*.md`
- Temporary evaluation output: a fresh `mktemp -d` directory outside the repository

**Interfaces:**
- Consumes: the finished skill from Task 2 and the RED scenarios from Task 1.
- Produces: discoverable repository documentation and fresh-session evidence that the skill corrects the baseline failures without claiming the negative boundary.

- [ ] **Step 1: Add the README catalog entry**

Add `doma-setup-kotlin-project` under `Available Skills` with:

- triggers for Kotlin/JVM Gradle Kotlin DSL setup, KAPT, first Kotlin DAO, and missing generated implementation;
- scope covering JDK 17+, aligned `doma-kotlin`/`doma-processor`, inline SQL, clean build, recursive generated-source inspection, and setup diagnostics;
- exclusions matching Global Constraints;
- `npx skills add momosetkn/doma-skills --skill doma-setup-kotlin-project`;
- one invocation example using `$doma-setup-kotlin-project`.

Preserve the Java skill entry and the Doma baseline statement.

- [ ] **Step 2: Run the three positive scenarios with the skill**

Dispatch fresh subagents with only the skill path and the exact Task 1 prompt. Each response must:

- select `doma-kotlin` plus KAPT-scoped `doma-processor`;
- preserve an existing project Kotlin version instead of replacing it blindly;
- give a minimal inline-SQL top-level DAO;
- verify via a clean Gradle build and recursive `build/generated` search;
- distinguish generation from database execution;
- give an ordered recovery sequence when the DAO implementation is missing.

Save raw responses only in the temporary directory.

- [ ] **Step 3: Run the negative scenario with the skill catalog available**

Dispatch the exact Task 1 KQueryDsl prompt in a fresh session. Expected: the setup skill is not selected as authority for designing the query, and the response does not stretch the setup workflow into Criteria API guidance.

- [ ] **Step 4: Refactor only observed gaps**

If forward tests expose omissions, ambiguous routing, or unsupported claims, patch the smallest applicable section in `SKILL.md` or one reference. Re-run only the affected positive prompt plus the negative boundary until behavior is stable. Do not add discipline-style rationalization tables or red-flags sections unless the observed failure is a deliberate rule violation rather than a reference or application gap.

### Task 4: Compile and Validate the Installable Artifact

**Files:**
- Read: `skills/doma-setup-kotlin-project/references/build-configuration.md`
- Read: `skills/doma-setup-kotlin-project/references/minimal-kotlin-project.md`
- Temporary fixture: a fresh directory from `mktemp -d`
- Temporary copy installation: another fresh directory from `mktemp -d`

**Interfaces:**
- Consumes: the exact published build and DAO snippets.
- Produces: compile evidence, CLI discovery evidence, and proof that the installed skill is self-contained.

- [ ] **Step 1: Create a disposable Gradle Kotlin fixture from the published snippets**

Create a temporary fixture path and a separate Gradle distribution path:

```bash
fixture="$(mktemp -d)"
gradle_dist="$(mktemp -d)"
mkdir -p "$fixture/src/main/kotlin/example/dao"
curl --fail --location \
  https://services.gradle.org/distributions/gradle-9.5.1-bin.zip \
  --output "$gradle_dist/gradle-9.5.1-bin.zip"
unzip -q "$gradle_dist/gradle-9.5.1-bin.zip" -d "$gradle_dist"
```

Use `apply_patch` to create `settings.gradle.kts`, `build.gradle.kts`, and
`src/main/kotlin/example/dao/HealthCheckDao.kt` below the resolved fixture path.
Set `rootProject.name = "doma-kotlin-kapt-smoke"`; copy the Gradle and DAO
snippets from the finished references exactly. Generate a wrapper with the
Gradle version used by the source snapshot:

```bash
"$gradle_dist/gradle-9.5.1/bin/gradle" --project-dir "$fixture" \
  wrapper --gradle-version 9.5.1
```

Do not place fixture or Gradle distribution files in this repository.

- [ ] **Step 2: Run the Kotlin/KAPT compile verification**

Run in the fixture:

```bash
./gradlew -PdomaVersion=3.14.0 clean build
find build/generated -type f -name 'HealthCheckDaoImpl.java' -print
```

Expected: the Gradle build passes and exactly one generated `HealthCheckDaoImpl.java` is found. If dependency resolution or the local toolchain prevents execution, retain the exact failure output and report this separately; do not weaken content assertions or claim compilation passed.

- [ ] **Step 3: Run repository structural checks**

Run:

```bash
python /home/momose/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/doma-setup-kotlin-project
npx skills add . --list
```

Expected: both public skills are listed, including `doma-setup-kotlin-project` with its final description.

- [ ] **Step 4: Copy-install and inspect the skill**

Run:

```bash
repo="$(pwd)"
tmp="$(mktemp -d)"
(cd "$tmp" && npx skills add "$repo" --skill doma-setup-kotlin-project --agent codex --copy -y)
installed_skill="$(find "$tmp" -path '*/doma-setup-kotlin-project/SKILL.md' -print -quit)"
test -n "$installed_skill"
installed_dir="$(dirname "$installed_skill")"
test "$(find "$installed_dir" -type f | wc -l)" -eq 5
! rg -n 'prisma-skills\.md|doma-project-bundle-[1-4]\.md' "$installed_dir"
```

Expected: a copied installation exists, contains the five intended files, and has no dependency on root research inputs.

- [ ] **Step 5: Run final content and diff checks**

Run:

```bash
! rg -n 'TODO|TBD|<skill-name>|3\.14\.1-SNAPSHOT.*(implementation|kapt)' README.md skills/doma-setup-kotlin-project
git diff --check -- README.md skills/doma-setup-kotlin-project
git diff -- README.md skills/doma-setup-kotlin-project
```

Trace every exact API, default, restriction, diagnostic, and version statement in the diff back to Task 1 source notes.

### Task 5: Stage Only the Requested Deliverable

**Files:**
- Stage: `README.md`
- Stage: `skills/doma-setup-kotlin-project/SKILL.md`
- Stage: `skills/doma-setup-kotlin-project/agents/openai.yaml`
- Stage: `skills/doma-setup-kotlin-project/references/build-configuration.md`
- Stage: `skills/doma-setup-kotlin-project/references/minimal-kotlin-project.md`
- Stage: `skills/doma-setup-kotlin-project/references/troubleshooting.md`

**Interfaces:**
- Consumes: all passing validation evidence from Tasks 3 and 4.
- Produces: an index containing only the requested Kotlin skill and root catalog update, ready for the user's later commit instruction.

- [ ] **Step 1: Stage exact paths without a broad add**

Run:

```bash
git add -- README.md skills/doma-setup-kotlin-project
```

- [ ] **Step 2: Prove the staged boundary**

Run:

```bash
git diff --cached --name-only
git status --short
```

Expected staged paths:

```text
README.md
skills/doma-setup-kotlin-project/SKILL.md
skills/doma-setup-kotlin-project/agents/openai.yaml
skills/doma-setup-kotlin-project/references/build-configuration.md
skills/doma-setup-kotlin-project/references/minimal-kotlin-project.md
skills/doma-setup-kotlin-project/references/troubleshooting.md
```

Root `AGENTS.md`, bundles, logs, `prisma-skills.md`, and every unrelated file must remain unstaged. Do not commit the staged implementation.
