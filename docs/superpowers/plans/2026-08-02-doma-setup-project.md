# Doma Setup Project Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an installable `doma-setup-project` skill that guides agents from a plain Java Gradle or Maven project to a compiling minimal Doma setup.

**Architecture:** Keep the trigger boundary and setup decision flow in `SKILL.md`; move build-tool snippets, the complete Java example, and diagnostic details into three directly linked references. Keep research and evaluation notes under root `docs/research/`, then expose only self-contained skill files through `skills/` and catalog them in the root README.

**Tech Stack:** Agent Skills Markdown/YAML, Codex skill metadata, `npx skills add`, Doma `3.14.1-SNAPSHOT` source bundles, Java, Gradle, and Maven.

## Global Constraints

- Treat bundled Doma `3.14.1-SNAPSHOT` as the research baseline, not the latest stable release.
- Use `prisma-skills.md` only for initial repository layout and README/install presentation.
- Never edit `prisma-skills.md` or `doma-project-bundle-1.md` through `doma-project-bundle-4.md`.
- Keep the installed skill independent of all root bootstrap and source-bundle files.
- Use Java for the primary example.
- Cover plain Gradle and Maven setup; exclude Spring Boot, Quarkus, Kotlin/KSP, advanced DAO/SQL, Criteria API, transactions, migrations, and broad dialect guidance.
- Preserve unrelated worktree and index changes. Commit only task-owned paths with `git commit --only`.
- Complete and validate this one skill before expanding toward the broad onboarding catalog.

## File Map

- Create `docs/research/doma-setup-project-evaluation.md`: exact positive/negative prompts, baseline outputs, post-skill outputs, and observed guidance gaps.
- Create `docs/research/doma-setup-project-source-notes.md`: bundled paths, symbols/sections, supporting role, and stable upstream links for every exact Doma claim.
- Create `skills/doma-setup-project/SKILL.md`: trigger metadata, boundary, setup workflow, verification, recovery routing, and reference navigation.
- Create `skills/doma-setup-project/agents/openai.yaml`: Codex UI metadata matching the finished skill.
- Create `skills/doma-setup-project/references/build-configuration.md`: Gradle/Maven dependencies, annotation processing, repositories, and build verification.
- Create `skills/doma-setup-project/references/minimal-java-project.md`: one complete Java setup with matching source/resource paths.
- Create `skills/doma-setup-project/references/troubleshooting.md`: setup-time compile failures, diagnostic evidence, and recovery actions.
- Create `README.md`: repository description, one-skill catalog, exact public install commands, examples, and snapshot baseline.

---

### Task 1: RED Baseline and Trigger Contract

**Files:**
- Create: `docs/research/doma-setup-project-evaluation.md`

**Interfaces:**
- Consumes: the four approved trigger-boundary prompts from the design.
- Produces: baseline gaps that Tasks 3–5 must address and fixed prompts reused by Task 6.

- [ ] **Step 1: Run three fresh positive scenarios without the new skill**

Use fresh agent contexts with no `doma-setup-project` skill path or intended answer. Submit these exact prompts:

```text
Set up Doma in this plain Java Gradle project. Include the minimum files and show how to verify annotation processing.

Configure Doma annotation processing with Maven and create a minimal DAO that can be compiled.

My first plain Java Doma project compiles no generated DAO implementation. Diagnose the project setup and tell me exactly what to inspect.
```

Save each response verbatim before assessing it.

- [ ] **Step 2: Run the fresh negative-boundary scenario without the new skill**

Submit this exact prompt:

```text
Write a complex Doma two-way SQL query with pagination and result mapping for an existing configured project.
```

Record whether a setup workflow would be irrelevant to this request.

- [ ] **Step 3: Write the baseline report**

Create the report with these headings and fill each from observed output:

```markdown
# Doma Setup Project Evaluation

## Trigger Contract
### Positive 1: Gradle setup
### Positive 2: Maven setup
### Positive 3: Missing generated DAO implementation
### Negative: Advanced two-way SQL

## Baseline Gaps
## Post-skill Results
## Remaining Gaps
```

Under each scenario, include `Prompt`, `Verbatim response`, and `Assessment`. Classify gaps only when directly observed: missing artifact, incorrect path, unsupported claim, missing verification, or boundary error.

- [ ] **Step 4: Verify RED is meaningful**

Confirm at least one positive response has a concrete evidence or execution gap. If all three are already complete and correct, stop authoring and report that a new skill has not demonstrated value.

- [ ] **Step 5: Commit only the evaluation report**

```bash
git add docs/research/doma-setup-project-evaluation.md
git commit --only docs/research/doma-setup-project-evaluation.md -m "test: capture Doma setup skill baseline"
```

### Task 2: Doma Source-first Evidence Notes

**Files:**
- Create: `docs/research/doma-setup-project-source-notes.md`

**Interfaces:**
- Consumes: baseline gaps from Task 1 and the read-only root Doma bundles.
- Produces: claim-by-claim evidence used by all skill content in Tasks 3–5.

- [ ] **Step 1: Read only the setup documentation ranges**

Run:

```bash
sed -n '2313,2681p' doma-project-bundle-1.md
sed -n '2682,4088p' doma-project-bundle-1.md
sed -n '8088,8430p' doma-project-bundle-1.md
```

Extract only rules relevant to plain Java build setup, annotation processing, the minimal example, source/resource paths, and compile verification.

- [ ] **Step 2: Locate and inspect the exact public APIs**

Run:

```bash
rg -n '^## .*/(Config|Dao|Entity|Select)\.java$' doma-project-bundle-*.md
rg -n 'public (interface|@interface) (Config|Dao|Entity|Select)' doma-project-bundle-*.md
```

Use `sed -n` from each relevant heading to the next heading. Record exact signatures/defaults only when needed by the example or troubleshooting guidance.

- [ ] **Step 3: Locate processor and Java integration evidence**

Run:

```bash
rg -n '^## .*/[^/]*(Dao|Config|Entity|Select)[^/]*(ProcessorTest|Test)\.java$' doma-project-bundle-*.md
rg -n 'DaoImpl|META-INF/.*/.*\.sql|Doma[0-9]{4}' doma-project-bundle-3.md doma-project-bundle-4.md
```

Read only candidate files that demonstrate the minimal artifact layout or a setup-time diagnostic. Treat tests as supporting cases, not standalone public guarantees.

- [ ] **Step 4: Write claim-level source notes**

Use this exact table shape:

```markdown
# Doma Setup Project Source Notes

| Claim or rule | Bundled file/section or symbol | Evidence role | Stable official URL or upstream source |
| --- | --- | --- | --- |
```

Add one row per exact dependency coordinate, processor configuration, annotation default, generated type convention, SQL resource path rule, and diagnostic included in the skill. Note conflicts explicitly and narrow the claim to documented behavior.

- [ ] **Step 5: Audit the source notes**

```bash
rg -n 'TODO|TBD|latest stable|probably|assume' docs/research/doma-setup-project-source-notes.md
```

Expected: no placeholders, unsupported current-version claim, or speculative wording.

- [ ] **Step 6: Commit only the source notes**

```bash
git add docs/research/doma-setup-project-source-notes.md
git commit --only docs/research/doma-setup-project-source-notes.md -m "docs: record Doma setup evidence"
```

### Task 3: Initialize the Skill and Write Build Guidance

**Files:**
- Create: `skills/doma-setup-project/SKILL.md` through the initializer, then leave body authoring for Task 5.
- Create: `skills/doma-setup-project/agents/openai.yaml` through the initializer.
- Create: `skills/doma-setup-project/references/build-configuration.md`

**Interfaces:**
- Consumes: exact build claims and links from Task 2.
- Produces: an initialized local skill workspace and a reviewable build reference linked by Task 5; the generated shell is not committed until its placeholders are replaced.

- [ ] **Step 1: Read Codex metadata requirements completely**

```bash
sed -n '1,260p' /home/momose/.codex/skills/.system/skill-creator/references/openai_yaml.md
```

Continue with later ranges if the file exceeds 260 lines; stop only at EOF.

- [ ] **Step 2: Initialize the skill**

```bash
/home/momose/.codex/skills/.system/skill-creator/scripts/init_skill.py doma-setup-project \
  --path skills \
  --resources references \
  --interface display_name="Doma Project Setup" \
  --interface short_description="Set up Doma in a plain Java project" \
  --interface default_prompt='Use $doma-setup-project to configure Doma in this plain Java project and verify annotation processing.'
```

Do not add scripts or assets because this skill needs reference guidance, not a reusable executable or output template.

- [ ] **Step 3: Write the build reference from evidence**

Structure `build-configuration.md` as:

```markdown
# Build Configuration

## Choose the Existing Build Tool
## Gradle
## Maven
## Compile and Inspect Generated Sources
## References
```

Include complete copyable snippets for the baseline's supported Doma coordinates and annotation processor placement. Keep versions parameterized by the project's chosen Doma version while identifying `3.14.1-SNAPSHOT` as this skill's evidence baseline. Include commands to compile and locate generated sources without claiming a universal project-specific output directory unless the build tool establishes it.

- [ ] **Step 4: Inspect the initialized workspace and build reference**

```bash
test -f skills/doma-setup-project/SKILL.md
test -f skills/doma-setup-project/agents/openai.yaml
test -f skills/doma-setup-project/references/build-configuration.md
```

Leave the generated shell uncommitted until Task 5 replaces every initializer placeholder and all linked references exist.

- [ ] **Step 5: Commit only the completed build reference**

```bash
git add skills/doma-setup-project/references/build-configuration.md
git commit --only skills/doma-setup-project/references/build-configuration.md -m "docs: add Doma build configuration guidance"
```

### Task 4: Complete Example and Troubleshooting References

**Files:**
- Create: `skills/doma-setup-project/references/minimal-java-project.md`
- Create: `skills/doma-setup-project/references/troubleshooting.md`

**Interfaces:**
- Consumes: artifact/path and diagnostic evidence from Task 2 plus build commands from Task 3.
- Produces: directly linked operational details for Task 5 and scenario evidence for Task 6.

- [ ] **Step 1: Write one complete Java example**

Structure `minimal-java-project.md` as:

```markdown
# Minimal Plain Java Project

## File Layout
## Config
## Entity
## DAO
## SQL Resource
## Compile and Call the Generated DAO
## References
```

Use one coherent package and matching paths throughout. Show the minimum compilable `Config`, entity, DAO, external SQL resource, and generated implementation invocation established by the evidence. Explain which types are generated and keep generated code out of handwritten-source blocks.

- [ ] **Step 2: Write evidence-backed setup diagnostics**

Structure `troubleshooting.md` as:

```markdown
# Setup Troubleshooting

| Symptom | Inspect | Recovery |
| --- | --- | --- |

## Diagnostic Messages
## Verification Sequence
## References
```

Cover only observed baseline gaps and sourced setup failures: annotation processor not running, generated DAO implementation absent, SQL resource path mismatch, processor diagnostic, and version/classpath mismatch when supported. Pair every symptom with an inspection step and a recovery action.

- [ ] **Step 3: Check example consistency mechanically**

```bash
rg -n 'package |class |interface |META-INF|DaoImpl|TODO|TBD' \
  skills/doma-setup-project/references/minimal-java-project.md \
  skills/doma-setup-project/references/troubleshooting.md
```

Manually confirm package names, DAO names, method parameters, SQL bind names, file paths, and generated implementation names match exactly.

- [ ] **Step 4: Commit the two references**

```bash
git add skills/doma-setup-project/references/minimal-java-project.md skills/doma-setup-project/references/troubleshooting.md
git commit --only skills/doma-setup-project/references/minimal-java-project.md skills/doma-setup-project/references/troubleshooting.md -m "docs: add Doma setup example and diagnostics"
```

### Task 5: Author the Skill Contract and Repository Catalog

**Files:**
- Modify: `skills/doma-setup-project/SKILL.md`
- Modify: `skills/doma-setup-project/agents/openai.yaml`
- Create: `README.md`

**Interfaces:**
- Consumes: baseline failures, all source notes, and all three references.
- Produces: the discoverable installed skill and public repository entry evaluated by Tasks 6–7.

- [ ] **Step 1: Replace the generated SKILL.md with the minimal workflow**

Use exactly two frontmatter fields:

```yaml
---
name: doma-setup-project
description: Use when adding Doma to a plain Java Gradle or Maven project, creating the first Config, entity, DAO, or SQL resource, or diagnosing missing generated DAO implementations during initial annotation processing.
---
```

The body must contain:

1. A core principle: make annotation processing and resource paths verifiable before adding application complexity.
2. A boundary that routes framework, Kotlin/KSP, advanced DAO/two-way SQL, Criteria API, transaction, and migration requests elsewhere.
3. A numbered workflow: inspect project/version/build tool; configure; add matching minimal artifacts; compile; inspect generated sources; diagnose before changing code.
4. A quick-reference table mapping Gradle/Maven, full example, and failure symptoms to the three references.
5. Direct links to every reference with explicit read conditions.
6. Common mistakes derived only from baseline failures and source evidence.

- [ ] **Step 2: Regenerate and inspect Codex metadata**

```bash
/home/momose/.codex/skills/.system/skill-creator/scripts/generate_openai_yaml.py \
  skills/doma-setup-project \
  --interface display_name="Doma Project Setup" \
  --interface short_description="Set up Doma in a plain Java project" \
  --interface default_prompt='Use $doma-setup-project to configure Doma in this plain Java project and verify annotation processing.'
sed -n '1,160p' skills/doma-setup-project/agents/openai.yaml
```

- [ ] **Step 3: Create the root README catalog**

Include:

- `# Doma Skills` and a short Agent Skills description.
- `## Available Skills` with `doma-setup-project`, its three positive triggers, covered scope, and explicit exclusions.
- `## Installation` with these exact commands:

```bash
npx skills add momosetkn/doma-skills --list
npx skills add momosetkn/doma-skills
npx skills add momosetkn/doma-skills --skill doma-setup-project
```

- `## Usage` with one Gradle setup prompt and one missing-generated-DAO prompt.
- `## Doma Baseline` stating that the authored guidance was researched against `3.14.1-SNAPSHOT` and does not claim to be the latest stable release.
- `## Contributing` linking to root `AGENTS.md`.

- [ ] **Step 4: Run content checks**

```bash
rg -n 'TODO|TBD|<skill-name>|placeholder' README.md skills/doma-setup-project
! rg -n 'prisma-skills\.md|doma-project-bundle-[1-4]\.md' skills/doma-setup-project
wc -l skills/doma-setup-project/SKILL.md skills/doma-setup-project/references/*.md
/home/momose/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/doma-setup-project
```

Expected: no publishable placeholders or root-bundle dependency; `SKILL.md` stays concise and each reference over roughly 100 lines has a short table of contents.

- [ ] **Step 5: Commit the public contract and catalog**

```bash
git add skills/doma-setup-project/SKILL.md skills/doma-setup-project/agents/openai.yaml README.md
git commit --only skills/doma-setup-project/SKILL.md skills/doma-setup-project/agents/openai.yaml README.md -m "feat: add Doma project setup skill"
```

### Task 6: GREEN Forward Tests and Refinement

**Files:**
- Modify: `docs/research/doma-setup-project-evaluation.md`
- Modify when evidence requires: `skills/doma-setup-project/SKILL.md`
- Modify when evidence requires: `skills/doma-setup-project/references/*.md`

**Interfaces:**
- Consumes: the exact Task 1 prompts and the completed skill directory.
- Produces: evidence that positive prompts follow the workflow and the negative prompt stays outside the setup boundary.

- [ ] **Step 1: Re-run all four prompts in fresh contexts with the skill**

For each prompt, tell the fresh agent only one of these complete messages:

```text
Use $doma-setup-project at /home/momose/IdeaProjects/doma-skills/skills/doma-setup-project to answer this request:
Set up Doma in this plain Java Gradle project. Include the minimum files and show how to verify annotation processing.

Use $doma-setup-project at /home/momose/IdeaProjects/doma-skills/skills/doma-setup-project to answer this request:
Configure Doma annotation processing with Maven and create a minimal DAO that can be compiled.

Use $doma-setup-project at /home/momose/IdeaProjects/doma-skills/skills/doma-setup-project to answer this request:
My first plain Java Doma project compiles no generated DAO implementation. Diagnose the project setup and tell me exactly what to inspect.

Use $doma-setup-project at /home/momose/IdeaProjects/doma-skills/skills/doma-setup-project to answer this request:
Write a complex Doma two-way SQL query with pagination and result mapping for an existing configured project.
```

Do not provide the expected answer, baseline diagnosis, or source notes.

- [ ] **Step 2: Score positive scenarios**

Require each relevant answer to select the correct build tool, preserve version choice, configure annotation processing, include or route to all required artifacts, preserve source/resource paths, compile, inspect generated output, and recover from sourced setup failures. Copy the response and assessment under `Post-skill Results`.

- [ ] **Step 3: Score the negative scenario**

Require the agent to recognize that advanced two-way SQL is outside this setup skill and avoid applying the onboarding workflow. It may answer from other knowledge only if it clearly preserves the boundary.

- [ ] **Step 4: Refine only observed gaps and re-test affected prompts**

Classify each failure by form: wrong-shaped output gets a positive ordered recipe; an omitted required artifact gets an explicit structural slot; conditional behavior gets an observable condition. Keep the source notes synchronized when exact Doma guidance changes.

- [ ] **Step 5: Commit the evaluation and any evidence-backed refinement**

```bash
git add docs/research/doma-setup-project-evaluation.md skills/doma-setup-project
git commit --only docs/research/doma-setup-project-evaluation.md skills/doma-setup-project -m "test: verify Doma setup skill behavior"
```

### Task 7: Independent Installation and Final Verification

**Files:**
- Verify: `README.md`
- Verify: `skills/doma-setup-project/**`
- Verify: `docs/research/doma-setup-project-*.md`

**Interfaces:**
- Consumes: the complete repository deliverable.
- Produces: structural, discovery, copy-install, content, and source-trace evidence for completion.

- [ ] **Step 1: Run skill-level validation**

```bash
/home/momose/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/doma-setup-project
```

Expected: valid skill.

- [ ] **Step 2: Verify names, links, and placeholders**

```bash
test "$(basename skills/doma-setup-project)" = "$(sed -n 's/^name: //p' skills/doma-setup-project/SKILL.md)"
rg -o '\]\([^)]*\)' skills/doma-setup-project/SKILL.md
test -f skills/doma-setup-project/references/build-configuration.md
test -f skills/doma-setup-project/references/minimal-java-project.md
test -f skills/doma-setup-project/references/troubleshooting.md
! rg -n 'TODO|TBD|<skill-name>|placeholder repository' README.md skills/doma-setup-project
```

- [ ] **Step 3: Verify local CLI discovery**

```bash
npx skills add . --list
```

Expected: `doma-setup-project` appears with the intended trigger description.

- [ ] **Step 4: Copy-install into a disposable directory**

```bash
repo="$(pwd)"
tmp="$(mktemp -d)"
(cd "$tmp" && npx skills add "$repo" --skill doma-setup-project --agent codex --copy -y)
installed_skill="$(find "$tmp" -path '*/doma-setup-project/SKILL.md' -print -quit)"
test -n "$installed_skill"
installed_dir="$(dirname "$installed_skill")"
! rg -n 'prisma-skills\.md|doma-project-bundle-[1-4]\.md' "$installed_dir"
find "$installed_dir" -maxdepth 3 -type f -print | sort
```

Expected: only the self-contained skill, metadata, and three references are required.

- [ ] **Step 5: Audit every exact Doma claim**

Read each dependency coordinate, annotation signature/default, generated-name statement, file-path rule, and diagnostic in the installed copy. Confirm a matching row exists in `docs/research/doma-setup-project-source-notes.md` with complementary evidence where practical.

- [ ] **Step 6: Run final repository checks**

```bash
git status --short
git log --oneline --decorate -8
```

Confirm task commits contain only owned files and pre-existing bundle/index changes remain untouched. Do not push or open a PR without a separate user request.
