package fixture.jdbc;

import java.io.IOException;
import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DatabaseMetaData;
import java.sql.Driver;
import java.sql.DriverManager;
import java.sql.DriverPropertyInfo;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.SQLFeatureNotSupportedException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Properties;
import java.util.logging.Logger;

/** A deterministic service-loaded JDBC metadata fixture. */
public final class FixtureJdbcDriver implements Driver {
  private static final List<String> CALLS = new ArrayList<>();

  static {
    try {
      DriverManager.registerDriver(new FixtureJdbcDriver());
    } catch (SQLException exception) {
      throw new ExceptionInInitializerError(exception);
    }
  }

  @Override public Connection connect(String url, Properties info) throws SQLException {
    if (!acceptsURL(url)) return null;
    return proxy(Connection.class, new ConnectionHandler(url));
  }
  @Override public boolean acceptsURL(String url) { return "jdbc:fixture:postgresql".equals(url) || "jdbc:fixture:mysql".equals(url); }
  @Override public DriverPropertyInfo[] getPropertyInfo(String url, Properties info) { return new DriverPropertyInfo[0]; }
  @Override public int getMajorVersion() { return 1; }
  @Override public int getMinorVersion() { return 0; }
  @Override public boolean jdbcCompliant() { return false; }
  @Override public Logger getParentLogger() throws SQLFeatureNotSupportedException { throw new SQLFeatureNotSupportedException(); }

  private static final class ConnectionHandler implements InvocationHandler {
    private final String url;
    ConnectionHandler(String url) { this.url = url; }
    @Override public Object invoke(Object proxy, Method method, Object[] args) throws Throwable {
      String name = method.getName();
      if (name.equals("getMetaData")) return proxy(DatabaseMetaData.class, new MetadataHandler(url));
      if (name.equals("close") || name.equals("clearWarnings")) { writeCalls(); return null; }
      if (name.equals("isClosed")) return false;
      if (name.equals("isValid")) return true;
      if (name.equals("getWarnings")) return null;
      if (name.equals("unwrap")) throw new SQLException("not a wrapper");
      if (name.equals("isWrapperFor")) return false;
      forbidden(name);
      throw new AssertionError(name);
    }
  }

  private static final class MetadataHandler implements InvocationHandler {
    private final String url;
    MetadataHandler(String url) { this.url = url; }
    @Override public Object invoke(Object proxy, Method method, Object[] args) {
      String name = method.getName();
      if (name.equals("getTables")) {
        record("getTables", args[0], args[1], args[2]);
        return resultSet(tables(url));
      }
      if (name.equals("getColumns")) {
        record("getColumns", args[0], args[1], args[2]);
        return resultSet(columns((String) args[2]));
      }
      if (name.equals("getPrimaryKeys")) {
        record("getPrimaryKeys", args[0], args[1], args[2]);
        return resultSet(keys((String) args[2]));
      }
      if (name.equals("unwrap")) return null;
      if (name.equals("isWrapperFor")) return false;
      return defaultValue(method.getReturnType());
    }
  }

  private static ResultSet resultSet(List<Map<String, Object>> rows) {
    return proxy(ResultSet.class, new InvocationHandler() {
      int index = -1;
      boolean wasNull;
      @Override public Object invoke(Object proxy, Method method, Object[] args) {
        String name = method.getName();
        if (name.equals("next")) return ++index < rows.size();
        if (name.equals("close")) return null;
        if (name.equals("wasNull")) return wasNull;
        if (name.equals("getString") || name.equals("getObject") || name.equals("getInt") || name.equals("getShort") || name.equals("getBoolean")) {
          Object value = rows.get(index).get(args[0]);
          wasNull = value == null;
          if (name.equals("getString")) return value == null ? null : String.valueOf(value);
          if (name.equals("getObject")) return value;
          if (name.equals("getBoolean")) return value != null && Boolean.parseBoolean(String.valueOf(value));
          if (name.equals("getShort")) return value == null ? (short) 0 : ((Number) value).shortValue();
          return value == null ? 0 : ((Number) value).intValue();
        }
        if (name.equals("unwrap")) return null;
        if (name.equals("isWrapperFor")) return false;
        return defaultValue(method.getReturnType());
      }
    });
  }

  private static List<Map<String, Object>> tables(String url) {
    String catalog = url.endsWith("mysql") ? "fixture_catalog" : null;
    String schema = url.endsWith("postgresql") ? "public" : null;
    return Arrays.asList(row("TABLE_CAT", catalog, "TABLE_SCHEM", schema, "TABLE_NAME", "tenant_zebra", "TABLE_TYPE", "TABLE", "REMARKS", "zebra"),
        row("TABLE_CAT", catalog, "TABLE_SCHEM", schema, "TABLE_NAME", "outside_scope", "TABLE_TYPE", "TABLE", "REMARKS", "outside"),
        row("TABLE_CAT", catalog, "TABLE_SCHEM", schema, "TABLE_NAME", "tenant_alpha", "TABLE_TYPE", "TABLE", "REMARKS", "alpha"));
  }
  private static List<Map<String, Object>> columns(String table) {
    if (table.equals("tenant_alpha")) return Arrays.asList(
        row("COLUMN_NAME", "created", "ORDINAL_POSITION", 3, "DATA_TYPE", 91, "TYPE_NAME", "date", "COLUMN_SIZE", 13, "DECIMAL_DIGITS", 0, "NULLABLE", 0, "COLUMN_DEF", "CURRENT_DATE", "IS_AUTOINCREMENT", "NO", "REMARKS", "created on"),
        row("COLUMN_NAME", "id", "ORDINAL_POSITION", 1, "DATA_TYPE", 4, "TYPE_NAME", "int4", "COLUMN_SIZE", 10, "DECIMAL_DIGITS", 0, "NULLABLE", 0, "COLUMN_DEF", null, "IS_AUTOINCREMENT", "YES", "REMARKS", "identifier"),
        row("COLUMN_NAME", "note", "ORDINAL_POSITION", 2, "DATA_TYPE", 12, "TYPE_NAME", "varchar", "COLUMN_SIZE", 255, "DECIMAL_DIGITS", null, "NULLABLE", 1, "COLUMN_DEF", null, "IS_AUTOINCREMENT", null, "REMARKS", null));
    if (table.equals("tenant_zebra")) return Arrays.asList(
        row("COLUMN_NAME", "part_b", "ORDINAL_POSITION", 2, "DATA_TYPE", 12, "TYPE_NAME", "varchar", "COLUMN_SIZE", 20, "DECIMAL_DIGITS", null, "NULLABLE", 0, "COLUMN_DEF", null, "IS_AUTOINCREMENT", "NO", "REMARKS", null),
        row("COLUMN_NAME", "part_a", "ORDINAL_POSITION", 1, "DATA_TYPE", 4, "TYPE_NAME", "int4", "COLUMN_SIZE", 10, "DECIMAL_DIGITS", 0, "NULLABLE", 0, "COLUMN_DEF", null, "IS_AUTOINCREMENT", "NO", "REMARKS", null));
    return List.of();
  }
  private static List<Map<String, Object>> keys(String table) {
    if (table.equals("tenant_alpha")) return List.of(row("PK_NAME", "tenant_alpha_pkey", "COLUMN_NAME", "id", "KEY_SEQ", 1));
    if (table.equals("tenant_zebra")) return Arrays.asList(row("PK_NAME", "tenant_zebra_pkey", "COLUMN_NAME", "part_b", "KEY_SEQ", 2), row("PK_NAME", "tenant_zebra_pkey", "COLUMN_NAME", "part_a", "KEY_SEQ", 1));
    return List.of();
  }
  private static Map<String, Object> row(Object... values) { Map<String, Object> row = new HashMap<>(); for (int i = 0; i < values.length; i += 2) row.put((String) values[i], values[i + 1]); return row; }
  private static void record(String name, Object... values) { StringBuilder line = new StringBuilder(name); for (Object value : values) line.append('|').append(value == null ? "null" : value); CALLS.add(line.toString()); }
  private static void forbidden(String name) { CALLS.add("forbidden|" + name); writeCalls(); throw new AssertionError("forbidden connection method"); }
  private static void writeCalls() { String file = System.getenv("FIXTURE_JDBC_CALLS"); if (file == null) return; try { Files.writeString(Path.of(file), "[" + CALLS.stream().map(call -> "\"" + call + "\"").reduce((a, b) -> a + "," + b).orElse("") + "]"); } catch (IOException exception) { throw new AssertionError(exception); } }
  @SuppressWarnings("unchecked") private static <T> T proxy(Class<T> type, InvocationHandler handler) { return (T) Proxy.newProxyInstance(FixtureJdbcDriver.class.getClassLoader(), new Class<?>[] {type}, handler); }
  private static Object defaultValue(Class<?> type) { if (!type.isPrimitive()) return null; if (type == boolean.class) return false; if (type == byte.class) return (byte) 0; if (type == short.class) return (short) 0; if (type == int.class) return 0; if (type == long.class) return 0L; if (type == float.class) return 0f; if (type == double.class) return 0d; if (type == char.class) return '\0'; return null; }
}
