"""Conservative, source-preserving parser for one top-level Kotlin Doma entity."""
from __future__ import annotations

from collections import Counter
from typing import Iterable, Sequence

from .java_parser import (
    DOMA_ANNOTATIONS,
    TEMPLATE_PROPERTY_ANNOTATIONS,
    _line_end,
    _line_ending_reasons,
    _line_start,
    _matching_index,
    _plain_string,
    _split_indices,
    _top_level_floor,
    _top_level_text,
    _type_text,
    _unique,
)
from .lexer import Token, lex_kotlin
from .model import (
    AnnotationModel,
    EntityModel,
    MethodModel,
    ParsedEntity,
    PropertyModel,
    SourceSpan,
    TableIdentity,
)


TRIVIA = {"WHITESPACE", "LINE_COMMENT", "BLOCK_COMMENT", "KDOC"}
CLASS_DOMA_ANNOTATIONS = {"org.seasar.doma.Entity", "org.seasar.doma.Table"}
KOTLIN_MODIFIERS = {
    "abstract", "actual", "annotation", "companion", "const", "crossinline", "data",
    "expect", "external", "final", "infix", "inline", "inner", "internal", "lateinit",
    "noinline", "open", "operator", "out", "override", "private", "protected", "public",
    "reified", "sealed", "suspend", "tailrec", "value", "vararg",
}
KOTLIN_KEYWORDS = KOTLIN_MODIFIERS | {
    "as", "break", "by", "catch", "class", "constructor", "continue", "delegate", "do",
    "dynamic", "else", "false", "field", "file", "finally", "for", "fun", "get", "if",
    "import", "in", "init", "interface", "is", "it", "null", "object", "package", "param",
    "property", "receiver", "return", "set", "setparam", "super", "this", "throw", "true",
    "try", "typealias", "typeof", "val", "var", "when", "where", "while",
}
KOTLIN_REFERENCE_KEYWORDS = KOTLIN_KEYWORDS - {"value"}


class KotlinParseError(ValueError):
    """Raised when the file has no identifiable top-level Doma type at all."""


def find_kotlin_domain_declarations(source: str) -> tuple[str, ...]:
    """Return fully qualified project Domain types with unambiguous annotations."""
    all_tokens = lex_kotlin(source)
    if any(token.kind == "ERROR" for token in all_tokens):
        return ()
    tokens = tuple(token for token in all_tokens if token.kind not in TRIVIA)
    imports, _ = _parse_imports(source, tokens)
    package_name = _parse_package(source, tokens)
    declarations: list[str] = []
    brace = paren = bracket = 0
    for index, token in enumerate(tokens):
        text = token.text
        if text == "class" and brace == paren == bracket == 0:
            floor = _top_level_floor(tokens, index)
            annotations, _, reasons = _annotations_in_range(source, tokens, floor, index, imports)
            if not reasons and any(
                annotation.qualified_name == "org.seasar.doma.Domain" for annotation in annotations
            ):
                name_index = _next_identifier(tokens, index + 1)
                if name_index is not None:
                    simple_name = _identifier(tokens[name_index].text)
                    declarations.append((package_name + "." if package_name else "") + simple_name)
        if text == "(": paren += 1
        elif text == ")": paren = max(0, paren - 1)
        elif text == "[": bracket += 1
        elif text == "]": bracket = max(0, bracket - 1)
        elif text == "{": brace += 1
        elif text == "}": brace = max(0, brace - 1)
    return tuple(declarations)


def parse_kotlin(
    source: str,
    path: str = "<memory>.kt",
    domain_types: Iterable[str] = (),
) -> ParsedEntity:
    """Parse one top-level Doma entity and fail closed on edit-sensitive syntax."""
    domain_type_names = frozenset(domain_types)
    tokens = lex_kotlin(source)
    significant = tuple(token for token in tokens if token.kind not in TRIVIA)
    imports, import_region = _parse_imports(source, significant)
    package_name = _parse_package(source, significant)
    reasons: list[str] = []
    if any(token.kind == "ERROR" for token in tokens):
        reasons.append("unmatched lexical construct")
    reasons.extend(_line_ending_reasons(source))

    candidates = _find_doma_types(source, significant, imports)
    if not candidates:
        raise KotlinParseError("no top-level Doma entity or embeddable declaration")
    if len(candidates) > 1:
        reasons.append("multiple top-level Doma entities")
    candidate = candidates[0]
    reasons.extend(candidate["reasons"])
    class_index = candidate["class_index"]
    name_index = _next_identifier(significant, class_index + 1)
    if name_index is None:
        raise KotlinParseError("Doma type declaration has no class name")
    class_name = _identifier(significant[name_index].text)

    open_index = _find_body_open(source, significant, name_index + 1)
    if open_index is None:
        header_end = _line_statement_end(source, significant, name_index, len(significant))
        close_index = None
        body_span = SourceSpan(significant[header_end - 1].span.end, significant[header_end - 1].span.end)
    else:
        header_end = open_index
        close_index = _matching_index(significant, open_index, "{", "}")
        if close_index is None:
            reasons.append("unmatched class body")
            close_index = len(significant)
            body_span = SourceSpan(significant[open_index].span.end, len(source))
        else:
            body_span = SourceSpan(significant[open_index].span.end, significant[close_index].span.start)

    class_annotations = candidate["annotations"]
    class_header_tokens = _tokens_outside_annotations(
        significant[candidate["declaration_floor"]:class_index], class_annotations
    )
    class_modifiers = tuple(
        token.text for token in class_header_tokens if token.kind == "IDENT"
    )
    if class_modifiers:
        reasons.append("non-template class modifiers")
    table, identity_reasons = _table_identity(class_name, class_annotations)
    reasons.extend(identity_reasons)
    is_data = candidate["data"]
    if is_data:
        reasons.append("kotlin data class")
    if name_index + 1 < header_end and significant[name_index + 1].text == "<":
        reasons.append("generic entity declaration")
    entity_naming = _has_non_default_entity_naming(class_annotations)

    custom_annotations: list[str] = []
    for annotation in class_annotations:
        if annotation.qualified_name not in CLASS_DOMA_ANNOTATIONS:
            _append_unique(custom_annotations, annotation.qualified_name)
            if annotation.qualified_name != "org.seasar.doma.Embeddable":
                reasons.append("custom annotation: " + annotation.qualified_name)

    constructor_open = _primary_constructor_open(significant, name_index + 1, header_end)
    constructor_close: int | None = None
    properties: list[PropertyModel] = []
    property_metadata: dict[str, dict[str, object]] = {}
    if constructor_open is not None:
        constructor_close = _matching_index(significant, constructor_open, "(", ")")
        if constructor_close is None or constructor_close > header_end:
            reasons.append("unmatched primary constructor")
        else:
            constructor_properties, constructor_reasons, constructor_custom = _parse_constructor_properties(
                source, significant, constructor_open + 1, constructor_close, imports
            )
            properties.extend(constructor_properties)
            reasons.extend(constructor_reasons)
            for annotation in constructor_custom:
                _append_unique(custom_annotations, annotation)
            for prop in constructor_properties:
                property_metadata[prop.name] = {
                    "kind": "constructor", "modifiers": (),
                    "documented": False, "generated_default": False,
                }

    super_start = constructor_close + 1 if constructor_close is not None else name_index + 1
    superclass, interfaces = _kotlin_supertypes(significant, super_start, header_end)
    if superclass:
        reasons.append("superclass: " + superclass)
    if interfaces:
        reasons.append("interfaces: " + ", ".join(interfaces))

    methods: list[MethodModel] = []
    if open_index is not None:
        body_end = close_index if close_index is not None else len(significant)
        member_floor = significant[open_index].span.end
        chunks = _member_chunks(
            source, significant, open_index + 1, body_end, imports
        )
        for chunk_position, (chunk_start, base_end, chunk_end, kind) in enumerate(chunks):
            chunk = significant[chunk_start:chunk_end]
            annotations, cursor, annotation_reasons = _leading_annotations(source, chunk, imports)
            reasons.extend(annotation_reasons)
            core = chunk[cursor:]
            if not core:
                member_floor = chunk[-1].span.end
                continue
            full_start = _leading_comment_start(source, tokens, chunk[0].span.start, member_floor)
            next_boundary = body_span.end
            if chunk_position + 1 < len(chunks):
                next_chunk_start = chunks[chunk_position + 1][0]
                next_boundary = _leading_comment_start(
                    source, tokens, significant[next_chunk_start].span.start, chunk[-1].span.end
                )
            full_end = min(_line_end(source, chunk[-1].span.end), next_boundary, body_span.end)
            full_span = SourceSpan(full_start, full_end)
            for annotation in annotations:
                if annotation.qualified_name not in TEMPLATE_PROPERTY_ANNOTATIONS and annotation.qualified_name not in {
                    "org.seasar.doma.Association", "org.seasar.doma.Embedded",
                    "org.seasar.doma.TenantId", "org.seasar.doma.Transient",
                }:
                    _append_unique(custom_annotations, annotation.qualified_name)
                    reasons.append("custom annotation: " + annotation.qualified_name)

            if kind == "property":
                base_count = base_end - chunk_start
                base_tokens = chunk[:base_count]
                base_annotations, base_cursor, _ = _leading_annotations(source, base_tokens, imports)
                property_tokens = base_tokens[base_cursor:]
                inline_annotations, _, inline_reasons = _annotations_in_range(
                    source, property_tokens, 0, len(property_tokens), imports
                )
                reasons.extend(inline_reasons)
                if inline_annotations:
                    property_tokens = _tokens_outside_annotations(property_tokens, inline_annotations)
                    base_annotations = base_annotations + inline_annotations
                    for annotation in inline_annotations:
                        if annotation.qualified_name not in TEMPLATE_PROPERTY_ANNOTATIONS and annotation.qualified_name not in {
                            "org.seasar.doma.Association", "org.seasar.doma.Embedded",
                            "org.seasar.doma.TenantId", "org.seasar.doma.Transient",
                        }:
                            _append_unique(custom_annotations, annotation.qualified_name)
                            reasons.append("custom annotation: " + annotation.qualified_name)
                if _is_destructuring(property_tokens):
                    reasons.append("kotlin destructuring declaration")
                    parsed_property = None
                else:
                    parsed_property = _parse_body_property(
                        source, property_tokens, base_annotations, full_span
                    )
                if parsed_property is None:
                    if not _is_destructuring(property_tokens):
                        reasons.append("unrecognized body property")
                else:
                    prop, declaration_kind, initializer, delegated, modifiers = parsed_property
                    properties.append(prop)
                    generated_default = _is_codegen_default(prop.type_name, prop.nullable, initializer)
                    property_metadata[prop.name] = {
                        "kind": declaration_kind,
                        "modifiers": modifiers,
                        "documented": _is_codegen_property_doc(source[full_start:prop.declaration_span.start]),
                        "generated_default": generated_default,
                    }
                    if delegated:
                        reasons.append("delegated property: " + prop.name)
                    elif not generated_default:
                        reasons.append("handwritten initializer: " + prop.name)
                    if any(
                        token.kind in {"LINE_COMMENT", "BLOCK_COMMENT", "KDOC"}
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
                    if chunk_end > base_end:
                        reasons.append("custom accessor: " + prop.name)
                        methods.extend(_parse_accessors(source, significant[base_end:chunk_end], prop.name))
            elif kind == "function":
                method = _parse_function(source, core, full_span)
                methods.append(method)
                reasons.append("handwritten method: " + method.name)
            elif kind == "initializer":
                method = _parse_initializer(source, core, full_span)
                methods.append(method)
                reasons.append("initializer block")
            elif kind == "constructor":
                method = _parse_secondary_constructor(source, core, full_span)
                methods.append(method)
                reasons.append("complex constructor change")
            elif kind == "nested":
                reasons.append("nested type or object")
            else:
                reasons.append("unrecognized class member")
            member_floor = chunk[-1].span.end

    counts = Counter(prop.column for prop in properties)
    for column in sorted(column for column, count in counts.items() if count > 1):
        reasons.append("duplicate column mapping: " + column)

    class_doc_start = _leading_comment_start(
        source, tokens, significant[candidate["annotation_start"]].span.start,
        _top_level_floor(significant, candidate["annotation_start"]),
    )
    class_documented = "/**" in source[class_doc_start:significant[class_index].span.start]
    generated_only = _is_generated_only(
        properties, methods, property_metadata, class_annotations, class_documented,
        superclass, interfaces, custom_annotations, reasons,
    )
    model = EntityModel(
        path=path,
        language="kotlin",
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
        class_body=body_span,
        generated_only=generated_only,
        unsupported_reasons=tuple(_unique(reasons)),
        line_ending="\r\n" if "\r\n" in source else "\n",
    )
    return ParsedEntity(source, model)


def _parse_package(source: str, tokens: Sequence[Token]) -> str:
    for index, token in enumerate(tokens):
        if token.text == "package":
            end = _line_statement_end(source, tokens, index + 1, len(tokens))
            return "".join(item.text for item in tokens[index + 1:end] if item.text != ";")
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
        end = _line_statement_end(source, tokens, index + 1, len(tokens))
        statement = tokens[index + 1:end]
        alias = next((position for position, token in enumerate(statement) if token.text == "as"), None)
        if alias is None:
            value = "".join(token.text for token in statement if token.text != ";")
        else:
            value = "".join(token.text for token in statement[:alias]) + " as " + "".join(
                token.text for token in statement[alias + 1:] if token.text != ";"
            )
        imports.append(value)
        first = tokens[index].span.start if first is None else first
        last = statement[-1].span.end if statement else tokens[index].span.end
        index = end
    if first is None or last is None:
        return tuple(imports), None
    return tuple(imports), _bounded_line_region(source, first, last)


def _find_doma_types(source: str, tokens: Sequence[Token], imports: tuple[str, ...]) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    brace = paren = bracket = 0
    for index, token in enumerate(tokens):
        text = token.text
        if text == "class" and brace == paren == bracket == 0:
            floor = _top_level_floor(tokens, index)
            annotations, start, annotation_reasons = _annotations_in_range(source, tokens, floor, index, imports)
            names = {annotation.qualified_name for annotation in annotations}
            if "org.seasar.doma.Entity" in names or "org.seasar.doma.Embeddable" in names:
                declaration_floor = start
                while declaration_floor > floor and tokens[declaration_floor - 1].text in KOTLIN_MODIFIERS:
                    declaration_floor -= 1
                if "org.seasar.doma.Embeddable" in names and "org.seasar.doma.Entity" not in names:
                    annotation_reasons.append("embeddable declaration")
                candidates.append({
                    "class_index": index,
                    "declaration_floor": declaration_floor,
                    "annotation_start": start,
                    "annotations": annotations,
                    "reasons": annotation_reasons,
                    "data": any(
                        item.text == "data"
                        for item in _tokens_outside_annotations(tokens[declaration_floor:index], annotations)
                    ),
                })
        if text == "(": paren += 1
        elif text == ")": paren = max(0, paren - 1)
        elif text == "[": bracket += 1
        elif text == "]": bracket = max(0, bracket - 1)
        elif text == "{": brace += 1
        elif text == "}": brace = max(0, brace - 1)
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
    while index < len(tokens) and tokens[index].text == "@":
        annotation, index, annotation_reasons = _parse_annotation(source, tokens, index, imports)
        annotations.append(annotation)
        reasons.extend(annotation_reasons)
    return tuple(annotations), index, reasons


def _parse_annotation(
    source: str, tokens: Sequence[Token], start: int, imports: tuple[str, ...]
) -> tuple[AnnotationModel, int, list[str]]:
    index = start + 1
    use_site: str | None = None
    if index + 1 < len(tokens) and tokens[index].kind == "IDENT" and tokens[index + 1].text == ":":
        use_site = tokens[index].text
        index += 2
    parts: list[str] = []
    while index < len(tokens):
        if tokens[index].kind != "IDENT":
            break
        parts.append(_identifier(tokens[index].text))
        index += 1
        if index + 1 < len(tokens) and tokens[index].text == "." and tokens[index + 1].kind == "IDENT":
            parts.append(".")
            index += 1
            continue
        break
    raw_name = "".join(parts)
    qualified_name, ambiguous = _resolve_annotation(raw_name, imports)
    reasons = ["ambiguous annotation: " + raw_name] if ambiguous else []
    if use_site is not None:
        reasons.append("annotation use-site target: " + use_site)
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
    result: list[tuple[str, str]] = []
    for position, (piece_start, piece_end) in enumerate(_split_indices(tokens, start, end, ",")):
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


def _parse_constructor_properties(
    source: str,
    tokens: Sequence[Token],
    start: int,
    end: int,
    imports: tuple[str, ...],
) -> tuple[list[PropertyModel], list[str], list[str]]:
    properties: list[PropertyModel] = []
    reasons: list[str] = []
    custom: list[str] = []
    for piece_start, piece_end in _split_indices(tokens, start, end, ","):
        if piece_start >= piece_end:
            continue
        piece = tokens[piece_start:piece_end]
        annotations, cursor, annotation_reasons = _leading_annotations(source, piece, imports)
        reasons.extend(annotation_reasons)
        declaration_index = next(
            (index for index in range(cursor, len(piece)) if piece[index].text in {"val", "var"}), None
        )
        if declaration_index is None:
            reasons.append("complex primary constructor")
            continue
        property_tokens = piece[declaration_index:]
        inline_annotations, _, inline_reasons = _annotations_in_range(
            source, property_tokens, 0, len(property_tokens), imports
        )
        reasons.extend(inline_reasons)
        if inline_annotations:
            annotations = annotations + inline_annotations
            property_tokens = _tokens_outside_annotations(property_tokens, inline_annotations)
        prop = _parse_kotlin_property(source, property_tokens, annotations,
                                      SourceSpan(piece[0].span.start, piece[-1].span.end), True)
        if prop is None:
            reasons.append("complex primary constructor")
            continue
        property_model, _, initializer, delegated, _ = prop
        properties.append(property_model)
        reasons.append("kotlin primary-constructor property: " + property_model.name)
        if initializer or delegated:
            reasons.append("complex constructor change: " + property_model.name)
        annotation_names = {annotation.qualified_name for annotation in annotations}
        column_annotation = next(
            (annotation for annotation in annotations
             if annotation.qualified_name == "org.seasar.doma.Column"), None
        )
        if column_annotation is not None:
            column_value = dict(column_annotation.arguments).get("name")
            if column_value is not None and _plain_string(column_value) is None:
                reasons.append("ambiguous @Column name: " + property_model.name)
        if "org.seasar.doma.TenantId" in annotation_names:
            reasons.append("tenant-id property: " + property_model.name)
        for annotation in annotations:
            if annotation.qualified_name not in TEMPLATE_PROPERTY_ANNOTATIONS and annotation.qualified_name not in {
                "org.seasar.doma.Association", "org.seasar.doma.Embedded",
                "org.seasar.doma.TenantId", "org.seasar.doma.Transient",
            }:
                _append_unique(custom, annotation.qualified_name)
                reasons.append("custom annotation: " + annotation.qualified_name)
    return properties, reasons, custom


def _parse_body_property(
    source: str,
    tokens: Sequence[Token],
    annotations: tuple[AnnotationModel, ...],
    full_span: SourceSpan,
) -> tuple[PropertyModel, str, str | None, bool, tuple[str, ...]] | None:
    return _parse_kotlin_property(source, tokens, annotations, full_span, False)


def _is_destructuring(tokens: Sequence[Token]) -> bool:
    declaration = next((index for index, token in enumerate(tokens) if token.text in {"val", "var"}), None)
    return declaration is not None and declaration + 1 < len(tokens) and tokens[declaration + 1].text == "("


def _parse_kotlin_property(
    source: str,
    tokens: Sequence[Token],
    annotations: tuple[AnnotationModel, ...],
    full_span: SourceSpan,
    constructor: bool,
) -> tuple[PropertyModel, str, str | None, bool, tuple[str, ...]] | None:
    declaration = next((index for index, token in enumerate(tokens) if token.text in {"val", "var"}), None)
    if declaration is None or declaration + 1 >= len(tokens):
        return None
    kind = tokens[declaration].text
    modifiers = tuple(token.text for token in tokens[:declaration] if token.kind == "IDENT")
    name_index = _next_identifier(tokens, declaration + 1)
    if name_index is None:
        return None
    name = _identifier(tokens[name_index].text)
    colon = _top_level_text(tokens, name_index + 1, len(tokens), ":")
    if colon is None:
        return None
    equals = _top_level_text(tokens, colon + 1, len(tokens), "=")
    delegated_at = _top_level_text(tokens, colon + 1, len(tokens), "by")
    type_end_candidates = [index for index in (equals, delegated_at) if index is not None]
    type_end = min(type_end_candidates) if type_end_candidates else len(tokens)
    type_tokens = list(tokens[colon + 1:type_end])
    nullable = bool(type_tokens and type_tokens[-1].text == "?")
    if nullable:
        type_tokens.pop()
    type_name = _type_text(type_tokens)
    if not type_name:
        return None
    initializer: str | None = None
    value_at = delegated_at if delegated_at is not None else equals
    if value_at is not None and value_at + 1 < len(tokens):
        initializer = source[tokens[value_at + 1].span.start:tokens[-1].span.end].strip()
    column = name
    column_annotation = next(
        (annotation for annotation in annotations if annotation.qualified_name == "org.seasar.doma.Column"), None
    )
    if column_annotation is not None:
        value = dict(column_annotation.arguments).get("name")
        literal = _plain_string(value) if value is not None else None
        if literal:
            column = literal
    model = PropertyModel(
        name=name,
        column=column,
        type_name=type_name,
        nullable=nullable,
        annotations=annotations,
        declaration_span=SourceSpan(tokens[0].span.start, tokens[-1].span.end),
        full_span=full_span,
        constructor_property=constructor,
    )
    return model, kind, initializer, delegated_at is not None, modifiers


def _member_chunks(
    source: str,
    tokens: Sequence[Token],
    start: int,
    end: int,
    imports: tuple[str, ...],
) -> tuple[tuple[int, int, int, str], ...]:
    chunks: list[tuple[int, int, int, str]] = []
    index = start
    while index < end:
        chunk_start = index
        cursor = index
        while cursor < end:
            if tokens[cursor].text == "@":
                _, cursor, _ = _parse_annotation(source, tokens, cursor, imports)
            elif tokens[cursor].text in KOTLIN_MODIFIERS:
                cursor += 1
            else:
                break
        if cursor >= end:
            chunks.append((chunk_start, end, end, "unknown"))
            break
        text = tokens[cursor].text
        if text in {"val", "var"}:
            base_end = _line_statement_end(source, tokens, cursor, end)
            chunk_end = base_end
            while chunk_end < end and tokens[chunk_end].text in {"get", "set"}:
                chunk_end = _accessor_end(source, tokens, chunk_end, end)
            chunks.append((chunk_start, base_end, chunk_end, "property"))
            index = chunk_end
        elif text == "fun":
            chunk_end = _declaration_end(source, tokens, cursor, end)
            chunks.append((chunk_start, chunk_end, chunk_end, "function"))
            index = chunk_end
        elif text == "init":
            chunk_end = _declaration_end(source, tokens, cursor, end)
            chunks.append((chunk_start, chunk_end, chunk_end, "initializer"))
            index = chunk_end
        elif text == "constructor":
            chunk_end = _declaration_end(source, tokens, cursor, end)
            chunks.append((chunk_start, chunk_end, chunk_end, "constructor"))
            index = chunk_end
        elif text in {"class", "interface", "object"}:
            chunk_end = _declaration_end(source, tokens, cursor, end)
            chunks.append((chunk_start, chunk_end, chunk_end, "nested"))
            index = chunk_end
        else:
            chunk_end = _line_statement_end(source, tokens, cursor, end)
            chunks.append((chunk_start, chunk_end, chunk_end, "unknown"))
            index = chunk_end
    return tuple(chunks)


def _line_statement_end(source: str, tokens: Sequence[Token], start: int, end: int) -> int:
    paren = bracket = brace = 0
    previous = start
    for index in range(start, end):
        if index > start and paren == bracket == brace == 0:
            gap = source[tokens[previous].span.end:tokens[index].span.start]
            if "\n" in gap and tokens[previous].text not in {".", "=", ",", ":", "?"}:
                return index
        text = tokens[index].text
        if text == "(": paren += 1
        elif text == ")": paren = max(0, paren - 1)
        elif text == "[": bracket += 1
        elif text == "]": bracket = max(0, bracket - 1)
        elif text == "{": brace += 1
        elif text == "}": brace = max(0, brace - 1)
        elif text == ";" and paren == bracket == brace == 0:
            return index + 1
        previous = index
    return end


def _declaration_end(source: str, tokens: Sequence[Token], start: int, end: int) -> int:
    equals = _top_level_text(tokens, start, end, "=")
    brace = _top_level_text(tokens, start, end, "{")
    if brace is not None and (equals is None or brace > equals or tokens[start].text == "init"):
        close = _matching_index(tokens, brace, "{", "}")
        return end if close is None or close >= end else close + 1
    return _line_statement_end(source, tokens, start, end)


def _accessor_end(source: str, tokens: Sequence[Token], start: int, end: int) -> int:
    return _line_statement_end(source, tokens, start, end)


def _parse_function(source: str, tokens: Sequence[Token], span: SourceSpan) -> MethodModel:
    open_paren = _top_level_text(tokens, 0, len(tokens), "(")
    name = "<function>"
    if open_paren is not None:
        identifiers = [token for token in tokens[:open_paren] if token.kind == "IDENT" and token.text != "fun"]
        if identifiers:
            name = _identifier(identifiers[-1].text)
    brace = _top_level_text(tokens, 0, len(tokens), "{")
    equals = _top_level_text(tokens, 0, len(tokens), "=")
    signature_end = min(index for index in (brace, equals, len(tokens)) if index is not None)
    signature = source[tokens[0].span.start:tokens[signature_end - 1].span.end].strip()
    body = tokens[brace + 1:_matching_index(tokens, brace, "{", "}")] if brace is not None else tokens[(equals + 1 if equals is not None else len(tokens)):]
    referenced = _referenced_names(body)
    return MethodModel(name, signature, span, None, referenced)


def _parse_initializer(source: str, tokens: Sequence[Token], span: SourceSpan) -> MethodModel:
    brace = _top_level_text(tokens, 0, len(tokens), "{")
    if brace is None:
        body: Sequence[Token] = ()
    else:
        close = _matching_index(tokens, brace, "{", "}")
        body = tokens[brace + 1:close] if close is not None else tokens[brace + 1:]
    return MethodModel("<init>", "init", span, None, _referenced_names(body))


def _parse_secondary_constructor(
    source: str, tokens: Sequence[Token], span: SourceSpan
) -> MethodModel:
    brace = _top_level_text(tokens, 0, len(tokens), "{")
    if brace is None:
        signature_end = len(tokens)
        body: Sequence[Token] = ()
    else:
        signature_end = brace
        close = _matching_index(tokens, brace, "{", "}")
        body = tokens[brace + 1:close] if close is not None else tokens[brace + 1:]
    signature = source[tokens[0].span.start:tokens[signature_end - 1].span.end].strip()
    return MethodModel("<constructor>", signature, span, None, _referenced_names(body))


def _parse_accessors(
    source: str, tokens: Sequence[Token], property_name: str
) -> tuple[MethodModel, ...]:
    methods: list[MethodModel] = []
    index = 0
    while index < len(tokens):
        if tokens[index].text not in {"get", "set"}:
            index += 1
            continue
        name = tokens[index].text + ":" + property_name
        end = _accessor_end(source, tokens, index, len(tokens))
        accessor = tokens[index:end]
        brace = _top_level_text(accessor, 0, len(accessor), "{")
        equals = _top_level_text(accessor, 0, len(accessor), "=")
        signature_end = min(value for value in (brace, equals, len(accessor)) if value is not None)
        signature = source[accessor[0].span.start:accessor[signature_end - 1].span.end].strip()
        body = accessor[(brace + 1 if brace is not None else equals + 1 if equals is not None else len(accessor)):]
        accessor_span = SourceSpan(
            _line_start(source, accessor[0].span.start),
            _line_end(source, accessor[-1].span.end),
        )
        methods.append(MethodModel(name, signature, accessor_span, None, _referenced_names(body)))
        index = end
    return tuple(methods)


def _referenced_names(tokens: Sequence[Token]) -> tuple[str, ...]:
    return tuple(_unique(
        _identifier(token.text) for token in tokens
        if token.kind == "IDENT" and _identifier(token.text) not in KOTLIN_REFERENCE_KEYWORDS
    ))


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
    for argument in ("catalog", "schema", "name"):
        if argument not in values:
            continue
        literal = _plain_string(values[argument])
        if literal is None:
            reasons.append("ambiguous @Table " + argument)
        else:
            resolved[argument] = literal or None
    return TableIdentity(resolved["catalog"], resolved["schema"], resolved["name"] or class_name), reasons


def _kotlin_supertypes(
    tokens: Sequence[Token], start: int, end: int
) -> tuple[str | None, tuple[str, ...]]:
    colon = _top_level_text(tokens, start, end, ":")
    if colon is None:
        return None, ()
    entries = [tokens[piece_start:piece_end] for piece_start, piece_end in _split_indices(tokens, colon + 1, end, ",")]
    superclass: str | None = None
    interfaces: list[str] = []
    for position, entry in enumerate(entries):
        if not entry:
            continue
        open_paren = _top_level_text(entry, 0, len(entry), "(")
        if position == 0 and open_paren is not None:
            superclass = _type_text(entry[:open_paren])
        else:
            interfaces.append(_type_text(entry))
    return superclass, tuple(interfaces)


def _primary_constructor_open(tokens: Sequence[Token], start: int, end: int) -> int | None:
    angle = 0
    for index in range(start, end):
        text = tokens[index].text
        if text == "<": angle += 1
        elif text == ">": angle = max(0, angle - 1)
        elif text == "(" and angle == 0:
            return index
        elif text == ":" and angle == 0:
            return None
    return None


def _find_body_open(source: str, tokens: Sequence[Token], start: int) -> int | None:
    paren = bracket = angle = 0
    previous = max(0, start - 1)
    for index in range(start, len(tokens)):
        text = tokens[index].text
        if text == ";" and paren == bracket == angle == 0:
            return None
        if paren == bracket == angle == 0:
            gap = source[tokens[previous].span.end:tokens[index].span.start]
            if "\n" in gap and text in {"@", "class", "fun", "interface", "object", "typealias", "val", "var"}:
                return None
        if text == "(": paren += 1
        elif text == ")": paren = max(0, paren - 1)
        elif text == "[": bracket += 1
        elif text == "]": bracket = max(0, bracket - 1)
        elif text == "<": angle += 1
        elif text == ">": angle = max(0, angle - 1)
        elif text == "{" and paren == bracket == angle == 0:
            return index
        previous = index
    return None


def _resolve_annotation(name: str, imports: tuple[str, ...]) -> tuple[str, bool]:
    if not name:
        return name, True
    first, separator, rest = name.partition(".")
    aliases = {}
    direct: list[str] = []
    for value in imports:
        if " as " in value:
            target, alias = value.split(" as ", 1)
            aliases[alias] = target
        else:
            direct.append(value)
    if first in aliases:
        return aliases[first] + (separator + rest if separator else ""), False
    exact = [value for value in direct if value.rsplit(".", 1)[-1] == first]
    if len(exact) == 1:
        return exact[0] + (separator + rest if separator else ""), False
    if len(exact) > 1:
        return name, True
    if separator and first[:1].islower():
        return name, False
    wildcard = [value[:-2] + "." + name for value in direct if value.endswith(".*")]
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
    aliases = {}
    direct: list[str] = []
    for value in imports:
        if " as " in value:
            target, alias = value.split(" as ", 1)
            aliases[alias] = target
        else:
            direct.append(value)
    if base in aliases:
        return aliases[base]
    exact = [value for value in direct if value.rsplit(".", 1)[-1] == base]
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
        target = imported.split(" as ", 1)[0]
        if target.endswith(".*"):
            candidates.add(target[:-2] + "." + resolved)
    return not candidates.isdisjoint(domain_types)


def _is_codegen_default(type_name: str, nullable: bool, initializer: str | None) -> bool:
    if initializer is None:
        return False
    if nullable:
        return initializer == "null"
    return initializer in {"-1", "-1L", "-1f", "-1.0"}


def _is_generated_only(
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
    if reasons or methods or superclass or interfaces or custom_annotations or not class_documented or not properties:
        return False
    if not any(annotation.qualified_name == "org.seasar.doma.Entity" for annotation in class_annotations):
        return False
    for prop in properties:
        values = metadata[prop.name]
        if prop.constructor_property or values["kind"] != "var":
            return False
        if values["modifiers"]:
            return False
        if not values["documented"] or not values["generated_default"]:
            return False
        if any(annotation.qualified_name not in TEMPLATE_PROPERTY_ANNOTATIONS for annotation in prop.annotations):
            return False
    return True


def _is_codegen_property_doc(prefix: str) -> bool:
    start = prefix.rfind("/**")
    if start < 0:
        return False
    end = prefix.find("*/", start + 3)
    if end < 0:
        return False
    doc = prefix[start:end + 2]
    return "\n" not in doc and "\r" not in doc


def _leading_comment_start(
    source: str, all_tokens: Sequence[Token], position: int, floor: int
) -> int:
    newline = source.find("\n", floor, position)
    comment_floor = newline + 1 if newline >= 0 else floor
    comments = [
        token for token in all_tokens
        if comment_floor <= token.span.start < position
        and token.kind in {"KDOC", "BLOCK_COMMENT", "LINE_COMMENT"}
    ]
    if comments:
        line_start = _line_start(source, comments[0].span.start)
        return comments[0].span.start if line_start < floor else line_start
    line_start = _line_start(source, position)
    return position if line_start < floor else line_start


def _next_identifier(tokens: Sequence[Token], start: int) -> int | None:
    for index in range(start, len(tokens)):
        if tokens[index].kind == "IDENT":
            return index
    return None


def _identifier(text: str) -> str:
    return text[1:-1] if text.startswith("`") and text.endswith("`") else text


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _bounded_line_region(source: str, start: int, end: int) -> SourceSpan:
    line_start = _line_start(source, start)
    region_start = start if source[line_start:start].strip() else line_start
    line_end = _line_end(source, end)
    region_end = end if source[end:line_end].strip() else line_end
    return SourceSpan(region_start, region_end)
