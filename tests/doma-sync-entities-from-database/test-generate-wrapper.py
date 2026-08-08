import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "skills/doma-sync-entities-from-database/scripts/generate-entities.sh"
FIXTURES = Path(__file__).with_name("fixtures") / "aws-stubs"
PASSWORD = "test-password-sentinel-4"
TOKEN = "test-iam-token-sentinel-4"


class GenerateWrapperTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.project = self.base / "project"
        self.project.mkdir()
        (self.project / "build.gradle.kts").write_text("plugins { java }\n", encoding="utf-8")
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.log = self.base / "calls.log"
        self.user_gradle = self.base / "user-gradle"
        self.user_gradle.mkdir()
        self._install(FIXTURES / "fake-aws", self.bin / "aws")
        self._install(FIXTURES / "fake-java", self.bin / "java")
        self._install(FIXTURES / "fake-gradlew", self.bin / "gradle")
        self._install(FIXTURES / "fake-gradlew", self.project / "gradlew")
        self.env = {
            **os.environ,
            "PATH": str(self.bin) + os.pathsep + os.environ.get("PATH", ""),
            "GRADLE_USER_HOME": str(self.user_gradle),
            "FAKE_CALL_LOG": str(self.log),
            "FAKE_AWS_FIXTURES": str(FIXTURES),
            "FAKE_SECRET_USERNAME": "app_user",
            "FAKE_SECRET_PASSWORD": PASSWORD,
            "FAKE_IAM_TOKEN": TOKEN,
        }
        for name in tuple(self.env):
            if name.startswith("DOMA_CODEGEN_") or name.startswith("DOMA_SYNC_"):
                self.env.pop(name)
        self.env.pop("GRADLE_CMD", None)

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def _install(source, target):
        shutil.copy2(source, target)
        target.chmod(target.stat().st_mode | stat.S_IXUSR)

    def _local_env(self):
        self.env.update({
            "DOMA_CODEGEN_DB_URL": "jdbc:postgresql://local.example.test:5432/app",
            "DOMA_CODEGEN_DB_USER": "local_user",
            "DOMA_CODEGEN_DB_PASSWORD": PASSWORD,
            "EXPECTED_DB_URL": "jdbc:postgresql://local.example.test:5432/app",
            "EXPECTED_DB_USER": "local_user",
            "EXPECTED_DB_PASSWORD": PASSWORD,
        })

    def _run(self, connection="local", database="postgresql", extra=()):
        command = [
            "bash", str(WRAPPER), "--project-root", str(self.project),
            "--connection", connection, "--database", database, *extra,
        ]
        return subprocess.run(command, env=self.env, text=True, capture_output=True, timeout=20)

    def _aws_args(self, kind="instance", identifier="app-instance", extra=()):
        return (
            "--expected-account", "123456789012", "--region", "ap-northeast-1",
            "--target-kind", kind, "--target-id", identifier,
            "--db-name", "appdb", *extra,
        )

    def _calls(self):
        return self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else []

    def _assert_redacted(self, result):
        combined = result.stdout + result.stderr
        self.assertNotIn(PASSWORD, combined)
        self.assertNotIn(TOKEN, combined)

    def test_local_environment_values_win_over_user_gradle_properties(self):
        self._local_env()
        (self.user_gradle / "gradle.properties").write_text(
            "domaCodegenDbUrl=jdbc:postgresql://wrong.example.test:5432/wrong\n"
            "domaCodegenDbUser=wrong_user\n"
            "domaCodegenDbPassword=wrong_password\n", encoding="utf-8")
        result = self._run()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("java|", "\n".join(self._calls()))

    def test_user_gradle_properties_are_used_when_environment_is_absent(self):
        (self.user_gradle / "gradle.properties").write_text(
            "domaCodegenDbUrl jdbc:postgresql://properties.example.test:5432/app\n"
            "domaCodegenDbUser: properties_user\n"
            f"domaCodegenDbPassword={PASSWORD}\n", encoding="utf-8")
        self.env.update({
            "EXPECTED_DB_URL": "jdbc:postgresql://properties.example.test:5432/app",
            "EXPECTED_DB_USER": "properties_user", "EXPECTED_DB_PASSWORD": PASSWORD,
        })
        result = self._run()
        self.assertEqual(0, result.returncode, result.stderr)

    def test_missing_local_credentials_stop_before_java_or_gradle(self):
        result = self._run()
        self.assertNotEqual(0, result.returncode)
        self.assertIn("DOMA_CODEGEN_DB_PASSWORD", result.stderr)
        self.assertEqual([], self._calls())

    def test_local_query_credentials_stop_before_java_or_gradle(self):
        self._local_env()
        query_secret = "query-secret-sentinel-4"
        self.env["DOMA_CODEGEN_DB_URL"] = (
            "jdbc:postgresql://local.example.test:5432/app?user=embedded&password=" + query_secret
        )
        result = self._run()
        self.assertNotEqual(0, result.returncode)
        self.assertEqual([], self._calls())
        self.assertNotIn(query_secret, result.stdout + result.stderr)

    def test_project_wrapper_is_preferred_and_path_gradle_is_safe_fallback(self):
        self._local_env()
        result = self._run()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(self._calls()[0].startswith("gradlew|"), self._calls())
        shutil.rmtree(self.project / "build", ignore_errors=True)
        (self.project / "gradlew").unlink()
        self.log.unlink()
        result = self._run()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(self._calls()[0].startswith("gradle|"), self._calls())

    def test_project_gradle_properties_secret_stops_before_generation(self):
        self._local_env()
        (self.project / "gradle.properties").write_text(
            "domaCodegenDbPassword=project-secret-must-not-appear\n", encoding="utf-8")
        result = self._run()
        self.assertNotEqual(0, result.returncode)
        self.assertIn("domaCodegenDbPassword", result.stderr)
        self.assertNotIn("project-secret-must-not-appear", result.stderr)
        self.assertEqual([], self._calls())

    def test_applied_gradle_literal_or_symlink_stops_before_generation(self):
        self._local_env()
        applied = self.project / "applied.gradle.kts"
        applied.write_text('val domaCodegenDbPassword: String = "applied-secret-must-not-appear"\n', encoding="utf-8")
        (self.project / "build.gradle.kts").write_text('apply(from = "applied.gradle.kts")\n', encoding="utf-8")
        result = self._run()
        self.assertNotEqual(0, result.returncode)
        self.assertIn("domaCodegenDbPassword", result.stderr)
        self.assertNotIn("applied-secret-must-not-appear", result.stderr)
        self.assertEqual([], self._calls())
        applied.unlink()
        outside = self.base / "outside.gradle.kts"
        outside.write_text("plugins { java }\n", encoding="utf-8")
        applied.symlink_to(outside)
        result = self._run()
        self.assertNotEqual(0, result.returncode)
        self.assertIn("Gradle build tree", result.stderr)
        self.assertEqual([], self._calls())
        applied.unlink()
        applied.write_text('domaCodegenDbPassword.set("setter-secret-must-not-appear")\n', encoding="utf-8")
        result = self._run()
        self.assertNotEqual(0, result.returncode)
        self.assertIn("domaCodegenDbPassword", result.stderr)
        self.assertNotIn("setter-secret-must-not-appear", result.stderr)
        self.assertEqual([], self._calls())
        applied.write_text(
            'val dbUrl = "jdbc:postgresql://db.example.test/app?user=u&password=query-secret-must-not-appear"\n',
            encoding="utf-8",
        )
        result = self._run()
        self.assertNotEqual(0, result.returncode)
        self.assertIn("credential-bearing JDBC URL", result.stderr)
        self.assertNotIn("query-secret-must-not-appear", result.stderr)
        self.assertEqual([], self._calls())

    def test_aws_identity_mismatch_stops_before_rds_and_secret_calls(self):
        self.env["FAKE_AWS_ACCOUNT"] = "999999999999"
        result = self._run("aws-secret", extra=self._aws_args(extra=("--secret-id", "app-secret")))
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(1, len(self._calls()), self._calls())
        self.assertIn("aws|sts|get-caller-identity", self._calls()[0])

    def test_exact_rds_instance_secret_flow(self):
        self.env.update({
            "FAKE_AWS_SCENARIO": "instance", "EXPECTED_DB_URL": "jdbc:postgresql://db.example.test:5432/appdb?sslmode=verify-full",
            "EXPECTED_DB_USER": "app_user", "EXPECTED_DB_PASSWORD": PASSWORD,
        })
        result = self._run("aws-secret", extra=self._aws_args(extra=("--secret-id", "app-secret")))
        self.assertEqual(0, result.returncode, result.stderr)
        calls = "\n".join(self._calls())
        self.assertIn("rds|describe-db-instances|--db-instance-identifier|app-instance", calls)
        self.assertIn("secretsmanager|describe-secret|--secret-id|app-secret", calls)
        self.assertIn("secretsmanager|get-secret-value|--secret-id|app-secret", calls)

    def test_exact_aurora_cluster_iam_flow(self):
        self.env.update({
            "FAKE_AWS_SCENARIO": "cluster", "EXPECTED_DB_URL": "jdbc:mysql://cluster.example.test:3306/appdb?sslMode=VERIFY_IDENTITY",
            "EXPECTED_DB_USER": "iam_user", "EXPECTED_DB_PASSWORD": TOKEN,
        })
        result = self._run("aws-iam", "mysql", self._aws_args("cluster", "app-cluster", ("--db-user", "iam_user")))
        self.assertEqual(0, result.returncode, result.stderr)
        calls = "\n".join(self._calls())
        self.assertIn("rds|describe-db-clusters|--db-cluster-identifier|app-cluster", calls)
        self.assertIn("rds|generate-db-auth-token|--hostname|cluster.example.test|--port|3306|--username|iam_user|--region|ap-northeast-1", calls)

    def test_proxy_target_engine_is_resolved_before_connection(self):
        self.env.update({
            "FAKE_AWS_SCENARIO": "proxy", "EXPECTED_DB_URL": "jdbc:postgresql://proxy.example.test:5432/appdb?sslmode=verify-full",
            "EXPECTED_DB_USER": "iam_user", "EXPECTED_DB_PASSWORD": TOKEN,
        })
        result = self._run("aws-iam", extra=self._aws_args("proxy", "app-proxy", ("--db-user", "iam_user")))
        self.assertEqual(0, result.returncode, result.stderr)
        calls = self._calls()
        proxy_target = next(i for i, line in enumerate(calls) if "describe-db-proxy-targets" in line)
        resolved = next(i for i, line in enumerate(calls) if "describe-db-instances" in line)
        generated = next(i for i, line in enumerate(calls) if "generate-db-auth-token" in line)
        self.assertLess(proxy_target, resolved)
        self.assertLess(resolved, generated)
        shutil.rmtree(self.project / "build")
        self.log.unlink()
        self.env["FAKE_PROXY_TARGETS_MIXED_INVALID"] = "true"
        result = self._run("aws-iam", extra=self._aws_args("proxy", "app-proxy", ("--db-user", "iam_user")))
        self.assertNotEqual(0, result.returncode)
        self.assertFalse(any("generate-db-auth-token" in line for line in self._calls()))
        shutil.rmtree(self.project / "build", ignore_errors=True)
        self.log.unlink()
        self.env.pop("FAKE_PROXY_TARGETS_MIXED_INVALID")
        self.env["FAKE_PROXY_TRACKED_CLUSTER"] = "true"
        result = self._run("aws-iam", extra=self._aws_args("proxy", "app-proxy", ("--db-user", "iam_user")))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(any(
            "describe-db-clusters|--db-cluster-identifier|app-pg-cluster" in line for line in self._calls()
        ))

    def test_secret_host_cannot_redirect_confirmed_rds_target(self):
        self.env.update({"FAKE_AWS_SCENARIO": "instance", "FAKE_SECRET_HOST": "evil.example.test"})
        result = self._run("aws-secret", extra=self._aws_args(extra=("--secret-id", "app-secret")))
        self.assertNotEqual(0, result.returncode)
        self.assertIn("Secret routing fields conflict", result.stderr)
        self.assertFalse(any(line.startswith("java|") for line in self._calls()))
        self.assertNotIn("evil.example.test", result.stdout + result.stderr)

    def test_iam_token_is_generated_for_confirmed_endpoint_user_and_region(self):
        self.env.update({
            "FAKE_AWS_SCENARIO": "instance", "EXPECTED_DB_URL": "jdbc:postgresql://db.example.test:5432/appdb?sslmode=verify-full",
            "EXPECTED_DB_USER": "exact_user", "EXPECTED_DB_PASSWORD": TOKEN,
        })
        result = self._run("aws-iam", extra=self._aws_args(extra=("--db-user", "exact_user")))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn(
            "rds|generate-db-auth-token|--hostname|db.example.test|--port|5432|--username|exact_user|--region|ap-northeast-1",
            "\n".join(self._calls()),
        )

    def test_iso_region_is_validated_before_exact_aws_calls(self):
        self.env.update({
            "FAKE_AWS_SCENARIO": "instance",
            "EXPECTED_DB_URL": "jdbc:postgresql://db.example.test:5432/appdb?sslmode=verify-full",
            "EXPECTED_DB_USER": "iso_user", "EXPECTED_DB_PASSWORD": TOKEN,
        })
        args = (
            "--expected-account", "123456789012", "--region", "us-iso-east-1",
            "--target-kind", "instance", "--target-id", "app-instance",
            "--db-name", "appdb", "--db-user", "iso_user",
        )
        result = self._run("aws-iam", extra=args)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_classpath_snapshot_and_entity_tasks_run_with_no_daemon(self):
        self._local_env()
        result = self._run()
        self.assertEqual(0, result.returncode, result.stderr)
        calls = self._calls()
        self.assertEqual("gradlew|--no-daemon|domaSyncWriteCodeGenClasspath", calls[0])
        self.assertTrue(calls[1].startswith("java|--class-path|fixture-classpath|"), calls)
        self.assertEqual("gradlew|--no-daemon|domaCodeGenDomaSyncEntity", calls[2])

    def test_secret_and_token_sentinels_are_redacted_from_both_streams(self):
        self._local_env()
        self.env["FAKE_LEAK_OUTPUT"] = "true"
        result = self._run()
        self.assertEqual(0, result.returncode, result.stderr)
        self._assert_redacted(result)
        self.assertIn("[REDACTED]", result.stdout + result.stderr)
        shutil.rmtree(self.project / "build")
        self.log.unlink()
        for name in ("DOMA_CODEGEN_DB_URL", "DOMA_CODEGEN_DB_USER", "DOMA_CODEGEN_DB_PASSWORD"):
            self.env.pop(name)
        self.env.update({
            "FAKE_AWS_SCENARIO": "instance",
            "EXPECTED_DB_URL": "jdbc:postgresql://db.example.test:5432/appdb?sslmode=verify-full",
            "EXPECTED_DB_USER": "iam_user", "EXPECTED_DB_PASSWORD": TOKEN,
        })
        result = self._run("aws-iam", extra=self._aws_args(extra=("--db-user", "iam_user")))
        self.assertEqual(0, result.returncode, result.stderr)
        self._assert_redacted(result)
        self.assertIn("[REDACTED]", result.stdout + result.stderr)

    def test_no_secret_appears_in_child_argv_or_call_log(self):
        self._local_env()
        result = self._run()
        self.assertEqual(0, result.returncode, result.stderr)
        logged = "\n".join(self._calls())
        self.assertNotIn(PASSWORD, logged)
        self.assertNotIn("jdbc:postgresql://local", logged)
        shutil.rmtree(self.project / "build")
        self.log.unlink()
        for name in ("DOMA_CODEGEN_DB_URL", "DOMA_CODEGEN_DB_USER", "DOMA_CODEGEN_DB_PASSWORD"):
            self.env.pop(name)
        self.env.update({
            "FAKE_AWS_SCENARIO": "instance",
            "EXPECTED_DB_URL": "jdbc:postgresql://db.example.test:5432/appdb?sslmode=verify-full",
            "EXPECTED_DB_USER": "app_user", "EXPECTED_DB_PASSWORD": PASSWORD,
        })
        result = self._run("aws-secret", extra=self._aws_args(extra=("--secret-id", "app-secret")))
        self.assertEqual(0, result.returncode, result.stderr)
        logged = "\n".join(self._calls())
        self.assertNotIn(PASSWORD, logged)
        shutil.rmtree(self.project / "build")
        self.log.unlink()
        self.env.update({"EXPECTED_DB_USER": "iam_user", "EXPECTED_DB_PASSWORD": TOKEN})
        result = self._run("aws-iam", extra=self._aws_args(extra=("--db-user", "iam_user")))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertNotIn(TOKEN, "\n".join(self._calls()))

    def test_generated_candidate_containing_secret_sentinel_is_removed_and_fails(self):
        self._local_env()
        self.env["FAKE_GENERATED_SECRET"] = PASSWORD
        result = self._run()
        self.assertNotEqual(0, result.returncode)
        self.assertIn("generated output failed credential scan", result.stderr)
        self._assert_redacted(result)
        self.assertFalse((self.project / "build/doma-codegen/generated").exists())
        self.assertFalse((self.project / "build/doma-codegen/schema-snapshot.json").exists())

    def test_output_paths_outside_project_build_are_rejected(self):
        self._local_env()
        outside = self.base / "outside"
        outside.mkdir()
        (self.project / "build").mkdir()
        (self.project / "build/doma-codegen").symlink_to(outside, target_is_directory=True)
        result = self._run()
        self.assertNotEqual(0, result.returncode)
        self.assertIn("output path", result.stderr)
        self.assertEqual([], self._calls())
        (self.project / "build/doma-codegen").unlink()
        self.log.unlink(missing_ok=True)
        redirected = self.base / "redirected-after-validation"
        self.env["FAKE_REDIRECT_GENERATED"] = str(redirected)
        result = self._run()
        self.assertNotEqual(0, result.returncode)
        self.assertIn("output path", result.stderr)
        self.assertTrue((redirected / "keep.txt").is_file())

    def test_path_replacement_after_classpath_stops_before_snapshot(self):
        self._local_env()
        redirected = self.base / "redirected-after-classpath"
        self.env["FAKE_REDIRECT_AFTER_CLASSPATH"] = str(redirected)
        result = self._run()
        self.assertNotEqual(0, result.returncode)
        self.assertIn("output path", result.stderr)
        self.assertFalse(any(line.startswith("java|") for line in self._calls()))
        self.assertTrue((redirected / "keep.txt").is_file())

    def test_failing_child_status_is_preserved_and_outputs_are_scanned(self):
        self._local_env()
        self.env["FAKE_JAVA_EXIT"] = "37"
        result = self._run()
        self.assertEqual(37, result.returncode, result.stderr)
        self.assertTrue((self.project / "build/doma-codegen/schema-snapshot.json").is_file())
        shutil.rmtree(self.project / "build")
        self.log.unlink()
        self.env["FAKE_SNAPSHOT_SECRET"] = PASSWORD
        result = self._run()
        self.assertEqual(65, result.returncode, result.stderr)
        self.assertFalse((self.project / "build/doma-codegen/schema-snapshot.json").exists())
        self.assertNotIn(PASSWORD, result.stdout + result.stderr)
        shutil.rmtree(self.project / "build", ignore_errors=True)
        self.log.unlink()
        self.env.pop("FAKE_JAVA_EXIT")
        self.env.pop("FAKE_SNAPSHOT_SECRET")
        self.env["FAKE_ENTITY_EXIT"] = "42"
        result = self._run()
        self.assertEqual(42, result.returncode, result.stderr)
        shutil.rmtree(self.project / "build")
        self.log.unlink()
        self.env["FAKE_GENERATED_SECRET"] = PASSWORD
        result = self._run()
        self.assertEqual(65, result.returncode, result.stderr)
        self.assertFalse((self.project / "build/doma-codegen/generated").exists())
        self.assertFalse((self.project / "build/doma-codegen/schema-snapshot.json").exists())

    def test_aws_mutation_and_database_cli_commands_never_run(self):
        self.env.update({
            "FAKE_AWS_SCENARIO": "instance", "EXPECTED_DB_URL": "jdbc:postgresql://db.example.test:5432/appdb?sslmode=verify-full",
            "EXPECTED_DB_USER": "app_user", "EXPECTED_DB_PASSWORD": PASSWORD,
        })
        for name in ("psql", "mysql"):
            self._install(FIXTURES / "fake-forbidden", self.bin / name)
        result = self._run("aws-secret", extra=self._aws_args(extra=("--secret-id", "app-secret")))
        self.assertEqual(0, result.returncode, result.stderr)
        calls = "\n".join(self._calls())
        self.assertNotIn("forbidden|", calls)
        self.assertNotRegex(calls, r"create-db-|modify-db-|delete-db-|failover-db-|restore-db-|rotate-secret")


if __name__ == "__main__":
    unittest.main()
