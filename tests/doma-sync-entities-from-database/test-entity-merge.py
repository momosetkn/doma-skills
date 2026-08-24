#!/usr/bin/env python3
"""Behavioral contract for deterministic, fail-closed entity merge planning."""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills/doma-sync-entities-from-database/scripts"
CLI = SCRIPTS / "compare-and-merge-entities.py"
FIXTURES = Path(__file__).parent / "fixtures"
sys.path.insert(0, str(SCRIPTS))

from entity_sync.applier import StalePlanError, UnsafeProjectError, apply_plan
from entity_sync.model import SourceSpan, TableIdentity
from entity_sync.planner import (
    Edit,
    Finding,
    MergePlan,
    PlanInputError,
    build_plan,
    load_plan,
    plan_json,
    render_diff,
)


def java_entity(
    *,
    fields: str,
    methods: str,
    class_decl: str = "public class Employee",
    class_annotations: str = (
        '@Entity(metamodel = @Metamodel)\n@Table(schema = "public", name = "employee")'
    ),
    imports: tuple[str, ...] = (),
    class_doc: str = "/** Employees */",
) -> str:
    all_imports = (
        "org.seasar.doma.Column",
        "org.seasar.doma.Entity",
        "org.seasar.doma.Metamodel",
        "org.seasar.doma.Table",
    ) + imports
    import_text = "".join(f"import {name};\n" for name in sorted(set(all_imports)))
    return (
        "package example.entity;\n\n"
        + import_text
        + "\n"
        + class_doc
        + "\n"
        + class_annotations
        + "\n"
        + class_decl
        + " {\n\n"
        + fields
        + methods
        + "}\n"
    )


def java_field(
    name: str,
    column: str,
    type_name: str = "Integer",
    annotations: tuple[str, ...] = (),
    doc: str = "/** */",
) -> str:
    annotation_text = "".join(f"    {annotation}\n" for annotation in annotations)
    return (
        f"    {doc}\n{annotation_text}    @Column(name = \"{column}\")\n"
        f"    {type_name} {name};\n\n"
    )


def java_accessors(name: str, type_name: str = "Integer", *, handwritten: str = "") -> str:
    cap = name[0].upper() + name[1:]
    extra = f" {handwritten}" if handwritten else ""
    return (
        f"    /** Returns the {name}. */\n"
        f"    public {type_name} get{cap}() {{{extra}\n        return {name};\n    }}\n\n"
        f"    /** Sets the {name}. */\n"
        f"    public void set{cap}({type_name} {name}) {{\n        this.{name} = {name};\n    }}\n\n"
    )


def kotlin_entity(*, properties: str, class_decl: str = "class Employee", extra: str = "") -> str:
    return (
        "package example.entity\n\n"
        "import org.seasar.doma.Column\n"
        "import org.seasar.doma.Entity\n"
        "import org.seasar.doma.Metamodel\n"
        "import org.seasar.doma.Table\n\n"
        "/** Employees */\n"
        "@Entity(metamodel = Metamodel())\n"
        "@Table(schema = \"public\", name = \"employee\")\n"
        f"{class_decl} {{\n\n{properties}{extra}}}\n"
    )


def kotlin_property(
    name: str,
    column: str,
    type_name: str,
    default: str,
    doc: str = "/** */",
) -> str:
    return (
        f"    {doc}\n"
        f"    @Column(name = \"{column}\")\n"
        f"    var {name}: {type_name} = {default}\n\n"
    )


def java_new_entity_candidate() -> str:
    return java_entity(
        fields=(
            java_field(
                "employeeId", "employee_id", annotations=(
                    "@Id", "@GeneratedValue(strategy = GenerationType.IDENTITY)"
                ), doc="/** Employee ID */"
            )
            + java_field(
                "displayName", "display_name", "String", doc="/** Display name */"
            )
            + java_field("version", "version")
        ),
        methods=(
            java_accessors("employeeId")
            + java_accessors("displayName", "String")
            + java_accessors("version")
        ),
        imports=(
            "org.seasar.doma.GeneratedValue",
            "org.seasar.doma.GenerationType",
            "org.seasar.doma.Id",
        ),
    )


def without_version_semantics(source: str, language: str) -> str:
    terminator = ";" if language == "java" else ""
    return source.replace(
        f"import org.seasar.doma.Version{terminator}\n", ""
    ).replace("    @Version\n", "")


class ProjectFixture:
    def __init__(self, owner: unittest.TestCase) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="entity-merge-test-")
        owner.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.snapshot = self.root / "build/doma-codegen/schema-snapshot.json"
        self.generated = self.root / "build/doma-codegen/generated"
        self.existing = self.root / "src/main/java"
        self.plan_path = self.root / "build/doma-codegen/entity-merge-plan.json"
        self.diff_path = self.root / "build/doma-codegen/entity-merge.diff"
        self.snapshot.parent.mkdir(parents=True)
        self.existing.mkdir(parents=True)
        shutil.copy2(FIXTURES / "schema-snapshots/employee-postgresql.json", self.snapshot)
        self.configure_codegen("java")

    def configure_codegen(
        self, language: str, package_name: str = "example.entity"
    ) -> None:
        language_type = language.upper()
        (self.root / "build.gradle.kts").write_text(
            "plugins { java }\n\n"
            "// doma-sync-entities-from-database:begin\n"
            "if (gradle.startParameter.taskNames.any { "
            "it.substringAfterLast(\":\").startsWith(\"domaCodeGenDomaSync\") }) {\n"
            "    domaCodeGen {\n"
            "        register(\"domaSync\") {\n"
            "            languageType.set(org.seasar.doma.gradle.codegen.desc.LanguageType."
            f"{language_type})\n"
            "            entity {\n"
            f"                packageName.set(\"{package_name}\")\n"
            "            }\n"
            "        }\n"
            "    }\n"
            "}\n"
            "// doma-sync-entities-from-database:end\n",
            encoding="utf-8",
        )

    def generated_file(self, language: str = "java") -> Path:
        self.configure_codegen(language)
        suffix = "java" if language == "java" else "kt"
        path = self.generated / f"example/entity/Employee.{suffix}"
        path.parent.mkdir(parents=True, exist_ok=True)
        source = FIXTURES / f"generated-candidates/{language}/example/entity/Employee.{suffix}"
        shutil.copy2(source, path)
        return path

    def existing_file(self, source: str, suffix: str = "java") -> Path:
        path = self.existing / f"example/entity/Employee.{suffix}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(source.encode("utf-8"))
        return path

    def plan(self, *, language: str = "auto") -> MergePlan:
        return build_plan(
            project_root=self.root,
            schema_snapshot=self.snapshot,
            generated_dir=self.generated,
            existing_roots=(self.existing,),
            language=language,
        )

    def retain_snapshot_columns(self, *names: str) -> None:
        snapshot = json.loads(self.snapshot.read_text())
        table = snapshot["tables"][0]
        table["columns"] = [column for column in table["columns"] if column["name"] in names]
        table["primary_key"] = [key for key in table["primary_key"] if key["column"] in names]
        self.snapshot.write_text(json.dumps(snapshot, separators=(",", ":")) + "\n")

    def commit(self) -> None:
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.name", "Fixture"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=self.root, check=True)
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=self.root, check=True)


class EntityMergeTests(unittest.TestCase):
    def test_contract_models_are_frozen_and_ids_are_stable_and_machine_independent(self) -> None:
        edit = Edit("insert", "src/main/java/X.java", SourceSpan(2, 2), "x")
        finding = Finding(
            "safe-add-id-000000000000", "SAFE", "add-id", "src/main/java/X.java",
            TableIdentity(None, "public", "employee"), "employee_id", {"primary_key": True},
            None, "@Id", "database primary key", "add @Id", (edit,),
        )
        plan = MergePlan(
            2, ".", "java", "a" * 64,
            (("src/main/java/X.java", "b" * 64),), (), (finding,),
        )

        self.assertEqual(2, plan.format_version)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            plan.project_root = "/tmp/elsewhere"  # type: ignore[misc]
        rendered = plan_json(plan)
        self.assertNotIn(str(Path.home()), rendered)
        self.assertEqual(rendered, plan_json(plan))

    def test_new_java_and_kotlin_entities_are_safe_creates_and_second_run_is_empty(self) -> None:
        for language in ("java", "kotlin"):
            with self.subTest(language=language):
                project = ProjectFixture(self)
                generated = project.generated_file(language)
                generated.write_text(without_version_semantics(generated.read_text(), language))
                project.existing = project.root / f"src/main/{language}"
                project.existing.mkdir(parents=True, exist_ok=True)
                plan = project.plan(language=language)
                creates = [f for f in plan.findings if f.kind == "create-entity"]
                self.assertEqual(["SAFE"], [f.status for f in creates])
                self.assertEqual("create", creates[0].edits[0].kind)
                project.commit()
                result = apply_plan(project.root, plan, approvals=())
                target = project.existing / generated.relative_to(project.generated)
                self.assertEqual("SUCCESS", result.state)
                self.assertEqual(generated.read_bytes(), target.read_bytes())
                self.assertEqual((), project.plan(language=language).findings)

    def test_new_entity_create_requires_exact_physical_snapshot_and_no_special_semantics(self) -> None:
        valid = java_new_entity_candidate()
        missing_columns = java_entity(
            fields=java_field(
                "id", "employee_id", annotations=(
                    "@Id", "@GeneratedValue(strategy = GenerationType.IDENTITY)"
                ), doc="/** Employee ID */"
            ),
            methods=java_accessors("id"),
            imports=(
                "org.seasar.doma.GeneratedValue",
                "org.seasar.doma.GenerationType",
                "org.seasar.doma.Id",
            ),
        )
        extra_column = valid.replace(
            "    /** Returns the employeeId. */",
            java_field("legacy", "legacy")
            + java_accessors("legacy")
            + "    /** Returns the employeeId. */",
            1,
        )
        wrong_type = valid.replace("String displayName;", "Integer displayName;").replace(
            "String getDisplayName()", "Integer getDisplayName()"
        ).replace("setDisplayName(String displayName)", "setDisplayName(Integer displayName)")
        missing_id = valid.replace("    @Id\n", "", 1)
        wrong_id = missing_id.replace(
            '    @Column(name = "display_name")\n',
            '    @Id\n    @Column(name = "display_name")\n',
            1,
        )
        missing_generated_value = valid.replace(
            "    @GeneratedValue(strategy = GenerationType.IDENTITY)\n", "", 1
        )
        wrong_generated_value = valid.replace(
            "GenerationType.IDENTITY", "GenerationType.SEQUENCE", 1
        )
        stock_version = (
            FIXTURES / "generated-candidates/java/example/entity/Employee.java"
        ).read_text()
        tenant_id = valid.replace(
            "import org.seasar.doma.Table;\n",
            "import org.seasar.doma.Table;\nimport org.seasar.doma.TenantId;\n",
            1,
        ).replace(
            '    @Column(name = "version")\n',
            '    @TenantId\n    @Column(name = "version")\n',
            1,
        )
        handwritten_method = (
            valid.rsplit("}\n", 1)[0]
            + "    public String label() { return displayName; }\n}\n"
        )

        cases = (
            ("missing-two-columns", missing_columns, "generated-column-mismatch"),
            ("extra-column", extra_column, "generated-column-mismatch"),
            ("wrong-type", wrong_type, "generated-type-mismatch"),
            ("missing-id", missing_id, "candidate-primary-key-mismatch"),
            ("wrong-id", wrong_id, "candidate-primary-key-mismatch"),
            ("missing-generated-value", missing_generated_value, "generated-value-semantics"),
            ("wrong-generated-value", wrong_generated_value, "generated-value-semantics"),
            ("version", stock_version, "version-semantics"),
            ("tenant-id", tenant_id, "special-mapping"),
            ("handwritten-method", handwritten_method, "unsupported-source"),
        )
        for label, candidate, expected_kind in cases:
            with self.subTest(case=label):
                project = ProjectFixture(self)
                project.generated_file().write_text(candidate)
                plan = project.plan()
                finding = next(
                    item for item in plan.findings if item.kind == expected_kind
                )
                self.assertEqual("BLOCKED", finding.status)
                self.assertFalse(finding.edits)
                self.assertFalse(any(
                    item.kind == "create-entity" and item.status == "SAFE"
                    for item in plan.findings
                ))

        project = ProjectFixture(self)
        project.generated_file().write_text(valid)
        snapshot = json.loads(project.snapshot.read_text())
        snapshot["tables"][0]["primary_key"] = [
            {"name": "employee_pkey", "column": "employee_id", "sequence": 1},
            {"name": "employee_pkey", "column": "version", "sequence": 2},
        ]
        project.snapshot.write_text(json.dumps(snapshot, separators=(",", ":")) + "\n")
        composite = next(
            item for item in project.plan().findings
            if item.kind == "candidate-primary-key-mismatch"
        )
        self.assertEqual("BLOCKED", composite.status)
        self.assertFalse(composite.edits)

    def test_new_kotlin_entity_nullability_must_match_snapshot(self) -> None:
        project = ProjectFixture(self)
        project.existing = project.root / "src/main/kotlin"
        project.existing.mkdir(parents=True)
        generated = project.generated_file("kotlin")
        candidate = without_version_semantics(generated.read_text(), "kotlin").replace(
            "var employeeId: Int = -1", "var employeeId: Int? = null", 1
        )
        generated.write_text(candidate)

        mismatch = next(
            item for item in project.plan(language="kotlin").findings
            if item.kind == "generated-nullability-mismatch"
        )
        self.assertEqual("BLOCKED", mismatch.status)
        self.assertFalse(mismatch.edits)

    def test_new_kotlin_entity_uses_codegen_resolver_nullability_and_defaults(self) -> None:
        cases = (
            (
                "not-null-reference",
                "display_name",
                False,
                kotlin_property(
                    "displayName", "display_name", "String?", "null",
                    "/** Display name */",
                ),
            ),
            (
                "nullable-number",
                "employee_id",
                True,
                kotlin_property(
                    "employeeId", "employee_id", "Int?", "-1",
                    "/** Employee ID */",
                ),
            ),
        )
        for label, column_name, nullable, candidate_property in cases:
            with self.subTest(case=label):
                project = ProjectFixture(self)
                project.existing = project.root / "src/main/kotlin"
                project.existing.mkdir(parents=True)
                project.retain_snapshot_columns(column_name)
                snapshot = json.loads(project.snapshot.read_text())
                table = snapshot["tables"][0]
                table["primary_key"] = []
                table["columns"][0]["nullable"] = nullable
                table["columns"][0]["auto_increment"] = False
                project.snapshot.write_text(
                    json.dumps(snapshot, separators=(",", ":")) + "\n"
                )
                project.generated_file("kotlin").write_text(
                    kotlin_entity(properties=candidate_property)
                )

                plan = project.plan(language="kotlin")
                creates = [item for item in plan.findings if item.kind == "create-entity"]
                self.assertEqual(["SAFE"], [item.status for item in creates])
                self.assertTrue(creates[0].edits)

    def test_new_entity_identity_matches_codegen_property_class_package_and_file_naming(self) -> None:
        valid = java_new_entity_candidate()

        def renamed_property(project: ProjectFixture) -> None:
            project.generated_file().write_text(
                valid.replace("displayName", "renamedDisplayName")
            )

        def renamed_class(project: ProjectFixture) -> None:
            project.generated_file().write_text(
                valid.replace("public class Employee", "public class Worker", 1)
            )

        def renamed_file(project: ProjectFixture) -> None:
            original = project.generated_file()
            moved = original.with_name("Worker.java")
            original.replace(moved)

        def renamed_package(project: ProjectFixture) -> None:
            original = project.generated_file()
            moved = project.generated / "other/entity/Employee.java"
            moved.parent.mkdir(parents=True)
            moved.write_text(valid.replace("package example.entity;", "package other.entity;"))
            original.unlink()

        for label, mutate in (
            ("property", renamed_property),
            ("class", renamed_class),
            ("file", renamed_file),
            ("package", renamed_package),
        ):
            with self.subTest(identity=label):
                project = ProjectFixture(self)
                mutate(project)
                plan = project.plan(language="java")
                mismatch = next((
                    item for item in plan.findings
                    if item.kind == "generated-identity-mismatch"
                ), None)
                self.assertIsNotNone(mismatch)
                assert mismatch is not None
                self.assertEqual("BLOCKED", mismatch.status)
                self.assertFalse(mismatch.edits)
                self.assertFalse(any(
                    item.kind == "create-entity" and item.status == "SAFE"
                    for item in plan.findings
                ))

    def test_new_entity_checks_opposite_language_class_collisions(self) -> None:
        for label, source in (
            (
                "doma-entity",
                kotlin_entity(properties="").replace(
                    '@Table(schema = "public", name = "employee")',
                    '@Table(schema = "public", name = "other")',
                ),
            ),
            ("ordinary-class", "package example.entity\nclass Employee\n"),
        ):
            with self.subTest(source=label):
                project = ProjectFixture(self)
                project.generated_file("java").write_text(java_new_entity_candidate())
                kotlin_root = project.root / "src/main/kotlin"
                collision = kotlin_root / "example/entity/Models.kt"
                collision.parent.mkdir(parents=True)
                collision.write_text(source)

                plan = build_plan(
                    project.root,
                    project.snapshot,
                    project.generated,
                    (project.existing, kotlin_root),
                    "java",
                )
                collision_findings = [
                    finding for finding in plan.findings
                    if finding.status == "BLOCKED"
                    and finding.path == collision.relative_to(project.root).as_posix()
                ]
                self.assertTrue(collision_findings)
                self.assertTrue(all(not finding.edits for finding in collision_findings))
                self.assertIn(
                    collision.relative_to(project.root).as_posix(),
                    dict(plan.source_hashes),
                )
                self.assertFalse(any(
                    finding.kind == "create-entity" and finding.status == "SAFE"
                    for finding in plan.findings
                ))

        project = ProjectFixture(self)
        project.generated_file("java").write_text(java_new_entity_candidate())
        kotlin_root = project.root / "src/main/kotlin"
        non_collision = kotlin_root / "example/entity/Employee.kt"
        non_collision.parent.mkdir(parents=True)
        non_collision.write_text("package example.entity\nclass Other\n")

        plan = build_plan(
            project.root,
            project.snapshot,
            project.generated,
            (project.existing, kotlin_root),
            "java",
        )
        creates = [
            finding for finding in plan.findings
            if finding.kind == "create-entity"
        ]
        self.assertEqual(["SAFE"], [finding.status for finding in creates])
        self.assertTrue(creates[0].edits)

        project = ProjectFixture(self)
        generated = project.generated_file("kotlin")
        generated.write_text(without_version_semantics(generated.read_text(), "kotlin"))
        kotlin_root = project.root / "src/main/kotlin"
        kotlin_root.mkdir(parents=True)
        collision = project.existing / "example/entity/Models.java"
        collision.parent.mkdir(parents=True)
        collision.write_text("package example.entity; public class Employee {}\n")

        plan = build_plan(
            project.root,
            project.snapshot,
            project.generated,
            (project.existing, kotlin_root),
            "kotlin",
        )
        self.assertTrue(any(
            finding.kind == "source-class-path-collision"
            and finding.path == collision.relative_to(project.root).as_posix()
            and finding.status == "BLOCKED"
            and not finding.edits
            for finding in plan.findings
        ))
        self.assertFalse(any(
            finding.kind == "create-entity" and finding.status == "SAFE"
            for finding in plan.findings
        ))

        project = ProjectFixture(self)
        project.generated_file("java").write_text(java_new_entity_candidate())
        kotlin_root = project.root / "src/main/kotlin"
        facade = kotlin_root / "example/entity/Facade.kt"
        facade.parent.mkdir(parents=True)
        facade.write_text(
            '@file:JvmName("Employee")\n'
            "package example.entity\n"
            "fun helper() = 1\n"
        )
        plan = build_plan(
            project.root,
            project.snapshot,
            project.generated,
            (project.existing, kotlin_root),
            "java",
        )
        self.assertTrue(any(
            finding.kind == "source-class-path-collision"
            and finding.path == facade.relative_to(project.root).as_posix()
            and finding.status == "BLOCKED"
            and not finding.edits
            for finding in plan.findings
        ))
        self.assertFalse(any(
            finding.kind == "create-entity" and finding.status == "SAFE"
            for finding in plan.findings
        ))

    def test_new_entity_nonempty_database_remarks_require_nonempty_candidate_docs(self) -> None:
        for label, candidate in (
            (
                "entity",
                java_new_entity_candidate().replace("/** Employees */", "/** */", 1),
            ),
            (
                "property",
                java_new_entity_candidate().replace("/** Display name */", "/** */", 1),
            ),
        ):
            with self.subTest(scope=label):
                project = ProjectFixture(self)
                project.generated_file().write_text(candidate)
                plan = project.plan(language="java")
                mismatch = next((
                    item for item in plan.findings
                    if item.kind == "database-comment-mismatch"
                ), None)
                self.assertIsNotNone(mismatch)
                assert mismatch is not None
                self.assertEqual("BLOCKED", mismatch.status)
                self.assertFalse(mismatch.edits)
                self.assertIsNone(mismatch.candidate)
                self.assertFalse(any(
                    item.kind == "create-entity" and item.status == "SAFE"
                    for item in plan.findings
                ))

    def test_new_entity_missing_or_unknown_required_metadata_is_editless_blocked(self) -> None:
        def base_project() -> tuple[ProjectFixture, dict[str, object]]:
            project = ProjectFixture(self)
            project.retain_snapshot_columns("employee_id")
            snapshot = json.loads(project.snapshot.read_text())
            table = snapshot["tables"][0]
            table["primary_key"] = []
            table["columns"][0]["auto_increment"] = False
            project.snapshot.write_text(
                json.dumps(snapshot, separators=(",", ":")) + "\n"
            )
            project.generated_file().write_text(java_entity(
                fields=java_field(
                    "id", "employee_id", "Integer", doc="/** Employee ID */"
                ),
                methods=java_accessors("id"),
            ))
            return project, snapshot

        cases = (
            ("jdbc-type", lambda table, column: column.__setitem__("jdbc_type", None)),
            ("type-name", lambda table, column: column.__setitem__("type_name", None)),
            ("nullable", lambda table, column: column.__setitem__("nullable", None)),
            ("auto-increment", lambda table, column: column.__setitem__("auto_increment", None)),
            ("primary-key", lambda table, column: table.__setitem__("primary_key", None)),
            (
                "unknown-type",
                lambda table, column: column.update({
                    "jdbc_type": 1111, "type_name": "opaque_unknown_type"
                }),
            ),
            (
                "mysql-bit-size",
                lambda table, column: (
                    table.update({"catalog": "application", "schema": None}),
                    column.update({
                        "jdbc_type": -7, "type_name": "bit", "size": None
                    }),
                ),
            ),
        )
        for label, mutate in cases:
            with self.subTest(metadata=label):
                project, snapshot = base_project()
                table = snapshot["tables"][0]
                column = table["columns"][0]
                mutate(table, column)
                if label == "mysql-bit-size":
                    snapshot["database"] = "mysql"
                    snapshot["scope"] = {
                        "catalog": "application", "schema": None,
                        "table_pattern": "employee",
                    }
                    candidate_path = (
                        project.generated / "example/entity/Employee.java"
                    )
                    candidate = candidate_path.read_text().replace(
                        '@Table(schema = "public", name = "employee")',
                        '@Table(catalog = "application", name = "employee")',
                    ).replace("Integer id", "Boolean id").replace(
                        "Integer getId", "Boolean getId"
                    ).replace("setId(Integer id)", "setId(Boolean id)")
                    candidate_path.write_text(candidate)
                project.snapshot.write_text(
                    json.dumps(snapshot, separators=(",", ":")) + "\n"
                )

                try:
                    plan = project.plan(language="java")
                except Exception as error:  # noqa: BLE001 - the contract is no planner crash
                    self.fail(
                        "incomplete metadata must produce a BLOCKED finding, not "
                        + type(error).__name__
                    )
                blockers = [item for item in plan.findings if item.status == "BLOCKED"]
                self.assertTrue(blockers)
                self.assertTrue(all(not item.edits for item in blockers))
                self.assertFalse(any(
                    item.kind == "create-entity" and item.status == "SAFE"
                    for item in plan.findings
                ))
                self.assertEqual(plan_json(plan), plan_json(project.plan(language="java")))

    def test_unknown_jdbc_mapping_blocks_existing_entity_edits(self) -> None:
        project = ProjectFixture(self)
        project.retain_snapshot_columns("employee_id")
        snapshot = json.loads(project.snapshot.read_text())
        table = snapshot["tables"][0]
        table["primary_key"] = []
        table["columns"][0].update({
            "jdbc_type": 1111,
            "type_name": "opaque_unknown_type",
            "auto_increment": False,
        })
        project.snapshot.write_text(
            json.dumps(snapshot, separators=(",", ":")) + "\n"
        )
        project.generated_file().write_text(java_entity(
            fields=java_field(
                "id", "employee_id", "Long", doc="/** Employee ID */"
            ),
            methods=java_accessors("id", "Long"),
        ))
        project.existing_file(java_entity(
            fields=java_field(
                "id", "employee_id", "Integer", doc="/** Employee ID */"
            ),
            methods=java_accessors("id", "Integer"),
        ))

        plan = project.plan(language="java")
        blockers = [finding for finding in plan.findings if finding.status == "BLOCKED"]
        self.assertTrue(blockers)
        self.assertTrue(all(not finding.edits for finding in blockers))
        self.assertFalse(any(
            finding.status in {"SAFE", "REVIEW_REQUIRED"} and finding.edits
            for finding in plan.findings
        ))

    def test_incomplete_column_metadata_does_not_hide_independent_safe_changes(self) -> None:
        project = ProjectFixture(self)
        snapshot = json.loads(project.snapshot.read_text())
        table = snapshot["tables"][0]
        table["primary_key"] = [{
            "name": "employee_pkey", "column": "employee_id", "sequence": 1,
        }]
        table["columns"][0]["auto_increment"] = False
        table["columns"][1].update({
            "jdbc_type": 1111,
            "type_name": "opaque_unknown_type",
        })
        project.snapshot.write_text(
            json.dumps(snapshot, separators=(",", ":")) + "\n"
        )
        fields = (
            java_field(
                "employeeId", "employee_id", doc="/** Employee ID */"
            )
            + java_field(
                "displayName", "display_name", "String",
                doc="/** Display name */",
            )
            + java_field("version", "version")
        )
        methods = (
            java_accessors("employeeId")
            + java_accessors("displayName", "String")
            + java_accessors("version")
        )
        project.generated_file().write_text(java_entity(
            fields=fields.replace(
                '    @Column(name = "employee_id")\n',
                '    @Id\n    @Column(name = "employee_id")\n',
                1,
            ),
            methods=methods,
            imports=("org.seasar.doma.Id",),
        ))
        project.existing_file(java_entity(fields=fields, methods=methods))

        plan = project.plan(language="java")
        metadata = [
            finding for finding in plan.findings
            if finding.kind == "schema-metadata-incomplete"
        ]
        self.assertEqual(["display_name"], [finding.column for finding in metadata])
        self.assertTrue(all(
            finding.status == "BLOCKED" and not finding.edits
            for finding in metadata
        ))
        primary_key = next(
            finding for finding in plan.findings
            if finding.kind == "synchronize-primary-key"
        )
        self.assertEqual("SAFE", primary_key.status)
        self.assertTrue(primary_key.edits)

    def test_missing_nullable_metadata_preserves_independent_column_and_comment_edits(self) -> None:
        project = ProjectFixture(self)
        project.retain_snapshot_columns("employee_id")
        snapshot = json.loads(project.snapshot.read_text())
        snapshot["tables"][0]["columns"][0].update({
            "nullable": None,
            "auto_increment": False,
        })
        project.snapshot.write_text(
            json.dumps(snapshot, separators=(",", ":")) + "\n"
        )
        candidate = java_entity(
            fields=java_field(
                "id", "employee_id", annotations=("@Id",),
                doc="/** Employee ID */",
            ),
            methods=java_accessors("id"),
            imports=("org.seasar.doma.Id",),
        )
        existing = candidate.replace(
            '    @Column(name = "employee_id")\n', "", 1
        ).replace("/** Employee ID */", "/** */", 1)
        project.generated_file().write_text(candidate)
        project.existing_file(existing)

        plan = project.plan(language="java")
        metadata = next(
            finding for finding in plan.findings
            if finding.kind == "schema-metadata-incomplete"
        )
        self.assertEqual("employee_id", metadata.column)
        self.assertIn("employee_id.nullable", metadata.database["missing_facts"])
        for kind in ("add-column", "add-database-comment"):
            finding = next(item for item in plan.findings if item.kind == kind)
            self.assertEqual("SAFE", finding.status)
            self.assertTrue(finding.edits)

    def test_missing_nullable_metadata_blocks_nullability_and_type_changes(self) -> None:
        for language, candidate_property, existing_property, expected_kind in (
            (
                "kotlin",
                kotlin_property(
                    "id", "employee_id", "Int?", "null", "/** Employee ID */"
                ),
                kotlin_property(
                    "id", "employee_id", "Int", "-1", "/** Employee ID */"
                ),
                "kotlin-nullability",
            ),
            (
                "java",
                java_field(
                    "id", "employee_id", "Long", doc="/** Employee ID */"
                ),
                java_field(
                    "id", "employee_id", "Integer", doc="/** Employee ID */"
                ),
                "widen-basic-type",
            ),
        ):
            with self.subTest(language=language):
                project = ProjectFixture(self)
                project.retain_snapshot_columns("employee_id")
                snapshot = json.loads(project.snapshot.read_text())
                table = snapshot["tables"][0]
                table["primary_key"] = []
                table["columns"][0].update({
                    "nullable": None,
                    "auto_increment": False,
                    "jdbc_type": -5,
                    "type_name": "int8",
                    "size": 64,
                    "scale": 0,
                })
                project.snapshot.write_text(
                    json.dumps(snapshot, separators=(",", ":")) + "\n"
                )
                if language == "kotlin":
                    project.existing = project.root / "src/main/kotlin"
                    project.existing.mkdir(parents=True)
                    project.generated_file("kotlin").write_text(
                        kotlin_entity(properties=candidate_property)
                    )
                    project.existing_file(
                        kotlin_entity(properties=existing_property), "kt"
                    )
                else:
                    project.generated_file().write_text(java_entity(
                        fields=candidate_property,
                        methods=java_accessors("id", "Long"),
                    ))
                    project.existing_file(java_entity(
                        fields=existing_property,
                        methods=java_accessors("id"),
                    ))

                plan = project.plan(language=language)
                finding = next(
                    item for item in plan.findings if item.kind == expected_kind
                )
                self.assertEqual("BLOCKED", finding.status)
                self.assertFalse(finding.edits)

    def test_new_mysql_bit_entity_uses_the_codegen_length_mapping(self) -> None:
        for size, type_name in ((1, "Boolean"), (8, "Byte")):
            with self.subTest(size=size, type_name=type_name):
                project = ProjectFixture(self)
                snapshot = json.loads(project.snapshot.read_text())
                snapshot["database"] = "mysql"
                snapshot["scope"] = {
                    "catalog": "application", "schema": None,
                    "table_pattern": "employee",
                }
                table = snapshot["tables"][0]
                table["catalog"] = "application"
                table["schema"] = None
                table["primary_key"] = []
                column = table["columns"][0]
                column.update({
                    "jdbc_type": -7,
                    "type_name": "bit",
                    "size": size,
                    "auto_increment": False,
                })
                table["columns"] = [column]
                project.snapshot.write_text(
                    json.dumps(snapshot, separators=(",", ":")) + "\n"
                )
                project.generated_file().write_text(java_entity(
                    fields=java_field(
                        "employeeId", "employee_id", type_name, doc="/** Employee ID */"
                    ),
                    methods=java_accessors("employeeId", type_name),
                    class_annotations=(
                        "@Entity(metamodel = @Metamodel)\n"
                        '@Table(catalog = "application", name = "employee")'
                    ),
                ))

                plan = project.plan(language="java")
                create = next(
                    finding for finding in plan.findings
                    if finding.kind == "create-entity"
                )
                self.assertEqual("SAFE", create.status)
                self.assertTrue(create.edits)

    def test_new_kotlin_mysql_bit_entity_uses_codegen_type_nullability_and_default(self) -> None:
        for size, type_name, default in (
            (1, "Boolean?", "null"),
            (8, "Byte", "-1"),
        ):
            with self.subTest(size=size, type_name=type_name):
                project = ProjectFixture(self)
                project.existing = project.root / "src/main/kotlin"
                project.existing.mkdir(parents=True)
                project.retain_snapshot_columns("employee_id")
                snapshot = json.loads(project.snapshot.read_text())
                snapshot["database"] = "mysql"
                snapshot["scope"] = {
                    "catalog": "application", "schema": None,
                    "table_pattern": "employee",
                }
                table = snapshot["tables"][0]
                table["catalog"] = "application"
                table["schema"] = None
                table["primary_key"] = []
                table["columns"][0].update({
                    "jdbc_type": -7,
                    "type_name": "bit",
                    "size": size,
                    "nullable": False,
                    "auto_increment": False,
                })
                project.snapshot.write_text(
                    json.dumps(snapshot, separators=(",", ":")) + "\n"
                )
                project.generated_file("kotlin").write_text(
                    kotlin_entity(properties=kotlin_property(
                        "employeeId", "employee_id", type_name, default,
                        "/** Employee ID */",
                    )).replace(
                        '@Table(schema = "public", name = "employee")',
                        '@Table(catalog = "application", name = "employee")',
                    )
                )

                plan = project.plan(language="kotlin")
                create = next((
                    item for item in plan.findings if item.kind == "create-entity"
                ), None)
                self.assertIsNotNone(create)
                assert create is not None
                self.assertEqual("SAFE", create.status)
                self.assertTrue(create.edits)

    def test_safe_insert_column_annotation_comment_type_widening_and_new_nullability(self) -> None:
        project = ProjectFixture(self)
        candidate = java_entity(
            fields=(
                java_field(
                    "id", "employee_id", annotations=("@Id",),
                    doc="/** Employee ID */",
                )
                + java_field("displayName", "display_name", "String", doc="/** Display name */")
                + java_field("version", "version", "Long")
            ),
            methods=(
                java_accessors("id")
                + java_accessors("displayName", "String")
                + java_accessors("version", "Long")
            ),
            imports=("org.seasar.doma.Id",),
        )
        project.generated_file().write_text(candidate)
        snapshot = json.loads(project.snapshot.read_text())
        snapshot["tables"][0]["columns"][0]["auto_increment"] = False
        next(
            column for column in snapshot["tables"][0]["columns"]
            if column["name"] == "version"
        ).update({"jdbc_type": -5, "type_name": "int8", "size": 64, "scale": 0})
        project.snapshot.write_text(json.dumps(snapshot, separators=(",", ":")) + "\n")
        existing = java_entity(
            fields=(java_field("id", "employee_id", annotations=("@Id",)) + java_field("version", "version")),
            methods=(java_accessors("id") + java_accessors("version")),
            imports=("org.seasar.doma.Id",),
        )
        target = project.existing_file(existing)

        plan = project.plan()
        kinds = {finding.kind: finding for finding in plan.findings}
        self.assertEqual("SAFE", kinds["add-property"].status)
        self.assertEqual("SAFE", kinds["widen-basic-type"].status)
        self.assertIn("Display name", kinds["add-property"].candidate or "")
        project.commit()
        apply_plan(project.root, plan, approvals=())
        merged = target.read_text()
        self.assertIn('@Column(name = "display_name")', merged)
        self.assertIn("/** Display name */", merged)
        self.assertIn("Long version;", merged)

    def test_existing_entity_add_property_requires_a_snapshot_proven_candidate_type(self) -> None:
        project = ProjectFixture(self)
        snapshot = json.loads(project.snapshot.read_text())
        snapshot["tables"][0]["columns"][0]["auto_increment"] = False
        project.snapshot.write_text(json.dumps(snapshot, separators=(",", ":")) + "\n")
        existing = java_entity(
            fields=(
                java_field("id", "employee_id", annotations=("@Id",))
                + java_field("version", "version")
            ),
            methods=java_accessors("id") + java_accessors("version"),
            imports=("org.seasar.doma.Id",),
        )
        project.existing_file(existing)

        wrong_type = java_entity(
            fields=(
                java_field("id", "employee_id", annotations=("@Id",), doc="/** Employee ID */")
                + java_field("displayName", "display_name", "LocalDate", doc="/** Display name */")
                + java_field("version", "version")
            ),
            methods=(
                java_accessors("id")
                + java_accessors("displayName", "LocalDate")
                + java_accessors("version")
            ),
            imports=("java.time.LocalDate", "org.seasar.doma.Id"),
        )
        project.generated_file().write_text(wrong_type)

        plan = project.plan()
        mismatch = next(item for item in plan.findings if item.kind == "generated-type-mismatch")
        self.assertEqual("BLOCKED", mismatch.status)
        self.assertFalse(mismatch.edits)
        self.assertFalse(any(
            item.kind == "add-property" and item.status == "SAFE" and item.edits
            for item in plan.findings
        ))

        valid_type = wrong_type.replace("LocalDate", "String")
        project.generated_file().write_text(valid_type)
        valid_plan = project.plan()
        addition = next(item for item in valid_plan.findings if item.kind == "add-property")
        self.assertEqual("SAFE", addition.status)
        self.assertTrue(addition.edits)

    def test_existing_entity_add_property_rejects_unproven_special_mapping(self) -> None:
        project = ProjectFixture(self)
        snapshot = json.loads(project.snapshot.read_text())
        snapshot["tables"][0]["columns"][0]["auto_increment"] = False
        project.snapshot.write_text(json.dumps(snapshot, separators=(",", ":")) + "\n")
        project.existing_file(java_entity(
            fields=(
                java_field("id", "employee_id", annotations=("@Id",))
                + java_field("version", "version")
            ),
            methods=java_accessors("id") + java_accessors("version"),
            imports=("org.seasar.doma.Id",),
        ))
        candidate = java_entity(
            fields=(
                java_field("id", "employee_id", annotations=("@Id",), doc="/** Employee ID */")
                + java_field(
                    "displayName", "display_name", "String",
                    annotations=("@Version",), doc="/** Display name */",
                )
                + java_field("version", "version")
            ),
            methods=(
                java_accessors("id")
                + java_accessors("displayName", "String")
                + java_accessors("version")
            ),
            imports=("org.seasar.doma.Id", "org.seasar.doma.Version"),
        )
        project.generated_file().write_text(candidate)

        plan = project.plan()
        version = next(item for item in plan.findings if item.kind == "version-semantics")
        self.assertEqual("BLOCKED", version.status)
        self.assertFalse(version.edits)
        self.assertFalse(any(
            item.kind == "add-property" and item.status == "SAFE" and item.edits
            for item in plan.findings
        ))

    def test_database_comment_must_match_snapshot_remarks_before_it_is_applied(self) -> None:
        project = ProjectFixture(self)
        project.retain_snapshot_columns("employee_id")
        candidate = java_entity(
            fields=java_field("id", "employee_id", annotations=("@Id",), doc="/** Employee ID */"),
            methods=java_accessors("id"), imports=("org.seasar.doma.Id",),
        )
        project.generated_file().write_text(candidate)
        existing = candidate.replace("/** Employee ID */", "/** */", 1)
        target = project.existing_file(existing)

        plan = project.plan()
        safe = next(f for f in plan.findings if f.kind == "add-database-comment")
        self.assertEqual("SAFE", safe.status)
        self.assertEqual("Employee ID", safe.database["column"]["remarks"])
        project.commit()
        self.assertEqual("SUCCESS", apply_plan(project.root, plan, approvals=()).state)
        self.assertIn("/** Employee ID */", target.read_text())

        project.existing_file(existing)
        sentinel = "STALE_MATCHED_CANARY_8V3N"
        project.generated_file().write_text(candidate.replace("Employee ID", sentinel, 1))
        mismatch_plan = project.plan()
        mismatch = next(
            f for f in mismatch_plan.findings if f.kind == "database-comment-mismatch"
        )
        self.assertEqual("BLOCKED", mismatch.status)
        self.assertFalse(mismatch.edits)
        self.assertNotIn(sentinel, plan_json(mismatch_plan) + render_diff(mismatch_plan))

        completed = subprocess.run([
            sys.executable, str(CLI), "plan", "--project-root", str(project.root),
            "--schema-snapshot", str(project.snapshot), "--generated-dir", str(project.generated),
            "--existing-root", str(project.existing), "--language", "auto",
            "--output-plan", str(project.plan_path), "--output-diff", str(project.diff_path),
        ], text=True, capture_output=True)
        self.assertEqual(3, completed.returncode)
        outputs = completed.stdout + completed.stderr + project.plan_path.read_text() + project.diff_path.read_text()
        self.assertNotIn(sentinel, outputs)

    def test_database_comment_and_primary_key_edits_apply_without_overlap(self) -> None:
        for label, candidate_annotations, existing_annotations, primary_key in (
            (
                "add-id",
                ("@Id",),
                (),
                [{"name": "employee_pkey", "column": "employee_id", "sequence": 1}],
            ),
            ("remove-id", (), ("@Id",), []),
        ):
            with self.subTest(change=label):
                project = ProjectFixture(self)
                project.retain_snapshot_columns("employee_id")
                snapshot = json.loads(project.snapshot.read_text())
                snapshot["tables"][0]["primary_key"] = primary_key
                snapshot["tables"][0]["columns"][0]["auto_increment"] = False
                project.snapshot.write_text(
                    json.dumps(snapshot, separators=(",", ":")) + "\n"
                )
                project.generated_file().write_text(java_entity(
                    fields=java_field(
                        "id", "employee_id", annotations=candidate_annotations,
                        doc="/** Employee ID */",
                    ),
                    methods=java_accessors("id"),
                    imports=("org.seasar.doma.Id",) if candidate_annotations else (),
                ))
                target = project.existing_file(java_entity(
                    fields=java_field(
                        "id", "employee_id", annotations=existing_annotations,
                    ),
                    methods=java_accessors("id"),
                    imports=("org.seasar.doma.Id",) if existing_annotations else (),
                ))

                plan = project.plan()
                kinds = {finding.kind: finding for finding in plan.findings}
                self.assertEqual("SAFE", kinds["add-database-comment"].status)
                self.assertEqual("SAFE", kinds["synchronize-primary-key"].status)
                project.commit()
                result = apply_plan(project.root, plan, approvals=())
                self.assertEqual("SUCCESS", result.state)
                merged = target.read_text()
                self.assertIn("/** Employee ID */", merged)
                self.assertEqual(bool(candidate_annotations), "@Id" in merged)

    def test_mismatching_new_property_comment_is_blocked_without_serializing_the_candidate_text(self) -> None:
        project = ProjectFixture(self)
        sentinel = "STALE_PROPERTY_CANARY_7QX9"
        project.retain_snapshot_columns("employee_id", "display_name")
        candidate = java_entity(
            fields=(
                java_field(
                    "id", "employee_id", annotations=("@Id",),
                    doc="/** Employee ID */",
                )
                + java_field("displayName", "display_name", "String", doc=f"/** {sentinel} */")
            ),
            methods=java_accessors("id") + java_accessors("displayName", "String"),
            imports=("org.seasar.doma.Id",),
        )
        project.generated_file().write_text(candidate)
        target = project.existing_file(java_entity(
            fields=java_field(
                "id", "employee_id", annotations=("@Id",),
                doc="/** Employee ID */",
            ),
            methods=java_accessors("id"), imports=("org.seasar.doma.Id",),
        ))

        plan = project.plan()
        mismatch = next(f for f in plan.findings if f.kind == "database-comment-mismatch")
        self.assertEqual("BLOCKED", mismatch.status)
        self.assertFalse(mismatch.edits)
        self.assertNotIn(sentinel, plan_json(plan) + render_diff(plan))
        project.commit()
        result = apply_plan(project.root, plan, approvals=())
        self.assertEqual("BLOCKED", result.state)
        self.assertNotIn(sentinel, target.read_text())

        completed = subprocess.run([
            sys.executable, str(CLI), "plan", "--project-root", str(project.root),
            "--schema-snapshot", str(project.snapshot), "--generated-dir", str(project.generated),
            "--existing-root", str(project.existing), "--language", "auto",
            "--output-plan", str(project.plan_path), "--output-diff", str(project.diff_path),
        ], text=True, capture_output=True)
        self.assertEqual(3, completed.returncode)
        outputs = completed.stdout + completed.stderr + project.plan_path.read_text() + project.diff_path.read_text()
        self.assertNotIn(sentinel, outputs)

    def test_mismatching_new_entity_comment_is_blocked_without_serializing_the_candidate_text(self) -> None:
        project = ProjectFixture(self)
        sentinel = "STALE_ENTITY_CANARY_4M2P"
        candidate = project.generated_file().read_text().replace(
            "/** Employees */", f"/** {sentinel} */", 1
        )
        project.generated_file().write_text(candidate)
        plan = project.plan()
        mismatch = next(f for f in plan.findings if f.kind == "database-comment-mismatch")
        self.assertEqual("BLOCKED", mismatch.status)
        self.assertFalse(mismatch.edits)
        self.assertNotIn(sentinel, plan_json(plan) + render_diff(plan))
        target = project.existing / "example/entity/Employee.java"
        project.commit()
        result = apply_plan(project.root, plan, approvals=())
        self.assertEqual("BLOCKED", result.state)
        self.assertFalse(target.exists())

        completed = subprocess.run([
            sys.executable, str(CLI), "plan", "--project-root", str(project.root),
            "--schema-snapshot", str(project.snapshot), "--generated-dir", str(project.generated),
            "--existing-root", str(project.existing), "--language", "auto",
            "--output-plan", str(project.plan_path), "--output-diff", str(project.diff_path),
        ], text=True, capture_output=True)
        self.assertEqual(3, completed.returncode)
        outputs = completed.stdout + completed.stderr + project.plan_path.read_text() + project.diff_path.read_text()
        self.assertNotIn(sentinel, outputs)

    def test_mismatching_new_entity_property_comment_is_blocked_without_serializing_the_candidate_text(self) -> None:
        project = ProjectFixture(self)
        sentinel = "STALE_NEW_ENTITY_PROPERTY_CANARY_5F1K"
        candidate = project.generated_file().read_text().replace(
            "/** Employee ID */", f"/** {sentinel} */", 1
        )
        project.generated_file().write_text(candidate)

        plan = project.plan()
        mismatch = next(f for f in plan.findings if f.kind == "database-comment-mismatch")
        self.assertEqual("BLOCKED", mismatch.status)
        self.assertFalse(mismatch.edits)
        self.assertNotIn(sentinel, plan_json(plan) + render_diff(plan))
        target = project.existing / "example/entity/Employee.java"
        project.commit()
        result = apply_plan(project.root, plan, approvals=())
        self.assertEqual("BLOCKED", result.state)
        self.assertFalse(target.exists())

        completed = subprocess.run([
            sys.executable, str(CLI), "plan", "--project-root", str(project.root),
            "--schema-snapshot", str(project.snapshot), "--generated-dir", str(project.generated),
            "--existing-root", str(project.existing), "--language", "auto",
            "--output-plan", str(project.plan_path), "--output-diff", str(project.diff_path),
        ], text=True, capture_output=True)
        self.assertEqual(3, completed.returncode)
        outputs = completed.stdout + completed.stderr + project.plan_path.read_text() + project.diff_path.read_text()
        self.assertNotIn(sentinel, outputs)

    def test_column_addition_and_unambiguous_correction_are_safe_but_property_rename_is_blocked(self) -> None:
        project = ProjectFixture(self)
        generated = java_entity(
            fields=java_field(
                "id", "employee_id", annotations=("@Id",),
                doc="/** Employee ID */",
            ),
            methods=java_accessors("id"), imports=("org.seasar.doma.Id",),
        )
        project.generated_file().write_text(generated)
        project.retain_snapshot_columns("employee_id")
        for declaration, expected_kind, expected_status in (
            (
                java_field("id", "employee_id", annotations=("@Id",)).replace(
                    '    @Column(name = "employee_id")\n', ""
                ),
                "add-column", "SAFE",
            ),
            (java_field("id", "id", annotations=("@Id",)), "correct-column", "SAFE"),
            (java_field("employeeId", "employee_id", annotations=("@Id",)), "property-rename", "BLOCKED"),
        ):
            with self.subTest(expected_kind=expected_kind):
                project.existing_file(java_entity(
                    fields=declaration,
                    methods=java_accessors("id" if expected_status == "SAFE" else "employeeId"),
                    imports=("org.seasar.doma.Id",),
                ))
                finding = next(f for f in project.plan().findings if f.kind == expected_kind)
                self.assertEqual(expected_status, finding.status)
                self.assertEqual((), finding.edits) if expected_status == "BLOCKED" else self.assertTrue(finding.edits)

    def test_single_and_composite_primary_key_changes_are_one_atomic_safe_finding(self) -> None:
        project = ProjectFixture(self)
        snapshot = json.loads(project.snapshot.read_text())
        table = snapshot["tables"][0]
        table["primary_key"] = [
            {"name": "employee_pkey", "column": "employee_id", "sequence": 1},
            {"name": "employee_pkey", "column": "version", "sequence": 2},
        ]
        project.snapshot.write_text(json.dumps(snapshot, separators=(",", ":")) + "\n")
        project.retain_snapshot_columns("employee_id", "version")
        generated = java_entity(
            fields=(
                java_field(
                    "id", "employee_id", annotations=("@Id",),
                    doc="/** Employee ID */",
                )
                + java_field("version", "version", annotations=("@Id",))
            ),
            methods=java_accessors("id") + java_accessors("version"),
            imports=("org.seasar.doma.Id",),
        )
        project.generated_file().write_text(generated)
        existing = java_entity(
            fields=java_field("id", "employee_id") + java_field("version", "version"),
            methods=java_accessors("id") + java_accessors("version"),
        )
        project.existing_file(existing)

        findings = [f for f in project.plan().findings if f.kind == "synchronize-primary-key"]
        self.assertEqual(1, len(findings))
        self.assertEqual("SAFE", findings[0].status)
        self.assertEqual(2, len([
            edit for edit in findings[0].edits if edit.kind == "insert" and "@Id" in edit.text
        ]))

    def test_id_removal_deletes_the_complete_annotation_line_without_reindenting_neighbors(self) -> None:
        project = ProjectFixture(self)
        project.retain_snapshot_columns("employee_id")
        snapshot = json.loads(project.snapshot.read_text())
        snapshot["tables"][0]["primary_key"] = []
        snapshot["tables"][0]["columns"][0]["auto_increment"] = False
        project.snapshot.write_text(json.dumps(snapshot, separators=(",", ":")) + "\n")
        candidate = java_entity(
            fields=java_field(
                "id", "employee_id", doc="/** Employee ID */"
            ),
            methods=java_accessors("id"),
        )
        project.generated_file().write_text(candidate)
        target = project.existing_file(java_entity(
            fields=java_field(
                "id", "employee_id", annotations=("@Id",),
                doc="/** Employee ID */",
            ),
            methods=java_accessors("id"), imports=("org.seasar.doma.Id",),
        ))
        plan = project.plan()
        finding = next(f for f in plan.findings if f.kind == "synchronize-primary-key")
        self.assertEqual("SAFE", finding.status)
        project.commit()
        apply_plan(project.root, plan, approvals=())
        merged = target.read_text()
        self.assertNotIn("@Id", merged)
        self.assertIn('\n    @Column(name = "employee_id")\n', merged)
        self.assertNotIn('\n        @Column(name = "employee_id")\n', merged)

    def test_generated_value_requires_matching_database_metadata_and_candidate(self) -> None:
        project = ProjectFixture(self)
        generated = (FIXTURES / "generated-candidates/java/example/entity/Employee.java").read_text()
        project.generated_file().write_text(generated)
        existing = generated.replace(
            "    @GeneratedValue(strategy = GenerationType.IDENTITY)\n", ""
        ).replace("import org.seasar.doma.GeneratedValue;\n", "").replace(
            "import org.seasar.doma.GenerationType;\n", ""
        )
        project.existing_file(existing)
        finding = next(f for f in project.plan().findings if f.kind == "add-generated-value")
        self.assertEqual("SAFE", finding.status)

        snapshot = json.loads(project.snapshot.read_text())
        snapshot["tables"][0]["columns"][0]["auto_increment"] = False
        project.snapshot.write_text(json.dumps(snapshot, separators=(",", ":")) + "\n")
        blocked = next(f for f in project.plan().findings if f.kind == "generated-value-semantics")
        self.assertEqual("BLOCKED", blocked.status)
        self.assertFalse(blocked.edits)

    def test_existing_generated_value_requires_identity_on_the_exact_single_column_primary_key(self) -> None:
        generated = (FIXTURES / "generated-candidates/java/example/entity/Employee.java").read_text()
        cases = (
            (
                "non-primary-key-auto-increment",
                generated.replace(
                    '    @Column(name = "display_name")\n',
                    "    @GeneratedValue(strategy = GenerationType.IDENTITY)\n"
                    '    @Column(name = "display_name")\n',
                    1,
                ),
                "display_name",
                lambda snapshot: next(
                    column for column in snapshot["tables"][0]["columns"]
                    if column["name"] == "display_name"
                ).update({"auto_increment": True}),
            ),
            (
                "primary-key-sequence",
                generated.replace("GenerationType.IDENTITY", "GenerationType.SEQUENCE", 1),
                "employee_id",
                lambda snapshot: None,
            ),
            (
                "primary-key-table",
                generated.replace("GenerationType.IDENTITY", "GenerationType.TABLE", 1),
                "employee_id",
                lambda snapshot: None,
            ),
            (
                "primary-key-unspecified",
                generated.replace(
                    "@GeneratedValue(strategy = GenerationType.IDENTITY)", "@GeneratedValue", 1
                ),
                "employee_id",
                lambda snapshot: None,
            ),
        )
        for label, candidate, column, mutate_snapshot in cases:
            with self.subTest(case=label):
                project = ProjectFixture(self)
                snapshot = json.loads(project.snapshot.read_text())
                mutate_snapshot(snapshot)
                project.snapshot.write_text(
                    json.dumps(snapshot, separators=(",", ":")) + "\n",
                    encoding="utf-8",
                )
                project.generated_file().write_text(candidate, encoding="utf-8")
                existing = candidate.replace(
                    "    @GeneratedValue(strategy = GenerationType.IDENTITY)\n"
                    f'    @Column(name = "{column}")\n',
                    f'    @Column(name = "{column}")\n',
                    1,
                ).replace(
                    "    @GeneratedValue(strategy = GenerationType.SEQUENCE)\n"
                    f'    @Column(name = "{column}")\n',
                    f'    @Column(name = "{column}")\n',
                    1,
                ).replace(
                    "    @GeneratedValue(strategy = GenerationType.TABLE)\n"
                    f'    @Column(name = "{column}")\n',
                    f'    @Column(name = "{column}")\n',
                    1,
                ).replace(
                    "    @GeneratedValue\n"
                    f'    @Column(name = "{column}")\n',
                    f'    @Column(name = "{column}")\n',
                    1,
                )
                if column == "employee_id":
                    existing = existing.replace("import org.seasar.doma.GeneratedValue;\n", "").replace(
                        "import org.seasar.doma.GenerationType;\n", ""
                    )
                target = project.existing_file(existing)

                plan = project.plan()
                finding = next(
                    item for item in plan.findings
                    if (
                        item.kind in {"add-generated-value", "generated-value-semantics"}
                        and item.column == column
                    ) or (
                        label == "primary-key-unspecified"
                        and item.kind == "unsupported-source"
                    )
                )
                self.assertEqual("BLOCKED", finding.status)
                self.assertFalse(finding.edits)
                project.commit()
                before = target.read_bytes()
                result = apply_plan(project.root, plan, approvals=())
                self.assertEqual("BLOCKED", result.state)
                self.assertEqual(before, target.read_bytes())

    def test_existing_type_change_requires_candidate_type_proven_by_snapshot(self) -> None:
        project = ProjectFixture(self)
        candidate = (FIXTURES / "generated-candidates/java/example/entity/Employee.java").read_text()
        candidate = candidate.replace("String displayName", "Long displayName").replace(
            "public String getDisplayName()", "public Long getDisplayName()"
        ).replace("setDisplayName(String displayName)", "setDisplayName(Long displayName)")
        existing = candidate.replace("Long displayName", "Integer displayName").replace(
            "public Long getDisplayName()", "public Integer getDisplayName()"
        ).replace("setDisplayName(Long displayName)", "setDisplayName(Integer displayName)")
        project.generated_file().write_text(candidate, encoding="utf-8")
        project.existing_file(existing)

        plan = project.plan()
        finding = next(
            item for item in plan.findings
            if item.column == "display_name"
            and item.kind in {"widen-basic-type", "narrow-basic-type", "generated-type-mismatch"}
        )
        self.assertEqual("BLOCKED", finding.status)
        self.assertFalse(finding.edits)

    def test_existing_snapshot_proven_basic_widening_remains_safe(self) -> None:
        project = ProjectFixture(self)
        snapshot = json.loads(project.snapshot.read_text())
        display_name = next(
            column for column in snapshot["tables"][0]["columns"]
            if column["name"] == "display_name"
        )
        display_name.update({"jdbc_type": -5, "type_name": "int8", "size": 64, "scale": 0})
        project.snapshot.write_text(
            json.dumps(snapshot, separators=(",", ":")) + "\n", encoding="utf-8"
        )
        candidate = (FIXTURES / "generated-candidates/java/example/entity/Employee.java").read_text()
        candidate = candidate.replace("String displayName", "Long displayName").replace(
            "public String getDisplayName()", "public Long getDisplayName()"
        ).replace("setDisplayName(String displayName)", "setDisplayName(Long displayName)")
        existing = candidate.replace("Long displayName", "Integer displayName").replace(
            "public Long getDisplayName()", "public Integer getDisplayName()"
        ).replace("setDisplayName(Long displayName)", "setDisplayName(Integer displayName)")
        project.generated_file().write_text(candidate, encoding="utf-8")
        project.existing_file(existing)

        finding = next(
            item for item in project.plan().findings
            if item.column == "display_name" and item.kind == "widen-basic-type"
        )
        self.assertEqual("SAFE", finding.status)
        self.assertTrue(finding.edits)

    def test_existing_addition_with_database_default_requires_manual_decision(self) -> None:
        project = ProjectFixture(self)
        snapshot = json.loads(project.snapshot.read_text())
        next(
            column for column in snapshot["tables"][0]["columns"]
            if column["name"] == "display_name"
        )["default"] = "ACTIVE"
        project.snapshot.write_text(
            json.dumps(snapshot, separators=(",", ":")) + "\n", encoding="utf-8"
        )
        candidate = (FIXTURES / "generated-candidates/java/example/entity/Employee.java").read_text()
        project.generated_file().write_text(candidate, encoding="utf-8")
        target = project.existing_file(candidate.replace(
            java_field("displayName", "display_name", "String", doc="/** Display name */"), ""
        ).replace(java_accessors("displayName", "String"), ""))

        plan = project.plan()
        finding = next(
            item for item in plan.findings
            if item.kind in {"add-property", "database-default-semantics"}
            and item.column == "display_name"
        )
        self.assertEqual("BLOCKED", finding.status)
        self.assertFalse(finding.edits)
        self.assertIn("manual", finding.action.lower())
        project.commit()
        before = target.read_bytes()
        result = apply_plan(project.root, plan, approvals=())
        self.assertEqual("BLOCKED", result.state)
        self.assertEqual(before, target.read_bytes())

    def test_localized_addition_with_handwritten_accessor_collision_is_blocked(self) -> None:
        project = ProjectFixture(self)
        candidate = (FIXTURES / "generated-candidates/java/example/entity/Employee.java").read_text()
        project.generated_file().write_text(candidate, encoding="utf-8")
        existing = candidate.replace(
            java_field("displayName", "display_name", "String", doc="/** Display name */"), ""
        ).replace(java_accessors("displayName", "String"), "")
        existing = existing.rsplit("}\n", 1)[0] + (
            '    public String getDisplayName() { return "manual"; }\n}\n'
        )
        target = project.existing_file(existing)

        plan = project.plan()
        finding = next(
            item for item in plan.findings if item.kind == "add-property"
        )
        self.assertEqual("BLOCKED", finding.status)
        self.assertFalse(finding.edits)
        project.commit()
        before = target.read_bytes()
        result = apply_plan(project.root, plan, approvals=())
        self.assertEqual("BLOCKED", result.state)
        self.assertEqual(before, target.read_bytes())

    def test_localized_kotlin_boolean_is_property_accessor_collision_is_blocked(self) -> None:
        project = ProjectFixture(self)
        project.existing = project.root / "src/main/kotlin"
        project.existing.mkdir(parents=True)
        project.retain_snapshot_columns("employee_id")
        snapshot = json.loads(project.snapshot.read_text())
        snapshot["tables"][0]["columns"].append({
            "name": "is_active", "ordinal": 2, "jdbc_type": -7,
            "type_name": "bool", "size": 1, "scale": 0, "nullable": True,
            "default": None, "auto_increment": False, "remarks": "Active flag",
        })
        project.snapshot.write_text(
            json.dumps(snapshot, separators=(",", ":")) + "\n", encoding="utf-8"
        )
        candidate = kotlin_entity(properties=(
            kotlin_property("employeeId", "employee_id", "Int", "-1", "/** Employee ID */")
            + kotlin_property("isActive", "is_active", "Boolean?", "null", "/** Active flag */")
        )).replace(
            '@Column(name = "employee_id")',
            '@org.seasar.doma.Id\n    @Column(name = "employee_id")',
            1,
        )
        project.generated_file("kotlin").write_text(candidate, encoding="utf-8")
        existing = kotlin_entity(properties=kotlin_property(
            "employeeId", "employee_id", "Int", "-1", "/** Employee ID */"
        )).replace(
            '@Column(name = "employee_id")',
            '@org.seasar.doma.Id\n    @Column(name = "employee_id")',
            1,
        ).replace("}\n", "    fun isActive(): Boolean? = null\n}\n", 1)
        target = project.existing_file(existing, "kt")

        plan = project.plan(language="kotlin")
        finding = next(item for item in plan.findings if item.kind == "add-property")
        self.assertEqual("BLOCKED", finding.status)
        self.assertFalse(finding.edits)
        project.commit()
        before = target.read_bytes()
        result = apply_plan(project.root, plan, approvals=())
        self.assertEqual("BLOCKED", result.state)
        self.assertEqual(before, target.read_bytes())

    def test_identical_generated_value_semantics_do_not_depend_on_source_offsets(self) -> None:
        project = ProjectFixture(self)
        candidate = project.generated_file().read_text()
        project.existing_file(candidate.replace("\n", "\r\n"))

        plan = project.plan()
        self.assertFalse(any("generated-value" in finding.kind for finding in plan.findings))

    def test_domain_special_mappings_inheritance_and_interfaces_stop_file_edits(self) -> None:
        project = ProjectFixture(self)
        project.generated_file()
        domain = project.existing / "example/Money.java"
        domain.parent.mkdir(parents=True, exist_ok=True)
        domain.write_text(
            "package example; import org.seasar.doma.Domain; "
            "@Domain(valueType = Integer.class) public class Money {}\n"
        )
        variants = (
            java_entity(
                fields=java_field("id", "employee_id", "Money", annotations=("@Id",)),
                methods=java_accessors("id", "Money"), imports=("org.seasar.doma.Id", "example.Money"),
            ),
            java_entity(
                fields=java_field("id", "employee_id", annotations=("@Id", "@TenantId")),
                methods=java_accessors("id"), imports=("org.seasar.doma.Id", "org.seasar.doma.TenantId"),
            ),
            java_entity(
                fields=java_field("id", "employee_id", annotations=("@Id",)), methods=java_accessors("id"),
                class_decl="public class Employee extends BaseEmployee implements Audited",
                imports=("org.seasar.doma.Id",),
            ),
        )
        for source in variants:
            with self.subTest(source=hashlib.sha256(source.encode()).hexdigest()[:8]):
                project.existing_file(source)
                plan = project.plan()
                self.assertTrue(any(f.status == "BLOCKED" for f in plan.findings))
                self.assertFalse(any(f.edits for f in plan.findings if f.path.endswith("Employee.java")))

    def test_handwritten_method_preserves_localized_new_property_and_composite_key_edits(self) -> None:
        project = ProjectFixture(self)
        snapshot = json.loads(project.snapshot.read_text())
        table = snapshot["tables"][0]
        table["primary_key"] = [
            {"name": "employee_pkey", "column": "employee_id", "sequence": 1},
            {"name": "employee_pkey", "column": "version", "sequence": 2},
        ]
        table["columns"][0]["auto_increment"] = False
        project.snapshot.write_text(json.dumps(snapshot, separators=(",", ":")) + "\n")
        candidate = java_entity(
            fields=(
                java_field(
                    "id", "employee_id", annotations=("@Id",),
                    doc="/** Employee ID */",
                )
                + java_field("displayName", "display_name", "String", doc="/** Display name */")
                + java_field("version", "version", annotations=("@Id",))
            ),
            methods=(
                java_accessors("id")
                + java_accessors("displayName", "String")
                + java_accessors("version")
            ),
            imports=("org.seasar.doma.Id",),
        )
        project.generated_file().write_text(candidate)
        handwritten = (
            "    /** Application-owned label. */\n"
            "    public String label() { return id.toString(); }\n"
        )
        target = project.existing_file(java_entity(
            fields=(
                java_field(
                    "id", "employee_id", annotations=("@Id",),
                    doc="/** Employee ID */",
                )
                + java_field("version", "version")
            ),
            methods=java_accessors("id") + java_accessors("version") + handwritten,
            imports=("org.seasar.doma.Id",),
        ))

        plan = project.plan()
        self.assertTrue(any(
            finding.status == "BLOCKED" and finding.kind == "unsupported-source"
            for finding in plan.findings
        ))
        for kind in ("add-property", "synchronize-primary-key"):
            finding = next(item for item in plan.findings if item.kind == kind)
            self.assertEqual("SAFE", finding.status)
            self.assertTrue(finding.edits)
        project.commit()
        result = apply_plan(project.root, plan, approvals=())
        self.assertEqual("BLOCKED", result.state)
        merged = target.read_text()
        self.assertIn('@Column(name = "display_name")', merged)
        self.assertEqual(2, merged.count("@Id"))
        self.assertIn(handwritten, merged)

    def test_localized_unsupported_edits_stay_blocked_for_data_classes_and_incomplete_metadata(self) -> None:
        project = ProjectFixture(self)
        project.existing = project.root / "src/main/kotlin"
        project.existing.mkdir(parents=True)
        project.retain_snapshot_columns("employee_id", "display_name")
        project.generated_file("kotlin").write_text(kotlin_entity(properties=(
            kotlin_property("employeeId", "employee_id", "Int", "-1", "/** Employee ID */")
            + kotlin_property("displayName", "display_name", "String?", "null", "/** Display name */")
        )).replace(
            '@Column(name = "employee_id")',
            '@org.seasar.doma.Id\n    @Column(name = "employee_id")',
            1,
        ))
        project.existing_file(kotlin_entity(
            properties="",
            class_decl=(
                "data class Employee(\n"
                "    @org.seasar.doma.Id @Column(name = \"employee_id\")\n"
                "    var employeeId: Int,\n"
                ")"
            ),
        ), "kt")
        data_class_plan = project.plan(language="kotlin")
        self.assertTrue(any(
            finding.kind == "kotlin-primary-constructor" and finding.status == "BLOCKED"
            for finding in data_class_plan.findings
        ))
        self.assertFalse(any(
            finding.kind == "add-property" and finding.edits
            for finding in data_class_plan.findings
        ))

        project = ProjectFixture(self)
        snapshot = json.loads(project.snapshot.read_text())
        snapshot["tables"][0]["columns"][1]["nullable"] = None
        snapshot["tables"][0]["columns"][0]["auto_increment"] = False
        project.snapshot.write_text(json.dumps(snapshot, separators=(",", ":")) + "\n")
        project.generated_file().write_text(java_entity(
            fields=(
                java_field("id", "employee_id", annotations=("@Id",), doc="/** Employee ID */")
                + java_field("displayName", "display_name", "String", doc="/** Display name */")
                + java_field("version", "version")
            ),
            methods=(
                java_accessors("id") + java_accessors("displayName", "String")
                + java_accessors("version")
            ),
            imports=("org.seasar.doma.Id",),
        ))
        project.existing_file(java_entity(
            fields=(
                java_field("id", "employee_id", annotations=("@Id",), doc="/** Employee ID */")
                + java_field("version", "version")
            ),
            methods=(
                java_accessors("id") + java_accessors("version")
                + "    public String label() { return id.toString(); }\n"
            ),
            imports=("org.seasar.doma.Id",),
        ))
        incomplete_plan = project.plan(language="java")
        self.assertTrue(any(
            finding.kind == "schema-metadata-incomplete"
            and finding.column == "display_name"
            for finding in incomplete_plan.findings
        ))
        self.assertFalse(any(
            finding.kind == "add-property" and finding.edits
            for finding in incomplete_plan.findings
        ))

    def test_localized_unsupported_edits_fail_closed_on_candidate_inconsistency(self) -> None:
        project = ProjectFixture(self)
        candidate_path = project.generated_file()
        generated = candidate_path.read_text()
        candidate_path.write_text(generated.replace(
            "    /** Returns the employeeId. */",
            java_field("legacy", "legacy") + java_accessors("legacy")
            + "    /** Returns the employeeId. */",
            1,
        ))
        existing = generated.replace(
            java_field("displayName", "display_name", "String", doc="/** Display name */"), ""
        ).replace(java_accessors("displayName", "String"), "")
        project.existing_file(existing.rsplit("}\n", 1)[0]
                              + "    public String label() { return employeeId.toString(); }\n}\n")

        plan = project.plan()
        blocker = next(
            finding for finding in plan.findings
            if finding.kind == "generated-column-mismatch"
        )
        self.assertEqual("BLOCKED", blocker.status)
        self.assertFalse(blocker.edits)
        self.assertFalse(any(
            finding.status == "SAFE" and finding.edits
            for finding in plan.findings
        ))

    def test_localized_unsupported_edits_fail_closed_on_unrelated_incomplete_metadata(self) -> None:
        project = ProjectFixture(self)
        snapshot = json.loads(project.snapshot.read_text())
        version = next(
            column for column in snapshot["tables"][0]["columns"]
            if column["name"] == "version"
        )
        version["nullable"] = None
        project.snapshot.write_text(json.dumps(snapshot, separators=(",", ":")) + "\n")
        generated = project.generated_file().read_text()
        existing = generated.replace(
            java_field("displayName", "display_name", "String", doc="/** Display name */"), ""
        ).replace(java_accessors("displayName", "String"), "")
        project.existing_file(existing.rsplit("}\n", 1)[0]
                              + "    public String label() { return employeeId.toString(); }\n}\n")

        plan = project.plan()
        blocker = next(
            finding for finding in plan.findings
            if finding.kind == "schema-metadata-incomplete" and finding.column == "version"
        )
        self.assertEqual("BLOCKED", blocker.status)
        self.assertFalse(any(
            finding.status == "SAFE" and finding.edits
            for finding in plan.findings
        ))

    def test_kotlin_nullability_is_review_and_primary_constructor_or_data_class_is_blocked(self) -> None:
        project = ProjectFixture(self)
        project.existing = project.root / "src/main/kotlin"
        project.existing.mkdir(parents=True)
        project.generated_file("kotlin")
        existing = (FIXTURES / "generated-candidates/kotlin/example/entity/Employee.kt").read_text().replace(
            "var employeeId: Int = -1", "var employeeId: Int? = null"
        )
        target = project.existing_file(existing, "kt")
        plan = project.plan(language="kotlin")
        review = next(f for f in plan.findings if f.kind == "kotlin-nullability")
        self.assertEqual("REVIEW_REQUIRED", review.status)
        self.assertIn(review.finding_id, review.action)
        self.assertIn("@@", review.action)
        self.assertIn("var employeeId: Int? = null", review.existing or "")
        self.assertIn("var employeeId: Int = -1", review.candidate or "")
        self.assertIn("-    var employeeId: Int? = null", render_diff(plan))
        self.assertIn("+    var employeeId: Int = -1", render_diff(plan))
        project.commit()
        applied = apply_plan(project.root, plan, approvals=(review.finding_id,))
        self.assertEqual("SUCCESS", applied.state)
        self.assertIn("var employeeId: Int = -1", target.read_text())
        self.assertNotIn("var employeeId: Int = null", target.read_text())

        for declaration in (
            "data class Employee(var id: Int)",
            "class Employee(var id: Int)",
        ):
            source = kotlin_entity(properties="", class_decl=declaration)
            project.existing_file(source, "kt")
            plan = project.plan(language="kotlin")
            self.assertTrue(any(f.status == "BLOCKED" for f in plan.findings))
            self.assertFalse(any(f.edits for f in plan.findings))

    def test_combined_kotlin_type_and_nullability_change_requires_one_exact_atomic_approval(self) -> None:
        cases = (
            ("Int?", "null", "Long", "-1L"),
            ("Long?", "null", "Int", "-1"),
        )
        for old_type, old_default, new_type, new_default in cases:
            with self.subTest(old_type=old_type, new_type=new_type):
                project = ProjectFixture(self)
                project.existing = project.root / "src/main/kotlin"
                project.existing.mkdir(parents=True)
                project.retain_snapshot_columns("employee_id")
                snapshot = json.loads(project.snapshot.read_text())
                snapshot["tables"][0]["primary_key"] = []
                snapshot["tables"][0]["columns"][0]["auto_increment"] = False
                project.snapshot.write_text(json.dumps(snapshot, separators=(",", ":")) + "\n")
                project.generated_file("kotlin").write_text(kotlin_entity(
                    properties=kotlin_property(
                        "id", "employee_id", new_type, new_default,
                        "/** Employee ID */",
                    )
                ))
                target = project.existing_file(kotlin_entity(
                    properties=kotlin_property(
                        "id", "employee_id", old_type, old_default,
                        "/** Employee ID */",
                    )
                ), "kt")

                plan = project.plan(language="kotlin")
                combined = [
                    finding for finding in plan.findings
                    if finding.kind == "kotlin-type-nullability"
                ]
                self.assertEqual(1, len(combined))
                self.assertEqual("REVIEW_REQUIRED", combined[0].status)
                self.assertTrue(combined[0].edits)
                self.assertFalse(any(
                    finding.kind in {
                        "widen-basic-type", "narrow-basic-type", "kotlin-nullability"
                    }
                    for finding in plan.findings
                ))

                project.commit()
                before = target.read_bytes()
                with self.assertRaises(PlanInputError):
                    apply_plan(
                        project.root,
                        plan,
                        approvals=("review-required-kotlin-nullability-old-dimension",),
                    )
                self.assertEqual(before, target.read_bytes())

                pending = apply_plan(project.root, plan, approvals=())
                self.assertEqual("PENDING_REVIEW", pending.state)
                self.assertEqual(before, target.read_bytes())

                applied = apply_plan(
                    project.root, plan, approvals=(combined[0].finding_id,)
                )
                self.assertEqual("SUCCESS", applied.state)
                merged = target.read_text()
                self.assertIn(f"var id: {new_type} = {new_default}", merged)
                self.assertNotIn(f"var id: {new_type} = {old_default}", merged)

    def test_kotlin_callable_references_block_removal_narrowing_and_nullability_edits(self) -> None:
        cases = (
            (
                "remove-property",
                kotlin_property(
                    "id", "employee_id", "Int", "-1", "/** Employee ID */"
                ),
                kotlin_property("id", "employee_id", "Int", "-1")
                + kotlin_property("legacy", "legacy", "String?", "null"),
                "Employee::legacy",
            ),
            (
                "narrow-basic-type",
                kotlin_property(
                    "id", "employee_id", "Int", "-1", "/** Employee ID */"
                ),
                kotlin_property("id", "employee_id", "Long", "-1L"),
                "Employee::id",
            ),
            (
                "kotlin-nullability",
                kotlin_property(
                    "id", "employee_id", "Int", "-1", "/** Employee ID */"
                ),
                kotlin_property("id", "employee_id", "Int?", "null"),
                "Employee::id",
            ),
        )
        for kind, candidate_properties, existing_properties, reference in cases:
            with self.subTest(kind=kind):
                project = ProjectFixture(self)
                project.existing = project.root / "src/main/kotlin"
                project.existing.mkdir(parents=True)
                project.retain_snapshot_columns("employee_id")
                snapshot = json.loads(project.snapshot.read_text())
                snapshot["tables"][0]["primary_key"] = []
                project.snapshot.write_text(json.dumps(snapshot, separators=(",", ":")) + "\n")
                project.generated_file("kotlin").write_text(
                    kotlin_entity(properties=candidate_properties)
                )
                project.existing_file(kotlin_entity(properties=existing_properties), "kt")
                use = project.existing / "example/entity/Use.kt"
                use.write_text(f"package example.entity\nval retained = {reference}\n")

                finding = next(f for f in project.plan(language="kotlin").findings if f.kind == kind)
                self.assertEqual("BLOCKED", finding.status)
                self.assertFalse(finding.edits)

    def test_kotlin_calls_and_callable_references_block_java_accessor_changes(self) -> None:
        removal_probes = (
            "fun use(e: Employee) = e.getLegacy()",
            "fun use(e: Employee) { e.setLegacy(1) }",
            "val use = Employee::getLegacy",
            "val use = Employee::setLegacy",
        )
        for probe in removal_probes:
            with self.subTest(change="removal", probe=probe):
                project = ProjectFixture(self)
                project.retain_snapshot_columns("employee_id")
                snapshot = json.loads(project.snapshot.read_text())
                snapshot["tables"][0]["columns"][0]["auto_increment"] = False
                project.snapshot.write_text(json.dumps(snapshot, separators=(",", ":")) + "\n")
                project.generated_file().write_text(java_entity(
                    fields=java_field(
                        "id", "employee_id", annotations=("@Id",),
                        doc="/** Employee ID */",
                    ),
                    methods=java_accessors("id"), imports=("org.seasar.doma.Id",),
                ))
                project.existing_file(java_entity(
                    fields=(
                        java_field("id", "employee_id", annotations=("@Id",))
                        + java_field("legacy", "legacy")
                    ),
                    methods=java_accessors("id") + java_accessors("legacy"),
                    imports=("org.seasar.doma.Id",),
                ))
                kotlin_root = project.root / "src/main/kotlin"
                use = kotlin_root / "example/entity/Use.kt"
                use.parent.mkdir(parents=True)
                use.write_text("package example.entity\n" + probe + "\n")

                plan = build_plan(
                    project.root, project.snapshot, project.generated,
                    (project.existing, kotlin_root), "java",
                )
                finding = next(item for item in plan.findings if item.kind == "remove-property")
                self.assertEqual("BLOCKED", finding.status)
                self.assertFalse(finding.edits)

        signature_probes = (
            "fun use(e: Employee) = e.getId()",
            "fun use(e: Employee) { e.setId(1) }",
            "val use = Employee::getId",
            "val use = Employee::setId",
        )
        for probe in signature_probes:
            with self.subTest(change="signature", probe=probe):
                project = ProjectFixture(self)
                project.retain_snapshot_columns("employee_id")
                snapshot = json.loads(project.snapshot.read_text())
                snapshot["tables"][0]["columns"][0]["auto_increment"] = False
                project.snapshot.write_text(json.dumps(snapshot, separators=(",", ":")) + "\n")
                project.generated_file().write_text(java_entity(
                    fields=java_field(
                        "id", "employee_id", "Long", annotations=("@Id",),
                        doc="/** Employee ID */",
                    ),
                    methods=java_accessors("id", "Long"), imports=("org.seasar.doma.Id",),
                ))
                project.existing_file(java_entity(
                    fields=java_field("id", "employee_id", annotations=("@Id",)),
                    methods=java_accessors("id"), imports=("org.seasar.doma.Id",),
                ))
                kotlin_root = project.root / "src/main/kotlin"
                use = kotlin_root / "example/entity/Use.kt"
                use.parent.mkdir(parents=True)
                use.write_text("package example.entity\n" + probe + "\n")

                plan = build_plan(
                    project.root, project.snapshot, project.generated,
                    (project.existing, kotlin_root), "java",
                )
                finding = next(
                    item for item in plan.findings
                    if item.kind in {"widen-basic-type", "narrow-basic-type"}
                )
                self.assertEqual("BLOCKED", finding.status)
                self.assertFalse(finding.edits)

    def test_java_jvm_accessor_references_block_kotlin_changes_with_kotlin_selection(self) -> None:
        cases = (
            (
                "remove-property",
                kotlin_property(
                    "id", "employee_id", "Int", "-1", "/** Employee ID */"
                ),
                kotlin_property("id", "employee_id", "Int", "-1")
                + kotlin_property("legacy", "legacy", "Int", "-1"),
                "class Use { Object use(Employee e) { return e.getLegacy(); } }",
            ),
            (
                "remove-property",
                kotlin_property(
                    "id", "employee_id", "Int", "-1", "/** Employee ID */"
                ),
                kotlin_property("id", "employee_id", "Int", "-1")
                + kotlin_property("isActive", "legacy", "Boolean?", "null"),
                "class Use { java.util.function.Predicate<Employee> p = Employee::isActive; }",
            ),
            (
                "remove-property",
                kotlin_property(
                    "id", "employee_id", "Int", "-1", "/** Employee ID */"
                ),
                kotlin_property("id", "employee_id", "Int", "-1")
                + kotlin_property("isActive", "legacy", "Boolean?", "null"),
                "class Use { void use(Employee e) { e.setActive(true); } }",
            ),
            (
                "narrow-basic-type",
                kotlin_property(
                    "id", "employee_id", "Int", "-1", "/** Employee ID */"
                ),
                kotlin_property("id", "employee_id", "Long", "-1L"),
                "class Use { java.util.function.Function<Employee, Long> f = Employee::getId; }",
            ),
            (
                "kotlin-nullability",
                kotlin_property(
                    "id", "employee_id", "Int?", "null", "/** Employee ID */"
                ),
                kotlin_property("id", "employee_id", "Int", "-1"),
                "class Use { void use(Employee e) { e.setId(1); } }",
            ),
        )
        for kind, candidate_properties, existing_properties, probe in cases:
            with self.subTest(change=kind):
                project = ProjectFixture(self)
                project.existing = project.root / "src/main/kotlin"
                project.existing.mkdir(parents=True)
                project.retain_snapshot_columns("employee_id")
                snapshot = json.loads(project.snapshot.read_text())
                snapshot["tables"][0]["primary_key"] = []
                snapshot["tables"][0]["columns"][0]["auto_increment"] = False
                project.snapshot.write_text(
                    json.dumps(snapshot, separators=(",", ":")) + "\n"
                )
                project.generated_file("kotlin").write_text(
                    kotlin_entity(properties=candidate_properties)
                )
                project.existing_file(kotlin_entity(properties=existing_properties), "kt")
                java_root = project.root / "src/main/java"
                use = java_root / "example/entity/Use.java"
                use.parent.mkdir(parents=True, exist_ok=True)
                use.write_text("package example.entity; " + probe + "\n")

                plan = build_plan(
                    project.root, project.snapshot, project.generated,
                    (java_root, project.existing), "kotlin",
                )
                finding = next(item for item in plan.findings if item.kind == kind)
                self.assertEqual("BLOCKED", finding.status)
                self.assertFalse(finding.edits)

    def test_receiver_scope_references_block_but_unrelated_accessors_do_not(self) -> None:
        cases = (
            (
                "with-receiver",
                {"probe/Use.kt": (
                    "package example.entity\n"
                    "fun use(e: Employee) = with(e) { legacy }\n"
                )},
                "legacy",
                "BLOCKED",
            ),
            (
                "extension-receiver",
                {"probe/Use.kt": (
                    "package example.entity\nfun Employee.use() = legacy\n"
                )},
                "legacy",
                "BLOCKED",
            ),
            (
                "multiline-extension-receiver",
                {"probe/Use.kt": (
                    "package example.entity\n"
                    "fun Employee.use() =\n"
                    "    legacy\n"
                )},
                "legacy",
                "BLOCKED",
            ),
            (
                "alias-extension-receiver",
                {"probe/Use.kt": (
                    "package probe\n"
                    "import example.entity.Employee as Staff\n"
                    "fun Staff.use() = legacy\n"
                )},
                "legacy",
                "BLOCKED",
            ),
            (
                "alias-typed-variable-receiver",
                {"probe/Use.kt": (
                    "package probe\n"
                    "import example.entity.Employee as Staff\n"
                    "fun use(employee: Staff) = employee.legacy\n"
                )},
                "legacy",
                "BLOCKED",
            ),
            (
                "safe-call-receiver",
                {"probe/Use.kt": (
                    "package example.entity\n"
                    "fun use(e: Employee?) = e?.legacy\n"
                )},
                "legacy",
                "BLOCKED",
            ),
            (
                "nonnull-receiver",
                {"probe/Use.kt": (
                    "package example.entity\n"
                    "fun use(e: Employee?) = e!!.legacy\n"
                )},
                "legacy",
                "BLOCKED",
            ),
            (
                "apply-receiver",
                {"probe/Use.kt": (
                    "package example.entity\n"
                    "fun use(e: Employee) = e.apply { legacy.toString() }\n"
                )},
                "legacy",
                "BLOCKED",
            ),
            (
                "run-receiver",
                {"probe/Use.kt": (
                    "package example.entity\n"
                    "fun use(e: Employee) = e.run { getLegacy() }\n"
                )},
                "legacy",
                "BLOCKED",
            ),
            (
                "let-argument",
                {"probe/Use.kt": (
                    "package example.entity\n"
                    "fun use(e: Employee) = e.let { retained -> retained.legacy }\n"
                )},
                "legacy",
                "BLOCKED",
            ),
            (
                "also-argument",
                {"probe/Use.kt": (
                    "package example.entity\n"
                    "fun use(e: Employee) = e.also { it.getLegacy() }\n"
                )},
                "legacy",
                "BLOCKED",
            ),
            (
                "labeled-apply-this",
                {"probe/Use.kt": (
                    "package example.entity\n"
                    "fun use(e: Employee) = e.apply { this@apply.legacy }\n"
                )},
                "legacy",
                "BLOCKED",
            ),
            (
                "labeled-run-this",
                {"probe/Use.kt": (
                    "package example.entity\n"
                    "fun use(e: Employee) = e.run { this@run.getLegacy() }\n"
                )},
                "legacy",
                "BLOCKED",
            ),
            (
                "labeled-apply-lambda",
                {"probe/Use.kt": (
                    "package example.entity\n"
                    "fun use(e: Employee) = e.apply retained@ { legacy }\n"
                )},
                "legacy",
                "BLOCKED",
            ),
            (
                "cross-file-factory-receiver",
                {
                    "probe/Provider.kt": (
                        "package example.service\n"
                        "import example.entity.Employee\n"
                        "fun loadEmployee(): Employee = Employee()\n"
                    ),
                    "probe/Use.kt": (
                        "package example.service\n"
                        "fun use() = with(loadEmployee()) { legacy }\n"
                    ),
                },
                "legacy",
                "BLOCKED",
            ),
            (
                "unrelated-legacy-accessor-same-package",
                {"probe/Other.kt": (
                    "package example.entity\n"
                    "class Other { fun getLegacy() = 1 }\n"
                )},
                "legacy",
                "REVIEW_REQUIRED",
            ),
            (
                "unrelated-id-accessor-same-package",
                {"probe/Other.kt": (
                    "package example.entity\n"
                    "class Other { var id: Int = -1 }\n"
                )},
                "id",
                "REVIEW_REQUIRED",
            ),
        )
        for label, probes, property_name, expected_status in cases:
            with self.subTest(reference=label):
                project = ProjectFixture(self)
                project.retain_snapshot_columns("employee_id")
                snapshot = json.loads(project.snapshot.read_text())
                snapshot["tables"][0]["columns"][0]["auto_increment"] = False
                project.snapshot.write_text(
                    json.dumps(snapshot, separators=(",", ":")) + "\n"
                )
                generated_id_type = "Integer"
                existing_id_type = "Long" if property_name == "id" else "Integer"
                project.generated_file().write_text(java_entity(
                    fields=java_field(
                        "id", "employee_id", generated_id_type,
                        annotations=("@Id",),
                        doc="/** Employee ID */",
                    ),
                    methods=java_accessors("id", generated_id_type),
                    imports=("org.seasar.doma.Id",),
                ))
                project.existing_file(java_entity(
                    fields=(
                        java_field(
                            "id", "employee_id", existing_id_type,
                            annotations=("@Id",),
                            doc="/** Employee ID */",
                        )
                        + java_field("legacy", "legacy")
                    ),
                    methods=(
                        java_accessors("id", existing_id_type)
                        + java_accessors("legacy")
                    ),
                    imports=("org.seasar.doma.Id",),
                ))
                kotlin_root = project.root / "src/main/kotlin"
                for relative, probe in probes.items():
                    use = kotlin_root / relative
                    use.parent.mkdir(parents=True, exist_ok=True)
                    use.write_text(probe)

                plan = build_plan(
                    project.root,
                    project.snapshot,
                    project.generated,
                    (project.existing, kotlin_root),
                    "java",
                )
                expected_kind = (
                    "narrow-basic-type" if property_name == "id"
                    else "remove-property"
                )
                finding = next(
                    item for item in plan.findings if item.kind == expected_kind
                )
                self.assertEqual(expected_status, finding.status)
                self.assertEqual(expected_status != "BLOCKED", bool(finding.edits))

    def test_inferred_entity_assignments_block_property_removal_and_type_changes(self) -> None:
        cases = (
            (
                "kotlin-removal",
                "kt",
                (
                    "package example.entity\n"
                    "val retained = Employee()\n"
                    "fun use() = retained.legacy\n"
                ),
                "remove-property",
                "Integer",
            ),
            (
                "java-removal",
                "java",
                (
                    "package example.entity;\n"
                    "class Use { Object use() { var retained = new Employee(); "
                    "return retained.getLegacy(); } }\n"
                ),
                "remove-property",
                "Integer",
            ),
            (
                "kotlin-widening",
                "kt",
                (
                    "package example.entity\n"
                    "val retained = Employee()\n"
                    "fun use(): Int = retained.id\n"
                ),
                "basic-type-change",
                "Long",
            ),
            (
                "kotlin-qualified-constructor-removal",
                "kt",
                (
                    "package example.entity\n"
                    "val retained = example.entity.Employee()\n"
                    "fun use() = retained.legacy\n"
                ),
                "remove-property",
                "Integer",
            ),
            (
                "java-qualified-constructor-removal",
                "java",
                (
                    "package example.entity;\n"
                    "class Use { Object use() { var retained = "
                    "new example.entity.Employee(); "
                    "return retained.getLegacy(); } }\n"
                ),
                "remove-property",
                "Integer",
            ),
            (
                "kotlin-parenthesized-constructor-widening",
                "kt",
                (
                    "package example.entity\n"
                    "val retained = (Employee())\n"
                    "fun use(): Int = retained.id\n"
                ),
                "basic-type-change",
                "Long",
            ),
            (
                "java-qualified-factory-widening",
                "java",
                (
                    "package example.entity;\n"
                    "class Provider { static Employee loadEmployee() { "
                    "return new Employee(); } }\n"
                    "class Use { Integer use() { var retained = "
                    "Provider.loadEmployee(); return retained.getId(); } }\n"
                ),
                "basic-type-change",
                "Long",
            ),
        )
        for label, suffix, probe, expected_kind, generated_id_type in cases:
            with self.subTest(reference=label):
                project = ProjectFixture(self)
                project.retain_snapshot_columns("employee_id")
                snapshot = json.loads(project.snapshot.read_text())
                snapshot["tables"][0]["columns"][0]["auto_increment"] = False
                project.snapshot.write_text(
                    json.dumps(snapshot, separators=(",", ":")) + "\n"
                )
                project.generated_file().write_text(java_entity(
                    fields=java_field(
                        "id", "employee_id", generated_id_type,
                        annotations=("@Id",), doc="/** Employee ID */",
                    ),
                    methods=java_accessors("id", generated_id_type),
                    imports=("org.seasar.doma.Id",),
                ))
                project.existing_file(java_entity(
                    fields=(
                        java_field(
                            "id", "employee_id", annotations=("@Id",),
                            doc="/** Employee ID */",
                        )
                        + java_field("legacy", "legacy")
                    ),
                    methods=java_accessors("id") + java_accessors("legacy"),
                    imports=("org.seasar.doma.Id",),
                ))
                reference_root = (
                    project.existing if suffix == "java"
                    else project.root / "src/main/kotlin"
                )
                reference = reference_root / f"example/entity/Use.{suffix}"
                reference.parent.mkdir(parents=True, exist_ok=True)
                reference.write_text(probe)

                roots = (
                    (project.existing,)
                    if suffix == "java"
                    else (project.existing, reference_root)
                )
                plan = build_plan(
                    project.root, project.snapshot, project.generated, roots, "java"
                )
                finding = next(
                    item for item in plan.findings
                    if item.kind == expected_kind
                    or expected_kind == "basic-type-change"
                    and item.kind in {"widen-basic-type", "narrow-basic-type"}
                )
                self.assertEqual("BLOCKED", finding.status)
                self.assertFalse(finding.edits)

    def test_kotlin_project_wrapper_factories_fail_closed_for_alias_imports_and_generic_typealiases(self) -> None:
        cases = (
            (
                "factory-import-alias",
                {
                    "probe/Factory.kt": (
                        "package probe\n"
                        "import example.entity.Employee\n"
                        "class Box<T>(val value: T)\n"
                        "fun make(): probe.Box<Employee> = TODO()\n"
                    ),
                    "example/entity/Use.kt": (
                        "package example.entity\n"
                        "import probe.make as create\n"
                        "fun use(): Int = create().value.id\n"
                    ),
                },
            ),
            (
                "factory-generic-typealias-cross-file",
                {
                    "probe/Factory.kt": (
                        "package probe\n"
                        "import example.entity.Employee\n"
                        "class Box<T>(val value: T)\n"
                        "typealias Alias<T> = Box<T>\n"
                        "fun make(): Alias<Employee> = TODO()\n"
                    ),
                    "example/entity/Use.kt": (
                        "package example.entity\n"
                        "import probe.make\n"
                        "fun use(): Int = make().value.id\n"
                    ),
                },
            ),
        )
        for label, probes in cases:
            with self.subTest(reference=label):
                project = ProjectFixture(self)
                project.retain_snapshot_columns("employee_id")
                snapshot = json.loads(project.snapshot.read_text())
                snapshot["tables"][0]["columns"][0]["auto_increment"] = False
                snapshot["tables"][0]["columns"][0].update({
                    "jdbc_type": -5, "type_name": "int8", "size": 64, "scale": 0,
                })
                project.snapshot.write_text(
                    json.dumps(snapshot, separators=(",", ":")) + "\n"
                )
                project.generated_file().write_text(java_entity(
                    fields=java_field(
                        "id", "employee_id", "Long",
                        annotations=("@Id",), doc="/** Employee ID */",
                    ),
                    methods=java_accessors("id", "Long"),
                    imports=("org.seasar.doma.Id",),
                ))
                project.existing_file(java_entity(
                    fields=java_field(
                        "id", "employee_id", "Integer",
                        annotations=("@Id",), doc="/** Employee ID */",
                    ),
                    methods=java_accessors("id", "Integer"),
                    imports=("org.seasar.doma.Id",),
                ))
                kotlin_root = project.root / "src/main/kotlin"
                for relative, probe in probes.items():
                    path = kotlin_root / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(probe)

                plan = build_plan(
                    project.root,
                    project.snapshot,
                    project.generated,
                    (project.existing, kotlin_root),
                    "java",
                )
                finding = next(
                    item for item in plan.findings
                    if item.kind in {"widen-basic-type", "narrow-basic-type"}
                )
                self.assertEqual("BLOCKED", finding.status)
                self.assertFalse(finding.edits)

    def test_generic_collection_get_receivers_block_java_and_kotlin_member_changes(self) -> None:
        compile_temp = tempfile.TemporaryDirectory(prefix="entity-receiver-javac-")
        self.addCleanup(compile_temp.cleanup)
        compile_dir = Path(compile_temp.name)
        compile_package = compile_dir / "example/entity"
        compile_package.mkdir(parents=True)
        (compile_package / "Employee.java").write_text(
            "package example.entity; class Employee { void setId(Integer id) {} }\n",
            encoding="utf-8",
        )
        (compile_package / "Box.java").write_text(
            "package example.entity; class Box<T> { void setId(Integer id) {} }\n",
            encoding="utf-8",
        )
        (compile_package / "Use.java").write_text(
            "package example.entity; import java.util.ArrayList; import java.util.List; "
            "class Use { List<Employee> employees() { return List.of(); } "
            "void direct(List<Employee> es) { es.get(0).setId(1); } "
            "void method() { employees().get(0).setId(1); } "
            "void iterator(List<Employee> es) { es.iterator().next().setId(1); } "
            "void subList(List<Employee> es) { es.subList(0, 1).get(0).setId(1); } "
            "void assigned(List<Employee> source) { var es = source; es.get(0).setId(1); } "
            "void constructed() { var es = new ArrayList<Employee>(); es.get(0).setId(1); } "
            "void unrelated(List<Box<Employee>> es) { es.get(0).setId(1); } }\n",
            encoding="utf-8",
        )
        compiled = subprocess.run(
            ["javac", "-proc:none", *map(str, sorted(compile_package.glob("*.java")))],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, compiled.returncode, compiled.stdout + compiled.stderr)

        cases = (
            (
                "java-list-get",
                "java",
                "package example.entity; import java.util.List; "
                "class Use { void use(List<Employee> es) { es.get(0).setId(1); } }\n",
            ),
            (
                "kotlin-list-get",
                "kt",
                "package example.entity\n"
                "fun use(es: List<Employee>) { es.get(0).id.toString() }\n",
            ),
            (
                "java-assigned-list-get",
                "java",
                "package example.entity; import java.util.List; "
                "class Use { void use(List<Employee> source) { "
                "var es = source; es.get(0).setId(1); } }\n",
            ),
            (
                "kotlin-assigned-list-get",
                "kt",
                "package example.entity\n"
                "fun use(source: List<Employee>) { "
                "val es = source; es.get(0).id.toString() }\n",
            ),
            (
                "java-method-list-get",
                "java",
                "package example.entity; import java.util.List; "
                "class Use { List<Employee> employees() { return List.of(); } "
                "void use() { employees().get(0).setId(1); } }\n",
            ),
            (
                "java-iterator-next",
                "java",
                "package example.entity; import java.util.List; "
                "class Use { void use(List<Employee> es) { "
                "es.iterator().next().setId(1); } }\n",
            ),
            (
                "java-sublist-get",
                "java",
                "package example.entity; import java.util.List; "
                "class Use { void use(List<Employee> es) { "
                "es.subList(0, 1).get(0).setId(1); } }\n",
            ),
            (
                "java-constructed-list-get",
                "java",
                "package example.entity; import java.util.ArrayList; "
                "class Use { void use() { var es = new ArrayList<Employee>(); "
                "es.get(0).setId(1); } }\n",
            ),
            (
                "kotlin-index",
                "kt",
                "package example.entity\n"
                "fun use(es: List<Employee>) { es[0].id.toString() }\n",
            ),
            (
                "kotlin-filter-first",
                "kt",
                "package example.entity\n"
                "fun use(es: List<Employee>) { "
                "es.filter { true }.first().id.toString() }\n",
            ),
            (
                "kotlin-function-first",
                "kt",
                "package example.entity\n"
                "fun employees(): List<Employee> = emptyList()\n"
                "fun use() { employees().first().id.toString() }\n",
            ),
            (
                "java-field-after-shadow",
                "java",
                "package example.entity; import java.util.List; "
                "class Box<T> {} class Use { List<Employee> es; "
                "void shadow(List<Box<Employee>> es) { es.size(); } "
                "void use() { es.get(0).setId(1); } }\n",
            ),
            (
                "kotlin-property-after-shadow",
                "kt",
                "package example.entity\n"
                "class Box<T>\n"
                "val es: List<Employee> = emptyList()\n"
                "fun shadow(es: List<Box<Employee>>) = es.size.toString()\n"
                "fun use() = es[0].id.toString()\n",
            ),
        )
        for label, suffix, probe in cases:
            with self.subTest(receiver=label):
                project = ProjectFixture(self)
                project.retain_snapshot_columns("employee_id")
                snapshot = json.loads(project.snapshot.read_text(encoding="utf-8"))
                snapshot["tables"][0]["columns"][0]["auto_increment"] = False
                snapshot["tables"][0]["columns"][0].update({
                    "jdbc_type": -5, "type_name": "int8", "size": 64, "scale": 0,
                })
                project.snapshot.write_text(
                    json.dumps(snapshot, separators=(",", ":")) + "\n",
                    encoding="utf-8",
                )
                project.generated_file().write_text(java_entity(
                    fields=java_field(
                        "id", "employee_id", "Long", annotations=("@Id",),
                        doc="/** Employee ID */",
                    ),
                    methods=java_accessors("id", "Long"),
                    imports=("org.seasar.doma.Id",),
                ))
                target = project.existing_file(java_entity(
                    fields=java_field(
                        "id", "employee_id", "Integer", annotations=("@Id",),
                        doc="/** Employee ID */",
                    ),
                    methods=java_accessors("id", "Integer"),
                    imports=("org.seasar.doma.Id",),
                ))
                reference_root = (
                    project.existing if suffix == "java"
                    else project.root / "src/main/kotlin"
                )
                reference = reference_root / f"example/entity/Use.{suffix}"
                reference.parent.mkdir(parents=True, exist_ok=True)
                reference.write_text(probe, encoding="utf-8")
                roots = (
                    (project.existing,)
                    if suffix == "java"
                    else (project.existing, reference_root)
                )

                plan = build_plan(
                    project.root, project.snapshot, project.generated, roots, "java"
                )
                finding = next(
                    item for item in plan.findings
                    if item.kind in {"widen-basic-type", "narrow-basic-type"}
                )
                self.assertEqual("BLOCKED", finding.status)
                self.assertFalse(finding.edits)
                before = target.read_bytes()
                project.commit()
                result = apply_plan(project.root, plan, approvals=())
                self.assertEqual("BLOCKED", result.state)
                self.assertEqual(before, target.read_bytes())

        unrelated_cases = (
            (
                "java-nested-generic",
                "java",
                "package example.entity; import java.util.List; "
                "class Box<T> { void setId(Integer id) {} } "
                "class Use { void use(List<Box<Employee>> es) { "
                "es.get(0).setId(1); } }\n",
            ),
            (
                "kotlin-nested-generic",
                "kt",
                "package example.entity\n"
                "class Box<T>(var id: Int)\n"
                "fun use(es: List<Box<Employee>>) { es.get(0).id.toString() }\n",
            ),
            (
                "java-member-after-entity",
                "java",
                "package example.entity; import java.util.List; "
                "class Holder { Integer getId() { return 1; } } "
                "class Use { void use(List<Employee> es) { "
                "es.get(0).getOther().getId(); } }\n",
            ),
            (
                "kotlin-member-after-entity",
                "kt",
                "package example.entity\n"
                "class Holder(var id: Int)\n"
                "fun use(es: List<Employee>) { es[0].other.id.toString() }\n",
            ),
            (
                "java-same-name-nested-generic-shadow",
                "java",
                "package example.entity; import java.util.List; "
                "class Box<T> { void setId(Integer id) {} } "
                "class Use { void boxList(List<Box<Employee>> es) { "
                "es.get(0).setId(1); } "
                "void entityList(List<Employee> es) { es.size(); } }\n",
            ),
            (
                "kotlin-same-name-nested-generic-shadow",
                "kt",
                "package example.entity\n"
                "class Box<T>(var id: Int)\n"
                "fun boxList(es: List<Box<Employee>>) { es[0].id.toString() }\n"
                "fun entityList(es: List<Employee>) { es.size.toString() }\n",
            ),
        )
        for label, suffix, probe in unrelated_cases:
            with self.subTest(receiver=label):
                project = ProjectFixture(self)
                project.retain_snapshot_columns("employee_id")
                snapshot = json.loads(project.snapshot.read_text(encoding="utf-8"))
                snapshot["tables"][0]["columns"][0]["auto_increment"] = False
                snapshot["tables"][0]["columns"][0].update({
                    "jdbc_type": -5, "type_name": "int8", "size": 64, "scale": 0,
                })
                project.snapshot.write_text(
                    json.dumps(snapshot, separators=(",", ":")) + "\n",
                    encoding="utf-8",
                )
                project.generated_file().write_text(java_entity(
                    fields=java_field(
                        "id", "employee_id", "Long", annotations=("@Id",),
                        doc="/** Employee ID */",
                    ),
                    methods=java_accessors("id", "Long"),
                    imports=("org.seasar.doma.Id",),
                ))
                project.existing_file(java_entity(
                    fields=java_field(
                        "id", "employee_id", "Integer", annotations=("@Id",),
                        doc="/** Employee ID */",
                    ),
                    methods=java_accessors("id", "Integer"),
                    imports=("org.seasar.doma.Id",),
                ))
                reference_root = (
                    project.existing if suffix == "java"
                    else project.root / "src/main/kotlin"
                )
                reference = reference_root / f"example/entity/Use.{suffix}"
                reference.parent.mkdir(parents=True, exist_ok=True)
                reference.write_text(probe, encoding="utf-8")
                roots = (
                    (project.existing,)
                    if suffix == "java"
                    else (project.existing, reference_root)
                )

                plan = build_plan(
                    project.root, project.snapshot, project.generated, roots, "java"
                )
                finding = next(
                    item for item in plan.findings
                    if item.kind in {"widen-basic-type", "narrow-basic-type"}
                )
                self.assertEqual("SAFE", finding.status)
                self.assertTrue(finding.edits)

    def test_qualified_alias_cast_and_test_source_receivers_block_type_changes(self) -> None:
        """Never change an Entity API while a non-target source can call it.

        These are deliberately ordinary handwritten call sites that compile before
        the proposed ``Integer`` -> ``Long`` Entity change and fail afterwards.
        The planner may be conservative, but it must not emit executable edits.
        """
        cases = (
            (
                "java-imported-map",
                "src/main/java/probe/Use.java",
                "package probe; import java.util.Map; import example.entity.Employee; "
                "class Use { Integer f(Map<String, Employee> xs, String key) { "
                "return xs.get(key).getId(); } }\n",
            ),
            (
                "java-fqcn-map",
                "src/main/java/probe/Use.java",
                "package probe; import java.util.Map; class Use { Integer f("
                "Map<String, example.entity.Employee> xs, String key) { "
                "return xs.get(key).getId(); } }\n",
            ),
            (
                "java-cast",
                "src/main/java/probe/Use.java",
                "package probe; import example.entity.Employee; class Use { "
                "Integer f(Object value) { return ((Employee) value).getId(); } }\n",
            ),
            (
                "java-optional-generic",
                "src/main/java/probe/Use.java",
                "package probe; import java.util.Optional; import example.entity.Employee; "
                "class Use { Integer f(Optional<Employee> value) { "
                "return value.orElseThrow().getId(); } }\n",
            ),
            (
                "java-custom-generic",
                "src/main/java/probe/Use.java",
                "package probe; import example.entity.Employee; "
                "class Box<T> { T unwrap() { return null; } } "
                "class Use { Integer f(Box<Employee> value) { "
                "return value.unwrap().getId(); } }\n",
            ),
            (
                "java-generic-factory-wrapper",
                "src/main/java/probe/Use.java",
                "package probe; import java.util.Optional; import example.entity.Employee; "
                "class Use { Optional<Employee> load() { return Optional.empty(); } "
                "Integer use() { return load().orElseThrow().getId(); } }\n",
            ),
            (
                "java-fqcn-variable",
                "src/main/java/probe/Use.java",
                "package probe; class Use { Integer f(example.entity.Employee value) { "
                "return value.getId(); } }\n",
            ),
            (
                "java-test-source",
                "src/test/java/probe/Use.java",
                "package probe; import example.entity.Employee; class Use { "
                "Integer f(Employee e) { return e.getId(); } }\n",
            ),
            (
                "kotlin-alias-collection",
                "src/main/kotlin/probe/Use.kt",
                "package probe\nimport example.entity.Employee as Staff\n"
                "fun use(xs: List<Staff>): Int = xs.first().id\n",
            ),
            (
                "kotlin-fqcn-collection",
                "src/main/kotlin/probe/Use.kt",
                "package probe\nfun use(xs: List<example.entity.Employee>): Int = "
                "xs.first().id\n",
            ),
            (
                "kotlin-cast",
                "src/main/kotlin/probe/Use.kt",
                "package probe\nimport example.entity.Employee\n"
                "fun use(value: Any): Int = ((value as Employee)).id\n",
            ),
            (
                "kotlin-typealias",
                "src/main/kotlin/probe/Use.kt",
                "package probe\nimport example.entity.Employee\n"
                "typealias Staff = Employee\nfun use(e: Staff): Int = e.id\n",
            ),
            (
                "kotlin-result-generic",
                "src/main/kotlin/probe/Use.kt",
                "package probe\nimport example.entity.Employee\n"
                "fun use(value: Result<Employee>): Int = value.getOrThrow().id\n",
            ),
            (
                "kotlin-optional-like-generic",
                "src/main/kotlin/probe/Use.kt",
                "package probe\nimport example.entity.Employee\n"
                "class Box<T>(private val value: T) { fun get(): T = value }\n"
                "fun use(box: Box<Employee>): Int = box.get().id\n",
            ),
            (
                "kotlin-custom-generic-property",
                "src/main/kotlin/probe/Use.kt",
                "package probe\nimport example.entity.Employee\n"
                "class Box<T>(val value: T) { fun unwrap(): T = value }\n"
                "fun use(box: Box<Employee>): Int = box.unwrap().id + box.value.id\n",
            ),
            (
                "kotlin-custom-generic-property-only",
                "src/main/kotlin/probe/Use.kt",
                "package probe\nimport example.entity.Employee\n"
                "class Box<T>(val value: T)\n"
                "fun use(box: Box<Employee>): Int = box.value.id\n",
            ),
            (
                "kotlin-generic-typealias-wrapper",
                "src/main/kotlin/probe/Use.kt",
                "package probe\nimport example.entity.Employee\n"
                "class Box<T>(val value: T)\n"
                "typealias StaffBox = Box<Employee>\n"
                "fun use(box: StaffBox): Int = box.value.id\n",
            ),
            (
                "kotlin-nullable-entity",
                "src/main/kotlin/probe/Use.kt",
                "package probe\nimport example.entity.Employee\n"
                "fun use(value: Employee?): Int = value!!.id\n",
            ),
            (
                "kotlin-nullable-alias",
                "src/main/kotlin/probe/Use.kt",
                "package probe\nimport example.entity.Employee as Staff\n"
                "fun use(value: Staff?): Int = value!!.id\n",
            ),
            (
                "kotlin-nullable-fqcn",
                "src/main/kotlin/probe/Use.kt",
                "package probe\nfun use(value: example.entity.Employee?): Int = value!!.id\n",
            ),
        )
        for label, relative, reference in cases:
            with self.subTest(receiver=label):
                project = ProjectFixture(self)
                project.retain_snapshot_columns("employee_id")
                snapshot = json.loads(project.snapshot.read_text(encoding="utf-8"))
                snapshot["tables"][0]["columns"][0].update({
                    "jdbc_type": -5, "type_name": "int8", "size": 64,
                    "scale": 0, "auto_increment": False,
                })
                project.snapshot.write_text(
                    json.dumps(snapshot, separators=(",", ":")) + "\n",
                    encoding="utf-8",
                )
                project.generated_file().write_text(java_entity(
                    fields=java_field(
                        "id", "employee_id", "Long", annotations=("@Id",),
                        doc="/** Employee ID */",
                    ),
                    methods=java_accessors("id", "Long"),
                    imports=("org.seasar.doma.Id",),
                ), encoding="utf-8")
                target = project.existing_file(java_entity(
                    fields=java_field(
                        "id", "employee_id", "Integer", annotations=("@Id",),
                        doc="/** Employee ID */",
                    ),
                    methods=java_accessors("id", "Integer"),
                    imports=("org.seasar.doma.Id",),
                ))
                (project.root / "src/main/kotlin").mkdir(parents=True, exist_ok=True)
                probe = project.root / relative
                probe.parent.mkdir(parents=True, exist_ok=True)
                probe.write_text(reference, encoding="utf-8")

                plan = build_plan(
                    project.root, project.snapshot, project.generated,
                    (project.existing, project.root / "src/main/kotlin"), "java",
                )
                finding = next(
                    item for item in plan.findings
                    if item.kind in {"widen-basic-type", "narrow-basic-type"}
                )
                self.assertEqual("BLOCKED", finding.status)
                self.assertFalse(finding.edits)
                self.assertIn(relative, dict(plan.source_hashes))
                before = target.read_bytes()
                project.commit()
                result = apply_plan(project.root, plan, approvals=())
                self.assertEqual("BLOCKED", result.state)
                self.assertEqual(before, target.read_bytes())

    def test_imported_direct_generic_kotlin_typealias_blocks_type_change(self) -> None:
        project = ProjectFixture(self)
        project.retain_snapshot_columns("employee_id")
        snapshot = json.loads(project.snapshot.read_text(encoding="utf-8"))
        snapshot["tables"][0]["columns"][0].update({
            "jdbc_type": -5, "type_name": "int8", "size": 64,
            "scale": 0, "auto_increment": False,
        })
        project.snapshot.write_text(
            json.dumps(snapshot, separators=(",", ":")) + "\n", encoding="utf-8"
        )
        project.generated_file().write_text(java_entity(
            fields=java_field("id", "employee_id", "Long", annotations=("@Id",), doc="/** Employee ID */"),
            methods=java_accessors("id", "Long"), imports=("org.seasar.doma.Id",),
        ), encoding="utf-8")
        target = project.existing_file(java_entity(
            fields=java_field("id", "employee_id", "Integer", annotations=("@Id",), doc="/** Employee ID */"),
            methods=java_accessors("id", "Integer"), imports=("org.seasar.doma.Id",),
        ))
        source_root = project.root / "src/main/kotlin/probe"
        source_root.mkdir(parents=True, exist_ok=True)
        (source_root / "Alias.kt").write_text(
            "package probe\nimport example.entity.Employee\n"
            "class Box<T>(val value: T)\n"
            "typealias StaffBox = probe.Box<Employee>\n",
            encoding="utf-8",
        )
        consumer_root = project.root / "src/main/kotlin/consumer"
        consumer_root.mkdir(parents=True, exist_ok=True)
        (consumer_root / "Use.kt").write_text(
            "package consumer\nimport probe.StaffBox as Staff\n"
            "fun use(box: Staff): Int = box.value.id\n",
            encoding="utf-8",
        )

        plan = build_plan(
            project.root, project.snapshot, project.generated,
            (project.existing, project.root / "src/main/kotlin"), "java",
        )
        finding = next(
            item for item in plan.findings
            if item.kind in {"widen-basic-type", "narrow-basic-type"}
        )
        self.assertEqual("BLOCKED", finding.status)
        self.assertFalse(finding.edits)
        before = target.read_bytes()
        project.commit()
        self.assertEqual("BLOCKED", apply_plan(project.root, plan, approvals=()).state)
        self.assertEqual(before, target.read_bytes())

    def test_star_imported_project_local_direct_wrapper_alias_blocks_type_change(self) -> None:
        """A project-local star import can expose a direct Entity wrapper alias."""
        project = ProjectFixture(self)
        project.retain_snapshot_columns("employee_id")
        snapshot = json.loads(project.snapshot.read_text(encoding="utf-8"))
        snapshot["tables"][0]["columns"][0].update({
            "jdbc_type": -5, "type_name": "int8", "size": 64,
            "scale": 0, "auto_increment": False,
        })
        project.snapshot.write_text(
            json.dumps(snapshot, separators=(",", ":")) + "\n", encoding="utf-8"
        )
        project.generated_file().write_text(java_entity(
            fields=java_field("id", "employee_id", "Long", annotations=("@Id",), doc="/** Employee ID */"),
            methods=java_accessors("id", "Long"), imports=("org.seasar.doma.Id",),
        ), encoding="utf-8")
        target = project.existing_file(java_entity(
            fields=java_field("id", "employee_id", "Integer", annotations=("@Id",), doc="/** Employee ID */"),
            methods=java_accessors("id", "Integer"), imports=("org.seasar.doma.Id",),
        ))
        probe = project.root / "src/main/kotlin/probe"
        probe.mkdir(parents=True, exist_ok=True)
        (probe / "Alias.kt").write_text(
            "package probe\nimport example.entity.Employee\n"
            "class Box<T>(val value: T)\n"
            "typealias StaffBox = Box<Employee>\n", encoding="utf-8"
        )
        consumer = project.root / "src/main/kotlin/consumer"
        consumer.mkdir(parents=True, exist_ok=True)
        (consumer / "Use.kt").write_text(
            "package consumer\nimport probe.*\n"
            "fun use(box: StaffBox): Int = box.value.id\n", encoding="utf-8"
        )

        plan = build_plan(
            project.root, project.snapshot, project.generated,
            (project.existing, project.root / "src/main/kotlin"), "java",
        )
        finding = next(
            item for item in plan.findings
            if item.kind in {"widen-basic-type", "narrow-basic-type"}
        )
        self.assertEqual("BLOCKED", finding.status)
        self.assertFalse(finding.edits)
        before = target.read_bytes()
        project.commit()
        self.assertEqual("BLOCKED", apply_plan(project.root, plan, approvals=()).state)
        self.assertEqual(before, target.read_bytes())

    def test_direct_wrapper_alias_factory_return_blocks_type_change(self) -> None:
        """An alias-expanded direct wrapper factory remains an Entity receiver."""
        project = ProjectFixture(self)
        project.retain_snapshot_columns("employee_id")
        snapshot = json.loads(project.snapshot.read_text(encoding="utf-8"))
        snapshot["tables"][0]["columns"][0].update({
            "jdbc_type": -5, "type_name": "int8", "size": 64,
            "scale": 0, "auto_increment": False,
        })
        project.snapshot.write_text(
            json.dumps(snapshot, separators=(",", ":")) + "\n", encoding="utf-8"
        )
        project.generated_file().write_text(java_entity(
            fields=java_field("id", "employee_id", "Long", annotations=("@Id",), doc="/** Employee ID */"),
            methods=java_accessors("id", "Long"), imports=("org.seasar.doma.Id",),
        ), encoding="utf-8")
        target = project.existing_file(java_entity(
            fields=java_field("id", "employee_id", "Integer", annotations=("@Id",), doc="/** Employee ID */"),
            methods=java_accessors("id", "Integer"), imports=("org.seasar.doma.Id",),
        ))
        probe = project.root / "src/main/kotlin/probe"
        probe.mkdir(parents=True, exist_ok=True)
        (probe / "Use.kt").write_text(
            "package probe\nimport example.entity.Employee\n"
            "class Box<T>(val value: T)\n"
            "typealias StaffBox = Box<Employee>\n"
            "fun load(): StaffBox = TODO()\n"
            "fun use(): Int = load().value.id\n", encoding="utf-8"
        )

        plan = build_plan(
            project.root, project.snapshot, project.generated,
            (project.existing, project.root / "src/main/kotlin"), "java",
        )
        finding = next(
            item for item in plan.findings
            if item.kind in {"widen-basic-type", "narrow-basic-type"}
        )
        self.assertEqual("BLOCKED", finding.status)
        self.assertFalse(finding.edits)
        before = target.read_bytes()
        project.commit()
        self.assertEqual("BLOCKED", apply_plan(project.root, plan, approvals=()).state)
        self.assertEqual(before, target.read_bytes())

    def test_generic_direct_wrapper_alias_blocks_type_change(self) -> None:
        """A generic typealias still directly exposes the Entity argument."""
        project = ProjectFixture(self)
        project.retain_snapshot_columns("employee_id")
        snapshot = json.loads(project.snapshot.read_text(encoding="utf-8"))
        snapshot["tables"][0]["columns"][0].update({
            "jdbc_type": -5, "type_name": "int8", "size": 64,
            "scale": 0, "auto_increment": False,
        })
        project.snapshot.write_text(
            json.dumps(snapshot, separators=(",", ":")) + "\n", encoding="utf-8"
        )
        project.generated_file().write_text(java_entity(
            fields=java_field("id", "employee_id", "Long", annotations=("@Id",), doc="/** Employee ID */"),
            methods=java_accessors("id", "Long"), imports=("org.seasar.doma.Id",),
        ), encoding="utf-8")
        target = project.existing_file(java_entity(
            fields=java_field("id", "employee_id", "Integer", annotations=("@Id",), doc="/** Employee ID */"),
            methods=java_accessors("id", "Integer"), imports=("org.seasar.doma.Id",),
        ))
        probe = project.root / "src/main/kotlin/probe"
        probe.mkdir(parents=True, exist_ok=True)
        (probe / "Alias.kt").write_text(
            "package probe\nimport example.entity.Employee\n"
            "class Box<T>(val value: T)\n"
            "typealias StaffBox<T> = Box<Employee>\n", encoding="utf-8"
        )
        consumer = project.root / "src/main/kotlin/consumer"
        consumer.mkdir(parents=True, exist_ok=True)
        (consumer / "Use.kt").write_text(
            "package consumer\nimport probe.StaffBox\n"
            "fun use(box: StaffBox<String>): Int = box.value.id\n", encoding="utf-8"
        )

        plan = build_plan(
            project.root, project.snapshot, project.generated,
            (project.existing, project.root / "src/main/kotlin"), "java",
        )
        finding = next(
            item for item in plan.findings
            if item.kind in {"widen-basic-type", "narrow-basic-type"}
        )
        self.assertEqual("BLOCKED", finding.status)
        self.assertFalse(finding.edits)
        before = target.read_bytes()
        project.commit()
        self.assertEqual("BLOCKED", apply_plan(project.root, plan, approvals=()).state)
        self.assertEqual(before, target.read_bytes())

    def test_generic_alias_substitution_to_entity_blocks_type_change(self) -> None:
        """A typealias parameter instantiated with the Entity is a wrapper use."""
        project = ProjectFixture(self)
        project.retain_snapshot_columns("employee_id")
        snapshot = json.loads(project.snapshot.read_text(encoding="utf-8"))
        snapshot["tables"][0]["columns"][0].update({
            "jdbc_type": -5, "type_name": "int8", "size": 64,
            "scale": 0, "auto_increment": False,
        })
        project.snapshot.write_text(json.dumps(snapshot, separators=(",", ":")) + "\n")
        project.generated_file().write_text(java_entity(
            fields=java_field("id", "employee_id", "Long", annotations=("@Id",), doc="/** Employee ID */"),
            methods=java_accessors("id", "Long"), imports=("org.seasar.doma.Id",),
        ))
        target = project.existing_file(java_entity(
            fields=java_field("id", "employee_id", "Integer", annotations=("@Id",), doc="/** Employee ID */"),
            methods=java_accessors("id", "Integer"), imports=("org.seasar.doma.Id",),
        ))
        probe = project.root / "src/main/kotlin/probe"
        probe.mkdir(parents=True, exist_ok=True)
        (probe / "Alias.kt").write_text(
            "package probe\nimport example.entity.Employee\n"
            "class Box<T>(val value: T)\n"
            "typealias Alias<T> = Box<T>\n"
            "fun use(box: Alias<Employee>): Int = box.value.id\n"
        )
        plan = build_plan(project.root, project.snapshot, project.generated,
                          (project.existing, project.root / "src/main/kotlin"), "java")
        finding = next(item for item in plan.findings
                       if item.kind in {"widen-basic-type", "narrow-basic-type"})
        self.assertEqual("BLOCKED", finding.status)
        self.assertFalse(finding.edits)
        before = target.read_bytes()
        project.commit()
        self.assertEqual("BLOCKED", apply_plan(project.root, plan).state)
        self.assertEqual(before, target.read_bytes())

    def test_imported_alias_wrapper_factory_blocks_type_change(self) -> None:
        """A visible project-local factory returning an alias keeps wrapper state."""
        project = ProjectFixture(self)
        project.retain_snapshot_columns("employee_id")
        snapshot = json.loads(project.snapshot.read_text(encoding="utf-8"))
        snapshot["tables"][0]["columns"][0].update({
            "jdbc_type": -5, "type_name": "int8", "size": 64,
            "scale": 0, "auto_increment": False,
        })
        project.snapshot.write_text(json.dumps(snapshot, separators=(",", ":")) + "\n")
        project.generated_file().write_text(java_entity(
            fields=java_field("id", "employee_id", "Long", annotations=("@Id",), doc="/** Employee ID */"),
            methods=java_accessors("id", "Long"), imports=("org.seasar.doma.Id",),
        ))
        target = project.existing_file(java_entity(
            fields=java_field("id", "employee_id", "Integer", annotations=("@Id",), doc="/** Employee ID */"),
            methods=java_accessors("id", "Integer"), imports=("org.seasar.doma.Id",),
        ))
        probe = project.root / "src/main/kotlin/probe"
        probe.mkdir(parents=True, exist_ok=True)
        (probe / "Factory.kt").write_text(
            "package probe\nimport example.entity.Employee\n"
            "class Box<T>(val value: T)\n"
            "typealias StaffBox = Box<Employee>\n"
            "fun make(): StaffBox = TODO()\n"
        )
        consumer = project.root / "src/main/kotlin/consumer"
        consumer.mkdir(parents=True, exist_ok=True)
        (consumer / "Use.kt").write_text(
            "package consumer\nimport probe.*\n"
            "fun use(): Int = make().value.id\n"
        )
        plan = build_plan(project.root, project.snapshot, project.generated,
                          (project.existing, project.root / "src/main/kotlin"), "java")
        finding = next(item for item in plan.findings
                       if item.kind in {"widen-basic-type", "narrow-basic-type"})
        self.assertEqual("BLOCKED", finding.status)
        self.assertFalse(finding.edits)
        before = target.read_bytes()
        project.commit()
        self.assertEqual("BLOCKED", apply_plan(project.root, plan).state)
        self.assertEqual(before, target.read_bytes())

    def test_qualified_alias_wrapper_factory_blocks_type_change(self) -> None:
        """A qualified project-local alias return keeps wrapper state across files."""
        project = ProjectFixture(self)
        project.retain_snapshot_columns("employee_id")
        snapshot = json.loads(project.snapshot.read_text(encoding="utf-8"))
        snapshot["tables"][0]["columns"][0].update({
            "jdbc_type": -5, "type_name": "int8", "size": 64,
            "scale": 0, "auto_increment": False,
        })
        project.snapshot.write_text(json.dumps(snapshot, separators=(",", ":")) + "\n")
        project.generated_file().write_text(java_entity(
            fields=java_field("id", "employee_id", "Long", annotations=("@Id",), doc="/** Employee ID */"),
            methods=java_accessors("id", "Long"), imports=("org.seasar.doma.Id",),
        ))
        target = project.existing_file(java_entity(
            fields=java_field("id", "employee_id", "Integer", annotations=("@Id",), doc="/** Employee ID */"),
            methods=java_accessors("id", "Integer"), imports=("org.seasar.doma.Id",),
        ))
        probe = project.root / "src/main/kotlin/probe"
        probe.mkdir(parents=True, exist_ok=True)
        (probe / "Factory.kt").write_text(
            "package probe\nimport example.entity.Employee\n"
            "class Box<T>(val value: T)\n"
            "typealias StaffBox = Box<Employee>\n"
            "fun make(): probe.StaffBox = TODO()\n"
        )
        consumer = project.root / "src/main/kotlin/consumer"
        consumer.mkdir(parents=True, exist_ok=True)
        (consumer / "Use.kt").write_text(
            "package consumer\nimport probe.make\n"
            "fun use(): Int = make().value.id\n"
        )
        plan = build_plan(project.root, project.snapshot, project.generated,
                          (project.existing, project.root / "src/main/kotlin"), "java")
        finding = next(item for item in plan.findings
                       if item.kind in {"widen-basic-type", "narrow-basic-type"})
        self.assertEqual("BLOCKED", finding.status)
        self.assertFalse(finding.edits)
        before = target.read_bytes()
        project.commit()
        self.assertEqual("BLOCKED", apply_plan(project.root, plan).state)
        self.assertEqual(before, target.read_bytes())

    def test_qualified_generic_wrapper_factory_blocks_type_change(self) -> None:
        """A qualified project-local generic return keeps wrapper state across files."""
        project = ProjectFixture(self)
        project.retain_snapshot_columns("employee_id")
        snapshot = json.loads(project.snapshot.read_text(encoding="utf-8"))
        snapshot["tables"][0]["columns"][0].update({
            "jdbc_type": -5, "type_name": "int8", "size": 64,
            "scale": 0, "auto_increment": False,
        })
        project.snapshot.write_text(json.dumps(snapshot, separators=(",", ":")) + "\n")
        project.generated_file().write_text(java_entity(
            fields=java_field("id", "employee_id", "Long", annotations=("@Id",), doc="/** Employee ID */"),
            methods=java_accessors("id", "Long"), imports=("org.seasar.doma.Id",),
        ))
        target = project.existing_file(java_entity(
            fields=java_field("id", "employee_id", "Integer", annotations=("@Id",), doc="/** Employee ID */"),
            methods=java_accessors("id", "Integer"), imports=("org.seasar.doma.Id",),
        ))
        probe = project.root / "src/main/kotlin/probe"
        probe.mkdir(parents=True, exist_ok=True)
        (probe / "Factory.kt").write_text(
            "package probe\nimport example.entity.Employee\n"
            "class Box<T>(val value: T)\n"
            "fun make(): probe.Box<Employee> = TODO()\n"
        )
        consumer = project.root / "src/main/kotlin/consumer"
        consumer.mkdir(parents=True, exist_ok=True)
        (consumer / "Use.kt").write_text(
            "package consumer\nimport probe.make\n"
            "fun use(): Int = make().value.id\n"
        )
        plan = build_plan(project.root, project.snapshot, project.generated,
                          (project.existing, project.root / "src/main/kotlin"), "java")
        finding = next(item for item in plan.findings
                       if item.kind in {"widen-basic-type", "narrow-basic-type"})
        self.assertEqual("BLOCKED", finding.status)
        self.assertFalse(finding.edits)
        before = target.read_bytes()
        project.commit()
        self.assertEqual("BLOCKED", apply_plan(project.root, plan).state)
        self.assertEqual(before, target.read_bytes())

    def test_alias_wrapper_java_accessor_and_method_reference_block_type_change(self) -> None:
        """Wrapper chains protect both Java getter calls and callable references."""
        project = ProjectFixture(self)
        project.retain_snapshot_columns("employee_id")
        snapshot = json.loads(project.snapshot.read_text(encoding="utf-8"))
        snapshot["tables"][0]["columns"][0].update({
            "jdbc_type": -5, "type_name": "int8", "size": 64,
            "scale": 0, "auto_increment": False,
        })
        project.snapshot.write_text(json.dumps(snapshot, separators=(",", ":")) + "\n")
        project.generated_file().write_text(java_entity(
            fields=java_field("id", "employee_id", "Long", annotations=("@Id",), doc="/** Employee ID */"),
            methods=java_accessors("id", "Long"), imports=("org.seasar.doma.Id",),
        ))
        target = project.existing_file(java_entity(
            fields=java_field("id", "employee_id", "Integer", annotations=("@Id",), doc="/** Employee ID */"),
            methods=java_accessors("id", "Integer"), imports=("org.seasar.doma.Id",),
        ))
        probe = project.root / "src/main/kotlin/probe"
        probe.mkdir(parents=True, exist_ok=True)
        (probe / "Use.kt").write_text(
            "package probe\nimport example.entity.Employee\n"
            "class Box<T>(val value: T)\n"
            "typealias StaffBox = Box<Employee>\n"
            "fun use(box: StaffBox): Int = box.value.getId()\n"
            "fun ref(box: StaffBox) = box.value::getId\n"
        )
        plan = build_plan(project.root, project.snapshot, project.generated,
                          (project.existing, project.root / "src/main/kotlin"), "java")
        finding = next(item for item in plan.findings
                       if item.kind in {"widen-basic-type", "narrow-basic-type"})
        self.assertEqual("BLOCKED", finding.status)
        self.assertFalse(finding.edits)
        before = target.read_bytes()
        project.commit()
        self.assertEqual("BLOCKED", apply_plan(project.root, plan).state)
        self.assertEqual(before, target.read_bytes())

    def test_alias_wrapper_method_reference_alone_blocks_type_change(self) -> None:
        """A callable reference cannot be masked by a separate direct getter call."""
        project = ProjectFixture(self)
        project.retain_snapshot_columns("employee_id")
        snapshot = json.loads(project.snapshot.read_text(encoding="utf-8"))
        snapshot["tables"][0]["columns"][0].update({
            "jdbc_type": -5, "type_name": "int8", "size": 64,
            "scale": 0, "auto_increment": False,
        })
        project.snapshot.write_text(json.dumps(snapshot, separators=(",", ":")) + "\n")
        project.generated_file().write_text(java_entity(
            fields=java_field("id", "employee_id", "Long", annotations=("@Id",), doc="/** Employee ID */"),
            methods=java_accessors("id", "Long"), imports=("org.seasar.doma.Id",),
        ))
        target = project.existing_file(java_entity(
            fields=java_field("id", "employee_id", "Integer", annotations=("@Id",), doc="/** Employee ID */"),
            methods=java_accessors("id", "Integer"), imports=("org.seasar.doma.Id",),
        ))
        probe = project.root / "src/main/kotlin/probe"
        probe.mkdir(parents=True, exist_ok=True)
        (probe / "Use.kt").write_text(
            "package probe\nimport example.entity.Employee\n"
            "class Box<T>(val value: T)\n"
            "typealias StaffBox = Box<Employee>\n"
            "fun ref(box: StaffBox) = box.value::getId\n"
        )
        plan = build_plan(project.root, project.snapshot, project.generated,
                          (project.existing, project.root / "src/main/kotlin"), "java")
        finding = next(item for item in plan.findings
                       if item.kind in {"widen-basic-type", "narrow-basic-type"})
        self.assertEqual("BLOCKED", finding.status)
        self.assertFalse(finding.edits)
        before = target.read_bytes()
        project.commit()
        self.assertEqual("BLOCKED", apply_plan(project.root, plan).state)
        self.assertEqual(before, target.read_bytes())

    def test_java_record_lombok_and_version_inference_are_blocked(self) -> None:
        project = ProjectFixture(self)
        project.generated_file()
        record_source = java_entity(fields="", methods="", class_decl="public record Employee(Integer id)")
        project.existing_file(record_source)
        self.assertTrue(any(f.status == "BLOCKED" for f in project.plan().findings))

        lombok = java_entity(
            fields=java_field("id", "employee_id", annotations=("@Id",)), methods="",
            imports=("org.seasar.doma.Id", "lombok.Data"),
            class_annotations=(
                '@Data\n@Entity(metamodel = @Metamodel)\n@Table(schema = "public", name = "employee")'
            ),
        )
        project.existing_file(lombok)
        self.assertTrue(any(f.status == "BLOCKED" for f in project.plan().findings))

        candidate = project.generated_file().read_text().replace("    @Version\n", "")
        project.generated_file().write_text(candidate)
        project.existing_file((FIXTURES / "generated-candidates/java/example/entity/Employee.java").read_text())
        blocked = next(f for f in project.plan().findings if f.kind == "version-semantics")
        self.assertEqual("BLOCKED", blocked.status)

    def test_removed_generated_property_is_executable_review_but_handwritten_reference_blocks(self) -> None:
        project = ProjectFixture(self)
        generated = java_entity(
            fields=java_field(
                "id", "employee_id", annotations=("@Id",),
                doc="/** Employee ID */",
            ),
            methods=java_accessors("id"), imports=("org.seasar.doma.Id",),
        )
        project.generated_file().write_text(generated)
        project.retain_snapshot_columns("employee_id")
        existing = java_entity(
            fields=(
                java_field(
                    "id", "employee_id", annotations=("@Id",),
                    doc="/** Employee ID */",
                )
                + java_field("legacy", "legacy")
            ),
            methods=java_accessors("id") + java_accessors("legacy"), imports=("org.seasar.doma.Id",),
        )
        target = project.existing_file(existing)
        snapshot = json.loads(project.snapshot.read_text())
        snapshot["tables"][0]["columns"] = snapshot["tables"][0]["columns"][:1]
        project.snapshot.write_text(json.dumps(snapshot, separators=(",", ":")) + "\n")
        review = next(f for f in project.plan().findings if f.kind == "remove-property")
        self.assertEqual("REVIEW_REQUIRED", review.status)
        self.assertTrue(review.edits)
        project.commit()
        pending = apply_plan(project.root, project.plan(), approvals=())
        self.assertEqual("PENDING_REVIEW", pending.state)
        self.assertIn("legacy", target.read_text())
        applied = apply_plan(project.root, project.plan(), approvals=(review.finding_id,))
        self.assertEqual("SUCCESS", applied.state)
        self.assertNotIn("legacy", target.read_text())

        handwritten = existing.replace(
            "}\n", "    public String label() { return legacy.toString(); }\n}\n", 1
        )
        project.existing_file(handwritten)
        blocked = next(f for f in project.plan().findings if f.kind == "remove-property")
        self.assertEqual("BLOCKED", blocked.status)
        self.assertFalse(blocked.edits)

        project.existing_file(existing)
        use = project.existing / "example/entity/Use.java"
        use.write_text(
            "package example.entity; class Use { Object x(Employee employee) { "
            "return employee.legacy; } }\n"
        )
        blocked = next(f for f in project.plan().findings if f.kind == "remove-property")
        self.assertEqual("BLOCKED", blocked.status)
        self.assertFalse(blocked.edits)

    def test_entity_missing_from_snapshot_is_reported_blocked_and_never_deleted(self) -> None:
        project = ProjectFixture(self)
        project.generated.mkdir(parents=True)
        source = (FIXTURES / "generated-candidates/java/example/entity/Employee.java").read_text()
        target = project.existing_file(source)
        snapshot = json.loads(project.snapshot.read_text())
        snapshot["tables"] = []
        project.snapshot.write_text(json.dumps(snapshot, separators=(",", ":")) + "\n")

        plan = project.plan()
        finding = next(f for f in plan.findings if f.kind == "removed-entity")
        self.assertEqual("BLOCKED", finding.status)
        self.assertEqual((), finding.edits)
        self.assertEqual(source.encode(), target.read_bytes())

    def test_type_narrowing_is_review_without_uses_and_blocked_with_project_use(self) -> None:
        project = ProjectFixture(self)
        generated = java_entity(
            fields=java_field(
                "id", "employee_id", "Integer", annotations=("@Id",),
                doc="/** Employee ID */",
            ),
            methods=java_accessors("id", "Integer"), imports=("org.seasar.doma.Id",),
        )
        project.generated_file().write_text(generated)
        project.retain_snapshot_columns("employee_id")
        existing = java_entity(
            fields=java_field("id", "employee_id", "Long", annotations=("@Id",)),
            methods=java_accessors("id", "Long"), imports=("org.seasar.doma.Id",),
        )
        target = project.existing_file(existing)
        plan = project.plan()
        review = next(f for f in plan.findings if f.kind == "narrow-basic-type")
        self.assertEqual("REVIEW_REQUIRED", review.status)
        self.assertIn("Long id;", review.existing or "")
        self.assertIn("public Long getId()", review.existing or "")
        self.assertIn("Integer id;", review.candidate or "")
        self.assertIn("public Integer getId()", review.candidate or "")
        diff = render_diff(plan)
        self.assertIn("-    Long id;", diff)
        self.assertIn("+    Integer id;", diff)
        project.commit()
        applied = apply_plan(project.root, plan, approvals=(review.finding_id,))
        self.assertEqual("SUCCESS", applied.state)
        merged = target.read_text()
        self.assertIn("Integer id;", merged)
        self.assertIn("public Integer getId()", merged)
        self.assertIn("setId(Integer id)", merged)
        self.assertNotIn("Long id", merged)

        project.existing_file(existing)
        use = project.existing / "example/entity/Use.java"
        use.write_text(
            "package example.entity; class Use { Long x(Employee employee) { "
            "return employee.id; } }\n"
        )
        blocked = next(f for f in project.plan().findings if f.kind == "narrow-basic-type")
        self.assertEqual("BLOCKED", blocked.status)
        self.assertFalse(blocked.edits)

    def test_table_schema_class_and_property_rename_inference_is_blocked(self) -> None:
        project = ProjectFixture(self)
        project.generated_file()
        sources = (
            java_entity(
                fields=java_field("id", "employee_id", annotations=("@Id",)), methods=java_accessors("id"),
                class_annotations='@Entity(metamodel = @Metamodel)\n@Table(schema = "archive", name = "employee")',
                imports=("org.seasar.doma.Id",),
            ),
            java_entity(
                fields=java_field("id", "employee_id", annotations=("@Id",)), methods=java_accessors("id"),
                class_decl="public class Staff", imports=("org.seasar.doma.Id",),
            ),
            java_entity(
                fields=java_field("id", "employee_id", annotations=("@Id",)),
                methods=java_accessors("id"), imports=("org.seasar.doma.Id",),
            ),
        )
        for source in sources:
            project.existing_file(source)
            plan = project.plan()
            self.assertTrue(any(f.status == "BLOCKED" and "rename" in f.kind for f in plan.findings))
            self.assertFalse(any(f.edits for f in plan.findings))

    def test_duplicate_embedded_and_parser_errors_are_file_level_blockers(self) -> None:
        project = ProjectFixture(self)
        project.generated_file()
        duplicate = java_entity(
            fields=java_field("id", "employee_id") + java_field("other", "employee_id"),
            methods=java_accessors("id") + java_accessors("other"),
        )
        for source in (duplicate, "@Entity public class Broken { String x = \"unterminated"):
            project.existing_file(source)
            plan = project.plan()
            self.assertTrue(any(f.status == "BLOCKED" for f in plan.findings))
            self.assertFalse(any(f.edits for f in plan.findings))

    def test_plan_json_ids_and_diff_are_deterministic_and_apply_preserves_bytes_and_permissions(self) -> None:
        project = ProjectFixture(self)
        generated = java_entity(
            fields=java_field("id", "employee_id", annotations=("@Id",)),
            methods=java_accessors("id"), imports=("org.seasar.doma.Id",),
        ).replace("\n", "\r\n").rstrip("\r\n")
        project.generated_file().write_bytes(generated.encode())
        project.retain_snapshot_columns("employee_id")
        existing = generated.replace("    @Id\r\n", "", 1)
        target = project.existing_file(existing)
        target.write_bytes(b"\xef\xbb\xbf" + existing.encode())
        target.chmod(0o640)

        first = project.plan()
        second = project.plan()
        self.assertEqual(plan_json(first), plan_json(second))
        self.assertEqual(render_diff(first), render_diff(second))
        self.assertEqual(
            [f.finding_id for f in first.findings], [f.finding_id for f in second.findings]
        )
        project.commit()
        apply_plan(project.root, first, approvals=())
        merged = target.read_bytes()
        self.assertTrue(merged.startswith(b"\xef\xbb\xbf"))
        self.assertIn(b"\r\n", merged)
        self.assertFalse(merged.endswith(b"\n"))
        self.assertEqual(0o640, stat.S_IMODE(target.stat().st_mode))

    def test_stale_hash_unknown_approval_and_dirty_git_stop_before_first_write(self) -> None:
        project = ProjectFixture(self)
        project.generated_file()
        target = project.existing_file(
            java_entity(
                fields=java_field("id", "employee_id"), methods=java_accessors("id")
            )
        )
        plan = project.plan()
        before = target.read_bytes()
        project.commit()
        target.write_text(target.read_text() + "// stale\n")
        with self.assertRaises(StalePlanError):
            apply_plan(project.root, plan, approvals=())
        self.assertNotEqual(before, target.read_bytes())
        self.assertTrue(target.read_bytes().endswith(b"// stale\n"))

        subprocess.run(["git", "checkout", "--", str(target.relative_to(project.root))], cwd=project.root, check=True)
        with self.assertRaises(PlanInputError):
            apply_plan(project.root, plan, approvals=("unknown-proposal",))

    def test_unrelated_tracked_changes_are_allowed_but_dirty_build_file_blocks_apply(self) -> None:
        project = ProjectFixture(self)
        candidate = java_entity(
            fields=(
                java_field("id", "employee_id", annotations=("@Id",), doc="/** Employee ID */")
                + java_field("displayName", "display_name", "String", doc="/** Display name */")
                + java_field("version", "version", "Long")
            ),
            methods=(
                java_accessors("id")
                + java_accessors("displayName", "String")
                + java_accessors("version", "Long")
            ),
            imports=("org.seasar.doma.Id",),
        )
        project.generated_file().write_text(candidate, encoding="utf-8")
        snapshot = json.loads(project.snapshot.read_text(encoding="utf-8"))
        snapshot["tables"][0]["columns"][0]["auto_increment"] = False
        next(
            column for column in snapshot["tables"][0]["columns"]
            if column["name"] == "version"
        ).update({"jdbc_type": -5, "type_name": "int8", "size": 64, "scale": 0})
        project.snapshot.write_text(
            json.dumps(snapshot, separators=(",", ":")) + "\n", encoding="utf-8"
        )
        target = project.existing_file(
            java_entity(
                fields=(
                    java_field("id", "employee_id", annotations=("@Id",))
                    + java_field("version", "version")
                ),
                methods=java_accessors("id") + java_accessors("version"),
                imports=("org.seasar.doma.Id",),
            )
        )
        readme = project.root / "README.md"
        readme.write_text("before\n", encoding="utf-8")
        plan = project.plan()
        project.commit()

        readme.write_text("unrelated tracked change\n", encoding="utf-8")
        result = apply_plan(project.root, plan, approvals=())
        self.assertTrue(result.applied)
        self.assertIn("displayName", target.read_text(encoding="utf-8"))

        subprocess.run(
            ["git", "checkout", "--", str(readme.relative_to(project.root)),
             str(target.relative_to(project.root))],
            cwd=project.root, check=True,
        )
        plan = project.plan()
        build_file = project.root / "build.gradle.kts"
        build_file.write_text(build_file.read_text(encoding="utf-8") + "// dirty\n", encoding="utf-8")
        before = target.read_bytes()
        with self.assertRaises(UnsafeProjectError):
            apply_plan(project.root, plan, approvals=())
        self.assertEqual(before, target.read_bytes())

    def test_untracked_and_ignored_existing_entity_targets_block_apply(self) -> None:
        for state in ("untracked", "ignored"):
            with self.subTest(state=state):
                project = ProjectFixture(self)
                project.retain_snapshot_columns("employee_id")
                snapshot = json.loads(project.snapshot.read_text(encoding="utf-8"))
                snapshot["tables"][0]["columns"][0]["auto_increment"] = False
                project.snapshot.write_text(
                    json.dumps(snapshot, separators=(",", ":")) + "\n",
                    encoding="utf-8",
                )
                project.generated_file().write_text(java_entity(
                    fields=java_field(
                        "id", "employee_id", annotations=("@Id",),
                        doc="/** Employee ID */",
                    ),
                    methods=java_accessors("id"), imports=("org.seasar.doma.Id",),
                ))
                target = project.existing_file(java_entity(
                    fields=java_field("id", "employee_id"),
                    methods=java_accessors("id"),
                ))
                if state == "ignored":
                    (project.root / ".gitignore").write_text(
                        "/src/main/java/example/entity/Employee.java\n",
                        encoding="utf-8",
                    )
                plan = project.plan(language="java")
                subprocess.run(["git", "init", "-q"], cwd=project.root, check=True)
                subprocess.run(
                    ["git", "config", "user.name", "Fixture"],
                    cwd=project.root,
                    check=True,
                )
                subprocess.run(
                    ["git", "config", "user.email", "fixture@example.invalid"],
                    cwd=project.root,
                    check=True,
                )
                subprocess.run(["git", "add", "."], cwd=project.root, check=True)
                if state == "untracked":
                    subprocess.run(
                        ["git", "reset", "--quiet", "--", str(target.relative_to(project.root))],
                        cwd=project.root,
                        check=True,
                    )
                subprocess.run(
                    ["git", "commit", "-qm", "fixture"], cwd=project.root, check=True
                )
                before = target.read_bytes()

                with self.assertRaises(UnsafeProjectError):
                    apply_plan(project.root, plan, approvals=())
                self.assertEqual(before, target.read_bytes())

    def test_auto_language_plan_replays_the_exact_mixed_language_plan(self) -> None:
        project = ProjectFixture(self)
        project.retain_snapshot_columns("employee_id")
        snapshot = json.loads(project.snapshot.read_text())
        snapshot["scope"]["table_pattern"] = "employee|audit"
        snapshot["tables"][0]["columns"][0]["auto_increment"] = False
        project.snapshot.write_text(
            json.dumps(snapshot, separators=(",", ":")) + "\n"
        )
        project.generated_file().write_text(java_entity(
            fields=java_field(
                "id", "employee_id", annotations=("@Id",),
                doc="/** Employee ID */",
            ),
            methods=java_accessors("id"),
            imports=("org.seasar.doma.Id",),
        ))
        target = project.existing_file(java_entity(
            fields=java_field(
                "id", "employee_id", doc="/** Employee ID */"
            ),
            methods=java_accessors("id"),
        ))
        kotlin_root = project.root / "src/main/kotlin"
        audit = kotlin_root / "example/entity/Audit.kt"
        audit.parent.mkdir(parents=True)
        audit.write_text(
            kotlin_entity(properties="", class_decl="class Audit")
            .replace("/** Employees */", "/** Audits */")
            .replace(
                '@Table(schema = "public", name = "employee")',
                '@Table(schema = "public", name = "audit")',
            )
        )

        plan = build_plan(
            project.root,
            project.snapshot,
            project.generated,
            (project.existing, kotlin_root),
            "auto",
        )
        self.assertEqual("auto", plan.language)
        self.assertTrue(any(
            finding.kind == "synchronize-primary-key" and finding.status == "SAFE"
            for finding in plan.findings
        ))
        self.assertTrue(any(
            finding.kind == "removed-entity" and finding.status == "BLOCKED"
            for finding in plan.findings
        ))
        project.commit()
        with self.assertRaises(PlanInputError):
            apply_plan(
                project.root,
                dataclasses.replace(plan, language="java"),
                approvals=(),
            )
        result = apply_plan(project.root, plan, approvals=())
        self.assertEqual("BLOCKED", result.state)
        self.assertIn("@Id", target.read_text())

    def test_java_only_plan_applies_in_mixed_project_with_its_exact_explicit_roots(self) -> None:
        project = ProjectFixture(self)
        project.retain_snapshot_columns("employee_id")
        snapshot = json.loads(project.snapshot.read_text())
        snapshot["tables"][0]["columns"][0]["auto_increment"] = False
        project.snapshot.write_text(json.dumps(snapshot, separators=(",", ":")) + "\n")
        project.generated_file().write_text(java_entity(
            fields=java_field(
                "id", "employee_id", annotations=("@Id",),
                doc="/** Employee ID */",
            ),
            methods=java_accessors("id"), imports=("org.seasar.doma.Id",),
        ))
        target = project.existing_file(java_entity(
            fields=java_field(
                "id", "employee_id", doc="/** Employee ID */"
            ),
            methods=java_accessors("id"),
        ))
        kotlin_root = project.root / "src/main/kotlin"
        unrelated = kotlin_root / "example/Unrelated.kt"
        unrelated.parent.mkdir(parents=True)
        unrelated.write_text("package example\nclass Unrelated\n")

        plan = build_plan(
            project.root, project.snapshot, project.generated,
            (project.existing, kotlin_root), "java",
        )
        self.assertIn(
            "src/main/kotlin/example/Unrelated.kt",
            dict(plan.source_hashes),
        )
        finding = next(
            item for item in plan.findings if item.kind == "synchronize-primary-key"
        )
        self.assertEqual("SAFE", finding.status)
        project.commit()
        result = apply_plan(project.root, plan, approvals=())
        self.assertEqual("SUCCESS", result.state)
        self.assertIn("@Id", target.read_text())
        self.assertEqual("package example\nclass Unrelated\n", unrelated.read_text())

        custom_source = project.root / "src/custom/java"
        custom_source.mkdir(parents=True)
        with self.assertRaises(PlanInputError):
            build_plan(
                project.root, project.snapshot, project.generated,
                (custom_source,), "java",
            )

        custom_generated = project.root / "build/custom-generated"
        custom_candidate = custom_generated / "example/entity/Employee.java"
        custom_candidate.parent.mkdir(parents=True)
        custom_candidate.write_text(project.generated_file().read_text())
        with self.assertRaises(PlanInputError):
            build_plan(
                project.root, project.snapshot, custom_generated,
                (project.existing,), "java",
            )

    def test_manifest_validation_rejects_versions_duplicates_scope_pk_family_and_paths(self) -> None:
        project = ProjectFixture(self)
        project.generated_file()
        cases = []
        base = json.loads(project.snapshot.read_text())
        wrong_version = json.loads(json.dumps(base)); wrong_version["format_version"] = 2; cases.append(wrong_version)
        duplicate = json.loads(json.dumps(base)); duplicate["tables"].append(duplicate["tables"][0]); cases.append(duplicate)
        out_scope = json.loads(json.dumps(base)); out_scope["tables"][0]["name"] = "outside"; cases.append(out_scope)
        bad_pk = json.loads(json.dumps(base)); bad_pk["tables"][0]["primary_key"][0]["sequence"] = 2; cases.append(bad_pk)
        family = json.loads(json.dumps(base)); family["database"] = "mysql"; cases.append(family)
        invalid_qualifier = json.loads(json.dumps(base)); invalid_qualifier["tables"][0]["catalog"] = []; cases.append(invalid_qualifier)
        for manifest in cases:
            with self.subTest(case=manifest.get("database"), version=manifest.get("format_version")):
                project.snapshot.write_text(json.dumps(manifest, separators=(",", ":")) + "\n")
                with self.assertRaises(PlanInputError):
                    project.plan()

        project.snapshot.write_text(json.dumps(base, separators=(",", ":")) + "\n")
        outside = project.root.parent / "outside-generated"
        outside.mkdir(exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(outside, ignore_errors=True))
        with self.assertRaises(PlanInputError):
            build_plan(project.root, project.snapshot, outside, (project.existing,), "auto")

    def test_cli_writes_plan_and_diff_and_uses_documented_result_codes(self) -> None:
        project = ProjectFixture(self)
        project.generated_file()
        project.existing_file(java_entity(
            fields=java_field("id", "employee_id", annotations=("@Id",)),
            methods=java_accessors("id"), imports=("org.seasar.doma.Id",),
        ))
        result = subprocess.run([
            sys.executable, str(CLI), "plan", "--project-root", str(project.root),
            "--schema-snapshot", str(project.snapshot), "--generated-dir", str(project.generated),
            "--existing-root", str(project.existing), "--language", "auto",
            "--output-plan", str(project.plan_path), "--output-diff", str(project.diff_path),
        ], text=True, capture_output=True)
        self.assertIn(result.returncode, {0, 2, 3}, result.stderr)
        self.assertTrue(project.plan_path.is_file())
        self.assertEqual(load_plan(project.plan_path), load_plan(project.plan_path))
        self.assertEqual(render_diff(load_plan(project.plan_path)), project.diff_path.read_text())


if __name__ == "__main__":
    unittest.main()
