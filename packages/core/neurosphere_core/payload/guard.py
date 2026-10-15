"""Shared, pure payload body guard for telemetry ingestion (PRP-07).

Prompt/response bodies are dropped by default before any persistence or publish. The ingest
edge, normalizer, quarantine and archive all use this one implementation.

Every walk here is ITERATIVE (explicit stacks, no recursion), so an arbitrarily deep structure
cannot overflow the interpreter stack. Callers should still bound depth with
`raw_json_exceeds_depth` before `json.loads` (the stdlib parser itself is recursive).

Only counts and JSON-pointer paths are ever returned; dropped values are never retained,
logged or returned. Inputs are JSON-like (dict / list / scalars) and must be acyclic.
"""

from __future__ import annotations

from typing import Any, Final

DEFAULT_MAX_DEPTH: Final = 32
DEFAULT_MAX_BODY_BYTES: Final = 1_048_576

BODY_FIELD_NAMES: Final[frozenset[str]] = frozenset(
    {
        "prompt",
        "response",
        "gen_ai.prompt",
        "gen_ai.completion",
        "gen_ai.input.messages",
        "gen_ai.output.messages",
        "gen_ai.system_instructions",
    }
)

_SUFFIXES: Final = frozenset({"prompt", "response"})


def normalize_field_name(name: str) -> str:
    """Case-fold a field name for matching and counting."""
    return name.strip().lower()


def is_body_field(name: str) -> bool:
    """True if `name` is a prompt/response body field.

    Rule (case-insensitive): the name is in `BODY_FIELD_NAMES`, OR its last dotted segment is
    `prompt` or `response` (so `llm.prompt` and `app.response` match; `prompt_tokens` and
    `gen_ai.usage.prompt_tokens` do not).
    """
    norm = normalize_field_name(name)
    if norm in BODY_FIELD_NAMES:
        return True
    return norm.rsplit(".", 1)[-1] in _SUFFIXES


def _otlp_item_name(item: Any) -> str | None:
    """Return the matching body-field name if `item` is an OTLP attribute item, else None."""
    if isinstance(item, dict) and "value" in item:
        key = item.get("key")
        if isinstance(key, str) and is_body_field(key):
            return normalize_field_name(key)
    return None


def drop_body_fields(payload: Any) -> tuple[Any, dict[str, int]]:
    """Return (new structure without body fields at any depth, counts per normalized name).

    Handles dict keys and OTLP/JSON attribute-list items (`{"key": name, "value": {...}}`, which
    are dropped whole). The input is never mutated. Iterative: safe for arbitrarily deep input.
    """
    counts: dict[str, int] = {}
    if not isinstance(payload, (dict, list)):
        return payload, counts
    root: Any = {} if isinstance(payload, dict) else []
    stack: list[tuple[Any, Any]] = [(payload, root)]
    while stack:
        src, dst = stack.pop()
        if isinstance(src, dict):
            for key, value in src.items():
                if isinstance(key, str) and is_body_field(key):
                    name = normalize_field_name(key)
                    counts[name] = counts.get(name, 0) + 1
                    continue
                if isinstance(value, (dict, list)):
                    child: Any = {} if isinstance(value, dict) else []
                    dst[key] = child
                    stack.append((value, child))
                else:
                    dst[key] = value
        else:
            for item in src:
                name = _otlp_item_name(item)
                if name is not None:
                    counts[name] = counts.get(name, 0) + 1
                    continue
                if isinstance(item, (dict, list)):
                    child = {} if isinstance(item, dict) else []
                    dst.append(child)
                    stack.append((item, child))
                else:
                    dst.append(item)
    return root, counts


def _escape_pointer(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def find_body_fields(payload: Any) -> list[str]:
    """RFC 6901 JSON-pointer paths of every body field still present (empty means clean).

    Reports dict keys and OTLP attribute items. Iterative: safe for arbitrarily deep input.
    Paths only, never values.
    """
    found: list[str] = []
    stack: list[tuple[Any, str]] = [(payload, "")]
    while stack:
        node, path = stack.pop()
        if isinstance(node, dict):
            for key, value in node.items():
                token = str(key)
                child_path = f"{path}/{_escape_pointer(token)}"
                if isinstance(key, str) and is_body_field(key):
                    found.append(child_path)
                elif isinstance(value, (dict, list)):
                    stack.append((value, child_path))
        elif isinstance(node, list):
            for index, item in enumerate(node):
                child_path = f"{path}/{index}"
                if _otlp_item_name(item) is not None:
                    found.append(child_path)
                elif isinstance(item, (dict, list)):
                    stack.append((item, child_path))
    found.sort()
    return found


def json_depth(payload: Any) -> int:
    """Container nesting depth: a scalar is 0, `[]` / `{}` is 1, `[[]]` is 2. Iterative."""
    deepest = 0
    stack: list[tuple[Any, int]] = [(payload, 0)]
    while stack:
        node, depth = stack.pop()
        if isinstance(node, dict):
            children: Any = node.values()
        elif isinstance(node, list):
            children = node
        else:
            continue
        depth += 1
        deepest = max(deepest, depth)
        stack.extend((child, depth) for child in children)
    return deepest


def exceeds_depth(payload: Any, max_depth: int) -> bool:
    """True if `json_depth(payload) > max_depth`. Iterative; stops early once exceeded."""
    stack: list[tuple[Any, int]] = [(payload, 0)]
    while stack:
        node, depth = stack.pop()
        if isinstance(node, dict):
            children: Any = node.values()
        elif isinstance(node, list):
            children = node
        else:
            continue
        depth += 1
        if depth > max_depth:
            return True
        stack.extend((child, depth) for child in children)
    return False


def raw_json_exceeds_depth(raw: bytes, max_depth: int) -> bool:
    """True if raw JSON bytes nest `{`/`[` deeper than `max_depth`, ignoring string literals.

    Runs BEFORE parsing so parser-DoS payloads are rejected cheaply. O(n), iterative; handles
    escaped quotes and backslashes inside strings. Does not validate the JSON.
    """
    depth = 0
    in_string = False
    escaped = False
    for byte in raw:
        if in_string:
            if escaped:
                escaped = False
            elif byte == 0x5C:  # backslash
                escaped = True
            elif byte == 0x22:  # quote
                in_string = False
            continue
        if byte == 0x22:
            in_string = True
        elif byte in (0x7B, 0x5B):  # { [
            depth += 1
            if depth > max_depth:
                return True
        elif byte in (0x7D, 0x5D) and depth > 0:  # } ]
            depth -= 1
    return False
