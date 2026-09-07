# Troubleshooting

Stop at the first failed layer. Preserve the visible project diff and sanitized
plans; do not reset or overwrite source to “recover.”

## Contents

- [Existing project and annotation processing](#1-existing-project-and-annotation-processing)
- [Git and paths](#2-git-and-paths)
- [Gradle and CodeGen configuration](#3-gradle-and-codegen-configuration)
- [Connection inputs](#4-connection-inputs)
- [AWS identity and target](#5-aws-identity-and-target)
- [Network, TLS, and JDBC](#6-network-tls-and-jdbc)
- [Metadata snapshot](#7-metadata-snapshot)
- [Entity generation](#8-entity-generation)
- [Parse and plan](#9-parse-and-plan)
- [Stale or unsafe apply](#10-stale-or-unsafe-apply)
- [Final build or idempotence](#11-final-build-or-idempotence)

## 1. Existing Project and Annotation Processing

Symptom: the initial clean build fails or expected generated DAO output is
absent.

Action: stop synchronization. Verify the selected subproject, Java 17+,
existing Doma/runtime-processor version alignment, Java `annotationProcessor`
or Kotlin KAPT task execution, and the first compiler/Doma diagnostic. Repair
initial setup separately, then rerun the clean baseline.

## 2. Git and Paths

Symptom: dirty target, symlink/path escape, source collision, unsafe generated
directory, or output rejected outside `build/doma-codegen`.

Action: identify the exact overlapping path. Ask the user to finish or set aside
their change; never stash/reset it yourself. Generated candidates must remain
under `build/doma-codegen/generated`, and merge inputs must use conventional
source roots. Do not bypass real-path or collision checks.

## 3. Gradle and CodeGen Configuration

Symptom: configuration planning exits `65`, ordinary Gradle tasks request
credentials, or the official entity task is absent.

Action: inspect for multiple/dynamic plugin or driver declarations, an
unmanaged `domaSync`, project-local secret fields, Gradle below 8, Java below
17, or both DSL build files. Ensure registration remains guarded by requested
`domaCodeGenDomaSync*` task basenames. Replan; never paste credentials into the
build to satisfy configuration.

Symptom: configuration apply exits `66`.

Action: the build file changed after planning. Discard only the obsolete plan,
inspect the current build, create a fresh plan, and review its new diff.

## 4. Connection Inputs

Symptom: missing local provider, family mismatch, credential-bearing URL, or
project/user properties rejected.

Action: supply only the named environment or user-home Gradle providers. Keep
the URL free of user/password/token parameters. Confirm PostgreSQL versus MySQL
and the exact schema/catalog/table scope. Do not echo values while diagnosing.

## 5. AWS Identity and Target

Symptom: account, region, target, engine, Proxy targets, Secret identity, or
Secret routing mismatch.

Action: stop before JDBC. Reconfirm the intended account and exact identifier.
Do not broaden discovery or substitute another instance/cluster/Proxy. For IAM,
generate a new token only after the corrected target is confirmed.

## 6. Network, TLS, and JDBC

Symptom: sanitized connection, TLS, authentication, timeout, or driver failure.

Action: preserve `verify-full`/`VERIFY_IDENTITY`; verify reachability, DNS,
certificate trust, security-group/routing prerequisites, exact driver family,
database name, and read-only user grants outside this workflow. Never weaken
TLS, grant mutation privileges, print a URL, or retry with an administrator.

## 7. Metadata Snapshot

Symptom: missing/invalid snapshot, out-of-scope table, duplicate identity,
unknown required facts, family/scope mismatch, or unsafe content.

Action: stop before merge. Reconfirm schema/catalog and table regex, rerun the
snapshot with the same selected target, and inspect only credential-free fields.
Unknown metadata is not permission to guess a type, nullability, key, default,
or identity-generation rule.

## 8. Entity Generation

Symptom: CodeGen failure, candidates in a source root, DAO/SQL output, or
candidate/snapshot disagreement.

Action: require `domaCodeGenDomaSyncEntity` and the isolated output path. Do not
invoke `All` or copy generated files over source. Verify the managed language,
package, filters, physical-name flags, comment flag, listener/mapped-superclass
settings, Metamodel policy, and compatible driver.

## 9. Parse and Plan

Symptom: `BLOCKED`, parser error, unsupported shape, collision, inferred rename,
candidate mismatch, or project reference.

Action: read the finding and the Java/Kotlin merge reference. Keep it editless.
Resolve application semantics manually or narrow the table/entity scope; do
not fall back to regex/text replacement. A `PENDING_REVIEW` result is not a
failure: display each exact proposal and wait for explicit ID approval.

## 10. Stale or Unsafe Apply

Symptom: merge apply exits `64`, `65`, or `66`.

Action: for `64`, fix command/approval input; for `65`, resolve dirty/path/Git
safety state; for `66`, regenerate snapshot/candidates and rebuild the complete
plan. Never edit plan JSON or reuse an old approval ID. Apply revalidates the
canonical plan before any write.

## 11. Final Build or Idempotence

Symptom: clean build/AP fails or the second plan has a diff.

Action: report `FAILED`, preserve the current diff, and diagnose the first
compiler/Doma error or remaining finding. Do not roll back destructively. A
successful first apply without a clean build, generated processor output, and
empty second plan is incomplete.

## Sanitized Failure Report

Include the failed layer, exit/state, selected project/module, database family,
schema/catalog/table scope, non-secret target identifier, affected relative
paths, finding IDs, and next safe action. Exclude JDBC URL, host, user,
password/token, Secret value, AWS credential data, classpath, and raw
credential-bearing exceptions.

## Sources

- [Doma CodeGen documentation](https://docs.domaframework.org/en/stable/codegen/)
- [Doma 3.14.0 annotation-processing options](https://docs.domaframework.org/en/3.14.0/annotation-processing/)
- [Gradle build environment](https://docs.gradle.org/current/userguide/build_environment.html)
