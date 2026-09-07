import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.sql.Connection;
import java.sql.DatabaseMetaData;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Properties;
import java.util.regex.Pattern;
import java.util.regex.PatternSyntaxException;

/** Writes a deterministic, credential-free view of JDBC table metadata. */
final class SchemaSnapshot {
  private static final String URL = "DOMA_CODEGEN_DB_URL";
  private static final String USER = "DOMA_CODEGEN_DB_USER";
  private static final String PASSWORD = "DOMA_CODEGEN_DB_PASSWORD";
  private static final String KIND = "DOMA_CODEGEN_DB_KIND";
  private static final String SCHEMA = "DOMA_CODEGEN_DB_SCHEMA";
  private static final String CATALOG = "DOMA_CODEGEN_DB_CATALOG";
  private static final String TABLE_PATTERN = "DOMA_CODEGEN_TABLE_PATTERN";
  private static final String SNAPSHOT = "DOMA_CODEGEN_SCHEMA_SNAPSHOT";
  private static final String PROJECT_ROOT = "DOMA_CODEGEN_PROJECT_ROOT";

  public static void main(String[] args) {
    try {
      Inputs inputs = Inputs.read();
      writeSnapshot(inputs, readTables(inputs));
    } catch (InputException exception) {
      System.err.println(exception.getMessage());
      System.exit(64);
    } catch (SQLException | IOException exception) {
      // JDBC drivers commonly include URLs and credentials in exception text.
      System.err.println("database metadata: read failed");
      System.exit(70);
    }
  }

  private static List<Table> readTables(Inputs inputs) throws SQLException {
    Properties properties = new Properties();
    properties.setProperty("user", inputs.user());
    properties.setProperty("password", inputs.password());
    List<Table> tables = new ArrayList<>();
    try (Connection connection = DriverManager.getConnection(inputs.url(), properties);
         ResultSet results = connection.getMetaData().getTables(
             inputs.catalog(), inputs.schema(), "%", new String[] {"TABLE"})) {
      DatabaseMetaData metadata = connection.getMetaData();
      while (results.next()) {
        String name = results.getString("TABLE_NAME");
        if (name != null && inputs.tableNamePattern().matcher(name).matches()) {
          tables.add(new Table(
              inputs.kind().equals("postgresql") ? null : results.getString("TABLE_CAT"),
              results.getString("TABLE_SCHEM"), name,
              results.getString("TABLE_TYPE"), results.getString("REMARKS"),
              readPrimaryKeys(metadata, inputs.catalog(), inputs.schema(), name),
              readColumns(metadata, inputs.catalog(), inputs.schema(), name)));
        }
      }
    }
    tables.sort(Comparator.comparing(Table::catalog, SchemaSnapshot::compareNullable)
        .thenComparing(Table::schema, SchemaSnapshot::compareNullable)
        .thenComparing(Table::name, SchemaSnapshot::compareNullable));
    return tables;
  }

  private static List<Column> readColumns(DatabaseMetaData metadata, String catalog, String schema, String table)
      throws SQLException {
    List<Column> columns = new ArrayList<>();
    try (ResultSet results = metadata.getColumns(catalog, schema, table, "%")) {
      while (results.next()) {
        Integer nullableCode = nullableInt(results, "NULLABLE");
        Boolean nullable = nullableCode == null ? null : switch (nullableCode) {
          case DatabaseMetaData.columnNoNulls -> false;
          case DatabaseMetaData.columnNullable -> true;
          default -> null;
        };
        String autoIncrement = results.getString("IS_AUTOINCREMENT");
        columns.add(new Column(
            results.getString("COLUMN_NAME"), nullableInt(results, "ORDINAL_POSITION"),
            nullableInt(results, "DATA_TYPE"), results.getString("TYPE_NAME"),
            nullableInt(results, "COLUMN_SIZE"), nullableInt(results, "DECIMAL_DIGITS"), nullable,
            results.getString("COLUMN_DEF"), yesNo(autoIncrement), results.getString("REMARKS")));
      }
    }
    columns.sort(Comparator.comparing(Column::ordinal, SchemaSnapshot::compareNullable)
        .thenComparing(Column::name, SchemaSnapshot::compareNullable));
    return columns;
  }

  private static List<PrimaryKey> readPrimaryKeys(DatabaseMetaData metadata, String catalog, String schema, String table)
      throws SQLException {
    List<PrimaryKey> keys = new ArrayList<>();
    try (ResultSet results = metadata.getPrimaryKeys(catalog, schema, table)) {
      while (results.next()) {
        keys.add(new PrimaryKey(results.getString("PK_NAME"), results.getString("COLUMN_NAME"),
            nullableInt(results, "KEY_SEQ")));
      }
    }
    keys.sort(Comparator.comparing(PrimaryKey::sequence, SchemaSnapshot::compareNullable)
        .thenComparing(PrimaryKey::column, SchemaSnapshot::compareNullable));
    return keys;
  }

  private static Integer nullableInt(ResultSet results, String name) throws SQLException {
    int value = results.getInt(name);
    return results.wasNull() ? null : value;
  }

  private static Boolean yesNo(String value) {
    if ("YES".equalsIgnoreCase(value)) return true;
    if ("NO".equalsIgnoreCase(value)) return false;
    return null;
  }

  private static <T extends Comparable<? super T>> int compareNullable(T left, T right) {
    if (left == null) return right == null ? 0 : -1;
    return right == null ? 1 : left.compareTo(right);
  }

  private static void writeSnapshot(Inputs inputs, List<Table> tables) throws IOException {
    StringBuilder json = new StringBuilder();
    json.append('{');
    field(json, "format_version", 1); json.append(',');
    field(json, "database", inputs.kind()); json.append(',');
    json.append("\"scope\":{");
    field(json, "catalog", inputs.catalog()); json.append(',');
    field(json, "schema", inputs.schema()); json.append(',');
    field(json, "table_pattern", inputs.patternText()); json.append("},\"tables\":[");
    for (int index = 0; index < tables.size(); index++) {
      if (index > 0) json.append(',');
      appendTable(json, tables.get(index));
    }
    json.append("]}\n");
    Files.createDirectories(inputs.output().getParent());
    Path temporary = Files.createTempFile(inputs.output().getParent(), ".schema-snapshot-", ".tmp");
    try {
      Files.writeString(temporary, json, StandardCharsets.UTF_8);
      try {
        Files.move(temporary, inputs.output(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
      } catch (AtomicMoveNotSupportedException exception) {
        Files.move(temporary, inputs.output(), StandardCopyOption.REPLACE_EXISTING);
      }
    } finally {
      Files.deleteIfExists(temporary);
    }
  }

  private static void appendTable(StringBuilder json, Table table) {
    json.append('{');
    field(json, "catalog", table.catalog()); json.append(','); field(json, "schema", table.schema()); json.append(',');
    field(json, "name", table.name()); json.append(','); field(json, "type", table.type()); json.append(',');
    field(json, "remarks", table.remarks()); json.append(",\"primary_key\":[");
    for (int index = 0; index < table.primaryKey().size(); index++) {
      if (index > 0) json.append(',');
      PrimaryKey key = table.primaryKey().get(index);
      json.append('{'); field(json, "name", key.name()); json.append(','); field(json, "column", key.column()); json.append(',');
      field(json, "sequence", key.sequence()); json.append('}');
    }
    json.append("],\"columns\":[");
    for (int index = 0; index < table.columns().size(); index++) {
      if (index > 0) json.append(',');
      Column column = table.columns().get(index);
      json.append('{'); field(json, "name", column.name()); json.append(','); field(json, "ordinal", column.ordinal()); json.append(',');
      field(json, "jdbc_type", column.jdbcType()); json.append(','); field(json, "type_name", column.typeName()); json.append(',');
      field(json, "size", column.size()); json.append(','); field(json, "scale", column.scale()); json.append(',');
      field(json, "nullable", column.nullable()); json.append(','); field(json, "default", column.defaultValue()); json.append(',');
      field(json, "auto_increment", column.autoIncrement()); json.append(','); field(json, "remarks", column.remarks()); json.append("}");
    }
    json.append("]}");
  }

  private static void field(StringBuilder json, String name, Object value) {
    quote(json, name); json.append(':');
    if (value == null) { json.append("null"); return; }
    if (value instanceof Number || value instanceof Boolean) { json.append(value); return; }
    quote(json, String.valueOf(value));
  }

  private static void quote(StringBuilder json, String value) {
    json.append('"');
    for (int index = 0; index < value.length(); index++) {
      char character = value.charAt(index);
      switch (character) {
        case '"' -> json.append("\\\"");
        case '\\' -> json.append("\\\\");
        case '\b' -> json.append("\\b");
        case '\f' -> json.append("\\f");
        case '\n' -> json.append("\\n");
        case '\r' -> json.append("\\r");
        case '\t' -> json.append("\\t");
        default -> {
          if (character < 0x20) json.append(String.format("\\u%04x", (int) character));
          else json.append(character);
        }
      }
    }
    json.append('"');
  }

  private record Table(String catalog, String schema, String name, String type, String remarks,
      List<PrimaryKey> primaryKey, List<Column> columns) { }
  private record Column(String name, Integer ordinal, Integer jdbcType, String typeName, Integer size,
      Integer scale, Boolean nullable, String defaultValue, Boolean autoIncrement, String remarks) { }
  private record PrimaryKey(String name, String column, Integer sequence) { }

  private record Inputs(String url, String user, String password, String kind, String catalog, String schema,
      String patternText, Pattern tableNamePattern, Path output) {
    static Inputs read() throws InputException {
      String url = required(URL), user = required(USER), password = required(PASSWORD), kind = required(KIND);
      String patternText = required(TABLE_PATTERN), rootText = required(PROJECT_ROOT), outputText = required(SNAPSHOT);
      if (!kind.equals("postgresql") && !kind.equals("mysql")) throw invalid(KIND, "must be postgresql or mysql");
      String schema = optional(SCHEMA), catalog = optional(CATALOG);
      if (kind.equals("postgresql")) {
        if (schema == null) throw invalid(SCHEMA, "is required for postgresql");
        if (catalog != null) throw invalid(CATALOG, "must be empty for postgresql");
      } else {
        if (catalog == null) throw invalid(CATALOG, "is required for mysql");
        if (schema != null) throw invalid(SCHEMA, "must be empty for mysql");
      }
      if (containsCredentials(url)) throw invalid(URL, "must not contain credentials");
      if (!hasExpectedFamily(url, kind)) throw invalid(URL, "does not match database kind");
      Pattern compiled;
      try { compiled = Pattern.compile(patternText); }
      catch (PatternSyntaxException exception) { throw invalid(TABLE_PATTERN, "is not a valid regex"); }
      Path root = Path.of(rootText).toAbsolutePath().normalize();
      Path output = Path.of(outputText);
      if (!output.isAbsolute()) output = root.resolve(output);
      output = output.toAbsolutePath().normalize();
      Path allowed = root.resolve("build/doma-codegen").normalize();
      if (!output.startsWith(allowed)) throw invalid(SNAPSHOT, "must be inside build/doma-codegen");
      return new Inputs(url, user, password, kind, catalog, schema, patternText, compiled, output);
    }

    private static String required(String name) throws InputException {
      String value = System.getenv(name);
      if (value == null || value.isEmpty()) throw invalid(name, "is required");
      validateControls(name, value);
      return value;
    }
    private static String optional(String name) throws InputException {
      String value = System.getenv(name);
      if (value == null || value.isEmpty()) return null;
      validateControls(name, value);
      return value;
    }
    private static void validateControls(String name, String value) throws InputException {
      for (int index = 0; index < value.length(); index++) if (value.charAt(index) < 0x20 || value.charAt(index) == 0x7f)
        throw invalid(name, "contains a control character");
    }
    private static boolean containsCredentials(String url) {
      String lowered = url.toLowerCase();
      int authority = lowered.indexOf("://");
      if (authority >= 0) {
        int end = lowered.indexOf('/', authority + 3);
        String host = lowered.substring(authority + 3, end < 0 ? lowered.length() : end);
        if (host.contains("@")) return true;
      }
      return lowered.matches(".*[?&](?:password|passwd|pwd|token|access[_-]?key|secret)=[^&]*.*");
    }
    private static boolean hasExpectedFamily(String url, String kind) {
      String lowered = url.toLowerCase();
      return kind.equals("postgresql") ? lowered.startsWith("jdbc:postgresql:")
          : lowered.startsWith("jdbc:mysql:");
    }
    private static InputException invalid(String field, String reason) { return new InputException(field + ": " + reason); }
  }

  private static final class InputException extends Exception {
    private static final long serialVersionUID = 1L;
    InputException(String message) { super(message); }
  }
}
