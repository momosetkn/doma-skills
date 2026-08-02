# Build Configuration

Use the project's existing Gradle and compatible Kotlin versions. The source snapshot exercises Kotlin `2.3.21`; it is shown below as a complete example, not as a reason to replace a compatible version the project already selected.

Doma 3.14 requires JDK 17 or later. `3.14.0` is the released example version documented by the baseline; replace it with the project's selected released version when needed, but keep `doma-kotlin` and `doma-processor` aligned. The source snapshot is research evidence, not a dependency coordinate.

```kotlin
plugins {
    kotlin("jvm") version "2.3.21"
    kotlin("kapt") version "2.3.21"
}

java {
    toolchain {
        languageVersion = JavaLanguageVersion.of(17)
    }
}

repositories {
    mavenCentral()
}

val domaVersion = providers.gradleProperty("domaVersion").getOrElse("3.14.0")

dependencies {
    implementation("org.seasar.doma:doma-kotlin:$domaVersion")
    kapt("org.seasar.doma:doma-processor:$domaVersion")
}
```

Build the probe and inspect every generated-source subtree:

```bash
./gradlew -PdomaVersion=3.14.0 clean build
find build/generated -type f -name '*DaoImpl.java' -print
```

The recursive search verifies generation without promising a deeper KAPT output directory as a Doma API contract.

## References

- [Doma 3.14.0: Kotlin support](https://docs.domaframework.org/en/3.14.0/kotlin-support/)
- [Doma 3.14.0: Building an application](https://docs.domaframework.org/en/3.14.0/build/)
- [Doma 3.14.0 Kotlin integration build](https://github.com/domaframework/doma/blob/3.14.0/integration-test-kotlin/build.gradle.kts)
