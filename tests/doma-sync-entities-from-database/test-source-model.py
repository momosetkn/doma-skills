#!/usr/bin/env python3
"""Behavioral tests for conservative Java/Kotlin entity source parsing."""
from __future__ import annotations

import dataclasses
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills/doma-sync-entities-from-database/scripts"
FIXTURES = Path(__file__).parent / "fixtures/source-model"
sys.path.insert(0, str(SCRIPTS))

from entity_sync.lexer import balanced_region, lex_java, lex_kotlin
from entity_sync.java_parser import find_java_domain_declarations, parse_java
from entity_sync.kotlin_parser import find_kotlin_domain_declarations, parse_kotlin
from entity_sync.model import (
    AnnotationModel,
    EntityModel,
    MethodModel,
    ParsedEntity,
    PropertyModel,
    SourceSpan,
    TableIdentity,
)


class SourceModelTests(unittest.TestCase):
    def test_core_models_are_immutable_and_table_identity_is_orderable(self) -> None:
        span = SourceSpan(2, 5)
        annotation = AnnotationModel("org.seasar.doma.Id", (), span)
        prop = PropertyModel("id", "employee_id", "Long", False, (annotation,), span, span, False)
        method = MethodModel("getId", "public Long getId()", span, "id", ("id",))
        entity = EntityModel(
            "src/Employee.java", "java", "example", "Employee",
            TableIdentity(None, "public", "employee"), (prop,), ("org.seasar.doma.Entity",),
            (method,), None, (), (), span, SourceSpan(10, 50), True, (), "\n",
        )
        parsed = ParsedEntity("@Entity class Employee {}\n", entity)

        self.assertEqual("employee", parsed.entity.table.table)
        self.assertLess(TableIdentity(None, None, "a"), TableIdentity(None, None, "b"))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            parsed.entity.class_name = "Other"  # type: ignore[misc]

    def assert_lossless_tokens(self, source: str, tokens: tuple[object, ...]) -> None:
        self.assertEqual(source, "".join(token.text for token in tokens))
        for token in tokens:
            self.assertEqual(token.text, source[token.span.start:token.span.end])
        self.assertEqual(list(range(len(source))), [
            offset
            for token in tokens
            for offset in range(token.span.start, token.span.end)
        ])

    def test_java_lexer_preserves_comments_literals_text_blocks_and_escapes(self) -> None:
        source = (
            '/** doc */ @A(value = "a\\\"b", nested = @B({1, 2}))\n'
            "class X { char quote = '\\''; String block = \"\"\"line // raw\n/* raw */\"\"\"; // tail\n}\n"
        )
        tokens = lex_java(source)

        self.assert_lossless_tokens(source, tokens)
        self.assertIn("JAVADOC", {token.kind for token in tokens})
        self.assertIn("STRING", {token.kind for token in tokens})
        self.assertIn("CHAR", {token.kind for token in tokens})
        self.assertIn("TEXT_BLOCK", {token.kind for token in tokens})
        self.assertEqual(1, sum(token.kind == "LINE_COMMENT" for token in tokens))

        significant = tuple(token for token in tokens if token.kind not in {"WHITESPACE", "JAVADOC"})
        opening = next(index for index, token in enumerate(significant) if token.text == "(")
        region = balanced_region(significant, opening, "(", ")")
        self.assertEqual('(value = "a\\\"b", nested = @B({1, 2}))', source[region.start:region.end])

    def test_kotlin_lexer_preserves_kdoc_comments_chars_and_triple_strings(self) -> None:
        source = (
            '/** kdoc */ @A(text = "x\\\"y")\n'
            "class X { val slash = '/'; val raw = \"\"\"// raw\n/* raw */\"\"\" /* block */ }\n"
        )
        tokens = lex_kotlin(source)

        self.assert_lossless_tokens(source, tokens)
        kinds = {token.kind for token in tokens}
        self.assertTrue({"KDOC", "STRING", "CHAR", "TRIPLE_STRING", "BLOCK_COMMENT"}.issubset(kinds))

    def test_unterminated_lexical_construct_is_preserved_as_error_token(self) -> None:
        for lexer, source in ((lex_java, 'class X { String s = "oops'), (lex_kotlin, "class X { /* oops")):
            with self.subTest(lexer=lexer.__name__):
                tokens = lexer(source)
                self.assert_lossless_tokens(source, tokens)
                self.assertEqual("ERROR", tokens[-1].kind)

    def test_official_java_codegen_shape_parses_exact_spans_and_generated_accessors(self) -> None:
        source = (FIXTURES / "official-java.java").read_text(encoding="utf-8")
        parsed = parse_java(source, path="src/main/java/example/entity/Employee.java")
        entity = parsed.entity

        self.assertIs(parsed.source, source)
        self.assertEqual("example.entity", entity.package_name)
        self.assertEqual("Employee", entity.class_name)
        self.assertEqual(TableIdentity(None, "public", "employee"), entity.table)
        self.assertEqual(("id", "hireDate", "version"), tuple(prop.name for prop in entity.properties))
        self.assertEqual(("employee_id", "hire_date", "version"), tuple(prop.column for prop in entity.properties))
        self.assertEqual(("Integer", "LocalDate", "Integer"), tuple(prop.type_name for prop in entity.properties))
        self.assertEqual((None, None, None), tuple(prop.nullable for prop in entity.properties))
        self.assertEqual(("id", "id", "hireDate", "hireDate", "version", "version"),
                         tuple(method.generated_accessor_for for method in entity.methods))
        self.assertTrue(entity.generated_only)
        self.assertEqual((), entity.unsupported_reasons)

        self.assertEqual(source[entity.import_region.start:entity.import_region.end].strip().splitlines(), [
            "import java.time.LocalDate;",
            "import org.seasar.doma.Column;",
            "import org.seasar.doma.Entity;",
            "import org.seasar.doma.GeneratedValue;",
            "import org.seasar.doma.GenerationType;",
            "import org.seasar.doma.Id;",
            "import org.seasar.doma.Metamodel;",
            "import org.seasar.doma.Table;",
            "import org.seasar.doma.Version;",
        ])
        self.assertEqual("{", source[entity.class_body.start - 1])
        self.assertEqual("}", source[entity.class_body.end])
        for prop in entity.properties:
            self.assertIn(prop.name, source[prop.declaration_span.start:prop.declaration_span.end])
            self.assertTrue(source[prop.full_span.start:prop.full_span.end].lstrip().startswith("/**"))

    def test_java_accessors_with_clauses_before_the_body_are_handwritten(self) -> None:
        source = """import org.seasar.doma.*;
/** */
@Entity @Table(name = "employee")
public class Employee {
  /** */ @Column(name = "name") String name;
  /** Returns the name. */
  public String getName() throws RuntimeException { return name; }
  /** Sets the name. */
  public void setName(String name) throws RuntimeException { this.name = name; }
}
"""

        entity = parse_java(source, path="Employee.java").entity
        self.assertEqual((None, None), tuple(
            method.generated_accessor_for for method in entity.methods
        ))
        self.assertIn("handwritten method: getName", entity.unsupported_reasons)
        self.assertIn("handwritten method: setName", entity.unsupported_reasons)
        self.assertFalse(entity.generated_only)

    def test_java_accessors_with_comments_before_the_body_are_handwritten(self) -> None:
        source = """import org.seasar.doma.*;
/** */
@Entity @Table(name = "employee")
public class Employee {
  /** */ @Column(name = "name") String name;
  /** Returns the name. */
  public String getName() /* custom getter */ { return name; }
  /** Sets the name. */
  public void setName(String name) /* custom setter */ { this.name = name; }
}
"""

        entity = parse_java(source, path="Employee.java").entity
        self.assertEqual((None, None), tuple(
            method.generated_accessor_for for method in entity.methods
        ))
        self.assertIn("handwritten method: getName", entity.unsupported_reasons)
        self.assertIn("handwritten method: setName", entity.unsupported_reasons)
        self.assertFalse(entity.generated_only)

    def test_java_annotation_arguments_ids_special_mappings_and_domain_types_are_preserved(self) -> None:
        source = (FIXTURES / "semantics-java.java").read_text(encoding="utf-8")
        parsed = parse_java(
            source,
            path="src/main/java/example/entity/Order.java",
            domain_types=("com.example.domain.Money",),
        )
        entity = parsed.entity

        self.assertEqual(TableIdentity("app", "tenant", "orders"), entity.table)
        self.assertEqual(("tenantId", "orderId"), tuple(
            prop.name for prop in entity.properties
            if any(annotation.qualified_name == "org.seasar.doma.Id" for annotation in prop.annotations)
        ))
        labels = next(prop for prop in entity.properties if prop.name == "labels")
        self.assertEqual("List<String[]>", labels.type_name)
        audited = next(name for name in entity.custom_annotations if name == "com.example.Audited")
        self.assertEqual("com.example.Audited", audited)
        class_annotations = source[:source.index("public class")]
        self.assertIn('@Audited(level = @Audited.Level(values = {"a", "b"}))', class_annotations)
        self.assertIn("domain-typed property: amount", entity.unsupported_reasons)
        self.assertIn("tenant-id property: tenantId", entity.unsupported_reasons)
        self.assertIn("transient property: labels", entity.unsupported_reasons)
        self.assertIn("association property: customer", entity.unsupported_reasons)
        self.assertIn("embedded property: address", entity.unsupported_reasons)

    def test_java_handwritten_application_semantics_fail_closed(self) -> None:
        source = (FIXTURES / "semantics-java.java").read_text(encoding="utf-8")
        entity = parse_java(source, path="Order.java", domain_types=("com.example.domain.Money",)).entity

        self.assertFalse(entity.generated_only)
        self.assertEqual("BaseEntity", entity.superclass)
        self.assertEqual(("Serializable", "Comparable<Order>"), entity.interfaces)
        self.assertIn("lombok annotation: lombok.Data", entity.unsupported_reasons)
        self.assertIn("custom annotation: com.example.Audited", entity.unsupported_reasons)
        self.assertIn("custom annotation: com.example.Valid", entity.unsupported_reasons)
        self.assertIn("field initializer: initialized", entity.unsupported_reasons)
        self.assertIn("handwritten method: score", entity.unsupported_reasons)
        score = next(method for method in entity.methods if method.name == "score")
        self.assertEqual(("orderId", "intValue"), score.referenced_names)

    def test_java_record_and_multiple_or_ambiguous_entities_fail_closed(self) -> None:
        record = """import org.seasar.doma.Entity;\n@Entity record Employee(int id) {}\n"""
        self.assertIn("java record", parse_java(record, path="Employee.java").entity.unsupported_reasons)

        multiple = """import org.seasar.doma.Entity;\n@Entity class One {}\n@Entity class Two {}\n"""
        entity = parse_java(multiple, path="Two.java").entity
        self.assertEqual("One", entity.class_name)
        self.assertIn("multiple top-level Doma entities", entity.unsupported_reasons)

        ambiguous = """@Entity class Maybe {}\n"""
        reasons = parse_java(ambiguous, path="Maybe.java").entity.unsupported_reasons
        self.assertIn("ambiguous annotation: Entity", reasons)

    def test_same_file_annotation_declaration_shadows_doma_wildcard_import(self) -> None:
        java = """package example;
import org.seasar.doma.*;
@interface Entity {}
/** */
@Entity @Table(name = "employee")
public class Employee {
  /** */ @Column(name = "id") public Long id;
}
"""
        kotlin = """package example
import org.seasar.doma.*
annotation class Entity
/** */
@Entity @Table(name = "employee")
class Employee {
  /** */ @Column(name = "id") var id: Long = -1L
}
"""

        for parsed in (parse_java(java, path="Employee.java"), parse_kotlin(kotlin, path="Employee.kt")):
            with self.subTest(language=parsed.entity.language):
                self.assertIn("ambiguous annotation: Entity", parsed.entity.unsupported_reasons)
                self.assertFalse(parsed.entity.generated_only)

    def test_java_duplicate_columns_crlf_and_missing_final_newline_are_preserved(self) -> None:
        source = (
            "package example;\r\nimport org.seasar.doma.*;\r\n\r\n/** */\r\n@Entity\r\n@Table(name = \"dup\")\r\n"
            "public class Dup {\r\n  /** */\r\n  @Column(name = \"same\") String first;\r\n"
            "  /** */\r\n  @Column(name = \"same\") String second;\r\n}"
        )
        parsed = parse_java(source, path="Dup.java")

        self.assertEqual(source, parsed.source)
        self.assertEqual("\r\n", parsed.entity.line_ending)
        self.assertFalse(parsed.source.endswith(("\n", "\r")))
        self.assertIn("duplicate column mapping: same", parsed.entity.unsupported_reasons)

    def test_official_kotlin_codegen_shape_parses_body_vars_and_nullability(self) -> None:
        source = (FIXTURES / "official-kotlin.kt").read_text(encoding="utf-8")
        parsed = parse_kotlin(source, path="src/main/kotlin/example/entity/Employee.kt")
        entity = parsed.entity

        self.assertIs(parsed.source, source)
        self.assertEqual("example.entity", entity.package_name)
        self.assertEqual("Employee", entity.class_name)
        self.assertEqual(TableIdentity(None, "public", "employee"), entity.table)
        self.assertEqual(("id", "displayName", "version"), tuple(prop.name for prop in entity.properties))
        self.assertEqual(("Int", "String", "Long"), tuple(prop.type_name for prop in entity.properties))
        self.assertEqual((False, True, False), tuple(prop.nullable for prop in entity.properties))
        self.assertTrue(all(not prop.constructor_property for prop in entity.properties))
        self.assertEqual((), entity.methods)
        self.assertTrue(entity.generated_only)
        self.assertEqual((), entity.unsupported_reasons)
        self.assertEqual(source[entity.import_region.start:entity.import_region.end].strip().splitlines(), [
            "import org.seasar.doma.Column",
            "import org.seasar.doma.Entity",
            "import org.seasar.doma.GeneratedValue",
            "import org.seasar.doma.GenerationType",
            "import org.seasar.doma.Id",
            "import org.seasar.doma.Metamodel",
            "import org.seasar.doma.Table",
            "import org.seasar.doma.Version",
        ])

    def test_kotlin_primary_constructor_properties_and_data_class_fail_closed(self) -> None:
        source = """package example\nimport org.seasar.doma.*\n\n/** */\n@Entity\n@Table(name = \"employee\")\ndata class Employee(\n  @Id @Column(name = \"id\") val id: Long,\n  var name: String? = null,\n)\n"""
        entity = parse_kotlin(source, path="Employee.kt").entity

        self.assertEqual(("id", "name"), tuple(prop.name for prop in entity.properties))
        self.assertTrue(all(prop.constructor_property for prop in entity.properties))
        self.assertEqual((False, True), tuple(prop.nullable for prop in entity.properties))
        self.assertIn("kotlin data class", entity.unsupported_reasons)
        self.assertIn("kotlin primary-constructor property: id", entity.unsupported_reasons)
        self.assertIn("kotlin primary-constructor property: name", entity.unsupported_reasons)
        self.assertIn("complex constructor change: name", entity.unsupported_reasons)
        self.assertFalse(entity.generated_only)

    def test_kotlin_special_mappings_domain_and_custom_annotations_are_preserved(self) -> None:
        source = (FIXTURES / "semantics-kotlin.kt").read_text(encoding="utf-8")
        entity = parse_kotlin(
            source,
            path="Order.kt",
            domain_types=("com.example.domain.Money",),
        ).entity

        self.assertEqual(TableIdentity("app", "tenant", "orders"), entity.table)
        self.assertIn("com.example.Audited", entity.custom_annotations)
        self.assertIn("com.example.Valid", entity.custom_annotations)
        self.assertIn("domain-typed property: amount", entity.unsupported_reasons)
        self.assertIn("transient property: labels", entity.unsupported_reasons)
        self.assertIn("embedded property: address", entity.unsupported_reasons)
        self.assertIn("delegated property: delegated", entity.unsupported_reasons)
        self.assertIn("custom accessor: normalized", entity.unsupported_reasons)
        getter = next(method for method in entity.methods if method.name == "get:normalized")
        setter = next(method for method in entity.methods if method.name == "set:normalized")
        self.assertTrue(source[getter.span.start:getter.span.end].lstrip().startswith("get()"))
        self.assertTrue(source[setter.span.start:setter.span.end].lstrip().startswith("set(value)"))

    def test_kotlin_methods_initializers_supertypes_and_complex_constructor_fail_closed(self) -> None:
        source = (FIXTURES / "semantics-kotlin.kt").read_text(encoding="utf-8")
        entity = parse_kotlin(source, path="Order.kt").entity

        self.assertEqual("BaseEntity", entity.superclass)
        self.assertEqual(("Serializable",), entity.interfaces)
        self.assertIn("complex primary constructor", entity.unsupported_reasons)
        self.assertIn("initializer block", entity.unsupported_reasons)
        self.assertIn("handwritten method: score", entity.unsupported_reasons)
        score = next(method for method in entity.methods if method.name == "score")
        self.assertEqual(("orderId",), score.referenced_names)
        self.assertFalse(entity.generated_only)

    def test_embeddable_declaration_and_embedded_property_are_never_generated_only(self) -> None:
        source = """import org.seasar.doma.Embeddable\n\n@Embeddable\n+data class Address(val street: String)\n"""
        entity = parse_kotlin(source, path="Address.kt").entity

        self.assertEqual("Address", entity.class_name)
        self.assertIn("embeddable declaration", entity.unsupported_reasons)
        self.assertIn("kotlin data class", entity.unsupported_reasons)
        self.assertIn("kotlin primary-constructor property: street", entity.unsupported_reasons)

    def test_kotlin_duplicate_columns_and_ambiguous_annotation_fail_closed(self) -> None:
        source = """@Entity\n@Table(name = \"dup\")\nclass Dup {\n  @Column(name = \"same\") var first: String? = null\n  @Column(name = \"same\") var second: String? = null\n}\n"""
        entity = parse_kotlin(source, path="Dup.kt").entity

        self.assertIn("ambiguous annotation: Entity", entity.unsupported_reasons)
        self.assertIn("ambiguous annotation: Table", entity.unsupported_reasons)
        self.assertIn("ambiguous annotation: Column", entity.unsupported_reasons)
        self.assertIn("duplicate column mapping: same", entity.unsupported_reasons)

    def test_domain_declarations_are_discovered_only_from_unambiguous_doma_annotations(self) -> None:
        java = """package com.example.domain;\nimport org.seasar.doma.Domain;\n@Domain(valueType = String.class) public final class Money {}\n"""
        kotlin = """package com.example.domain\nimport org.seasar.doma.Domain\n@Domain(valueType = String::class) value class Code(val value: String)\n"""

        self.assertEqual(("com.example.domain.Money",), find_java_domain_declarations(java))
        self.assertEqual(("com.example.domain.Code",), find_kotlin_domain_declarations(kotlin))
        self.assertEqual((), find_java_domain_declarations("@Domain(valueType = String.class) class Ambiguous {}"))
        self.assertEqual((), find_kotlin_domain_declarations("@Domain(valueType = String::class) class Ambiguous"))

    def test_java_enum_domain_declaration_blocks_generated_only_entity_classification(self) -> None:
        domain_source = """package example;
import org.seasar.doma.Domain;
@Domain(valueType = String.class)
public enum Money { VALUE }
"""
        entity_source = """package example;
import org.seasar.doma.*;
/** */
@Entity @Table(name = "wallet")
public class Wallet {
  /** */ @Column(name = "amount") public Money amount;
}
"""

        domains = find_java_domain_declarations(domain_source)
        self.assertEqual(("example.Money",), domains)
        entity = parse_java(entity_source, path="Wallet.java", domain_types=domains).entity
        self.assertIn("domain-typed property: amount", entity.unsupported_reasons)
        self.assertFalse(entity.generated_only)

    def test_java_nested_and_anonymous_edit_targets_and_unmatched_body_fail_closed(self) -> None:
        source = """import org.seasar.doma.*;\n@Entity @Table(name = \"holder\") class Holder {\n  Runnable task = new Runnable() { public void run() {} };\n  static class Nested {}\n}\n"""
        reasons = parse_java(source, path="Holder.java").entity.unsupported_reasons
        self.assertIn("anonymous class edit target", reasons)
        self.assertIn("nested type or anonymous class", reasons)

        unmatched = """import org.seasar.doma.*;\n@Entity @Table(name = \"broken\") class Broken { String name;\n"""
        parsed = parse_java(unmatched, path="Broken.java")
        self.assertIn("unmatched class body", parsed.entity.unsupported_reasons)
        self.assertEqual(len(unmatched), parsed.entity.class_body.end)

    def test_kotlin_destructuring_and_unmatched_body_fail_closed_explicitly(self) -> None:
        destructuring = """import org.seasar.doma.*\n@Entity @Table(name = \"pair\") class PairHolder {\n  val (left, right) = loadPair()\n}\n"""
        reasons = parse_kotlin(destructuring, path="PairHolder.kt").entity.unsupported_reasons
        self.assertIn("kotlin destructuring declaration", reasons)

        unmatched = """import org.seasar.doma.*\n@Entity @Table(name = \"broken\") class Broken { var name: String? = null\n"""
        parsed = parse_kotlin(unmatched, path="Broken.kt")
        self.assertIn("unmatched class body", parsed.entity.unsupported_reasons)
        self.assertEqual(len(unmatched), parsed.entity.class_body.end)

    def test_nonliteral_column_identity_is_explicitly_ambiguous(self) -> None:
        java = """import org.seasar.doma.*;\n@Entity @Table(name = \"x\") class X { @Column(name = Names.ID) String id; }\n"""
        kotlin = """import org.seasar.doma.*\n@Entity @Table(name = \"x\") class X { @Column(name = Names.ID) var id: String? = null }\n"""

        java_entity = parse_java(java, path="X.java").entity
        kotlin_entity = parse_kotlin(kotlin, path="X.kt").entity
        self.assertEqual("id", java_entity.properties[0].column)
        self.assertEqual("id", kotlin_entity.properties[0].column)
        self.assertIn("ambiguous @Column name: id", java_entity.unsupported_reasons)
        self.assertIn("ambiguous @Column name: id", kotlin_entity.unsupported_reasons)

    def test_non_template_doma_annotation_arguments_fail_closed_and_are_retained(self) -> None:
        java = """import org.seasar.doma.*;
/** */
@Entity(metamodel = @Metamodel) @Table(name = "x", quote = true)
public class X {
  /** */ @Column(name = "id", updatable = false) public Long id;
}
"""
        kotlin = """import org.seasar.doma.*
/** */
@Entity(metamodel = Metamodel()) @Table(name = "x", quote = true)
class X {
  /** */ @Column(name = "id", updatable = false) var id: Long = -1L
}
"""

        for parsed in (parse_java(java, path="X.java"), parse_kotlin(kotlin, path="X.kt")):
            with self.subTest(language=parsed.entity.language):
                entity = parsed.entity
                column = next(
                    annotation for annotation in entity.properties[0].annotations
                    if annotation.qualified_name == "org.seasar.doma.Column"
                )
                self.assertEqual((("name", '"id"'), ("updatable", "false")), column.arguments)
                self.assertIn(
                    'non-template annotation arguments: org.seasar.doma.Table on class '
                    '(name="x", quote=true)',
                    entity.unsupported_reasons,
                )
                self.assertIn(
                    'non-template annotation arguments: org.seasar.doma.Column on property id '
                    '(name="id", updatable=false)',
                    entity.unsupported_reasons,
                )
                self.assertFalse(entity.generated_only)

    def test_fully_qualified_annotation_expressions_are_not_codegen_template_shapes(self) -> None:
        java = """import org.seasar.doma.*;
/** */
@Entity(listener = com.example.EmployeeListener.class, naming = org.seasar.doma.jdbc.entity.NamingType.LOWER_CASE, metamodel = @Metamodel)
@Table(name = "x")
public class X {
  /** */ @Id @GeneratedValue(strategy = org.seasar.doma.GenerationType.IDENTITY) @Column(name = "id") public Long id;
}
"""
        kotlin = """import org.seasar.doma.*
/** */
@Entity(listener = com.example.EmployeeListener::class, naming = org.seasar.doma.jdbc.entity.NamingType.LOWER_CASE, metamodel = Metamodel())
@Table(name = "x")
class X {
  /** */ @Id @GeneratedValue(strategy = org.seasar.doma.GenerationType.IDENTITY) @Column(name = "id") var id: Long = -1L
}
"""

        for parsed in (parse_java(java, path="X.java"), parse_kotlin(kotlin, path="X.kt")):
            with self.subTest(language=parsed.entity.language):
                reasons = parsed.entity.unsupported_reasons
                self.assertTrue(any(
                    reason.startswith(
                        "non-template annotation arguments: org.seasar.doma.Entity on class"
                    )
                    for reason in reasons
                ))
                self.assertIn(
                    "non-template annotation arguments: org.seasar.doma.GeneratedValue "
                    "on property id (strategy=org.seasar.doma.GenerationType.IDENTITY)",
                    reasons,
                )
                self.assertFalse(parsed.entity.generated_only)

    def test_handwritten_multiline_property_docs_never_classify_as_codegen_only(self) -> None:
        java = """import org.seasar.doma.*;\n/** Handwritten entity. */\n@Entity @Table(name = \"x\") public class X {\n  /**\n   * Application-owned meaning.\n   */\n  @Column(name = \"value\") public String value;\n}\n"""
        kotlin = """import org.seasar.doma.*\n/** Handwritten entity. */\n@Entity @Table(name = \"x\") class X {\n  /**\n+   * Application-owned meaning.\n   */\n  @Column(name = \"value\") var value: String? = null\n}\n"""

        self.assertFalse(parse_java(java, path="X.java").entity.generated_only)
        self.assertFalse(parse_kotlin(kotlin, path="X.kt").entity.generated_only)
        empty_java = """import org.seasar.doma.*;\n/** */\n@Entity @Table(name = \"empty\") public class Empty {}\n"""
        empty_kotlin = """import org.seasar.doma.*\n/** */\n@Entity @Table(name = \"empty\") class Empty {}\n"""
        self.assertFalse(parse_java(empty_java, path="Empty.java").entity.generated_only)
        self.assertFalse(parse_kotlin(empty_kotlin, path="Empty.kt").entity.generated_only)

    def test_kotlin_secondary_constructor_is_an_explicit_complex_constructor_finding(self) -> None:
        source = """import org.seasar.doma.*\n@Entity @Table(name = \"x\") class X {\n  @Column(name = \"value\") var value: String? = null\n  constructor(value: String) { this.value = value }\n}\n"""

        entity = parse_kotlin(source, path="X.kt").entity
        self.assertIn("complex constructor change", entity.unsupported_reasons)
        constructor = next(method for method in entity.methods if method.name == "<constructor>")
        self.assertIn("value", constructor.referenced_names)

    def test_same_package_domain_types_are_detected_for_every_property_from_an_iterable(self) -> None:
        java = """package p;\nimport org.seasar.doma.*;\n@Entity @Table(name = \"x\") class X {\n  @Column(name = \"gross\") Money gross;\n  @Column(name = \"net\") Money net;\n}\n"""
        kotlin = """package p\nimport org.seasar.doma.*\n@Entity @Table(name = \"x\") class X {\n  @Column(name = \"gross\") var gross: Money? = null\n  @Column(name = \"net\") var net: Money? = null\n}\n"""

        java_reasons = parse_java(java, path="X.java", domain_types=(name for name in ("p.Money",))).entity.unsupported_reasons
        kotlin_reasons = parse_kotlin(kotlin, path="X.kt", domain_types=(name for name in ("p.Money",))).entity.unsupported_reasons
        self.assertIn("domain-typed property: gross", java_reasons)
        self.assertIn("domain-typed property: net", java_reasons)
        self.assertIn("domain-typed property: gross", kotlin_reasons)
        self.assertIn("domain-typed property: net", kotlin_reasons)

    def test_java_class_literals_inside_entity_annotation_are_not_type_declarations(self) -> None:
        source = """package p;\nimport org.seasar.doma.*;\n/** */\n@Entity(listener = EmployeeListener.class, metamodel = @Metamodel)\n@Table(name = \"employee\")\npublic class Employee {\n  /** */\n  @Column(name = \"name\") public String name;\n}\n"""

        entity = parse_java(source, path="Employee.java").entity
        self.assertEqual("Employee", entity.class_name)
        self.assertEqual(TableIdentity(None, None, "employee"), entity.table)
        self.assertNotIn("multiple top-level Doma entities", entity.unsupported_reasons)

    def test_kotlin_bodyless_entity_does_not_capture_later_top_level_function_body(self) -> None:
        source = """import org.seasar.doma.*\n@Entity @Table(name = \"marker\") class Marker\nfun helper() { println(\"not an entity body\") }\n"""

        entity = parse_kotlin(source, path="Marker.kt").entity
        self.assertEqual(SourceSpan(source.index("Marker") + len("Marker"), source.index("Marker") + len("Marker")),
                         entity.class_body)
        self.assertEqual((), entity.properties)
        self.assertEqual((), entity.methods)
        self.assertFalse(entity.generated_only)

    def test_trailing_comments_do_not_overlap_adjacent_property_full_spans(self) -> None:
        java = """import org.seasar.doma.*;\n@Entity @Table(name = \"x\") class X {\n  /** */ @Column(name = \"first\") String first; // belongs to first\n  /** */ @Column(name = \"second\") String second;\n}\n"""
        kotlin = """import org.seasar.doma.*\n@Entity @Table(name = \"x\") class X {\n  /** */ @Column(name = \"first\") var first: String? = null // belongs to first\n  /** */ @Column(name = \"second\") var second: String? = null\n}\n"""

        for parsed in (parse_java(java, path="X.java"), parse_kotlin(kotlin, path="X.kt")):
            with self.subTest(language=parsed.entity.language):
                first, second = parsed.entity.properties
                self.assertLessEqual(first.full_span.end, second.full_span.start)
                self.assertTrue(parsed.source[second.full_span.start:second.full_span.end].lstrip().startswith("/**"))

    def test_non_template_class_and_property_modifiers_never_classify_as_generated_only(self) -> None:
        java = """import org.seasar.doma.*;\n/** */\n@Entity @Table(name = \"x\") public final class X {\n  /** */ @Column(name = \"id\") protected Long id;\n  /** Returns the id. */ public Long getId() { return id; }\n  /** Sets the id. */ public void setId(Long id) { this.id = id; }\n}\n"""
        kotlin = """import org.seasar.doma.*\n/** */\n@Entity @Table(name = \"x\") open class X {\n  /** */ @Column(name = \"id\") private var id: Long = -1L\n}\n"""

        self.assertFalse(parse_java(java, path="X.java").entity.generated_only)
        self.assertFalse(parse_kotlin(kotlin, path="X.kt").entity.generated_only)

    def test_type_use_custom_annotations_are_preserved_and_block_generated_only(self) -> None:
        java = """import java.util.List;\nimport org.seasar.doma.*;\n/** */\n@Entity @Table(name = \"x\") public class X {\n  /** */ @Column(name = \"values\") public List<@com.example.Valid String> values;\n}\n"""
        kotlin = """import org.seasar.doma.*\n/** */\n@Entity @Table(name = \"x\") class X {\n  /** */ @Column(name = \"value\") var value: @com.example.Valid String? = null\n}\n"""

        for parsed in (parse_java(java, path="X.java"), parse_kotlin(kotlin, path="X.kt")):
            with self.subTest(language=parsed.entity.language):
                self.assertFalse(parsed.entity.generated_only)
                self.assertIn("com.example.Valid", parsed.entity.custom_annotations)
                self.assertIn("com.example.Valid", tuple(
                    annotation.qualified_name for annotation in parsed.entity.properties[0].annotations
                ))

    def test_interleaved_modifiers_and_generic_headers_never_look_like_codegen_templates(self) -> None:
        java = """import org.seasar.doma.*;\n/** */\n@Entity @Table(name = \"x\") public class X<T> {\n  /** */ protected @Column(name = \"id\") T id;\n  /** Returns the id. */ public T getId() { return id; }\n  /** Sets the id. */ public void setId(T id) { this.id = id; }\n}\n"""
        kotlin = """import org.seasar.doma.*\n/** */\nopen @Entity @Table(name = \"x\") class X<T> {\n  /** */ @Column(name = \"id\") var id: T? = null\n}\n"""

        java_entity = parse_java(java, path="X.java").entity
        kotlin_entity = parse_kotlin(kotlin, path="X.kt").entity
        self.assertFalse(java_entity.generated_only)
        self.assertFalse(kotlin_entity.generated_only)
        self.assertIn("generic entity declaration", java_entity.unsupported_reasons)
        self.assertIn("generic entity declaration", kotlin_entity.unsupported_reasons)
        self.assertIn("non-template class modifiers", kotlin_entity.unsupported_reasons)

    def test_trailing_member_comments_never_classify_as_codegen_only(self) -> None:
        java = """import org.seasar.doma.*;\n/** */\n@Entity @Table(name = \"x\") public class X {\n  /** */ @Column(name = \"id\") public Long id; // handwritten note\n}\n"""
        kotlin = """import org.seasar.doma.*\n/** */\n@Entity @Table(name = \"x\") class X {\n  /** */ @Column(name = \"id\") var id: Long = -1L // handwritten note\n}\n"""

        java_entity = parse_java(java, path="X.java").entity
        kotlin_entity = parse_kotlin(kotlin, path="X.kt").entity
        self.assertFalse(java_entity.generated_only)
        self.assertFalse(kotlin_entity.generated_only)
        self.assertIn("non-template member comment: id", java_entity.unsupported_reasons)
        self.assertIn("non-template member comment: id", kotlin_entity.unsupported_reasons)

    def test_entity_naming_with_implicit_column_identity_fails_closed(self) -> None:
        java = """import org.seasar.doma.*;\n/** */\n@Entity(naming = NamingType.SNAKE_LOWER_CASE) @Table(name = \"x\") public class X {\n  /** */ public String firstName;\n}\n"""
        kotlin = """import org.seasar.doma.*\n/** */\n@Entity(naming = NamingType.SNAKE_LOWER_CASE) @Table(name = \"x\") class X {\n  /** */ var firstName: String? = null\n}\n"""

        for parsed in (parse_java(java, path="X.java"), parse_kotlin(kotlin, path="X.kt")):
            with self.subTest(language=parsed.entity.language):
                self.assertEqual("firstName", parsed.entity.properties[0].column)
                self.assertIn(
                    "implicit column identity under entity naming: firstName",
                    parsed.entity.unsupported_reasons,
                )
                self.assertFalse(parsed.entity.generated_only)

        empty_java = """import org.seasar.doma.*;\n@Entity @Table(name = \"x\") class X { @Column(name = \"\") String firstName; }\n"""
        empty_kotlin = """import org.seasar.doma.*\n@Entity @Table(name = \"x\") class X { @Column(name = \"\") var firstName: String? = null }\n"""
        self.assertEqual("firstName", parse_java(empty_java, path="X.java").entity.properties[0].column)
        self.assertEqual("firstName", parse_kotlin(empty_kotlin, path="X.kt").entity.properties[0].column)

    def test_compact_member_and_import_spans_never_escape_their_constructs(self) -> None:
        java = """package p; import org.seasar.doma.*; @Entity @Table(name = \"x\") class X { /** */ @Column(name = \"a\") String a; /** */ @Column(name = \"b\") String b; }"""
        kotlin = """package p; import org.seasar.doma.*; @Entity @Table(name = \"x\") class X { /** */ @Column(name = \"a\") var a: String? = null; /** */ @Column(name = \"b\") var b: String? = null; }"""

        for parsed in (parse_java(java, path="X.java"), parse_kotlin(kotlin, path="X.kt")):
            with self.subTest(language=parsed.entity.language):
                entity = parsed.entity
                self.assertEqual("import org.seasar.doma.*;", parsed.source[
                    entity.import_region.start:entity.import_region.end
                ].strip())
                first, second = entity.properties
                self.assertGreaterEqual(first.full_span.start, entity.class_body.start)
                self.assertLessEqual(second.full_span.end, entity.class_body.end)
                self.assertLessEqual(first.full_span.end, second.full_span.start)
                self.assertTrue(parsed.source[first.full_span.start:first.full_span.end].lstrip().startswith("/** */"))
                self.assertTrue(parsed.source[second.full_span.start:second.full_span.end].lstrip().startswith("/** */"))

    def test_kotlin_bodyless_entity_stops_at_semicolon_before_same_line_declaration(self) -> None:
        source = """import org.seasar.doma.*\n@Entity @Table(name = \"e\") class E; object H { /** */ var x: Long = -1L }\n"""

        entity = parse_kotlin(source, path="E.kt").entity
        self.assertEqual("E", entity.class_name)
        self.assertEqual((), entity.properties)
        self.assertEqual((), entity.methods)
        self.assertLessEqual(entity.class_body.end, source.index("object H"))
        self.assertFalse(entity.generated_only)


if __name__ == "__main__":
    unittest.main()
