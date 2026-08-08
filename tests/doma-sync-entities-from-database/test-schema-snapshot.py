#!/usr/bin/env python3
"""Black-box tests for the source-file JDBC schema snapshot helper."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills/doma-sync-entities-from-database/scripts/schema-snapshot.java"
FIXTURE_SOURCE = ROOT / "tests/doma-sync-entities-from-database/fixtures/fixture-jdbc/FixtureJdbcDriver.java"
FIXTURE_SERVICE = ROOT / "tests/doma-sync-entities-from-database/fixtures/fixture-jdbc/META-INF/services/java.sql.Driver"


class SchemaSnapshotTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.work = tempfile.TemporaryDirectory(prefix="schema-snapshot-test-")
        cls.work_path = Path(cls.work.name)
        classes = cls.work_path / "classes"
        classes.mkdir()
        subprocess.run(["javac", "-d", str(classes), str(FIXTURE_SOURCE)], check=True)
        service = classes / "META-INF/services"
        service.mkdir(parents=True)
        shutil.copy2(FIXTURE_SERVICE, service / "java.sql.Driver")
        cls.driver_jar = cls.work_path / "fixture-driver.jar"
        subprocess.run(["jar", "--create", "--file", str(cls.driver_jar), "-C", str(classes), "."], check=True)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.work.cleanup()

    def run_snapshot(self, *, database: str = "postgresql", schema: str | None = "public",
                     catalog: str | None = None, pattern: str = "tenant_.*", url: str | None = None,
                     output: Path | None = None, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        project = self.work_path / "project"
        output = output or project / "build/doma-codegen/schema-snapshot.json"
        trace = self.work_path / "calls.json"
        env = os.environ.copy()
        for key in tuple(env):
            if key.startswith("DOMA_CODEGEN_"):
                env.pop(key)
        env.update({
            "DOMA_CODEGEN_DB_URL": url or f"jdbc:fixture:{database}",
            "DOMA_CODEGEN_DB_USER": "fixture-user-sentinel",
            "DOMA_CODEGEN_DB_PASSWORD": "fixture-password-sentinel",
            "DOMA_CODEGEN_DB_KIND": database,
            "DOMA_CODEGEN_TABLE_PATTERN": pattern,
            "DOMA_CODEGEN_SCHEMA_SNAPSHOT": str(output),
            "DOMA_CODEGEN_PROJECT_ROOT": str(project),
            "FIXTURE_JDBC_CALLS": str(trace),
        })
        if schema is not None:
            env["DOMA_CODEGEN_DB_SCHEMA"] = schema
        if catalog is not None:
            env["DOMA_CODEGEN_DB_CATALOG"] = catalog
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            ["java", "--class-path", str(self.driver_jar), str(SCRIPT)],
            text=True, capture_output=True, env=env, cwd=self.work_path,
        )

    def load_manifest(self) -> dict[str, object]:
        return json.loads((self.work_path / "project/build/doma-codegen/schema-snapshot.json").read_text())

    def load_calls(self) -> list[str]:
        return json.loads((self.work_path / "calls.json").read_text())

    def assert_success(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(0, result.returncode, result.stderr)

    def test_postgresql_snapshot_is_sorted_and_complete(self) -> None:
        result = self.run_snapshot()
        self.assert_success(result)
        manifest = self.load_manifest()
        self.assertEqual({
            "format_version": 1,
            "database": "postgresql",
            "scope": {"catalog": None, "schema": "public", "table_pattern": "tenant_.*"},
            "tables": manifest["tables"],
        }, manifest)
        tables = manifest["tables"]
        self.assertEqual(["tenant_alpha", "tenant_zebra"], [table["name"] for table in tables])
        alpha = tables[0]
        self.assertEqual(["catalog", "schema", "name", "type", "remarks", "primary_key", "columns"], list(alpha))
        self.assertEqual(["id", "note", "created"], [column["name"] for column in alpha["columns"]])
        self.assertEqual(
            {"name": "tenant_alpha_pkey", "column": "id", "sequence": 1}, alpha["primary_key"][0])
        self.assertEqual(
            ["name", "ordinal", "jdbc_type", "type_name", "size", "scale", "nullable", "default", "auto_increment", "remarks"],
            list(alpha["columns"][0]),
        )

    def test_mysql_catalog_filter_is_used_instead_of_schema(self) -> None:
        result = self.run_snapshot(database="mysql", schema=None, catalog="fixture_catalog")
        self.assert_success(result)
        manifest = self.load_manifest()
        self.assertEqual({"catalog": "fixture_catalog", "schema": None, "table_pattern": "tenant_.*"}, manifest["scope"])
        self.assertIn("getTables|fixture_catalog|null|%", self.load_calls())
        self.assertIn("getPrimaryKeys|fixture_catalog|null|tenant_alpha", self.load_calls())

    def test_primary_key_sequence_is_numeric_and_stable(self) -> None:
        self.assert_success(self.run_snapshot())
        pk = self.load_manifest()["tables"][1]["primary_key"]
        self.assertEqual([{"name": "tenant_zebra_pkey", "column": "part_a", "sequence": 1},
                          {"name": "tenant_zebra_pkey", "column": "part_b", "sequence": 2}], pk)

    def test_unknown_optional_metadata_is_json_null(self) -> None:
        self.assert_success(self.run_snapshot())
        note = self.load_manifest()["tables"][0]["columns"][1]
        self.assertIsNone(note["default"])
        self.assertIsNone(note["auto_increment"])
        self.assertIsNone(note["remarks"])

    def test_table_regex_filters_after_metadata_read(self) -> None:
        self.assert_success(self.run_snapshot(pattern="tenant_alpha"))
        self.assertEqual(["tenant_alpha"], [table["name"] for table in self.load_manifest()["tables"]])
        self.assertIn("getTables|null|public|%", self.load_calls())

    def test_output_is_byte_identical_on_second_run(self) -> None:
        self.assert_success(self.run_snapshot())
        snapshot = self.work_path / "project/build/doma-codegen/schema-snapshot.json"
        first = snapshot.read_bytes()
        self.assert_success(self.run_snapshot())
        self.assertEqual(first, snapshot.read_bytes())

    def test_credential_bearing_url_is_rejected_without_echo(self) -> None:
        secret_url = "jdbc:fixture:postgresql://url-user-sentinel:url-password-sentinel@fixture-host-sentinel/db"
        result = self.run_snapshot(url=secret_url)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("DOMA_CODEGEN_DB_URL", result.stderr)
        self.assertNotIn("url-user-sentinel", result.stdout + result.stderr)
        self.assertNotIn("url-password-sentinel", result.stdout + result.stderr)
        self.assertNotIn("fixture-host-sentinel", result.stdout + result.stderr)

    def test_manifest_and_errors_do_not_contain_connection_sentinels(self) -> None:
        self.assert_success(self.run_snapshot())
        manifest = (self.work_path / "project/build/doma-codegen/schema-snapshot.json").read_text()
        for sentinel in ("fixture-user-sentinel", "fixture-password-sentinel", "fixture-host-sentinel"):
            self.assertNotIn(sentinel, manifest)
        result = self.run_snapshot(database="mysql", url="jdbc:fixture:postgresql")
        self.assertNotEqual(0, result.returncode)
        for sentinel in ("fixture-user-sentinel", "fixture-password-sentinel", "fixture-host-sentinel"):
            self.assertNotIn(sentinel, result.stdout + result.stderr)

    def test_no_statement_or_mutating_connection_method_is_called(self) -> None:
        self.assert_success(self.run_snapshot())
        self.assertEqual([call for call in self.load_calls() if call.startswith("forbidden|")], [])

    def test_output_path_outside_build_directory_is_rejected(self) -> None:
        result = self.run_snapshot(output=self.work_path / "outside.json")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("DOMA_CODEGEN_SCHEMA_SNAPSHOT", result.stderr)
        self.assertFalse((self.work_path / "outside.json").exists())

    def test_source_compiles_without_xlint_warnings(self) -> None:
        classes = self.work_path / "lint-classes"
        result = subprocess.run(
            ["javac", "-Xlint:all", "-d", str(classes), str(SCRIPT)],
            text=True, capture_output=True,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stderr)


if __name__ == "__main__":
    unittest.main()
