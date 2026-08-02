# Build Configuration

Doma 3.14 requires JDK 17 or later to develop and run an application. Choose one
released Doma version for the project and use that identical value for both
`doma-core` and `doma-processor`. This skill's evidence baseline is the bundled
`3.14.1-SNAPSHOT` source; it is not a Maven Central release coordinate. The
examples use the released version documented by that baseline (`3.14.0`), which
you may replace with the project's chosen released version.

## Contents

- [Choose the Existing Build Tool](#choose-the-existing-build-tool)
- [Gradle](#gradle)
- [Maven](#maven)
- [Compile and Inspect Generated Sources](#compile-and-inspect-generated-sources)
- [References](#references)

## Choose the Existing Build Tool

Keep the project's existing Gradle or Maven build tool. Do not add a Doma Gradle
compile plugin just to configure annotation processing: direct dependency wiring
below is sufficient. If the project already uses a Doma plugin, select and verify
its published version separately; do not copy a plugin version from the source
snapshot because its examples conflict.

For SQL files or `doma.compile.config` stored in the conventional
`src/main/resources` directory, pass `doma.resources.dir` as an absolute path.
Without the option, Doma uses the generated-class directory instead, which is
not normally the source resources directory. Keep SQL validation enabled (the
default) while setting up the project.

## Gradle

Use the Java plugin, place `doma-core` on `implementation`, and place
`doma-processor` only on `annotationProcessor`. This Groovy DSL configuration is
complete for those baseline requirements:

```groovy
plugins {
    id 'java'
}

java {
    toolchain {
        languageVersion = JavaLanguageVersion.of(17)
    }
}

repositories {
    mavenCentral()
}

def domaVersion = providers.gradleProperty('domaVersion').getOrElse('3.14.0')

dependencies {
    implementation "org.seasar.doma:doma-core:${domaVersion}"
    annotationProcessor "org.seasar.doma:doma-processor:${domaVersion}"
}

tasks.withType(JavaCompile).configureEach {
    options.compilerArgs += [
        "-Adoma.resources.dir=${project.projectDir}/src/main/resources"
    ]
}
```

Change the default or supply the selected released version at build time, while
keeping the two Doma artifacts aligned:

```bash
./gradlew -PdomaVersion=3.14.0 clean compileJava
```

The `doma.resources.dir` value above resolves from `project.projectDir` and is
therefore absolute. Keep the `JavaCompile` block when external SQL templates or
`doma.compile.config` live under `src/main/resources`; change that path if the
project deliberately uses a different resource directory.

## Maven

Declare `doma-core` as a normal dependency. Put `doma-processor` in
`maven-compiler-plugin`'s `annotationProcessorPaths`, rather than in the runtime
dependencies. Add the following sections to the existing `pom.xml` (or merge
their values with equivalent existing properties and compiler-plugin settings):

```xml
<properties>
  <doma.version>3.14.0</doma.version>
  <maven.compiler.source>17</maven.compiler.source>
  <maven.compiler.target>17</maven.compiler.target>
</properties>

<dependencies>
  <dependency>
    <groupId>org.seasar.doma</groupId>
    <artifactId>doma-core</artifactId>
    <version>${doma.version}</version>
  </dependency>
</dependencies>

<build>
  <plugins>
    <plugin>
      <artifactId>maven-compiler-plugin</artifactId>
      <version>3.8.1</version>
      <configuration>
        <compilerArgs>
          <arg>-Adoma.resources.dir=${project.basedir}/src/main/resources</arg>
        </compilerArgs>
        <annotationProcessorPaths>
          <path>
            <groupId>org.seasar.doma</groupId>
            <artifactId>doma-processor</artifactId>
            <version>${doma.version}</version>
          </path>
        </annotationProcessorPaths>
      </configuration>
    </plugin>
  </plugins>
</build>
```

Set `doma.version` to one released version chosen for the project, and do not
give `doma-core` and `doma-processor` different versions. Preserve a compiler
plugin version already managed by the parent POM or build when it supports
`annotationProcessorPaths`. The standalone snippet uses Maven Compiler Plugin
`3.8.1`, the version in Doma's documented Maven example. That is an example,
not a Doma version requirement.

## Compile and Inspect Generated Sources

Compile after adding at least one top-level `@Dao` interface with a valid query
method. Doma generates the implementation during annotation processing; by
default a DAO named `example.dao.HealthCheckDao` produces
`example.dao.HealthCheckDaoImpl`.

For Gradle, compile and search recursively from the documented public generated
source root:

```bash
./gradlew clean compileJava
find build/generated/sources/annotationProcessor -type f -name '*DaoImpl.java' -print
```

For Maven:

```bash
mvn clean compile
find target/generated-sources/annotations -type f -name '*DaoImpl.java' -print
```

Do not assume a deeper Gradle directory is a Doma guarantee; Gradle can choose
additional source-set or task-specific path segments. If no implementation is
found, first confirm that compilation ran, then check the processor placement
(`annotationProcessor` for Gradle or `annotationProcessorPaths` for Maven), and
search recursively from the appropriate root. For SQL-file diagnostics, also
recheck the `doma.resources.dir` absolute path and the exact classpath resource
path.

## References

- [Doma 3.14.0: Building an application](https://docs.domaframework.org/en/3.14.0/build/)
- [Doma 3.14.0: Annotation-processing options](https://docs.domaframework.org/en/3.14.0/annotation-processing/)
- [Doma 3.14.0 FAQ: runtime, development, and generated sources](https://docs.domaframework.org/en/3.14.0/faq/)
- [Doma 3.14.0: DAO interfaces](https://docs.domaframework.org/en/3.14.0/dao/)
