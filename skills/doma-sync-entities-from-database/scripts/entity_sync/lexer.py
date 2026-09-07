"""Lossless lexical scanning for the conservative Java and Kotlin parsers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .model import SourceSpan


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    span: SourceSpan


def lex_java(source: str) -> tuple[Token, ...]:
    return _lex(source, kotlin=False)


def lex_kotlin(source: str) -> tuple[Token, ...]:
    return _lex(source, kotlin=True)


def balanced_region(
    tokens: Sequence[Token], start: int, opener: str, closer: str
) -> SourceSpan:
    """Return the span from an opener token through its balanced closer."""
    if start < 0 or start >= len(tokens) or tokens[start].text != opener:
        raise ValueError("start does not identify the requested opener")
    depth = 0
    for token in tokens[start:]:
        if token.text == opener:
            depth += 1
        elif token.text == closer:
            depth -= 1
            if depth == 0:
                return SourceSpan(tokens[start].span.start, token.span.end)
    raise ValueError("unmatched delimiter")


def _lex(source: str, *, kotlin: bool) -> tuple[Token, ...]:
    tokens: list[Token] = []
    length = len(source)
    index = 0
    while index < length:
        start = index
        char = source[index]
        if char.isspace():
            index += 1
            while index < length and source[index].isspace():
                index += 1
            _append(tokens, "WHITESPACE", source, start, index)
            continue
        if source.startswith("//", index):
            newline = source.find("\n", index + 2)
            index = length if newline < 0 else newline
            _append(tokens, "LINE_COMMENT", source, start, index)
            continue
        if source.startswith("/*", index):
            kind = "KDOC" if kotlin and source.startswith("/**", index) else (
                "JAVADOC" if not kotlin and source.startswith("/**", index) else "BLOCK_COMMENT"
            )
            index = _block_comment_end(source, index, nested=kotlin)
            if index < 0:
                _append(tokens, "ERROR", source, start, length)
                break
            _append(tokens, kind, source, start, index)
            continue
        if source.startswith('"""', index):
            closer = source.find('"""', index + 3)
            if closer < 0:
                _append(tokens, "ERROR", source, start, length)
                break
            index = closer + 3
            _append(tokens, "TRIPLE_STRING" if kotlin else "TEXT_BLOCK", source, start, index)
            continue
        if char in {'"', "'"}:
            index = _quoted_end(source, index, char)
            if index < 0:
                _append(tokens, "ERROR", source, start, length)
                break
            _append(tokens, "STRING" if char == '"' else "CHAR", source, start, index)
            continue
        if kotlin and char == "`":
            closer = source.find("`", index + 1)
            if closer < 0:
                _append(tokens, "ERROR", source, start, length)
                break
            index = closer + 1
            _append(tokens, "IDENT", source, start, index)
            continue
        if char.isalpha() or char in {"_", "$"}:
            index += 1
            while index < length and (source[index].isalnum() or source[index] in {"_", "$"}):
                index += 1
            _append(tokens, "IDENT", source, start, index)
            continue
        if char.isdigit():
            index += 1
            while index < length and (source[index].isalnum() or source[index] in {"_", "."}):
                index += 1
            _append(tokens, "NUMBER", source, start, index)
            continue
        index += 1
        _append(tokens, "SYMBOL", source, start, index)
    return tuple(tokens)


def _block_comment_end(source: str, start: int, *, nested: bool) -> int:
    index = start + 2
    depth = 1
    while index < len(source):
        if nested and source.startswith("/*", index):
            depth += 1
            index += 2
        elif source.startswith("*/", index):
            depth -= 1
            index += 2
            if depth == 0:
                return index
        else:
            index += 1
    return -1


def _quoted_end(source: str, start: int, quote: str) -> int:
    index = start + 1
    escaped = False
    while index < len(source):
        char = source[index]
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == quote:
            return index + 1
        elif char in {"\n", "\r"}:
            return -1
        index += 1
    return -1


def _append(tokens: list[Token], kind: str, source: str, start: int, end: int) -> None:
    tokens.append(Token(kind, source[start:end], SourceSpan(start, end)))
