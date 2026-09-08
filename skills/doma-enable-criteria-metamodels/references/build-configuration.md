# Build Configuration

- [Choosing where to put the option](#choosing-where-to-put-the-option)
- [Gradle, Java](#gradle-java)
- [Gradle, Kotlin with KAPT](#gradle-kotlin-with-kapt)
- [Maven](#maven)
- [doma.compile.config, every build tool](#domacompileconfig-every-build-tool)
- [Verification](#verification)
- [References](#references)

Apply this file only for the project-wide option path. Per-entity `@Entity(metamodel = @Metamodel)` needs no build change at all.

## Choosing where to put the option

| Situation | Put the option in |
| --- | --- |
| Java sources compiled by `compileJava` | the `compileJava` task's `compilerArgs` |
| Kotlin sources processed by KAPT | the `kapt` block's `arguments` |
| Maven | `maven-compiler-plugin` `compilerArgs` |
| Mixed build tools, Eclipse or IntelliJ IDEA imports, or a value that must hold everywhere | `doma.compile.config` |

Options set directly in a build tool override the same option in `doma.compile.config`. Doma documents `doma.compile.config` as available across Eclipse, IntelliJ IDEA, Gradle, and Maven, which makes it the most portable place for a project-wide value.

## Gradle, Java

Options reach the processor as `-A` javac arguments:

```kotlin
tasks {
    compileJava {
        options.compilerArgs.addAll(listOf("-Adoma.metamodel.enabled=true"))
    }
}
```

```groovy
compileJava {
    options {
        compilerArgs += ['-Adoma.metamodel.enabled=true']
    }
}
```

Add to `compilerArgs` rather than assigning it, so options contributed elsewhere in the build survive.

## Gradle, Kotlin with KAPT

`compileJava.options.compilerArgs` does not reach the Kotlin annotation processing tasks. KAPT passes processor options through its own `arguments` block (this syntax is defined by KAPT, not by Doma):

```kotlin
kapt {
    arguments {
        arg("doma.metamodel.enabled", true)
    }
}
```

If the build must avoid KAPT-specific configuration, use `doma.compile.config` instead; it is read by the processor regardless of which build tool invoked it.

## Maven

```xml
<plugin>
    <groupId>org.apache.maven.plugins</groupId>
    <artifactId>maven-compiler-plugin</artifactId>
    <configuration>
        <annotationProcessorPaths>
            <path>
                <groupId>org.seasar.doma</groupId>
                <artifactId>doma-processor</artifactId>
                <version>${doma.version}</version>
            </path>
        </annotationProcessorPaths>
        <compilerArgs>
            <arg>-Adoma.metamodel.enabled=true</arg>
        </compilerArgs>
    </configuration>
</plugin>
```

Keep any `-Adoma.resources.dir` or other existing `<arg>` entries; add to the list instead of replacing it.

The `annotationProcessorPaths` entry is shown only so the snippet is readable in isolation. This file covers where the metamodel option goes, not how to wire the processor itself; a project whose processor is not yet configured needs project setup first.

## doma.compile.config, every build tool

Create a properties file at the resource root, for example `src/main/resources/doma.compile.config`:

```properties
doma.metamodel.enabled=true
```

The file must follow the properties format and be placed in a root resource directory. Its values are overridden by options passed directly by the build tool, so do not set the same option in both places with different values.

## Verification

Run a clean build, then prove the class was generated:

```bash
./gradlew clean build
find build/generated -type f -name '*_.java' -print
```

```bash
mvn -q clean compile
find target/generated-sources -type f -name '*_.java' -print
```

`*_.java` matches the default suffix. Search for the configured name when a prefix or suffix is set, and do not confuse the metamodel `Employee_.java` with the entity meta class `_Employee.java`, which Doma generates for every entity independently of this option.

## References

- [Doma 3.14.0: Annotation processing options](https://docs.domaframework.org/en/3.14.0/annotation-processing/)
- [Doma 3.14.0: Setting options in Gradle, Maven, and `doma.compile.config`](https://docs.domaframework.org/en/3.14.0/annotation-processing/)
- [Doma 3.14.0: Kotlin support, using kapt in Gradle](https://docs.domaframework.org/en/3.14.0/kotlin-support/)
- [KAPT annotation processor arguments](https://kotlinlang.org/docs/kapt.html)
