# Setup Troubleshooting

Run a clean build first and keep Doma SQL and version validation enabled. Then use the first applicable recovery.

## Establish the KAPT failure point first

Before changing a DAO or any application logic, capture one clean build with task-detail output:

```bash
log_file="$(mktemp)"
set -o pipefail
./gradlew clean build --info |& tee "$log_file"
rg -n '^> Task :kaptGenerateStubsKotlin( |$)' "$log_file"
rg -n '^> Task :kaptKotlin( |$)' "$log_file"
rg -n -m 1 -C 3 '([Ss]tub|DOMA[0-9]{4}|[Ee]rror:)' "$log_file"
```

Use this order: first confirm that both KAPT tasks ran; if either did not, correct the plugin or dependency wiring below. If they ran and the build failed, inspect the first Kotlin-stub or Doma processor diagnostic from the final command before changing DAO or application logic. A successful build with no generated implementation proceeds to the generated-source search.

| Symptom | Inspect | Recovery |
| --- | --- | --- |
| Doma annotations are unresolved | Check that `org.seasar.doma:doma-kotlin` is on `implementation`, Maven Central is configured, and a released Doma version was selected. | Add or correct `doma-kotlin`; do not substitute `doma-core` for this Kotlin workflow. |
| The `kapt` configuration is unavailable | Check the plugins block. | Apply `kotlin("kapt")` with the Kotlin plugin version used by the project. |
| Kotlin compiles but KAPT does not process Doma | Check where `doma-processor` is declared. | Move it from `implementation` or `annotationProcessor` to `kapt`, and align its version with `doma-kotlin`. |
| No `*DaoImpl.java` appears | First confirm both KAPT tasks and inspect the first stub or processor diagnostic using the ordered commands above, then inspect generated output. | Run `find build/generated -type f -name '*DaoImpl.java' -print`; do not assume a deeper directory. |
| `DOMA4005` | Check the DAO method for a query annotation. | Add the query annotation; use `@Select` with the inline `@Sql` probe. |
| `DOMA4014` | Check the declaration kind. | Annotate an interface, not a class. |
| `DOMA4017` | Check nesting. | Move the DAO to a top-level interface. |
| Runtime version validation fails | Compare the runtime Doma artifact and annotation-processor versions. | Select one released version for both artifacts, then clean-build to regenerate sources. |
| KSP is requested | This baseline verifies KAPT only. | Perform separate current official research before changing processors; do not infer a KSP configuration from this skill. |

## References

- [Doma 3.14.0: Kotlin support](https://docs.domaframework.org/en/3.14.0/kotlin-support/)
- [Doma 3.14.0: Annotation-processing options](https://docs.domaframework.org/en/3.14.0/annotation-processing/)
- [Doma 3.14.0: DAO interfaces](https://docs.domaframework.org/en/3.14.0/dao/)
- [Doma 3.14.0 DAO processor tests](https://github.com/domaframework/doma/tree/3.14.0/doma-processor/src/test/java/org/seasar/doma/internal/apt/processor/dao)
