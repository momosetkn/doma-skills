# Setup Troubleshooting

| Symptom | Inspect | Recovery |
| --- | --- | --- |
| Doma annotations such as `org.seasar.doma.Dao` do not resolve during compilation. | Check that `doma-core` is a normal Gradle `implementation` dependency or Maven dependency. Check that the selected Doma release exists and that Java is 17 or later. | Add `org.seasar.doma:doma-core:<doma-version>` to the compile/runtime classpath, choose a released version, and compile with JDK 17 or later. |
| Compilation finishes, no `*DaoImpl.java` appears, and no Doma diagnostic is reported. | Confirm compilation actually ran. Check that `doma-processor` is on Gradle's `annotationProcessor` configuration or Maven's `annotationProcessorPaths`. Search recursively under `build/generated/sources/annotationProcessor` or `target/generated-sources/annotations`. | Correct the processor-path wiring, run a clean compile, and repeat the recursive search. Do not infer failure from one unsupported deeper output path. |
| Compilation reports `DOMA4019`. | Compare the resource against `META-INF/<DAO package path>/<DAO simple name>/<DAO method name>.sql`, including spelling and case. Confirm the SQL file is under the directory named by the absolute `doma.resources.dir` processor option. | Move or rename the UTF-8 SQL file to the exact path, or correct `doma.resources.dir`, then clean-compile with SQL validation enabled. |
| Compilation reports `DOMA4005`. | Inspect the affected DAO method for a Doma query annotation. | Add the appropriate query annotation; for the external SELECT setup example, use plain `@Select`. |
| Compilation reports `DOMA4014`. | Inspect whether `@Dao` annotates a class or another non-interface type. | Put `@Dao` on an interface. |
| Compilation reports `DOMA4017`. | Inspect whether the DAO interface is nested inside another type. | Move it to a top-level interface. |
| Compilation reports `DOMA4020`. | Open the SQL template named for the reported DAO method and check whether it is empty. | Add a valid SQL template and compile again. |
| Execution reports `DOMA0003`. | Compare the runtime `doma-core` jar version with the `doma-processor` version used to generate the DAO implementation. Do not confuse either with the JDK version or Maven Compiler Plugin version. | Set `doma-core` and `doma-processor` to the same released Doma version, clean away stale generated output, and compile again. Keep version validation enabled. |
| Compilation fails under a Java release older than 17. | Run `java -version` and inspect the Gradle toolchain or Maven compiler source/target settings. | Use JDK 17 or later for Doma 3.14 and set the build's Java level consistently. |

## Diagnostic Messages

The following meanings are limited to diagnostics established by the Doma 3.14
source baseline:

- `DOMA4005`: a DAO method lacks a query annotation.
- `DOMA4014`: `@Dao` is attached to a non-interface.
- `DOMA4017`: the DAO interface is not top-level.
- `DOMA4019`: the expected SQL file was not found in the classpath.
- `DOMA4020`: the SQL template is empty.
- `DOMA0003`: the runtime `doma-core` version differs from the processor version
  recorded in generated code.

`DOMA4005`, `DOMA4014`, `DOMA4017`, `DOMA4019`, and `DOMA4020` are annotation-
processing compilation failures. `DOMA0003` is a runtime version-validation
failure. Do not diagnose database connectivity, SQL execution, or transaction
behavior from these setup codes.

Keep these version concepts separate:

- Doma 3.14 requires JDK/JRE 17 or later.
- `doma-core` and `doma-processor` must use one identical released Doma version.
- `3.14.1-SNAPSHOT` is the research source baseline, not a released coordinate
  to copy into a build.
- Maven Compiler Plugin `3.8.1` is the version in Doma's Maven example, not a
  Doma version or documented minimum. Preserve a compatible version already
  managed by the project when present.

## Verification Sequence

1. Run `java -version` and confirm Java 17 or later.
2. Inspect the build configuration. Put `doma-core` on the compile/runtime
   classpath, put `doma-processor` only on the annotation-processor path, and
   give both artifacts the same released Doma version.
3. For external SQL under `src/main/resources`, confirm that
   `doma.resources.dir` resolves to that absolute directory and leave
   `doma.sql.validation` at its default value, `true`.
4. Compare every SQL resource with
   `META-INF/<DAO package path>/<DAO simple name>/<DAO method name>.sql`. Match
   DAO parameter names and types to the SQL bind expressions and test data.
5. Run a clean compile using the command from
   [Build Configuration](build-configuration.md):

   ```bash
   # Gradle
   ./gradlew -PdomaVersion=3.14.0 clean compileJava

   # Maven
   mvn clean compile
   ```

   Run only the command for the project's build tool.
6. If compilation succeeds, search recursively rather than assuming a deeper
   generated-source leaf path:

   ```bash
   # Gradle
   find build/generated/sources/annotationProcessor -type f -name '*DaoImpl.java' -print

   # Maven
   find target/generated-sources/annotations -type f -name '*DaoImpl.java' -print
   ```

7. If compilation fails, fix the reported compile-time diagnostic before
   looking for a generated DAO. If compilation succeeds without a Doma
   diagnostic but the implementation is absent, return to processor-path wiring
   and the recursive output search.
8. Exercise the DAO only after compile-time verification. Runtime execution
   requires a configured `DataSource`, an appropriate Doma `Dialect`, and the
   database objects expected by the SQL.

This sequence covers plain Java Gradle/Maven setup only. Use separate guidance
for frameworks, Kotlin/KAPT/KSP, transactions, migrations, database-specific
SQL, and advanced query design.

## References

- [Doma 3.14.0: Building an application](https://docs.domaframework.org/en/3.14.0/build/)
- [Doma 3.14.0: Annotation-processing options](https://docs.domaframework.org/en/3.14.0/annotation-processing/)
- [Doma 3.14.0 FAQ: setup and generated sources](https://docs.domaframework.org/en/3.14.0/faq/)
- [Doma 3.14.0 `Message` diagnostics](https://github.com/domaframework/doma/blob/3.14.0/doma-core/src/main/java/org/seasar/doma/message/Message.java)
- [Doma 3.14.0 DAO processor tests](https://github.com/domaframework/doma/blob/3.14.0/doma-processor/src/test/java/org/seasar/doma/internal/apt/processor/dao/DaoProcessorTest.java)
