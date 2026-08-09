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

from entity_sync.applier import StalePlanError, apply_plan
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


def kotlin_property(name: str, column: str, type_name: str, default: str) -> str:
    return (
        "    /** */\n"
        f"    @Column(name = \"{column}\")\n"
        f"    var {name}: {type_name} = {default}\n\n"
    )


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

    def generated_file(self, language: str = "java") -> Path:
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
        plan = MergePlan(1, ".", "a" * 64, (("src/main/java/X.java", "b" * 64),), (), (finding,))

        self.assertEqual(1, plan.format_version)
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

    def test_safe_insert_column_annotation_comment_type_widening_and_new_nullability(self) -> None:
        project = ProjectFixture(self)
        candidate = java_entity(
            fields=(
                java_field("id", "employee_id", annotations=("@Id",))
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

    def test_mismatching_new_property_comment_is_blocked_without_serializing_the_candidate_text(self) -> None:
        project = ProjectFixture(self)
        sentinel = "STALE_PROPERTY_CANARY_7QX9"
        project.retain_snapshot_columns("employee_id", "display_name")
        candidate = java_entity(
            fields=(
                java_field("id", "employee_id", annotations=("@Id",))
                + java_field("displayName", "display_name", "String", doc=f"/** {sentinel} */")
            ),
            methods=java_accessors("id") + java_accessors("displayName", "String"),
            imports=("org.seasar.doma.Id",),
        )
        project.generated_file().write_text(candidate)
        target = project.existing_file(java_entity(
            fields=java_field("id", "employee_id", annotations=("@Id",)),
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
            fields=java_field("id", "employee_id", annotations=("@Id",)),
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
                java_field("id", "employee_id", annotations=("@Id",))
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
            fields=java_field("id", "employee_id"), methods=java_accessors("id")
        )
        project.generated_file().write_text(candidate)
        target = project.existing_file(java_entity(
            fields=java_field("id", "employee_id", annotations=("@Id",)),
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

    def test_identical_generated_value_semantics_do_not_depend_on_source_offsets(self) -> None:
        project = ProjectFixture(self)
        candidate = project.generated_file().read_text()
        project.existing_file(candidate.replace("\n", "\r\n"))

        plan = project.plan()
        self.assertFalse(any("generated-value" in finding.kind for finding in plan.findings))

    def test_domain_special_mappings_methods_inheritance_interfaces_and_custom_annotations_stop_file_edits(self) -> None:
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
                fields=java_field("id", "employee_id", annotations=("@Id",)),
                methods=java_accessors("id") + "    public String label() { return id.toString(); }\n",
                imports=("org.seasar.doma.Id",),
            ),
            java_entity(
                fields=java_field("id", "employee_id", annotations=("@Id",)), methods=java_accessors("id"),
                class_decl="public class Employee extends BaseEmployee implements Audited",
                imports=("org.seasar.doma.Id",),
            ),
            java_entity(
                fields=java_field("id", "employee_id", annotations=("@Id", "@SecretMarker")),
                methods=java_accessors("id"), imports=("org.seasar.doma.Id", "example.SecretMarker"),
            ),
        )
        for source in variants:
            with self.subTest(source=hashlib.sha256(source.encode()).hexdigest()[:8]):
                project.existing_file(source)
                plan = project.plan()
                self.assertTrue(any(f.status == "BLOCKED" for f in plan.findings))
                self.assertFalse(any(f.edits for f in plan.findings if f.path.endswith("Employee.java")))

    def test_kotlin_nullability_is_review_and_primary_constructor_or_data_class_is_blocked(self) -> None:
        project = ProjectFixture(self)
        project.existing = project.root / "src/main/kotlin"
        project.existing.mkdir(parents=True)
        project.generated_file("kotlin")
        existing = (FIXTURES / "generated-candidates/kotlin/example/entity/Employee.kt").read_text().replace(
            "var id: Int = -1", "var id: Int? = null"
        )
        target = project.existing_file(existing, "kt")
        plan = project.plan(language="kotlin")
        review = next(f for f in plan.findings if f.kind == "kotlin-nullability")
        self.assertEqual("REVIEW_REQUIRED", review.status)
        self.assertIn(review.finding_id, review.action)
        self.assertIn("@@", review.action)
        self.assertIn("var id: Int? = null", review.existing or "")
        self.assertIn("var id: Int = -1", review.candidate or "")
        self.assertIn("-    var id: Int? = null", render_diff(plan))
        self.assertIn("+    var id: Int = -1", render_diff(plan))
        project.commit()
        applied = apply_plan(project.root, plan, approvals=(review.finding_id,))
        self.assertEqual("SUCCESS", applied.state)
        self.assertIn("var id: Int = -1", target.read_text())
        self.assertNotIn("var id: Int = null", target.read_text())

        for declaration in (
            "data class Employee(var id: Int)",
            "class Employee(var id: Int)",
        ):
            source = kotlin_entity(properties="", class_decl=declaration)
            project.existing_file(source, "kt")
            plan = project.plan(language="kotlin")
            self.assertTrue(any(f.status == "BLOCKED" for f in plan.findings))
            self.assertFalse(any(f.edits for f in plan.findings))

    def test_kotlin_callable_references_block_removal_narrowing_and_nullability_edits(self) -> None:
        cases = (
            (
                "remove-property",
                kotlin_property("id", "employee_id", "Int", "-1"),
                kotlin_property("id", "employee_id", "Int", "-1")
                + kotlin_property("legacy", "legacy", "String?", "null"),
                "Employee::legacy",
            ),
            (
                "narrow-basic-type",
                kotlin_property("id", "employee_id", "Int", "-1"),
                kotlin_property("id", "employee_id", "Long", "-1L"),
                "Employee::id",
            ),
            (
                "kotlin-nullability",
                kotlin_property("id", "employee_id", "Int", "-1"),
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
            fields=java_field("id", "employee_id", annotations=("@Id",)),
            methods=java_accessors("id"), imports=("org.seasar.doma.Id",),
        )
        project.generated_file().write_text(generated)
        project.retain_snapshot_columns("employee_id")
        existing = java_entity(
            fields=java_field("id", "employee_id", annotations=("@Id",)) + java_field("legacy", "legacy"),
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
            fields=java_field("id", "employee_id", "Integer", annotations=("@Id",)),
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
                fields=java_field("employeeId", "employee_id", annotations=("@Id",)),
                methods=java_accessors("employeeId"), imports=("org.seasar.doma.Id",),
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
