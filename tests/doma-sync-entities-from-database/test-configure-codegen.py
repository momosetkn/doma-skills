from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONFIGURATOR = ROOT / "skills/doma-sync-entities-from-database/scripts/configure-codegen.py"
FIXTURES = Path(__file__).parent / "fixtures/gradle-config"
SENTINEL = "S3CR3T-CONFIG-FIXTURE"


def run_configurator(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CONFIGURATOR), *args, "--project-root", str(project)],
        text=True,
        capture_output=True,
        check=False,
    )


class ConfigureCodegenTests(unittest.TestCase):
    def make_project(self, build_name: str = "build.gradle.kts", extra: str = "") -> tuple[tempfile.TemporaryDirectory[str], Path]:
        directory = tempfile.TemporaryDirectory()
        project = Path(directory.name)
        (project / build_name).write_text((FIXTURES / build_name).read_text() + extra, encoding="utf-8")
        return directory, project

    def plan_args(self, output: str = "build/doma-codegen/configure-plan.json") -> tuple[str, ...]:
        return (
            "plan", "--language", "kotlin", "--database", "postgresql",
            "--entity-package", "example.generated", "--schema", "public",
            "--table-pattern", "tenant_.*", "--codegen-version", "3.2.2",
            "--driver-coordinate", "org.postgresql:postgresql:42.7.10",
            "--metamodel", "true", "--output-plan", output,
        )

    def create_plan(self, project: Path, output: str = "build/doma-codegen/configure-plan.json") -> Path:
        result = run_configurator(project, *self.plan_args(output))
        self.assertEqual(2, result.returncode, result.stderr)
        plan = project / output
        self.assertTrue(plan.is_file())
        return plan

    def plan_fragment_text(self, plan: Path) -> str:
        return plan.read_text(encoding="utf-8").replace('\\"', '"').replace("\\n", "\n")

    def test_kotlin_dsl_plan_contains_plugin_dependency_provider_block_and_temp_output(self) -> None:
        directory, project = self.make_project()
        with directory:
            plan = self.create_plan(project)
            text = self.plan_fragment_text(plan)
            self.assertIn('id("org.domaframework.doma.codegen") version "3.2.2"', text)
            self.assertIn('domaCodeGen("org.postgresql:postgresql:42.7.10")', text)
            self.assertIn('providers.environmentVariable("DOMA_SYNC_JDBC_URL").orElse(providers.gradleProperty("domaSyncJdbcUrl"))', text)
            self.assertIn("build/doma-codegen/generated", text)

    def test_kotlin_dsl_ordinary_gradle_tasks_configure_without_credentials(self) -> None:
        directory, project = self.make_project()
        with directory:
            plan = self.create_plan(project)
            applied = run_configurator(project, "apply", "--plan", str(plan))
            self.assertEqual(0, applied.returncode, applied.stderr)
            result = subprocess.run(
                ["gradle", "--no-daemon", "tasks", "--console=plain"],
                cwd=project,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_groovy_dsl_plan_contains_plugin_dependency_provider_block_and_temp_output(self) -> None:
        directory, project = self.make_project("build.gradle")
        with directory:
            plan = self.create_plan(project)
            text = self.plan_fragment_text(plan)
            self.assertIn("id 'org.domaframework.doma.codegen' version '3.2.2'", text)
            self.assertIn("domaCodeGen 'org.postgresql:postgresql:42.7.10'", text)
            self.assertIn("providers.environmentVariable('DOMA_SYNC_JDBC_URL').orElse(providers.gradleProperty('domaSyncJdbcUrl'))", text)
            self.assertIn("build/doma-codegen/generated", text)

    def test_apply_then_plan_is_byte_identical_and_returns_no_change(self) -> None:
        directory, project = self.make_project()
        with directory:
            plan = self.create_plan(project)
            applied = run_configurator(project, "apply", "--plan", str(plan))
            self.assertEqual(0, applied.returncode, applied.stderr)
            first = (project / "build.gradle.kts").read_bytes()
            planned = run_configurator(project, *self.plan_args())
            self.assertEqual(0, planned.returncode, planned.stderr)
            self.assertEqual(first, (project / "build.gradle.kts").read_bytes())

    def test_existing_plugin_and_driver_are_not_duplicated(self) -> None:
        extra = '''
plugins { id("org.domaframework.doma.codegen") version "3.2.2" }
dependencies { domaCodeGen("org.postgresql:postgresql:42.7.10") }
'''
        directory, project = self.make_project(extra=extra)
        with directory:
            self.create_plan(project)
            applied = run_configurator(project, "apply", "--plan", str(project / "build/doma-codegen/configure-plan.json"))
            self.assertEqual(0, applied.returncode, applied.stderr)
            build = (project / "build.gradle.kts").read_text(encoding="utf-8")
            self.assertEqual(1, build.count('id("org.domaframework.doma.codegen")'))
            self.assertEqual(1, build.count('domaCodeGen("org.postgresql:postgresql:42.7.10")'))

    def test_existing_managed_doma_sync_block_is_repaired(self) -> None:
        extra = '''
// doma-sync-entities-from-database:begin
broken managed content
// doma-sync-entities-from-database:end
'''
        directory, project = self.make_project(extra=extra)
        with directory:
            self.create_plan(project)
            applied = run_configurator(project, "apply", "--plan", str(project / "build/doma-codegen/configure-plan.json"))
            self.assertEqual(0, applied.returncode, applied.stderr)
            build = (project / "build.gradle.kts").read_text(encoding="utf-8")
            self.assertNotIn("broken managed content", build)
            self.assertIn('register("domaSync")', build)

    def test_unmanaged_ambiguous_doma_sync_block_stops_without_write(self) -> None:
        extra = '''
domaCodeGen { register("domaSync") { url.set("jdbc:postgresql://host/db") } }
'''
        directory, project = self.make_project(extra=extra)
        with directory:
            before = (project / "build.gradle.kts").read_bytes()
            result = run_configurator(project, *self.plan_args())
            self.assertEqual(65, result.returncode)
            self.assertEqual(before, (project / "build.gradle.kts").read_bytes())

    def test_dynamic_plugins_block_stops_without_write(self) -> None:
        directory, project = self.make_project(extra='\nplugins { id(pluginId) }\n')
        with directory:
            before = (project / "build.gradle.kts").read_bytes()
            result = run_configurator(project, *self.plan_args())
            self.assertEqual(65, result.returncode)
            self.assertEqual(before, (project / "build.gradle.kts").read_bytes())

    def test_project_gradle_properties_secret_key_stops_without_echoing_value(self) -> None:
        directory, project = self.make_project()
        with directory:
            (project / "gradle.properties").write_text(f"domaSyncPassword={SENTINEL}\n", encoding="utf-8")
            result = run_configurator(project, *self.plan_args())
            self.assertEqual(65, result.returncode)
            combined = result.stdout + result.stderr
            self.assertNotIn(SENTINEL, combined)
            self.assertFalse((project / "build/doma-codegen/configure-plan.json").exists())

    def test_ordinary_build_guard_is_present(self) -> None:
        directory, project = self.make_project()
        with directory:
            plan = self.create_plan(project)
            text = self.plan_fragment_text(plan)
            self.assertIn('gradle.startParameter.taskNames.any', text)
            self.assertIn('startsWith("domaCodeGenDomaSync")', text)

    def test_codegen_task_registration_guard_is_present(self) -> None:
        directory, project = self.make_project()
        with directory:
            plan = self.create_plan(project)
            text = self.plan_fragment_text(plan)
            self.assertIn('register("domaSync")', text)
            self.assertIn("domaCodeGenDomaSync", text)

    def test_classpath_writer_is_credential_independent(self) -> None:
        directory, project = self.make_project()
        with directory:
            plan = self.create_plan(project)
            text = self.plan_fragment_text(plan)
            self.assertIn('register("domaSyncWriteCodeGenClasspath")', text)
            self.assertLess(text.index('register("domaSyncWriteCodeGenClasspath")'), text.index('if (gradle.startParameter.taskNames.any'))

    def test_stale_configuration_plan_is_rejected(self) -> None:
        directory, project = self.make_project()
        with directory:
            plan = self.create_plan(project)
            build = project / "build.gradle.kts"
            build.write_text(build.read_text(encoding="utf-8") + "\n// changed after plan\n", encoding="utf-8")
            result = run_configurator(project, "apply", "--plan", str(plan))
            self.assertEqual(66, result.returncode)
            self.assertIn("changed after plan", build.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
