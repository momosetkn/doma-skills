#!/usr/bin/env python3
"""Security regressions for entity merge planning and apply boundaries."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills/doma-sync-entities-from-database/scripts"
CLI = SCRIPTS / "compare-and-merge-entities.py"
sys.path.insert(0, str(SCRIPTS))

from entity_sync.applier import UnsafeProjectError, apply_plan
from entity_sync.model import SourceSpan
from entity_sync.planner import Edit, PlanInputError, _finding_id, build_plan


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
            finding_id=_finding_id(finding.status, finding.kind, finding.table, finding.column, path),
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


if __name__ == "__main__":
    unittest.main()
