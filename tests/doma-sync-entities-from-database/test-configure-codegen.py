from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONFIGURATOR = ROOT / "skills/doma-sync-entities-from-database/scripts/configure-codegen.py"
FIXTURES = Path(__file__).parent / "fixtures/gradle-config"
UNIT_RUNNER = Path(__file__).parent / "run-unit-tests.py"
SENTINEL = "S3CR3T-CONFIG-FIXTURE"


def request_args(inputs: dict[str, str | None]) -> tuple[str, ...]:
    args = [
        "--language", str(inputs["language"]),
        "--database", str(inputs["database"]),
        "--entity-package", str(inputs["entity_package"]),
    ]
    if inputs["schema"] is not None:
        args.extend(("--schema", str(inputs["schema"])))
    if inputs["catalog"] is not None:
        args.extend(("--catalog", str(inputs["catalog"])))
    args.extend((
        "--table-pattern", str(inputs["table_pattern"]),
        "--codegen-version", str(inputs["codegen_version"]),
        "--driver-coordinate", str(inputs["driver_coordinate"]),
        "--metamodel", str(inputs["metamodel"]),
    ))
    return tuple(args)


def run_configurator(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    command_args = list(args)
    if command_args and command_args[0] == "apply" and "--language" not in command_args:
        plan_value = command_args[command_args.index("--plan") + 1]
        plan_path = Path(plan_value)
        if not plan_path.is_absolute():
            plan_path = project / plan_path
        inputs = json.loads(plan_path.read_text(encoding="utf-8"))["inputs"]
        command_args.extend(request_args(inputs))
    return subprocess.run(
        [sys.executable, str(CONFIGURATOR), *command_args, "--project-root", str(project)],
        text=True,
        capture_output=True,
        check=False,
    )


class ConfigureCodegenTests(unittest.TestCase):
    def test_release_runner_lists_all_six_hyphenated_test_modules(self) -> None:
        result = subprocess.run(
            [sys.executable, str(UNIT_RUNNER), "--list-files"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(
            [
                "test-configure-codegen.py",
                "test-entity-merge.py",
                "test-generate-wrapper.py",
                "test-schema-snapshot.py",
                "test-security.py",
                "test-source-model.py",
            ],
            result.stdout.splitlines(),
        )

    def make_project(self, build_name: str = "build.gradle.kts", extra: str = "") -> tuple[tempfile.TemporaryDirectory[str], Path]:
        directory = tempfile.TemporaryDirectory()
        project = Path(directory.name)
        (project / build_name).write_text((FIXTURES / build_name).read_text() + extra, encoding="utf-8")
        subprocess.run(["git", "init", "-q"], cwd=project, check=True)
        subprocess.run(["git", "config", "user.name", "Fixture"], cwd=project, check=True)
        subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=project, check=True)
        subprocess.run(
            ["git", "config", "user.email", "fixture@example.invalid"],
            cwd=project,
            check=True,
        )
        subprocess.run(["git", "add", "."], cwd=project, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=project, check=True)
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
        build = project / ("build.gradle.kts" if (project / "build.gradle.kts").exists() else "build.gradle")
        status = subprocess.run(
            ["git", "status", "--porcelain=v1", "--", build.name],
            cwd=project,
            text=True,
            capture_output=True,
            check=True,
        )
        if status.stdout:
            subprocess.run(["git", "add", "--", build.name], cwd=project, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "fixture build state"], cwd=project, check=True
            )
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

    def test_regex_scope_is_a_valid_exact_kotlin_and_groovy_literal_for_clean(self) -> None:
        table_pattern = r"tenant_\d+'archive"
        for build_name in ("build.gradle.kts", "build.gradle"):
            with self.subTest(build_name=build_name):
                directory, project = self.make_project(build_name)
                with directory:
                    args = list(self.plan_args())
                    args[args.index("--table-pattern") + 1] = table_pattern
                    planned = run_configurator(project, *args)
                    self.assertEqual(2, planned.returncode, planned.stderr)
                    plan = project / "build/doma-codegen/configure-plan.json"
                    self.assertEqual(
                        table_pattern,
                        json.loads(plan.read_text(encoding="utf-8"))["inputs"]["table_pattern"],
                    )
                    applied = run_configurator(project, "apply", "--plan", str(plan))
                    self.assertEqual(0, applied.returncode, applied.stderr)
                    if build_name.endswith(".kts"):
                        probe = """
tasks.register("domaCodeGenDomaSyncVerifyPattern") {
    doLast {
        val configs = project.extensions.getByName("domaCodeGen")
            as org.gradle.api.NamedDomainObjectContainer<org.seasar.doma.gradle.codegen.extension.CodeGenConfig>
        println("DOMA_SYNC_PATTERN=" + configs.getByName("domaSync").tableNamePattern.get())
    }
}
"""
                    else:
                        probe = """
tasks.register('domaCodeGenDomaSyncVerifyPattern') {
    doLast {
        def configs = project.extensions.getByName('domaCodeGen')
        println('DOMA_SYNC_PATTERN=' + configs.getByName('domaSync').tableNamePattern.get())
    }
}
"""
                    build = project / build_name
                    build.write_text(
                        build.read_text(encoding="utf-8") + probe,
                        encoding="utf-8",
                    )
                    clean = subprocess.run(
                        [
                            "gradle", "--no-daemon", "clean",
                            "domaCodeGenDomaSyncVerifyPattern", "--console=plain",
                        ],
                        cwd=project,
                        env={
                            **os.environ,
                            "DOMA_SYNC_JDBC_URL": "jdbc:postgresql://127.0.0.1:1/test",
                            "DOMA_SYNC_JDBC_USER": "fixture",
                            "DOMA_SYNC_JDBC_PASSWORD": "fixture",
                        },
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                    self.assertEqual(0, clean.returncode, clean.stdout + clean.stderr)
                    self.assertIn("DOMA_SYNC_PATTERN=" + table_pattern, clean.stdout)

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

    def test_kotlin_plugin_declarations_in_comments_and_strings_do_not_block_insertion(self) -> None:
        directory, project = self.make_project(extra='''
// id("org.domaframework.doma.codegen") version "3.2.2"
val ignoredCodeGenPlugin = "id(\\\"org.domaframework.doma.codegen\\\") version \\\"3.2.2\\\""
''')
        with directory:
            plan = self.create_plan(project)
            self.assertEqual(0, run_configurator(project, "apply", "--plan", str(plan)).returncode)
            plugins = (project / "build.gradle.kts").read_text(encoding="utf-8").split("}", 1)[0]
            self.assertIn('id("org.domaframework.doma.codegen") version "3.2.2"', plugins)

    def test_groovy_plugin_declarations_in_comments_and_strings_do_not_block_insertion(self) -> None:
        directory, project = self.make_project("build.gradle", extra="""
// id 'org.domaframework.doma.codegen' version '3.2.2'
def ignoredCodeGenPlugin = \"id 'org.domaframework.doma.codegen' version '3.2.2'\"
""")
        with directory:
            plan = self.create_plan(project)
            self.assertEqual(0, run_configurator(project, "apply", "--plan", str(plan)).returncode)
            plugins = (project / "build.gradle").read_text(encoding="utf-8").split("}", 1)[0]
            self.assertIn("id 'org.domaframework.doma.codegen' version '3.2.2'", plugins)

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

    def test_project_gradle_properties_credential_url_stops_without_echoing_value(self) -> None:
        directory, project = self.make_project()
        with directory:
            credential_url = f"jdbc:postgresql://{SENTINEL}:password@db.example/app"
            (project / "gradle.properties").write_text(
                f"domaSyncJdbcUrl={credential_url}\n", encoding="utf-8"
            )
            result = run_configurator(project, *self.plan_args())
            self.assertEqual(65, result.returncode)
            self.assertNotIn(SENTINEL, result.stdout + result.stderr)
            self.assertFalse((project / "build/doma-codegen/configure-plan.json").exists())

    def test_credential_url_provider_is_rejected_in_generated_gradle(self) -> None:
        directory, project = self.make_project()
        with directory:
            text = self.plan_fragment_text(self.create_plan(project))
            self.assertIn("Credential-bearing JDBC URL is unsafe", text)
            self.assertIn("domaSyncJdbcUrl", text)

    def test_apply_preserves_crlf_build_file_line_endings(self) -> None:
        directory, project = self.make_project()
        with directory:
            build = project / "build.gradle.kts"
            build.write_bytes(build.read_bytes().replace(b"\n", b"\r\n"))
            plan = self.create_plan(project)
            applied = run_configurator(project, "apply", "--plan", str(plan))
            self.assertEqual(0, applied.returncode, applied.stderr)
            content = build.read_bytes()
            self.assertIn(b"\r\n", content)
            self.assertNotIn(b"\n", content.replace(b"\r\n", b""))
            self.assertNotIn(b"\r\r\n", content)
            planned = run_configurator(project, *self.plan_args())
            self.assertEqual(0, planned.returncode, planned.stderr)

    def test_missing_codegen_driver_is_restored_after_initial_apply(self) -> None:
        directory, project = self.make_project()
        with directory:
            first_plan = self.create_plan(project)
            self.assertEqual(0, run_configurator(project, "apply", "--plan", str(first_plan)).returncode)
            build = project / "build.gradle.kts"
            coordinate = 'domaCodeGen("org.postgresql:postgresql:42.7.10")'
            build.write_text(build.read_text(encoding="utf-8").replace(coordinate, ""), encoding="utf-8")
            repaired_plan = self.create_plan(project)
            self.assertEqual(0, run_configurator(project, "apply", "--plan", str(repaired_plan)).returncode)
            self.assertIn(coordinate, build.read_text(encoding="utf-8"))

    def test_mismatched_codegen_plugin_and_driver_are_repaired(self) -> None:
        directory, project = self.make_project()
        with directory:
            build = project / "build.gradle.kts"
            build.write_text('''plugins {
    id("org.domaframework.doma.codegen") version "3.1.0"
}
dependencies {
    domaCodeGen("org.postgresql:postgresql:42.7.9")
}
''', encoding="utf-8")
            plan = self.create_plan(project)
            self.assertEqual(0, run_configurator(project, "apply", "--plan", str(plan)).returncode)
            text = build.read_text(encoding="utf-8")
            self.assertIn('id("org.domaframework.doma.codegen") version "3.2.2"', text)
            self.assertIn('domaCodeGen("org.postgresql:postgresql:42.7.10")', text)
            self.assertNotIn("3.1.0", text)
            self.assertNotIn("42.7.9", text)

    def test_existing_groovy_codegen_plugin_is_not_duplicated(self) -> None:
        directory, project = self.make_project("build.gradle")
        with directory:
            build = project / "build.gradle"
            build.write_text("""plugins {
    id 'org.domaframework.doma.codegen' version '3.2.2'
}
dependencies {
    domaCodeGen 'org.postgresql:postgresql:42.7.10'
}
""", encoding="utf-8")
            plan = self.create_plan(project)
            self.assertEqual(0, run_configurator(project, "apply", "--plan", str(plan)).returncode)
            text = build.read_text(encoding="utf-8")
            self.assertEqual(1, text.count("id 'org.domaframework.doma.codegen'"))
            self.assertEqual(0, run_configurator(project, *self.plan_args()).returncode)

    def test_mismatched_groovy_codegen_plugin_is_repaired(self) -> None:
        directory, project = self.make_project("build.gradle")
        with directory:
            build = project / "build.gradle"
            build.write_text("""plugins {
    id 'org.domaframework.doma.codegen' version '3.1.0'
}
dependencies {
    domaCodeGen 'org.postgresql:postgresql:42.7.10'
}
""", encoding="utf-8")
            plan = self.create_plan(project)
            self.assertEqual(0, run_configurator(project, "apply", "--plan", str(plan)).returncode)
            text = build.read_text(encoding="utf-8")
            self.assertEqual(1, text.count("id 'org.domaframework.doma.codegen'"))
            self.assertIn("id 'org.domaframework.doma.codegen' version '3.2.2'", text)
            self.assertNotIn("3.1.0", text)

    def test_gradle_7_wrapper_stops_without_write(self) -> None:
        directory, project = self.make_project()
        with directory:
            wrapper = project / "gradle/wrapper/gradle-wrapper.properties"
            wrapper.parent.mkdir(parents=True)
            wrapper.write_text("distributionUrl=https\\://services.gradle.org/distributions/gradle-7.6-bin.zip\n", encoding="utf-8")
            before = (project / "build.gradle.kts").read_bytes()
            result = run_configurator(project, *self.plan_args())
            self.assertEqual(65, result.returncode)
            self.assertIn("Gradle 8+", result.stderr)
            self.assertEqual(before, (project / "build.gradle.kts").read_bytes())
            self.assertFalse((project / "build/doma-codegen/configure-plan.json").exists())

    def test_java_11_toolchain_stops_without_write(self) -> None:
        directory, project = self.make_project(extra="""
java { toolchain { languageVersion.set(JavaLanguageVersion.of(11)) } }
""")
        with directory:
            before = (project / "build.gradle.kts").read_bytes()
            result = run_configurator(project, *self.plan_args())
            self.assertEqual(65, result.returncode)
            self.assertIn("Java 17+", result.stderr)
            self.assertEqual(before, (project / "build.gradle.kts").read_bytes())
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

    def test_generated_candidates_render_physical_names_and_database_comments(self) -> None:
        for build_name, qualifier in (
            ("build.gradle.kts", "showSchemaName.set(true)"),
            ("build.gradle", "showSchemaName.set(true)"),
        ):
            with self.subTest(build_name=build_name):
                directory, project = self.make_project(build_name)
                with directory:
                    text = self.plan_fragment_text(self.create_plan(project))
                    self.assertIn(qualifier, text)
                    self.assertIn("showCatalogName.set(false)", text)
                    self.assertIn("showTableName.set(true)", text)
                    self.assertIn("showColumnName.set(true)", text)
                    self.assertIn("showDbComment.set(true)", text)

        directory, project = self.make_project("build.gradle")
        with directory:
            result = run_configurator(
                project, "plan", "--language", "java", "--database", "mysql",
                "--entity-package", "example.generated", "--catalog", "fixture_catalog",
                "--table-pattern", ".*", "--codegen-version", "3.2.2",
                "--driver-coordinate", "com.mysql:mysql-connector-j:26.7.0",
                "--metamodel", "false", "--output-plan",
                "build/doma-codegen/configure-plan.json",
            )
            self.assertEqual(2, result.returncode, result.stderr)
            text = self.plan_fragment_text(
                project / "build/doma-codegen/configure-plan.json"
            )
            self.assertIn("showCatalogName.set(true)", text)
            self.assertIn("showSchemaName.set(false)", text)

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
            subprocess.run(["git", "add", "--", build.name], cwd=project, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "post-plan build change"], cwd=project, check=True
            )
            result = run_configurator(project, "apply", "--plan", str(plan))
            self.assertEqual(66, result.returncode)
            self.assertIn("changed after plan", build.read_text(encoding="utf-8"))

    def test_crafted_configuration_plan_cannot_retarget_readme(self) -> None:
        directory, project = self.make_project()
        with directory:
            readme = project / "README.md"
            readme.write_text("retain me\n", encoding="utf-8")
            plan = self.create_plan(project)
            data = json.loads(plan.read_text(encoding="utf-8"))
            independent_request = request_args(data["inputs"])
            replacement = "attacker-controlled\n"
            data["mutations"] = [{
                "path": "README.md",
                "before_sha256": hashlib.sha256(readme.read_bytes()).hexdigest(),
                "after_sha256": hashlib.sha256(replacement.encode("utf-8")).hexdigest(),
                "edits": [{
                    "start": 0,
                    "end": len(readme.read_text(encoding="utf-8")),
                    "replacement": replacement,
                }],
            }]
            plan.write_text(json.dumps(data), encoding="utf-8")
            before = readme.read_bytes()

            result = run_configurator(
                project, "apply", "--plan", str(plan), *independent_request
            )

            self.assertNotEqual(0, result.returncode)
            self.assertEqual(before, readme.read_bytes())
            self.assertNotEqual(replacement, readme.read_text(encoding="utf-8"))

    def test_dirty_build_file_blocks_configuration_apply_but_unrelated_change_is_allowed(self) -> None:
        directory, project = self.make_project()
        with directory:
            readme = project / "README.md"
            readme.write_text("before\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=project, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "tracked readme"], cwd=project, check=True
            )
            readme.write_text("unrelated tracked change\n", encoding="utf-8")
            clean_plan = self.create_plan(project)
            clean_apply = run_configurator(project, "apply", "--plan", str(clean_plan))
            self.assertEqual(0, clean_apply.returncode, clean_apply.stderr)

            subprocess.run(
                ["git", "checkout", "--", "build.gradle.kts"], cwd=project, check=True
            )
            build = project / "build.gradle.kts"
            build.write_text(
                build.read_text(encoding="utf-8") + "\n// local build edit\n",
                encoding="utf-8",
            )
            dirty_planned = run_configurator(project, *self.plan_args())
            self.assertEqual(2, dirty_planned.returncode, dirty_planned.stderr)
            dirty_plan = project / "build/doma-codegen/configure-plan.json"
            before = build.read_bytes()

            dirty_apply = run_configurator(project, "apply", "--plan", str(dirty_plan))

            self.assertEqual(65, dirty_apply.returncode, dirty_apply.stderr)
            self.assertEqual(before, build.read_bytes())
            self.assertEqual("unrelated tracked change\n", readme.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
