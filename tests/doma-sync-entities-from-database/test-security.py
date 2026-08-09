#!/usr/bin/env python3
"""Security regressions for entity merge planning and apply boundaries."""
from __future__ import annotations

import json
import hashlib
import os
import re
import subprocess
import sys
import tempfile
import unittest
import unicodedata
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills/doma-sync-entities-from-database/scripts"
CLI = SCRIPTS / "compare-and-merge-entities.py"
sys.path.insert(0, str(SCRIPTS))

from entity_sync.applier import UnsafeProjectError, apply_plan
from entity_sync.model import SourceSpan
from entity_sync.planner import Edit, PlanInputError, _expected_finding_id, build_plan


SAFE_SNAPSHOT = {
    "format_version": 1,
    "database": "postgresql",
    "scope": {"catalog": None, "schema": "public", "table_pattern": "employee"},
    "tables": [{
        "catalog": None, "schema": "public", "name": "employee", "type": "TABLE",
        "remarks": None,
        "primary_key": [{"name": "employee_pkey", "column": "id", "sequence": 1}],
        "columns": [{
            "name": "id", "ordinal": 1, "jdbc_type": 4, "type_name": "int4",
            "size": 32, "scale": 0, "nullable": False, "default": None,
            "auto_increment": False, "remarks": None,
        }],
    }],
}

JAVA = '''package example;
import org.seasar.doma.Column;
import org.seasar.doma.Entity;
import org.seasar.doma.Id;
import org.seasar.doma.Metamodel;
import org.seasar.doma.Table;
/** */
@Entity(metamodel = @Metamodel)
@Table(schema = "public", name = "employee")
public class Employee {
    /** */
    @Id
    @Column(name = "id")
    Integer id;
    /** Returns the id. */
    public Integer getId() {
        return id;
    }
    /** Sets the id. */
    public void setId(Integer id) {
        this.id = id;
    }
}
'''


def old_style_finding_id(finding: object, path: str) -> str:
    table = finding.table
    normalized = [
        finding.status,
        finding.kind,
        unicodedata.normalize("NFKC", table.catalog or "").casefold(),
        unicodedata.normalize("NFKC", table.schema or "").casefold(),
        unicodedata.normalize("NFKC", table.table).casefold(),
        unicodedata.normalize("NFKC", finding.column or "").casefold(),
        path,
    ]
    digest = hashlib.sha256(json.dumps(normalized, separators=(",", ":")).encode()).hexdigest()[:12]
    prefix = re.sub(r"[^a-z0-9]+", "-", (finding.status + "-" + finding.kind).lower()).strip("-")
    return prefix + "-" + digest


def with_current_finding_id(finding: object) -> object:
    finding = replace(finding, finding_id="attacker-recomputed")
    return replace(finding, finding_id=_expected_finding_id(finding))


class SecurityTests(unittest.TestCase):
    def project(self) -> tuple[Path, Path, Path, tempfile.TemporaryDirectory[str]]:
        temp = tempfile.TemporaryDirectory(prefix="entity-merge-security-")
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        snapshot = root / "build/doma-codegen/schema-snapshot.json"
        generated = root / "build/doma-codegen/generated/example/Employee.java"
        existing = root / "src/main/java/example/Employee.java"
        snapshot.parent.mkdir(parents=True)
        generated.parent.mkdir(parents=True)
        existing.parent.mkdir(parents=True)
        snapshot.write_text(json.dumps(SAFE_SNAPSHOT, separators=(",", ":")) + "\n")
        generated.write_text(JAVA)
        existing.write_text(JAVA)
        return root, snapshot, generated.parent.parent, temp

    def test_secret_bearing_manifest_source_and_generated_inputs_are_rejected_without_echo(self) -> None:
        sentinels = (
            "jdbc:postgresql://url-sentinel.invalid/db",
            "user=user-sentinel",
            "password=password-sentinel",
            "token=token-sentinel",
            "access_key=AKIAACCESSKEYSENTINEL",
            "Secret=secret-sentinel",
        )
        for location in ("snapshot", "source", "generated"):
            for sentinel in sentinels:
                with self.subTest(location=location, sentinel=sentinel.split("=", 1)[0]):
                    root, snapshot, generated_root, _ = self.project()
                    existing = root / "src/main/java/example/Employee.java"
                    if location == "snapshot":
                        data = json.loads(snapshot.read_text())
                        data["tables"][0]["remarks"] = sentinel
                        snapshot.write_text(json.dumps(data))
                    elif location == "source":
                        existing.write_text(JAVA + "// " + sentinel)
                    else:
                        (generated_root / "example/Employee.java").write_text(JAVA + "// " + sentinel)
                    plan_path = root / "build/doma-codegen/plan.json"
                    diff_path = root / "build/doma-codegen/plan.diff"
                    result = subprocess.run([
                        sys.executable, str(CLI), "plan", "--project-root", str(root),
                        "--schema-snapshot", str(snapshot), "--generated-dir", str(generated_root),
                        "--existing-root", str(root / "src/main/java"), "--language", "auto",
                        "--output-plan", str(plan_path), "--output-diff", str(diff_path),
                    ], text=True, capture_output=True)
                    self.assertEqual(64, result.returncode)
                    self.assertFalse(plan_path.exists())
                    self.assertFalse(diff_path.exists())
                    self.assertNotIn(sentinel, result.stdout + result.stderr)

    def test_symlink_escape_and_outside_roots_are_rejected_without_touching_external_file(self) -> None:
        root, snapshot, generated_root, _ = self.project()
        external = root.parent / f"external-{root.name}.java"
        external.write_text("external sentinel\n")
        self.addCleanup(lambda: external.unlink(missing_ok=True))
        link = root / "src/main/java/example/Escape.java"
        link.symlink_to(external)
        with self.assertRaises(PlanInputError):
            build_plan(root, snapshot, generated_root, (root / "src/main/java",), "auto")
        self.assertEqual("external sentinel\n", external.read_text())

    def test_apply_rechecks_symlinks_and_prepares_every_edit_before_replacing_any(self) -> None:
        root, snapshot, generated_root, _ = self.project()
        existing_root = root / "src/main/java"
        target = existing_root / "example/Employee.java"
        generated = generated_root / "example/Employee.java"
        generated.write_text(JAVA.replace("    @Id\n", ""))
        plan = build_plan(root, snapshot, generated_root, (existing_root,), "auto")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "Fixture"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=root, check=True)
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)
        before = target.read_bytes()
        external = root.parent / f"external-apply-{root.name}.java"
        external.write_text("external sentinel\n")
        self.addCleanup(lambda: external.unlink(missing_ok=True))
        target.unlink()
        target.symlink_to(external)
        with self.assertRaises((UnsafeProjectError, OSError)):
            apply_plan(root, plan, approvals=())
        self.assertEqual("external sentinel\n", external.read_text())
        self.assertNotEqual(before, target.read_bytes())

    def test_tampered_plan_cannot_retarget_a_source_edit_to_a_non_source_file(self) -> None:
        root, snapshot, generated_root, _ = self.project()
        existing_root = root / "src/main/java"
        (existing_root / "example/Employee.java").write_text(JAVA.replace("    @Id\n", ""))
        plan = build_plan(root, snapshot, generated_root, (existing_root,), "auto")
        finding = next(item for item in plan.findings if item.edits)
        path = "build/doma-codegen/schema-snapshot.json"
        tampered = replace(
            finding,
            finding_id=old_style_finding_id(finding, path),
            path=path,
            database={**finding.database, "existing_root": "build"},
            edits=(Edit("replace", path, SourceSpan(0, 1), "{"),),
        )
        plan = replace(plan, findings=(tampered,))
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "Fixture"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=root, check=True)
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)
        before = snapshot.read_bytes()

        with self.assertRaises(PlanInputError):
            apply_plan(root, plan, approvals=())
        self.assertEqual(before, snapshot.read_bytes())

    def test_old_style_recomputed_create_id_cannot_escape_source_root_or_change_payload(self) -> None:
        root, snapshot, generated_root, _ = self.project()
        existing_root = root / "src/main/java"
        (existing_root / "example/Employee.java").unlink()
        plan = build_plan(root, snapshot, generated_root, (existing_root,), "auto")
        finding = next(item for item in plan.findings if item.kind == "create-entity")
        path = "outside-source-root/payload.txt"
        tampered = replace(
            finding,
            finding_id=old_style_finding_id(finding, path),
            path=path,
            database={**finding.database, "existing_root": "."},
            edits=(Edit("create", path, None, "review-exploit-payload\n"),),
        )
        plan = replace(plan, findings=(tampered,))
        self._commit(root)

        with self.assertRaises((PlanInputError, UnsafeProjectError)):
            apply_plan(root, plan, approvals=())
        self.assertFalse((root / path).exists())
        self.assertFalse((existing_root / "example/Employee.java").exists())

    def test_current_id_recomputation_cannot_create_arbitrary_content_under_substituted_roots(self) -> None:
        root, snapshot, generated_root, _ = self.project()
        existing_root = root / "src/main/java"
        (existing_root / "example/Employee.java").unlink()
        plan = build_plan(root, snapshot, generated_root, (existing_root,), "auto")
        finding = next(item for item in plan.findings if item.kind == "create-entity")

        payload = "arbitrary content that is not a Doma Entity\n"
        attacker_source = root / "attacker-source"
        attacker_generated = root / "attacker-generated"
        attacker_source.mkdir()
        attacker_generated.mkdir()
        attacker_candidate = attacker_generated / "payload.txt"
        attacker_candidate.write_text(payload)
        path = "attacker-source/payload.txt"
        tampered = replace(
            finding,
            path=path,
            database={
                **finding.database,
                "existing_root": "attacker-source",
                "generated_root": "attacker-generated",
                "generated_path": "attacker-generated/payload.txt",
            },
            candidate=payload,
            edits=(Edit("create", path, None, payload),),
        )
        tampered = with_current_finding_id(tampered)
        plan = replace(
            plan,
            generated_hashes=((
                "attacker-generated/payload.txt",
                hashlib.sha256(payload.encode()).hexdigest(),
            ),),
            findings=(tampered,),
        )
        self._commit(root)

        with self.assertRaises((PlanInputError, UnsafeProjectError)):
            apply_plan(root, plan, approvals=())
        self.assertFalse((root / path).exists())

    def test_current_id_recomputation_cannot_escalate_review_to_safe_without_approval(self) -> None:
        root, snapshot, generated_root, _ = self.project()
        existing_root = root / "src/main/java"
        target = existing_root / "example/Employee.java"
        target.write_text(JAVA.replace("Integer", "Long"))
        plan = build_plan(root, snapshot, generated_root, (existing_root,), "auto")
        review = next(item for item in plan.findings if item.kind == "narrow-basic-type")
        self.assertEqual("REVIEW_REQUIRED", review.status)
        tampered = with_current_finding_id(replace(
            review,
            status="SAFE",
            action="Apply without review approval.",
        ))
        plan = replace(plan, findings=(tampered,))
        before = target.read_bytes()
        self._commit(root)

        with self.assertRaises(PlanInputError):
            apply_plan(root, plan, approvals=())
        self.assertEqual(before, target.read_bytes())

    def test_current_id_cannot_select_project_root_as_the_canonical_existing_root(self) -> None:
        root, snapshot, generated_root, _ = self.project()
        existing_root = root / "src/main/java"
        target = existing_root / "example/Employee.java"
        target.write_text(JAVA.replace("    @Id\n", "", 1))
        plan = build_plan(root, snapshot, generated_root, (existing_root,), "java")
        finding = next(
            item for item in plan.findings if item.kind == "synchronize-primary-key"
        )
        tampered = with_current_finding_id(replace(
            finding,
            database={**finding.database, "existing_root": "."},
        ))
        plan = replace(plan, findings=(tampered,))
        before = target.read_bytes()
        self._commit(root)

        with self.assertRaises(UnsafeProjectError):
            apply_plan(root, plan, approvals=())
        self.assertEqual(before, target.read_bytes())

    def test_exact_proposal_binding_rejects_edit_span_text_and_database_fact_mutation(self) -> None:
        for mutation in ("span", "text", "database"):
            with self.subTest(mutation=mutation):
                root, snapshot, generated_root, _ = self.project()
                existing_root = root / "src/main/java"
                (existing_root / "example/Employee.java").write_text(JAVA.replace("    @Id\n", ""))
                plan = build_plan(root, snapshot, generated_root, (existing_root,), "auto")
                finding = next(item for item in plan.findings if item.edits)
                edits = list(finding.edits)
                database = finding.database
                if mutation == "span":
                    edit = edits[0]
                    assert edit.span is not None
                    edits[0] = replace(edit, span=SourceSpan(edit.span.start + 1, edit.span.end + 1))
                elif mutation == "text":
                    edits[0] = replace(edits[0], text=edits[0].text + "/* mutated */")
                else:
                    database = {**database, "column_present": True}
                tampered = replace(finding, database=database, edits=tuple(edits))
                plan = replace(plan, findings=(tampered,))
                self._commit(root)
                before = (existing_root / "example/Employee.java").read_bytes()

                with self.assertRaises(PlanInputError):
                    apply_plan(root, plan, approvals=())
                self.assertEqual(before, (existing_root / "example/Employee.java").read_bytes())

    def test_create_requires_the_exact_hashed_generated_candidate(self) -> None:
        root, snapshot, generated_root, _ = self.project()
        existing_root = root / "src/main/java"
        (existing_root / "example/Employee.java").unlink()
        plan = build_plan(root, snapshot, generated_root, (existing_root,), "auto")
        finding = next(item for item in plan.findings if item.kind == "create-entity")
        plan = replace(plan, generated_hashes=())
        self._commit(root)

        with self.assertRaises(PlanInputError):
            apply_plan(root, plan, approvals=())
        self.assertFalse((root / finding.path).exists())

    def _commit(self, root: Path) -> None:
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "Fixture"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=root, check=True)
        subprocess.run(["git", "add", "."], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)


if __name__ == "__main__":
    unittest.main()
