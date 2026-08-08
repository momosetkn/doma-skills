"""Conservative, source-preserving parser for one top-level Java Doma entity."""
from __future__ import annotations

from collections import Counter
from typing import Iterable, Sequence

from .lexer import Token, lex_java
from .model import (
    AnnotationModel,
    EntityModel,
    MethodModel,
    ParsedEntity,
    PropertyModel,
    SourceSpan,
    TableIdentity,
)


TRIVIA = {"WHITESPACE", "LINE_COMMENT", "BLOCK_COMMENT", "JAVADOC"}
DOMA_ANNOTATIONS = {
    "Association", "Column", "Domain", "Embeddable", "Embedded", "Entity",
    "GeneratedValue", "Id", "Metamodel", "OriginalStates", "SequenceGenerator",
    "Table", "TableGenerator", "TenantId", "Transient", "Version",
}
CLASS_DOMA_ANNOTATIONS = {"org.seasar.doma.Entity", "org.seasar.doma.Table"}
TEMPLATE_PROPERTY_ANNOTATIONS = {
    "org.seasar.doma.Column", "org.seasar.doma.GeneratedValue", "org.seasar.doma.Id",
    "org.seasar.doma.OriginalStates", "org.seasar.doma.SequenceGenerator",
    "org.seasar.doma.TableGenerator", "org.seasar.doma.Version",
}
JAVA_MODIFIERS = {
    "abstract", "final", "native", "private", "protected", "public", "static",
    "strictfp", "synchronized", "transient", "volatile",
}
JAVA_KEYWORDS = JAVA_MODIFIERS | {
    "assert", "boolean", "break", "byte", "case", "catch", "char", "class",
    "const", "continue", "default", "do", "double", "else", "enum", "extends",
    "false", "finally", "float", "for", "goto", "if", "implements", "import",
    "instanceof", "int", "interface", "long", "new", "null", "package", "record",
    "return", "short", "super", "switch", "this", "throw", "throws", "true", "try",
    "void", "while",
}


class JavaParseError(ValueError):
    """Raised when the file has no identifiable top-level Doma type at all."""


def find_java_domain_declarations(source: str) -> tuple[str, ...]:
    """Return fully qualified project Domain types with unambiguous annotations."""
    all_tokens = lex_java(source)
    if any(token.kind == "ERROR" for token in all_tokens):
        return ()
    tokens = tuple(token for token in all_tokens if token.kind not in TRIVIA)
    imports, _ = _parse_imports(source, tokens)
    package_name = _parse_package(tokens)
    declarations: list[str] = []
    brace = paren = bracket = 0
    for index, token in enumerate(tokens):
        text = token.text
        if text in {"class", "record"} and brace == paren == bracket == 0:
            floor = _top_level_floor(tokens, index)
            annotations, _, reasons = _annotations_in_range(source, tokens, floor, index, imports)
            if not reasons and any(
                annotation.qualified_name == "org.seasar.doma.Domain" for annotation in annotations
            ):
                name_index = _next_identifier(tokens, index + 1)
                if name_index is not None:
                    simple_name = tokens[name_index].text
                    declarations.append((package_name + "." if package_name else "") + simple_name)
        if text == "(": paren += 1
        elif text == ")": paren = max(0, paren - 1)
        elif text == "[": bracket += 1
        elif text == "]": bracket = max(0, bracket - 1)
        elif text == "{": brace += 1
        elif text == "}": brace = max(0, brace - 1)
    return tuple(declarations)


def parse_java(
    source: str,
    path: str = "<memory>.java",
    domain_types: Iterable[str] = (),
) -> ParsedEntity:
    """Parse one top-level Doma entity and retain all uncertain syntax as findings."""
    domain_type_names = frozenset(domain_types)
    tokens = lex_java(source)
    significant = tuple(token for token in tokens if token.kind not in TRIVIA)
    imports, import_region = _parse_imports(source, significant)
    package_name = _parse_package(significant)
    reasons: list[str] = []
    if any(token.kind == "ERROR" for token in tokens):
        reasons.append("unmatched lexical construct")
    reasons.extend(_line_ending_reasons(source))

    candidates = _find_doma_types(source, significant, imports)
    if not candidates:
        raise JavaParseError("no top-level Doma entity or embeddable declaration")
    if len(candidates) > 1:
        reasons.append("multiple top-level Doma entities")
    candidate = candidates[0]
    reasons.extend(candidate["reasons"])

    kind_index = candidate["kind_index"]
    kind = significant[kind_index].text
    name_index = _next_identifier(significant, kind_index + 1)
    if name_index is None:
        raise JavaParseError("Doma type declaration has no class name")
    class_name = significant[name_index].text
    open_index = _find_header_open(significant, name_index + 1)
    if open_index is None:
        raise JavaParseError("Doma type declaration has no class body")
    close_index = _matching_index(significant, open_index, "{", "}")
    if close_index is None:
        close_index = len(significant)
        reasons.append("unmatched class body")
        class_body = SourceSpan(significant[open_index].span.end, len(source))
    else:
        class_body = SourceSpan(significant[open_index].span.end, significant[close_index].span.start)

    class_annotations = candidate["annotations"]
    class_header_tokens = _tokens_outside_annotations(
        significant[candidate["declaration_floor"]:kind_index], class_annotations
    )
    class_modifiers = tuple(
        token.text for token in class_header_tokens if token.kind == "IDENT"
    )
    if class_modifiers != ("public",):
        reasons.append("non-template class modifiers")
    table, identity_reasons = _table_identity(class_name, class_annotations)
    reasons.extend(identity_reasons)
    superclass, interfaces = _java_supertypes(significant, name_index + 1, open_index)
    if superclass:
        reasons.append("superclass: " + superclass)
    if interfaces:
        reasons.append("interfaces: " + ", ".join(interfaces))
    if kind == "record":
        reasons.append("java record")
    if name_index + 1 < open_index and significant[name_index + 1].text == "<":
        reasons.append("generic entity declaration")
    entity_naming = _has_non_default_entity_naming(class_annotations)

    custom_annotations: list[str] = []
    for annotation in class_annotations:
        if annotation.qualified_name not in CLASS_DOMA_ANNOTATIONS:
            _append_unique(custom_annotations, annotation.qualified_name)
            if annotation.qualified_name.startswith("lombok."):
                reasons.append("lombok annotation: " + annotation.qualified_name)
            elif annotation.qualified_name != "org.seasar.doma.Embeddable":
                reasons.append("custom annotation: " + annotation.qualified_name)

    properties: list[PropertyModel] = []
    raw_methods: list[dict[str, object]] = []
    field_metadata: dict[str, dict[str, object]] = {}
    member_floor = significant[open_index].span.end
    if close_index < len(significant):
        chunks = _member_chunks(significant, open_index + 1, close_index)
    else:
        chunks = _member_chunks(significant, open_index + 1, len(significant))
    for chunk_position, (chunk_start, chunk_end, terminator) in enumerate(chunks):
        chunk = significant[chunk_start:chunk_end]
        if not chunk:
            continue
        annotations, cursor, annotation_reasons = _leading_annotations(source, chunk, imports)
        reasons.extend(annotation_reasons)
        for annotation in annotations:
            if annotation.qualified_name not in TEMPLATE_PROPERTY_ANNOTATIONS:
                if annotation.qualified_name not in {
                    "org.seasar.doma.Association", "org.seasar.doma.Embedded",
                    "org.seasar.doma.TenantId", "org.seasar.doma.Transient",
                }:
                    _append_unique(custom_annotations, annotation.qualified_name)
                    reasons.append("custom annotation: " + annotation.qualified_name)
        core = chunk[cursor:]
        if not core:
            member_floor = chunk[-1].span.end
            continue
        full_start = _leading_comment_start(source, tokens, chunk[0].span.start, member_floor)
        next_boundary = class_body.end
        if chunk_position + 1 < len(chunks):
            next_chunk_start = chunks[chunk_position + 1][0]
            next_boundary = _leading_comment_start(
                source, tokens, significant[next_chunk_start].span.start, chunk[-1].span.end
            )
        full_end = min(_line_end(source, chunk[-1].span.end), next_boundary, class_body.end)

        inline_annotations, _, inline_reasons = _annotations_in_range(
            source, core, 0, len(core), imports
        )
        reasons.extend(inline_reasons)
        classification_core = _tokens_outside_annotations(core, inline_annotations)

        if _is_nested_type(classification_core):
            reasons.append("nested type or anonymous class")
            member_floor = chunk[-1].span.end
            continue
        if _is_method_chunk(classification_core):
            raw_methods.append({
                "tokens": classification_core,
                "span": SourceSpan(full_start, full_end),
                "terminator": terminator,
            })
            member_floor = chunk[-1].span.end
            continue
        if inline_annotations:
            annotations = annotations + inline_annotations
            core = classification_core
            for annotation in inline_annotations:
                if annotation.qualified_name not in TEMPLATE_PROPERTY_ANNOTATIONS and annotation.qualified_name not in {
                    "org.seasar.doma.Association", "org.seasar.doma.Embedded",
                    "org.seasar.doma.TenantId", "org.seasar.doma.Transient",
                }:
                    _append_unique(custom_annotations, annotation.qualified_name)
                    reasons.append("custom annotation: " + annotation.qualified_name)

        if _has_anonymous_class(core):
            reasons.append("anonymous class edit target")

        parsed_field = _parse_field(source, core, annotations, SourceSpan(full_start, full_end))
        if parsed_field is None:
            reasons.append("unrecognized class member")
            member_floor = chunk[-1].span.end
            continue
        prop, modifiers, initializer = parsed_field
        properties.append(prop)
        field_metadata[prop.name] = {
            "modifiers": modifiers,
            "documented": _is_codegen_property_doc(source[full_start:prop.declaration_span.start]),
            "initializer": initializer,
        }
        if initializer:
            reasons.append("field initializer: " + prop.name)
            if "new" in {token.text for token in core} and terminator == "block":
                reasons.append("nested type or anonymous class")
        if "static" in modifiers:
            reasons.append("static field: " + prop.name)
        if any(
            token.kind in {"LINE_COMMENT", "BLOCK_COMMENT", "JAVADOC"}
            and prop.declaration_span.start <= token.span.start < prop.full_span.end
            for token in tokens
        ):
            reasons.append("non-template member comment: " + prop.name)
        annotation_names = {annotation.qualified_name for annotation in prop.annotations}
        column_annotation = next(
            (annotation for annotation in prop.annotations
             if annotation.qualified_name == "org.seasar.doma.Column"), None
        )
        if column_annotation is not None:
            column_value = dict(column_annotation.arguments).get("name")
            if column_value is not None and _plain_string(column_value) is None:
                reasons.append("ambiguous @Column name: " + prop.name)
        if entity_naming and not _has_explicit_column_name(column_annotation):
            reasons.append("implicit column identity under entity naming: " + prop.name)
        if "org.seasar.doma.Transient" in annotation_names:
            reasons.append("transient property: " + prop.name)
        if "org.seasar.doma.Association" in annotation_names:
            reasons.append("association property: " + prop.name)
        if "org.seasar.doma.Embedded" in annotation_names:
            reasons.append("embedded property: " + prop.name)
        if "org.seasar.doma.TenantId" in annotation_names:
            reasons.append("tenant-id property: " + prop.name)
        if _is_domain_type(prop.type_name, imports, package_name, domain_type_names):
            reasons.append("domain-typed property: " + prop.name)
        member_floor = chunk[-1].span.end

    counts = Counter(prop.column for prop in properties)
    for column in sorted(column for column, count in counts.items() if count > 1):
        reasons.append("duplicate column mapping: " + column)

    methods: list[MethodModel] = []
    property_by_name = {prop.name: prop for prop in properties}
    for raw_method in raw_methods:
        method = _parse_method(source, raw_method["tokens"], raw_method["span"], property_by_name)
        methods.append(method)
        if method.generated_accessor_for is None:
            reasons.append("handwritten method: " + method.name)

    class_doc_start = _leading_comment_start(
        source, tokens, significant[candidate["annotation_start"]].span.start,
        _top_level_floor(significant, candidate["annotation_start"]),
    )
    class_documented = "/**" in source[class_doc_start:significant[kind_index].span.start]
    generated_only = _is_generated_only(
        source, properties, methods, field_metadata, class_annotations,
        class_documented, superclass, interfaces, custom_annotations, reasons,
    )
    model = EntityModel(
        path=path,
        language="java",
        package_name=package_name,
        class_name=class_name,
        table=table,
        properties=tuple(properties),
        imports=imports,
        methods=tuple(methods),
        superclass=superclass,
        interfaces=interfaces,
        custom_annotations=tuple(custom_annotations),
        import_region=import_region,
        class_body=class_body,
        generated_only=generated_only,
        unsupported_reasons=tuple(_unique(reasons)),
        line_ending="\r\n" if "\r\n" in source else "\n",
    )
    return ParsedEntity(source, model)


def _parse_package(tokens: Sequence[Token]) -> str:
    for index, token in enumerate(tokens):
        if token.text == "package":
            end = _find_text(tokens, ";", index + 1)
            if end is not None:
                return "".join(item.text for item in tokens[index + 1:end])
    return ""


def _parse_imports(source: str, tokens: Sequence[Token]) -> tuple[tuple[str, ...], SourceSpan | None]:
    imports: list[str] = []
    first: int | None = None
    last: int | None = None
    index = 0
    while index < len(tokens):
        if tokens[index].text != "import":
            index += 1
            continue
        end = _find_text(tokens, ";", index + 1)
        if end is None:
            break
        imports.append("".join(token.text for token in tokens[index + 1:end]))
        first = tokens[index].span.start if first is None else first
        last = tokens[end].span.end
        index = end + 1
    if first is None or last is None:
        return tuple(imports), None
    return tuple(imports), _bounded_line_region(source, first, last)


def _find_doma_types(source: str, tokens: Sequence[Token], imports: tuple[str, ...]) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    brace_depth = paren_depth = bracket_depth = 0
    for index, token in enumerate(tokens):
        if token.text in {"class", "record"} and brace_depth == paren_depth == bracket_depth == 0:
            floor = _top_level_floor(tokens, index)
            annotations, start, annotation_reasons = _annotations_in_range(source, tokens, floor, index, imports)
            names = {annotation.qualified_name for annotation in annotations}
            if "org.seasar.doma.Entity" in names or "org.seasar.doma.Embeddable" in names:
                if "org.seasar.doma.Embeddable" in names and "org.seasar.doma.Entity" not in names:
                    annotation_reasons.append("embeddable declaration")
                candidates.append({
                    "kind_index": index,
                    "declaration_floor": floor,
                    "annotation_start": start,
                    "annotations": annotations,
                    "reasons": annotation_reasons,
                })
        if token.text == "(":
            paren_depth += 1
        elif token.text == ")":
            paren_depth = max(0, paren_depth - 1)
        elif token.text == "[":
            bracket_depth += 1
        elif token.text == "]":
            bracket_depth = max(0, bracket_depth - 1)
        elif token.text == "{":
            brace_depth += 1
        elif token.text == "}":
            brace_depth = max(0, brace_depth - 1)
    return candidates


def _annotations_in_range(
    source: str, tokens: Sequence[Token], start: int, end: int, imports: tuple[str, ...]
) -> tuple[tuple[AnnotationModel, ...], int, list[str]]:
    annotations: list[AnnotationModel] = []
    reasons: list[str] = []
    first = end
    index = start
    while index < end:
        if tokens[index].text != "@":
            index += 1
            continue
        annotation, next_index, annotation_reasons = _parse_annotation(source, tokens, index, imports)
        annotations.append(annotation)
        reasons.extend(annotation_reasons)
        first = min(first, index)
        index = next_index
    return tuple(annotations), first, reasons


def _leading_annotations(
    source: str, tokens: Sequence[Token], imports: tuple[str, ...]
) -> tuple[tuple[AnnotationModel, ...], int, list[str]]:
    annotations: list[AnnotationModel] = []
    reasons: list[str] = []
    index = 0
    while index < len(tokens):
        if tokens[index].text == "@":
            annotation, index, annotation_reasons = _parse_annotation(source, tokens, index, imports)
            annotations.append(annotation)
            reasons.extend(annotation_reasons)
            continue
        break
    return tuple(annotations), index, reasons


def _parse_annotation(
    source: str, tokens: Sequence[Token], start: int, imports: tuple[str, ...]
) -> tuple[AnnotationModel, int, list[str]]:
    index = start + 1
    parts: list[str] = []
    while index < len(tokens):
        if tokens[index].kind != "IDENT":
            break
        parts.append(tokens[index].text)
        index += 1
        if index + 1 < len(tokens) and tokens[index].text == "." and tokens[index + 1].kind == "IDENT":
            parts.append(".")
            index += 1
            continue
        break
    raw_name = "".join(parts)
    qualified_name, ambiguous = _resolve_annotation(raw_name, imports)
    reasons = ["ambiguous annotation: " + raw_name] if ambiguous else []
    arguments: tuple[tuple[str, str], ...] = ()
    end = tokens[index - 1].span.end if index > start + 1 else tokens[start].span.end
    if index < len(tokens) and tokens[index].text == "(":
        close = _matching_index(tokens, index, "(", ")")
        if close is None:
            reasons.append("unmatched annotation: " + raw_name)
            close = len(tokens) - 1
        arguments = _annotation_arguments(source, tokens, index + 1, close)
        end = tokens[close].span.end
        index = close + 1
    return AnnotationModel(qualified_name, arguments, SourceSpan(tokens[start].span.start, end)), index, reasons


def _annotation_arguments(
    source: str, tokens: Sequence[Token], start: int, end: int
) -> tuple[tuple[str, str], ...]:
    pieces = _split_indices(tokens, start, end, ",")
    result: list[tuple[str, str]] = []
    for position, (piece_start, piece_end) in enumerate(pieces):
        if piece_start >= piece_end:
            continue
        equals = _top_level_text(tokens, piece_start, piece_end, "=")
        if equals is None:
            key = "value" if position == 0 else "$" + str(position + 1)
            value = source[tokens[piece_start].span.start:tokens[piece_end - 1].span.end].strip()
        else:
            key = source[tokens[piece_start].span.start:tokens[equals - 1].span.end].strip()
            value = source[tokens[equals + 1].span.start:tokens[piece_end - 1].span.end].strip()
        result.append((key, value))
    return tuple(result)


def _table_identity(
    class_name: str, annotations: Sequence[AnnotationModel]
) -> tuple[TableIdentity, list[str]]:
    table_annotation = next(
        (annotation for annotation in annotations if annotation.qualified_name == "org.seasar.doma.Table"), None
    )
    if table_annotation is None:
        return TableIdentity(None, None, class_name), ["implicit table identity"]
    values = dict(table_annotation.arguments)
    reasons: list[str] = []
    resolved: dict[str, str | None] = {"catalog": None, "schema": None, "name": class_name}
    for argument, target in (("catalog", "catalog"), ("schema", "schema"), ("name", "name")):
        if argument not in values:
            continue
        literal = _plain_string(values[argument])
        if literal is None:
            reasons.append("ambiguous @Table " + argument)
        else:
            resolved[target] = literal or None
    return TableIdentity(resolved["catalog"], resolved["schema"], resolved["name"] or class_name), reasons


def _java_supertypes(
    tokens: Sequence[Token], start: int, end: int
) -> tuple[str | None, tuple[str, ...]]:
    extends = _top_level_text(tokens, start, end, "extends")
    implements = _top_level_text(tokens, start, end, "implements")
    superclass: str | None = None
    if extends is not None:
        superclass_end = implements if implements is not None else end
        superclass = _type_text(tokens[extends + 1:superclass_end]) or None
    interfaces: tuple[str, ...] = ()
    if implements is not None:
        interfaces = tuple(
            _type_text(tokens[piece_start:piece_end])
            for piece_start, piece_end in _split_indices(tokens, implements + 1, end, ",")
            if piece_start < piece_end
        )
    return superclass, interfaces


def _member_chunks(
    tokens: Sequence[Token], start: int, end: int
) -> tuple[tuple[int, int, str], ...]:
    chunks: list[tuple[int, int, str]] = []
    index = start
    while index < end:
        chunk_start = index
        paren = bracket = 0
        equals_seen = False
        while index < end:
            text = tokens[index].text
            if text == "(":
                paren += 1
            elif text == ")":
                paren = max(0, paren - 1)
            elif text == "[":
                bracket += 1
            elif text == "]":
                bracket = max(0, bracket - 1)
            elif text == "=" and paren == 0 and bracket == 0:
                equals_seen = True
            elif text == ";" and paren == 0 and bracket == 0:
                chunks.append((chunk_start, index + 1, "semicolon"))
                index += 1
                break
            elif text == "{" and paren == 0 and bracket == 0:
                close = _matching_index(tokens, index, "{", "}")
                if close is None or close >= end:
                    chunks.append((chunk_start, end, "unmatched"))
                    return tuple(chunks)
                header = tokens[chunk_start:index]
                field_initializer = equals_seen and not _header_has_method_paren(header)
                if field_initializer:
                    index = close + 1
                    continue
                chunks.append((chunk_start, close + 1, "block"))
                index = close + 1
                if index < end and tokens[index].text == ";":
                    index += 1
                break
            index += 1
        else:
            chunks.append((chunk_start, end, "unmatched"))
            break
    return tuple(chunks)


def _parse_field(
    source: str,
    tokens: Sequence[Token],
    annotations: tuple[AnnotationModel, ...],
    full_span: SourceSpan,
) -> tuple[PropertyModel, tuple[str, ...], bool] | None:
    declaration_start = tokens[0].span.start
    end = len(tokens) - 1 if tokens and tokens[-1].text == ";" else len(tokens)
    equals = _top_level_text(tokens, 0, end, "=")
    left_end = equals if equals is not None else end
    if _top_level_text(tokens, 0, left_end, ",") is not None:
        return None
    index = 0
    modifiers: list[str] = []
    while index < left_end and tokens[index].text in JAVA_MODIFIERS:
        modifiers.append(tokens[index].text)
        index += 1
    identifiers = [position for position in range(index, left_end) if tokens[position].kind == "IDENT"]
    if len(identifiers) < 2:
        return None
    name_index = identifiers[-1]
    name = tokens[name_index].text
    suffix = tokens[name_index + 1:left_end]
    if any(token.text not in {"[", "]"} for token in suffix):
        return None
    type_name = _type_text(tuple(tokens[index:name_index]) + tuple(suffix))
    if not type_name:
        return None
    column = name
    column_annotation = next(
        (annotation for annotation in annotations if annotation.qualified_name == "org.seasar.doma.Column"), None
    )
    if column_annotation is not None:
        value = dict(column_annotation.arguments).get("name")
        literal = _plain_string(value) if value is not None else None
        if literal:
            column = literal
    declaration_end = tokens[-1].span.end
    prop = PropertyModel(
        name, column, type_name, None, annotations,
        SourceSpan(declaration_start, declaration_end), full_span, False,
    )
    return prop, tuple(modifiers), equals is not None


def _parse_method(
    source: str,
    tokens: Sequence[Token],
    span: SourceSpan,
    properties: dict[str, PropertyModel],
) -> MethodModel:
    open_paren = _top_level_text(tokens, 0, len(tokens), "(")
    if open_paren is None or open_paren == 0:
        name = "<initializer>"
        signature_end = tokens[0].span.end
    else:
        name = tokens[open_paren - 1].text
        brace = _top_level_text(tokens, open_paren + 1, len(tokens), "{")
        terminal = brace if brace is not None else len(tokens)
        if terminal and tokens[terminal - 1].text == ";":
            terminal -= 1
        signature_end = tokens[terminal - 1].span.end if terminal > 0 else tokens[-1].span.end
    signature = source[tokens[0].span.start:signature_end].strip()
    body_tokens: Sequence[Token] = ()
    brace = _top_level_text(tokens, 0, len(tokens), "{")
    if brace is not None:
        close = _matching_index(tokens, brace, "{", "}")
        if close is not None:
            body_tokens = tokens[brace + 1:close]
    referenced = tuple(_unique(
        token.text for token in body_tokens
        if token.kind == "IDENT" and token.text not in JAVA_KEYWORDS
    ))
    generated = _generated_accessor(name, tokens, body_tokens, properties, source[span.start:span.end])
    return MethodModel(name, signature, span, generated, referenced)


def _generated_accessor(
    name: str,
    tokens: Sequence[Token],
    body: Sequence[Token],
    properties: dict[str, PropertyModel],
    method_source: str,
) -> str | None:
    open_paren = _top_level_text(tokens, 0, len(tokens), "(")
    if open_paren is None:
        return None
    close_paren = _matching_index(tokens, open_paren, "(", ")")
    if close_paren is None:
        return None
    header = tokens[:open_paren]
    if len(header) < 3 or header[0].text != "public" or header[-1].text != name:
        return None
    for property_name, prop in properties.items():
        capitalized = property_name[:1].upper() + property_name[1:]
        if name == "get" + capitalized:
            if _type_text(header[1:-1]) != prop.type_name or tokens[open_paren + 1:close_paren]:
                continue
            if [token.text for token in body] == ["return", property_name, ";"]:
                if "Returns the " + property_name + "." in method_source:
                    return property_name
        if name == "set" + capitalized:
            if [token.text for token in header] != ["public", "void", name]:
                continue
            params = tokens[open_paren + 1:close_paren]
            if len(params) < 2 or params[-1].text != property_name:
                continue
            if _type_text(params[:-1]) != prop.type_name:
                continue
            if [token.text for token in body] == ["this", ".", property_name, "=", property_name, ";"]:
                if "Sets the " + property_name + "." in method_source:
                    return property_name
    return None


def _is_generated_only(
    source: str,
    properties: Sequence[PropertyModel],
    methods: Sequence[MethodModel],
    metadata: dict[str, dict[str, object]],
    class_annotations: Sequence[AnnotationModel],
    class_documented: bool,
    superclass: str | None,
    interfaces: tuple[str, ...],
    custom_annotations: Sequence[str],
    reasons: Sequence[str],
) -> bool:
    if reasons or superclass or interfaces or custom_annotations or not class_documented or not properties:
        return False
    if not any(annotation.qualified_name == "org.seasar.doma.Entity" for annotation in class_annotations):
        return False
    if any(not metadata[prop.name]["documented"] or metadata[prop.name]["initializer"] for prop in properties):
        return False
    if any(
        annotation.qualified_name not in TEMPLATE_PROPERTY_ANNOTATIONS
        for prop in properties for annotation in prop.annotations
    ):
        return False
    if any(method.generated_accessor_for is None for method in methods):
        return False
    if not methods:
        return all(metadata[prop.name]["modifiers"] == ("public",) for prop in properties)
    if any(metadata[prop.name]["modifiers"] for prop in properties):
        return False
    accessor_counts = Counter(method.generated_accessor_for for method in methods)
    return all(accessor_counts[prop.name] == 2 for prop in properties)


def _is_codegen_property_doc(prefix: str) -> bool:
    start = prefix.rfind("/**")
    if start < 0:
        return False
    end = prefix.find("*/", start + 3)
    if end < 0:
        return False
    doc = prefix[start:end + 2]
    return "\n" not in doc and "\r" not in doc


def _resolve_annotation(name: str, imports: tuple[str, ...]) -> tuple[str, bool]:
    if not name:
        return name, True
    first, separator, rest = name.partition(".")
    exact = [value for value in imports if not value.startswith("static") and value.rsplit(".", 1)[-1] == first]
    if len(exact) == 1:
        return exact[0] + (separator + rest if separator else ""), False
    if len(exact) > 1:
        return name, True
    if separator and first[:1].islower():
        return name, False
    wildcard = [value[:-2] + "." + name for value in imports if value.endswith(".*")]
    if len(wildcard) == 1:
        return wildcard[0], False
    if first in DOMA_ANNOTATIONS:
        return "org.seasar.doma." + name, True
    return name, bool(wildcard)


def _resolve_type(type_name: str, imports: tuple[str, ...]) -> str:
    base = type_name
    for marker in ("<", "["):
        if marker in base:
            base = base.split(marker, 1)[0]
    if "." in base:
        return base
    exact = [value for value in imports if value.rsplit(".", 1)[-1] == base]
    return exact[0] if len(exact) == 1 else base


def _has_non_default_entity_naming(annotations: Sequence[AnnotationModel]) -> bool:
    entity = next(
        (annotation for annotation in annotations
         if annotation.qualified_name == "org.seasar.doma.Entity"), None
    )
    if entity is None:
        return False
    value = dict(entity.arguments).get("naming")
    return value is not None and value not in {"NamingType.NONE", "org.seasar.doma.jdbc.entity.NamingType.NONE"}


def _has_explicit_column_name(annotation: AnnotationModel | None) -> bool:
    if annotation is None:
        return False
    value = dict(annotation.arguments).get("name")
    literal = _plain_string(value) if value is not None else None
    return bool(literal)


def _tokens_outside_annotations(
    tokens: Sequence[Token], annotations: Sequence[AnnotationModel]
) -> tuple[Token, ...]:
    return tuple(
        token for token in tokens
        if not any(
            annotation.span.start <= token.span.start and token.span.end <= annotation.span.end
            for annotation in annotations
        )
    )


def _is_domain_type(
    type_name: str,
    imports: tuple[str, ...],
    package_name: str,
    domain_types: frozenset[str],
) -> bool:
    resolved = _resolve_type(type_name, imports)
    candidates = {resolved}
    if "." not in resolved and package_name:
        candidates.add(package_name + "." + resolved)
    for imported in imports:
        if imported.endswith(".*"):
            candidates.add(imported[:-2] + "." + resolved)
    return not candidates.isdisjoint(domain_types)


def _plain_string(value: str | None) -> str | None:
    if value is None or len(value) < 2 or not (value.startswith('"') and value.endswith('"')):
        return None
    interior = value[1:-1]
    if "\\" in interior or "\n" in interior or "\r" in interior:
        return None
    return interior


def _line_ending_reasons(source: str) -> list[str]:
    if "\r\n" in source and "\n" in source.replace("\r\n", ""):
        return ["mixed line endings"]
    if "\r" in source.replace("\r\n", ""):
        return ["unsupported carriage return"]
    return []


def _leading_comment_start(
    source: str, all_tokens: Sequence[Token], position: int, floor: int
) -> int:
    newline = source.find("\n", floor, position)
    comment_floor = newline + 1 if newline >= 0 else floor
    comments = [
        token for token in all_tokens
        if comment_floor <= token.span.start < position
        and token.kind in {"JAVADOC", "BLOCK_COMMENT", "LINE_COMMENT"}
    ]
    if comments:
        line_start = _line_start(source, comments[0].span.start)
        return comments[0].span.start if line_start < floor else line_start
    line_start = _line_start(source, position)
    return position if line_start < floor else line_start


def _top_level_floor(tokens: Sequence[Token], index: int) -> int:
    floor = 0
    paren = bracket = brace = 0
    for position in range(index):
        text = tokens[position].text
        if text == "(":
            paren += 1
        elif text == ")":
            paren = max(0, paren - 1)
        elif text == "[":
            bracket += 1
        elif text == "]":
            bracket = max(0, bracket - 1)
        elif text == "{":
            brace += 1
        elif text == "}":
            brace = max(0, brace - 1)
            if paren == bracket == brace == 0:
                floor = position + 1
        elif text == ";" and paren == bracket == brace == 0:
            floor = position + 1
    return floor


def _find_header_open(tokens: Sequence[Token], start: int) -> int | None:
    paren = bracket = 0
    for index in range(start, len(tokens)):
        text = tokens[index].text
        if text == "(": paren += 1
        elif text == ")": paren = max(0, paren - 1)
        elif text == "[": bracket += 1
        elif text == "]": bracket = max(0, bracket - 1)
        elif text == "{" and paren == 0 and bracket == 0:
            return index
        elif text == ";" and paren == 0 and bracket == 0:
            return None
    return None


def _is_nested_type(tokens: Sequence[Token]) -> bool:
    return any(token.text in {"class", "record", "interface", "enum"} for token in tokens[:8])


def _is_method_chunk(tokens: Sequence[Token]) -> bool:
    equals = _top_level_text(tokens, 0, len(tokens), "=")
    paren = _top_level_text(tokens, 0, len(tokens), "(")
    return paren is not None and (equals is None or paren < equals)


def _has_anonymous_class(tokens: Sequence[Token]) -> bool:
    equals = _top_level_text(tokens, 0, len(tokens), "=")
    if equals is None:
        return False
    for index in range(equals + 1, len(tokens)):
        if tokens[index].text != "new":
            continue
        open_paren = next((position for position in range(index + 1, len(tokens)) if tokens[position].text == "("), None)
        if open_paren is None:
            continue
        close_paren = _matching_index(tokens, open_paren, "(", ")")
        if close_paren is not None and close_paren + 1 < len(tokens) and tokens[close_paren + 1].text == "{":
            return True
    return False


def _header_has_method_paren(tokens: Sequence[Token]) -> bool:
    equals = _top_level_text(tokens, 0, len(tokens), "=")
    paren = _top_level_text(tokens, 0, len(tokens), "(")
    return paren is not None and (equals is None or paren < equals)


def _type_text(tokens: Sequence[Token]) -> str:
    return "".join(token.text for token in tokens)


def _matching_index(
    tokens: Sequence[Token], start: int, opener: str, closer: str
) -> int | None:
    if start >= len(tokens) or tokens[start].text != opener:
        return None
    depth = 0
    for index in range(start, len(tokens)):
        if tokens[index].text == opener:
            depth += 1
        elif tokens[index].text == closer:
            depth -= 1
            if depth == 0:
                return index
    return None


def _top_level_text(
    tokens: Sequence[Token], start: int, end: int, wanted: str
) -> int | None:
    paren = bracket = brace = angle = 0
    for index in range(start, end):
        text = tokens[index].text
        if text == wanted and paren == bracket == brace == angle == 0:
            return index
        if text == "(": paren += 1
        elif text == ")": paren = max(0, paren - 1)
        elif text == "[": bracket += 1
        elif text == "]": bracket = max(0, bracket - 1)
        elif text == "{": brace += 1
        elif text == "}": brace = max(0, brace - 1)
        elif text == "<": angle += 1
        elif text == ">": angle = max(0, angle - 1)
    return None


def _split_indices(
    tokens: Sequence[Token], start: int, end: int, delimiter: str
) -> tuple[tuple[int, int], ...]:
    pieces: list[tuple[int, int]] = []
    piece_start = start
    paren = bracket = brace = angle = 0
    for index in range(start, end):
        text = tokens[index].text
        if text == delimiter and paren == bracket == brace == angle == 0:
            pieces.append((piece_start, index))
            piece_start = index + 1
            continue
        if text == "(": paren += 1
        elif text == ")": paren = max(0, paren - 1)
        elif text == "[": bracket += 1
        elif text == "]": bracket = max(0, bracket - 1)
        elif text == "{": brace += 1
        elif text == "}": brace = max(0, brace - 1)
        elif text == "<": angle += 1
        elif text == ">": angle = max(0, angle - 1)
    pieces.append((piece_start, end))
    return tuple(pieces)


def _find_text(tokens: Sequence[Token], text: str, start: int) -> int | None:
    for index in range(start, len(tokens)):
        if tokens[index].text == text:
            return index
    return None


def _next_identifier(tokens: Sequence[Token], start: int) -> int | None:
    for index in range(start, len(tokens)):
        if tokens[index].kind == "IDENT":
            return index
    return None


def _line_start(source: str, position: int) -> int:
    newline = source.rfind("\n", 0, position)
    return newline + 1


def _line_end(source: str, position: int) -> int:
    newline = source.find("\n", position)
    return len(source) if newline < 0 else newline + 1


def _bounded_line_region(source: str, start: int, end: int) -> SourceSpan:
    line_start = _line_start(source, start)
    region_start = start if source[line_start:start].strip() else line_start
    line_end = _line_end(source, end)
    region_end = end if source[end:line_end].strip() else line_end
    return SourceSpan(region_start, region_end)


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        _append_unique(result, value)
    return result
