#!/usr/bin/env bash
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

if ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
  printf 'SKIP: Docker unavailable\n'
  exit 77
fi

readonly GRADLE_VERSION="9.4.1"
readonly GRADLE_SHA256="2ab2958f2a1e51120c326cad6f385153bb11ee93b3c216c5fccebfdfbb7ec6cb"
readonly TEST_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly REPO_ROOT="$(cd -- "$TEST_DIR/../.." && pwd -P)"

work_dir=""
cleanup() {
  if [[ -n "$work_dir" && -d "$work_dir" ]]; then
    rm -rf -- "$work_dir"
  fi
}
trap cleanup EXIT HUP INT TERM

fail() {
  printf 'FAIL: %s\n' "$1" >&2
  exit 1
}

path_is_outside_repo() {
  local candidate
  candidate=$(cd -- "$1" 2>/dev/null && pwd -P) || return 1
  [[ "$candidate" != "$REPO_ROOT" && "$candidate" != "$REPO_ROOT/"* ]]
}

select_temp_base() {
  local candidate canonical
  for candidate in "${TMPDIR:-}" /tmp /var/tmp; do
    [[ -n "$candidate" && -d "$candidate" && -w "$candidate" ]] || continue
    canonical=$(cd -- "$candidate" && pwd -P) || continue
    if path_is_outside_repo "$canonical"; then
      printf '%s\n' "$canonical"
      return
    fi
  done
  fail "no writable temporary directory exists outside the repository"
}

create_work_dir() {
  local base created
  base=$(select_temp_base)
  path_is_outside_repo "$base" || fail "temporary base resolved inside the repository"
  path_is_outside_repo "$REPO_ROOT" \
    && fail "temporary containment preflight accepted the repository root"
  path_is_outside_repo "$TEST_DIR" \
    && fail "temporary containment preflight accepted a repository child"
  created=$(mktemp -d --tmpdir="$base" 'doma-sync-testcontainers.XXXXXX')
  work_dir=$(cd -- "$created" && pwd -P)
  path_is_outside_repo "$work_dir" || fail "temporary work directory resolved inside the repository"
}

create_work_dir
if [[ "${DOMA_SYNC_TEMP_PREFLIGHT_ONLY:-0}" == "1" ]]; then
  printf 'PASS: temporary work directory outside repository\n'
  exit 0
fi

if [[ -n "${GRADLE_CMD:-}" ]]; then
  [[ -x "$GRADLE_CMD" ]] || { printf 'FAIL: GRADLE_CMD is not executable\n' >&2; exit 1; }
  gradle_command="$GRADLE_CMD"
else
  archive="$work_dir/gradle-${GRADLE_VERSION}-bin.zip"
  url="https://services.gradle.org/distributions/gradle-${GRADLE_VERSION}-bin.zip"
  if command -v curl >/dev/null 2>&1; then
    curl --fail --location --silent --show-error --output "$archive" "$url"
  elif command -v wget >/dev/null 2>&1; then
    wget --quiet --output-document="$archive" "$url"
  else
    printf 'FAIL: curl or wget is required to download Gradle\n' >&2
    exit 1
  fi
  printf '%s  %s\n' "$GRADLE_SHA256" "$archive" | sha256sum --check --status || {
    printf 'FAIL: Gradle distribution checksum mismatch\n' >&2
    exit 1
  }
  unzip -q "$archive" -d "$work_dir"
  gradle_command="$work_dir/gradle-${GRADLE_VERSION}/bin/gradle"
fi

launcher="$work_dir/launcher"
mkdir -p "$launcher/src/main/java/integration" "$launcher/src/main/resources"
cat > "$launcher/settings.gradle.kts" <<'GRADLE'
rootProject.name = "doma-sync-testcontainers"
GRADLE
cat > "$launcher/build.gradle.kts" <<'GRADLE'
plugins {
    java
    application
}

repositories {
    mavenCentral()
}

java {
    toolchain {
        languageVersion = JavaLanguageVersion.of(17)
    }
}

dependencies {
    implementation("com.fasterxml.jackson.core:jackson-databind:2.18.2")
    implementation("org.testcontainers:testcontainers-postgresql:2.0.4")
    implementation("org.testcontainers:testcontainers-mysql:2.0.4")
    implementation("org.postgresql:postgresql:42.7.10")
    implementation("com.mysql:mysql-connector-j:26.7.0")
}

application {
    mainClass = "integration.IntegrationMain"
}
GRADLE
cat > "$launcher/assert-final-entity.py" <<'PY'
#!/usr/bin/env python3
import json
import pathlib
import sys

project = pathlib.Path(sys.argv[1])
relative = pathlib.Path(sys.argv[2])
language = sys.argv[3]
expected_columns = tuple(sys.argv[4].split(","))
expected_primary_key = tuple(sys.argv[5].split(","))
sys.path.insert(0, str(pathlib.Path(sys.argv[6])))

if language == "java":
    from entity_sync.java_parser import parse_java
    parsed = parse_java((project / relative).read_text(encoding="utf-8"), path=str(relative))
else:
    from entity_sync.kotlin_parser import parse_kotlin
    parsed = parse_kotlin(
        (project / relative).read_text(encoding="utf-8"),
        path=str(relative),
        annotation_declarations=("example.entity.Audited",),
    )

columns = tuple(prop.column for prop in parsed.entity.properties)
primary_key = tuple(
    prop.column for prop in parsed.entity.properties
    if any(annotation.qualified_name == "org.seasar.doma.Id" for annotation in prop.annotations)
)
if columns != expected_columns:
    raise SystemExit(f"final entity columns differ: expected={expected_columns} actual={columns}")
if primary_key != expected_primary_key:
    raise SystemExit(
        f"final entity primary key differs: expected={expected_primary_key} actual={primary_key}"
    )

contract = json.loads((project / "fixture/handwritten-slices.json").read_text(encoding="utf-8"))
for item in contract:
    source = (project / item["path"]).read_bytes()
    start = item["start"].encode()
    end = item["end"].encode()
    first = source.find(start)
    last = source.find(end, first + len(start))
    if first < 0 or last < 0:
        raise SystemExit(f"preservation markers missing after real merge: {item['path']}")
    finish = last + len(end)
    if source[finish:finish + 2] == b"\r\n":
        finish += 2
    elif source[finish:finish + 1] == b"\n":
        finish += 1
    if source[first:finish] != (project / item["expected"]).read_bytes():
        raise SystemExit(f"preservation target changed after real merge: {item['path']}")
PY
cat > "$launcher/src/main/resources/postgresql-init.sql" <<'SQL'
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
CREATE TABLE customer (
  tenant_id BIGINT NOT NULL,
  customer_id BIGINT NOT NULL,
  email VARCHAR(255),
  generated_number BIGINT GENERATED BY DEFAULT AS IDENTITY,
  PRIMARY KEY (tenant_id, customer_id)
);
COMMENT ON TABLE customer IS 'Customers';
COMMENT ON COLUMN customer.tenant_id IS 'Tenant ID';
COMMENT ON COLUMN customer.customer_id IS 'Customer ID';
COMMENT ON COLUMN customer.email IS 'Email address';
COMMENT ON COLUMN customer.generated_number IS 'Generated number';
SQL
cat > "$launcher/src/main/resources/mysql-init.sql" <<'SQL'
CREATE TABLE customer (
  customer_id BIGINT NOT NULL AUTO_INCREMENT,
  tenant_id BIGINT NOT NULL,
  sync_note VARCHAR(255) NULL COMMENT 'Synchronization note',
  PRIMARY KEY (customer_id, tenant_id)
) COMMENT='Customers';
SQL
cat > "$launcher/src/main/java/integration/IntegrationMain.java" <<'JAVA'
package integration;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.testcontainers.mysql.MySQLContainer;
import org.testcontainers.postgresql.PostgreSQLContainer;

public final class IntegrationMain {
  private static final ObjectMapper JSON = new ObjectMapper();
  private static final Path REPO = Path.of(required("INTEGRATION_REPO_ROOT"));
  private static final Path GRADLE = Path.of(required("INTEGRATION_GRADLE_CMD"));
  private static final Path WORK = Path.of(required("INTEGRATION_WORK_ROOT"));
  private static final Path CONFIGURATOR = REPO.resolve(
      "skills/doma-sync-entities-from-database/scripts/configure-codegen.py");
  private static final Path MERGER = REPO.resolve(
      "skills/doma-sync-entities-from-database/scripts/compare-and-merge-entities.py");
  private static final Path SNAPSHOT_HELPER = REPO.resolve(
      "skills/doma-sync-entities-from-database/scripts/schema-snapshot.java");
  private static final Path ENTITY_ASSERTION = Path.of(required("INTEGRATION_ENTITY_ASSERTION"));
  private static final Path ENTITY_SYNC_SCRIPTS = REPO.resolve(
      "skills/doma-sync-entities-from-database/scripts");

  private IntegrationMain() {}

  public static void main(String[] args) throws Exception {
    runPostgresql();
    runMysql();
  }

  private static void runPostgresql() throws Exception {
    String adminPassword = randomPassword();
    try (PostgreSQLContainer container = new PostgreSQLContainer("postgres:16.4-alpine")
        .withDatabaseName("fixture")
        .withUsername("fixture_admin")
        .withPassword(adminPassword)
        .withInitScript("postgresql-init.sql")) {
      container.start();
      String readerPassword = randomPassword();
      try (Connection connection = DriverManager.getConnection(
          container.getJdbcUrl(), container.getUsername(), container.getPassword());
          Statement statement = connection.createStatement()) {
        statement.execute("CREATE USER metadata_reader WITH PASSWORD '" + readerPassword + "'");
        statement.execute("GRANT CONNECT ON DATABASE fixture TO metadata_reader");
        statement.execute("GRANT USAGE ON SCHEMA public TO metadata_reader");
        statement.execute("GRANT SELECT ON customer TO metadata_reader");
      }
      Path project = prepareProject(
          "java-kotlin-dsl-postgresql", "java", "postgresql", true);
      runRealWorkflow(project, "postgresql", container.getJdbcUrl(), "metadata_reader",
          readerPassword, "public", null, ".java");
      assertPostgresqlMetadata(project.resolve("build/doma-codegen/schema-snapshot.json"));
      assertReadOnly(container.getJdbcUrl(), "metadata_reader", readerPassword, true);
      compileProject(project);
      System.out.println("PASS: testcontainers-postgresql");
    }
  }

  private static void runMysql() throws Exception {
    String adminPassword = randomPassword();
    try (MySQLContainer container = new MySQLContainer("mysql:8.4.0")
        .withDatabaseName("fixture_catalog")
        .withUsername("fixture_admin")
        .withPassword(adminPassword)
        .withInitScript("mysql-init.sql")) {
      container.start();
      String readerPassword = randomPassword();
      try (Connection connection = DriverManager.getConnection(
          container.getJdbcUrl(), "root", adminPassword);
          Statement statement = connection.createStatement()) {
        statement.execute("CREATE USER 'metadata_reader'@'%' IDENTIFIED BY '" + readerPassword + "'");
        statement.execute("GRANT SELECT ON fixture_catalog.* TO 'metadata_reader'@'%'");
      }
      Path project = prepareProject(
          "kotlin-groovy-dsl-mysql", "kotlin", "mysql", true);
      runRealWorkflow(project, "mysql", container.getJdbcUrl(), "metadata_reader",
          readerPassword, null, "fixture_catalog", ".kt");
      assertMysqlMetadata(project.resolve("build/doma-codegen/schema-snapshot.json"));
      assertReadOnly(container.getJdbcUrl(), "metadata_reader", readerPassword, false);
      compileProject(project);
      System.out.println("PASS: testcontainers-mysql");
    }
  }

  private static Path prepareProject(
      String fixtureName, String language, String database, boolean metamodel) throws Exception {
    Path source = REPO.resolve(
        "tests/doma-sync-entities-from-database/fixtures/" + fixtureName);
    Path project = WORK.resolve(fixtureName);
    copyTree(source, project);
    List<String> configure = new ArrayList<>(List.of(
        "python3", CONFIGURATOR.toString(), "plan", "--project-root", project.toString(),
        "--language", language, "--database", database,
        "--entity-package", "example.entity"));
    if (database.equals("postgresql")) {
      configure.addAll(List.of("--schema", "public"));
    } else {
      configure.addAll(List.of("--catalog", "fixture_catalog"));
    }
    configure.addAll(List.of(
        "--table-pattern", ".*", "--codegen-version", "3.2.2",
        "--driver-coordinate", database.equals("postgresql")
            ? "org.postgresql:postgresql:42.7.10"
            : "com.mysql:mysql-connector-j:26.7.0",
        "--metamodel", Boolean.toString(metamodel),
        "--output-plan", "build/doma-codegen/configure-plan.json"));
    run(project, Map.of(), 2, configure);
    run(project, Map.of(), 0, List.of(
        "python3", CONFIGURATOR.toString(), "apply", "--project-root", project.toString(),
        "--plan", "build/doma-codegen/configure-plan.json"));
    run(project, Map.of(), 0, List.of("git", "init", "-q"));
    run(project, Map.of(), 0, List.of("git", "config", "user.name", "Doma Integration"));
    run(project, Map.of(), 0, List.of("git", "config", "user.email", "fixture@example.invalid"));
    run(project, Map.of(), 0, List.of("git", "add", "--", "."));
    run(project, Map.of(), 0, List.of("git", "commit", "-qm", "fixture baseline"));
    return project;
  }

  private static void runRealWorkflow(
      Path project, String database, String jdbcUrl, String user, String password,
      String schema, String catalog, String suffix) throws Exception {
    run(project, Map.of(), 0, List.of(
        GRADLE.toString(), "--no-daemon", "--console=plain",
        "domaSyncWriteCodeGenClasspath"));
    Path classpathFile = project.resolve("build/doma-codegen/codegen-classpath.txt");
    String classpath = Files.readString(classpathFile, StandardCharsets.UTF_8).trim();
    Map<String, String> snapshotEnvironment = new java.util.HashMap<>();
    snapshotEnvironment.put("DOMA_CODEGEN_DB_URL", jdbcUrl);
    snapshotEnvironment.put("DOMA_CODEGEN_DB_USER", user);
    snapshotEnvironment.put("DOMA_CODEGEN_DB_PASSWORD", password);
    snapshotEnvironment.put("DOMA_CODEGEN_DB_KIND", database);
    snapshotEnvironment.put("DOMA_CODEGEN_DB_SCHEMA", schema == null ? "" : schema);
    snapshotEnvironment.put("DOMA_CODEGEN_DB_CATALOG", catalog == null ? "" : catalog);
    snapshotEnvironment.put("DOMA_CODEGEN_TABLE_PATTERN", "customer");
    snapshotEnvironment.put("DOMA_CODEGEN_SCHEMA_SNAPSHOT",
        project.resolve("build/doma-codegen/schema-snapshot.json").toString());
    snapshotEnvironment.put("DOMA_CODEGEN_PROJECT_ROOT", project.toString());
    run(project, snapshotEnvironment, 0, List.of(
        "java", "--class-path", classpath, SNAPSHOT_HELPER.toString()));

    Map<String, String> generationEnvironment = Map.of(
        "DOMA_SYNC_JDBC_URL", jdbcUrl,
        "DOMA_SYNC_JDBC_USER", user,
        "DOMA_SYNC_JDBC_PASSWORD", password);
    run(project, generationEnvironment, 0, List.of(
        GRADLE.toString(), "--no-daemon", "--console=plain",
        "domaCodeGenDomaSyncEntity"));
    Path generated = project.resolve("build/doma-codegen/generated/example/entity/Customer" + suffix);
    check(Files.isRegularFile(generated), "CodeGen did not create the expected entity candidate");

    Path plan = project.resolve("build/doma-codegen/merge-plan.json");
    Path diff = project.resolve("build/doma-codegen/merge.diff");
    int planStatus = runAny(project, Map.of(), List.of(
        "python3", MERGER.toString(), "plan", "--project-root", project.toString(),
        "--schema-snapshot", "build/doma-codegen/schema-snapshot.json",
        "--generated-dir", "build/doma-codegen/generated",
        "--existing-root", "src/main/" + (suffix.equals(".java") ? "java" : "kotlin"),
        "--language", suffix.equals(".java") ? "java" : "kotlin",
        "--output-plan", "build/doma-codegen/merge-plan.json",
        "--output-diff", "build/doma-codegen/merge.diff"));
    check(planStatus == 0 || planStatus == 2 || planStatus == 3, "merge planning failed");
    if (!Files.isRegularFile(plan) || Files.size(diff) == 0) {
      String planText = Files.isRegularFile(plan) ? Files.readString(plan) : "";
      Matcher findings = Pattern.compile(
          "\\\"kind\\\"\\s*:\\s*\\\"([^\\\"]+)\\\"|"
          + "\\\"status\\\"\\s*:\\s*\\\"([^\\\"]+)\\\"").matcher(planText);
      List<String> summary = new ArrayList<>();
      while (findings.find()) summary.add(findings.group(1) != null ? findings.group(1) : findings.group(2));
      String generatedIdentity = Files.readAllLines(generated).stream()
          .filter(line -> line.contains("@Table"))
          .findFirst().orElse("missing @Table").trim();
      String snapshotText = Files.readString(
          project.resolve("build/doma-codegen/schema-snapshot.json"));
      Matcher snapshotIdentityMatcher = Pattern.compile(
          "\\\"catalog\\\":(null|\\\"[^\\\"]*\\\"),\\\"schema\\\":(null|\\\"[^\\\"]*\\\"),\\\"name\\\":\\\"([^\\\"]+)\\\"")
          .matcher(snapshotText);
      String snapshotIdentity = snapshotIdentityMatcher.find()
          ? snapshotIdentityMatcher.group() : "missing snapshot identity";
      throw new IllegalStateException("real CodeGen produced no merge proposal; findings="
          + summary + "; generated=" + generatedIdentity + "; snapshot=" + snapshotIdentity);
    }
    int applyStatus = runAny(project, Map.of(), List.of(
        "python3", MERGER.toString(), "apply", "--project-root", project.toString(),
        "--plan", plan.toString()));
    check(applyStatus == 0 || applyStatus == 2 || applyStatus == 3, "merge apply failed");
    int secondPlanStatus = runAny(project, Map.of(), List.of(
        "python3", MERGER.toString(), "plan", "--project-root", project.toString(),
        "--schema-snapshot", "build/doma-codegen/schema-snapshot.json",
        "--generated-dir", "build/doma-codegen/generated",
        "--existing-root", "src/main/" + (suffix.equals(".java") ? "java" : "kotlin"),
        "--language", suffix.equals(".java") ? "java" : "kotlin",
        "--output-plan", "build/doma-codegen/second-merge-plan.json",
        "--output-diff", "build/doma-codegen/second-merge.diff"));
    check(secondPlanStatus == 0 || secondPlanStatus == 3, "second merge planning failed");
    check(Files.isRegularFile(project.resolve("build/doma-codegen/second-merge.diff"))
        && Files.size(project.resolve("build/doma-codegen/second-merge.diff")) == 0,
        "real merge was not idempotent");
    assertFinalEntity(project, database, suffix);
  }

  private static void assertFinalEntity(Path project, String database, String suffix)
      throws Exception {
    String language = suffix.equals(".java") ? "java" : "kotlin";
    String relative = "src/main/" + language + "/example/entity/Customer" + suffix;
    String columns = database.equals("postgresql")
        ? "tenant_id,customer_id,email,generated_number"
        : "customer_id,tenant_id,sync_note";
    String primaryKey = database.equals("postgresql")
        ? "tenant_id,customer_id" : "customer_id,tenant_id";
    run(project, Map.of(), 0, List.of(
        "python3", ENTITY_ASSERTION.toString(), project.toString(), relative, language,
        columns, primaryKey, ENTITY_SYNC_SCRIPTS.toString()));
  }

  private static void compileProject(Path project) throws Exception {
    run(project, Map.of(), 0, List.of(
        GRADLE.toString(), "--no-daemon", "--console=plain", "clean", "build"));
    try (var paths = Files.walk(project.resolve("build"))) {
      check(paths.anyMatch(path -> path.getFileName().toString().endsWith("DaoImpl.java")),
          "Doma annotation processing did not generate a DAO implementation");
    }
  }

  private static void assertPostgresqlMetadata(Path path) throws IOException {
    JsonNode table = assertSingleTable(
        path, "postgresql", null, "public", "customer", "TABLE", "Customers", 4);
    assertColumn(table, "tenant_id", 1, "int8", -5, 19, 0, false, false, "Tenant ID");
    assertColumn(table, "customer_id", 2, "int8", -5, 19, 0, false, false, "Customer ID");
    assertColumn(table, "email", 3, "varchar", 12, 255, 0, true, false, "Email address");
    assertColumn(table, "generated_number", 4, "int8", -5, 19, 0, false, true,
        "Generated number");
    assertPrimaryKey(table, "customer_pkey", List.of("tenant_id", "customer_id"));
  }

  private static void assertMysqlMetadata(Path path) throws IOException {
    JsonNode table = assertSingleTable(
        path, "mysql", "fixture_catalog", null, "customer", "TABLE", "Customers", 3);
    assertColumn(table, "customer_id", 1, "BIGINT", -5, 19, null, false, true, "");
    assertColumn(table, "tenant_id", 2, "BIGINT", -5, 19, null, false, false, "");
    assertColumn(table, "sync_note", 3, "VARCHAR", 12, 255, null, true, false,
        "Synchronization note");
    assertPrimaryKey(table, "PRIMARY", List.of("customer_id", "tenant_id"));
  }

  private static JsonNode assertSingleTable(
      Path path, String database, String catalog, String schema, String name, String type,
      String remarks, int columnCount) throws IOException {
    JsonNode root = JSON.readTree(path.toFile());
    check(root.path("format_version").asInt(-1) == 1, "snapshot format version differs");
    check(database.equals(root.path("database").textValue()), "snapshot database differs");
    JsonNode tables = root.path("tables");
    check(tables.isArray() && tables.size() == 1, "snapshot table set differs");
    JsonNode table = tables.get(0);
    assertNullableText(table.get("catalog"), catalog, "table catalog");
    assertNullableText(table.get("schema"), schema, "table schema");
    assertNullableText(table.get("name"), name, "table name");
    assertNullableText(table.get("type"), type, "table type");
    assertNullableText(table.get("remarks"), remarks, "table remarks");
    check(table.path("columns").isArray() && table.path("columns").size() == columnCount,
        "snapshot column set differs");
    return table;
  }

  private static void assertColumn(
      JsonNode table, String name, int ordinal, String typeName, int jdbcType, int size,
      Integer scale, boolean nullable, boolean autoIncrement, String remarks) {
    JsonNode column = null;
    for (JsonNode item : table.path("columns")) {
      if (name.equals(item.path("name").textValue())) column = item;
    }
    check(column != null, "metadata column missing: " + name);
    check(column.path("ordinal").asInt(-1) == ordinal, "column ordinal differs: " + name);
    check(typeName.equals(column.path("type_name").textValue()), "SQL type differs: " + name);
    check(column.path("jdbc_type").asInt(Integer.MIN_VALUE) == jdbcType,
        "JDBC type differs: " + name);
    check(column.path("size").asInt(Integer.MIN_VALUE) == size, "column size differs: " + name);
    assertNullableInt(column.get("scale"), scale, "column scale: " + name);
    check(column.path("nullable").isBoolean() && column.path("nullable").booleanValue() == nullable,
        "nullability differs: " + name);
    check(column.path("auto_increment").isBoolean()
        && column.path("auto_increment").booleanValue() == autoIncrement,
        "auto-increment differs: " + name);
    assertNullableText(column.get("remarks"), remarks, "column remarks: " + name);
  }

  private static void assertPrimaryKey(JsonNode table, String keyName, List<String> columns) {
    JsonNode primaryKey = table.path("primary_key");
    check(primaryKey.isArray() && primaryKey.size() == columns.size(),
        "primary-key set differs");
    for (int index = 0; index < columns.size(); index++) {
      JsonNode item = primaryKey.get(index);
      check(keyName.equals(item.path("name").textValue()), "primary-key name differs");
      check(columns.get(index).equals(item.path("column").textValue()),
          "primary-key column differs");
      check(item.path("sequence").asInt(-1) == index + 1, "primary-key sequence differs");
    }
  }

  private static void assertNullableText(JsonNode value, String expected, String label) {
    if (expected == null) check(value == null || value.isNull(),
        label + " differs: expected=null actual=" + value);
    else check(value != null && value.isTextual() && expected.equals(value.textValue()),
        label + " differs: expected=" + expected + " actual=" + value);
  }

  private static void assertNullableInt(JsonNode value, Integer expected, String label) {
    if (expected == null) check(value == null || value.isNull(),
        label + " differs: expected=null actual=" + value);
    else check(value != null && value.isIntegralNumber() && value.intValue() == expected,
        label + " differs: expected=" + expected + " actual=" + value);
  }

  private static void assertReadOnly(
      String jdbcUrl, String user, String password, boolean postgresql) throws SQLException {
    List<String> probes = postgresql
        ? List.of(
            "INSERT INTO customer (tenant_id, customer_id) VALUES (1, 1)",
            "UPDATE customer SET email = 'denied'",
            "DELETE FROM customer",
            "CREATE TABLE denied_table (id INT)",
            "ALTER TABLE customer ADD COLUMN denied_column INT",
            "DROP TABLE customer")
        : List.of(
            "INSERT INTO customer (tenant_id, sync_note) VALUES (1, 'denied')",
            "UPDATE customer SET sync_note = 'denied'",
            "DELETE FROM customer",
            "CREATE TABLE denied_table (id INT)",
            "ALTER TABLE customer ADD COLUMN denied_column INT",
            "DROP TABLE customer");
    try (Connection connection = DriverManager.getConnection(jdbcUrl, user, password)) {
      for (String sql : probes) {
        try (Statement statement = connection.createStatement()) {
          statement.execute(sql);
          throw new IllegalStateException("read-only metadata user executed a forbidden statement");
        } catch (SQLException expected) {
          if (postgresql) {
            check("42501".equals(expected.getSQLState()),
                "PostgreSQL denial probe failed for a non-authorization reason");
          } else {
            check("42000".equals(expected.getSQLState()) && expected.getErrorCode() == 1142,
                "MySQL denial probe failed for a non-authorization reason");
          }
        }
      }
    }
  }

  private static int runAny(Path cwd, Map<String, String> environment, List<String> command)
      throws IOException, InterruptedException {
    ProcessBuilder builder = new ProcessBuilder(command).directory(cwd.toFile()).inheritIO();
    builder.environment().keySet().removeIf(key -> key.startsWith("AWS_"));
    builder.environment().putAll(environment);
    return builder.start().waitFor();
  }

  private static void run(
      Path cwd, Map<String, String> environment, int expected, List<String> command)
      throws IOException, InterruptedException {
    int status = runAny(cwd, environment, command);
    check(status == expected, "child command failed with exit " + status);
  }

  private static void copyTree(Path source, Path target) throws IOException {
    try (var paths = Files.walk(source)) {
      for (Path path : paths.toList()) {
        Path destination = target.resolve(source.relativize(path));
        if (Files.isDirectory(path)) Files.createDirectories(destination);
        else Files.copy(path, destination, StandardCopyOption.COPY_ATTRIBUTES);
      }
    }
  }

  private static String randomPassword() {
    return "p" + UUID.randomUUID().toString().replace("-", "");
  }

  private static String required(String name) {
    String value = System.getenv(name);
    if (value == null || value.isBlank()) throw new IllegalStateException(name + " is required");
    return value;
  }

  private static void check(boolean condition, String message) {
    if (!condition) throw new IllegalStateException(message);
  }
}
JAVA

export INTEGRATION_REPO_ROOT="$REPO_ROOT"
export INTEGRATION_GRADLE_CMD="$gradle_command"
export INTEGRATION_WORK_ROOT="$work_dir/projects"
export INTEGRATION_ENTITY_ASSERTION="$launcher/assert-final-entity.py"
mkdir -p "$INTEGRATION_WORK_ROOT"
while IFS='=' read -r variable _; do
  if [[ "$variable" == AWS_* ]]; then
    unset "$variable"
  fi
done < <(env)
"$gradle_command" --no-daemon --console=plain -p "$launcher" run
