"""Customer dictionaries and bounded customer patterns (PRP-101 item 4).

Customer patterns are untrusted configuration that runs on every captured content part, and
Python ``re`` cannot be interrupted mid-match. The bound is therefore static: a pattern is
analysed once, at load, and refused unless its worst case is provably small. The engine adds
the second half of the bound (fixed-size chunks and a per-part time budget, item 5); neither
detector here chunks or times itself.

Static safety check (``check_pattern_safety``), applied in this order, first failure wins:

``too_long``               more than ``MAX_PATTERN_CHARS`` (256) characters, or empty.
``invalid``                ``re.compile`` or the stdlib parser rejects it, or the parse tree
                           holds a node this check does not know (fail closed).
``flags``                  an inline flag other than ``i`` (``(?i)`` / ``(?i:...)``) or the
                           implicit ``u``. ``(?x)``, ``(?s)``, ``(?m)``, ``(?a)`` are refused.
                           ``(?i)`` only widens literal comparisons; it adds no backtracking.
``backreference``          ``\\1``, ``(?P=name)``.
``conditional``            ``(?(1)a|b)``.
``lookaround``             ``(?=``, ``(?!``, ``(?<=``, ``(?<!``.
``nested_quantifier``      a repeat with an upper bound above 1 whose body holds a repeat
                           of variable length, or a variable repeat whose body holds any
                           repeat with an upper bound above 1: ``(a+)+``, ``(.*a){20}``.
``quantified_alternation`` a repeat with an upper bound above 1 whose body holds ``|``:
                           ``(a|aa)+``. (Single-character alternatives that the parser folds
                           into a character class, ``(a|b){1,5}``, are a class and allowed.)
``unbounded_repeat_cap``   any repeat whose upper bound exceeds ``MAX_REPEAT_BOUND`` (100),
                           which includes every unbounded ``*``, ``+`` and ``{n,}``, or whose
                           lower bound does. An unbounded repeat followed by anything is
                           quadratic in the text length (``\\w+x`` over 64 KiB of ``a`` takes
                           seconds), so customers write ``[0-9]{1,12}`` instead of ``[0-9]+``.
``too_deep``               groups nested more than ``MAX_GROUP_DEPTH`` (2) levels. A level is
                           a group (capturing or ``(?i:...)``) or a repeat of anything but one
                           character, so ``(?:(?:(?:\\w?){1}){1}){1}`` and ``(((\\w?)))`` are
                           refused. Each level adds interpreter work to every path through
                           it (15 nested groups made a pattern 10x slower than its flat form).
``empty_match``            the pattern can match the empty string (``x?``, ``\\b``).
``too_complex``            the cost estimate ``paths * (max_width + steps)`` exceeds
                           ``MAX_COMPLEXITY`` (160).
                           ``paths`` multiplies the choices of every variable repeat (x4 when
                           the repeated body is a group rather than one character) and
                           alternation, so adjacent overlapping repeats
                           (``\\w{1,64}\\w{1,64}x``) and ``?`` chains (``\\w?`` x5 is 32
                           paths) are caught here. Every path may re-check up to
                           ``max_width`` characters and re-run ``steps`` interpreter
                           operations: 1 per character, character repeat, group or
                           alternation, plus ``GROUP_REPEAT_WEIGHT`` (4) for every repeat of
                           a group, fixed counts such as ``{1}`` included, whose body is
                           charged once per repetition. The old ``paths * max_width`` alone
                           ignored that per-path overhead and accepted patterns 30x over
                           their claimed cost.

Cost contract (what the engine, item 5, sizes chunks and the time budget on): one accepted
pattern costs at most about 1 ms per estimate unit per 64 KiB of text on the reference
machine (Python 3.12, Windows 11 dev workstation), so at the cap **at most 250 ms per
64 KiB chunk per pattern**, budget 4x that (1 s) on a shared CI runner. The worst accepted
pattern measured is a long case-insensitive class run with a failing tail,
``(?i)[a-z]{100}[a-z]{50}1`` (cost 154), at 96 ms idle and 157 ms with a core busy, over
64 KiB of ``a``; ``(?i)``
classes are the slowest per character. Typical identifiers cost far less: ``EMP-[0-9]{6}``
(cost 13) and ``(?i)case-[0-9]{4,10}`` (cost 154, the largest legitimate shape the tests
pin) scan 64 KiB in about 1 ms. ``finditer`` itself adds about 12 ms per 64 KiB when the
pattern matches at every position.

The check reads the stdlib parse tree (``re._parser``, private but present and stable in the
supported range ``>=3.12,<3.14``; a test pins that range). Any exception while parsing or
walking refuses the pattern.

Nothing here logs. ``PatternRefused`` carries only codes, never the pattern; detector
``repr`` shows the id and version, never terms.
"""

from __future__ import annotations

import hashlib
import importlib
import re
from collections.abc import Iterable
from typing import Annotated, Any, Final

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from neurosphere_core.classification.models import (
    PLACEHOLDER_RE,
    Confidence,
    Match,
    ReasonCode,
    SensitivityCategory,
)
from neurosphere_core.classification.protocol import Detector

MAX_PATTERN_CHARS: Final = 256
MAX_REPEAT_BOUND: Final = 100
MAX_COMPLEXITY: Final = 160
MAX_GROUP_DEPTH: Final = 2
#: Weight for a repeat of a group rather than one character: measured about 3x slower per
#: step than a single-character repeat, which ``re`` runs in a tight C loop. Multiplies the
#: paths of a variable group repeat and is added to the steps of every group repeat.
GROUP_REPEAT_WEIGHT: Final = 4
MAX_TERMS: Final = 10_000
MAX_TERM_CHARS: Final = 256

DETECTOR_VERSION: Final = "1.0.0"
_ID_LIMIT: Final = 64

_Slug = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")]

_ALLOWED_FLAGS: Final = re.IGNORECASE | re.UNICODE

#: Refusal codes in check order (first failure wins).
REFUSAL_DETAILS: Final[tuple[str, ...]] = (
    "too_long",
    "invalid",
    "flags",
    "backreference",
    "conditional",
    "lookaround",
    "nested_quantifier",
    "quantified_alternation",
    "unbounded_repeat_cap",
    "too_deep",
    "empty_match",
    "too_complex",
)

_LEAF_OPS: Final = frozenset({"LITERAL", "NOT_LITERAL", "ANY", "IN", "AT"})
_REPEAT_OPS: Final = frozenset({"MAX_REPEAT", "MIN_REPEAT", "POSSESSIVE_REPEAT"})


class PatternRefused(Exception):  # noqa: N818 - name fixed by the PRP-101 brief
    """A customer pattern failed the static safety check.

    Deliberately not a ``ValueError``: pydantic lets it propagate unchanged out of
    ``CustomerPattern(...)`` so callers keep ``reason_code`` and ``detail``. The message holds
    only those two codes, never the pattern text.
    """

    def __init__(self, detail: str) -> None:
        self.reason_code: ReasonCode = "pattern_unsafe"
        self.detail = detail
        super().__init__(f"customer pattern refused: pattern_unsafe ({detail})")


class _Walk:
    """Facts collected from one parse tree."""

    __slots__ = ("found",)

    def __init__(self) -> None:
        self.found: set[str] = set()


def _parser() -> Any:
    return importlib.import_module("re._parser")


def _items(node: Any) -> list[tuple[Any, Any]]:
    return [(str(op), av) for op, av in node]


def _repeats(seq: Any) -> list[tuple[int, int]]:
    """All (min, max) repeat bounds anywhere below ``seq``."""
    out: list[tuple[int, int]] = []
    for op, av in _items(seq):
        for child in _children(op, av):
            out.extend(_repeats(child))
        if op in _REPEAT_OPS:
            out.append((int(av[0]), int(av[1])))
    return out


def _has_branch(seq: Any) -> bool:
    for op, av in _items(seq):
        if op == "BRANCH":
            return True
        if any(_has_branch(child) for child in _children(op, av)):
            return True
    return False


def _children(op: str, av: Any) -> list[Any]:
    if op in _REPEAT_OPS:
        return [av[2]]
    if op == "SUBPATTERN":
        return [av[3]]
    if op == "ATOMIC_GROUP":
        return [av]
    if op == "BRANCH":
        return list(av[1])
    if op == "GROUPREF_EXISTS":
        return [b for b in (av[1], av[2]) if b is not None]
    if op in ("ASSERT", "ASSERT_NOT"):
        return [av[1]]
    return []


def _visit(seq: Any, walk: _Walk) -> None:
    for op, av in _items(seq):
        if op in _LEAF_OPS:
            continue
        if op in ("GROUPREF", "GROUPREF_IGNORE"):
            walk.found.add("backreference")
        elif op == "GROUPREF_EXISTS":
            walk.found.add("conditional")
        elif op in ("ASSERT", "ASSERT_NOT"):
            walk.found.add("lookaround")
        elif op == "SUBPATTERN":
            add_flags, del_flags = int(av[1]), int(av[2])
            if (add_flags | del_flags) & ~_ALLOWED_FLAGS:
                walk.found.add("flags")
        elif op in _REPEAT_OPS:
            low, high = int(av[0]), int(av[1])
            inner = _repeats(av[2])
            if high > 1 and any(lo != hi for lo, hi in inner):
                walk.found.add("nested_quantifier")
            if high > 1 and low != high and any(hi > 1 for _, hi in inner):
                walk.found.add("nested_quantifier")
            if high > 1 and _has_branch(av[2]):
                walk.found.add("quantified_alternation")
            if high > MAX_REPEAT_BOUND or low > MAX_REPEAT_BOUND:
                walk.found.add("unbounded_repeat_cap")
        elif op not in ("BRANCH", "ATOMIC_GROUP"):
            walk.found.add("invalid")
        for child in _children(op, av):
            _visit(child, walk)


_PATH_CLAMP: Final = MAX_COMPLEXITY + 1


def _single_char(seq: Any) -> bool:
    items = _items(seq)
    return len(items) == 1 and items[0][0] in _LEAF_OPS and items[0][0] != "AT"


def _paths(seq: Any) -> int:
    """Upper bound on backtracking choice combinations, clamped above ``MAX_COMPLEXITY``."""
    total = 1
    for op, av in _items(seq):
        if op in _REPEAT_OPS:
            low, high = int(av[0]), int(av[1])
            body = _paths(av[2])
            # Bodies under a repeat with max > 1 hold no alternation or variable repeat
            # (refused earlier), so ``body`` is 1 there; ``?`` bodies multiply once.
            factor = (high - low + 1) * (body if high <= 1 else body ** min(high, 16))
            if low != high and not _single_char(av[2]):
                factor *= GROUP_REPEAT_WEIGHT
        elif op == "BRANCH":
            factor = sum(_paths(b) for b in av[1])
        elif op == "SUBPATTERN":
            factor = _paths(av[3])
        elif op == "ATOMIC_GROUP":
            factor = _paths(av)
        else:
            factor = 1
        total = min(total * min(factor, _PATH_CLAMP), _PATH_CLAMP)
    return total


def _steps(seq: Any) -> int:
    """Interpreter operations one path may run: see ``too_complex`` in the module docstring."""
    total = 0
    for op, av in _items(seq):
        if op in _REPEAT_OPS:
            if _single_char(av[2]):
                total += 1
            else:
                total += GROUP_REPEAT_WEIGHT + _steps(av[2]) * max(1, int(av[1]))
        elif op == "BRANCH":
            total += 1 + sum(_steps(b) for b in av[1])
        elif op == "SUBPATTERN":
            total += 1 + _steps(av[3])
        elif op == "ATOMIC_GROUP":
            total += 1 + _steps(av)
        else:
            total += 1
    return total


def _depth(seq: Any) -> int:
    """Group nesting depth: groups and repeats of anything but one character."""
    deepest = 0
    for op, av in _items(seq):
        if op in _REPEAT_OPS:
            level = _depth(av[2]) + (0 if _single_char(av[2]) else 1)
        elif op == "BRANCH":
            level = max(_depth(b) for b in av[1])
        elif op == "SUBPATTERN":
            level = 1 + _depth(av[3])
        elif op == "ATOMIC_GROUP":
            level = 1 + _depth(av)
        else:
            level = 0
        deepest = max(deepest, level)
    return deepest


def check_pattern_safety(pattern: str) -> None:
    """Refuse ``pattern`` unless its backtracking cost is statically bounded.

    Raises ``PatternRefused`` with one detail code from ``REFUSAL_DETAILS``; returns ``None``
    when the pattern is safe to run on bounded chunks.
    """
    if not pattern or len(pattern) > MAX_PATTERN_CHARS:
        raise PatternRefused("too_long")
    try:
        re.compile(pattern)
        tree = _parser().parse(pattern)
        flags = int(tree.state.flags)
        walk = _Walk()
        _visit(tree, walk)
        if _depth(tree) > MAX_GROUP_DEPTH:
            walk.found.add("too_deep")
        low_width, high_width = (int(w) for w in tree.getwidth())
        paths = _paths(tree)
        steps = _steps(tree)
    except PatternRefused:
        raise
    except Exception:
        raise PatternRefused("invalid") from None
    if flags & ~_ALLOWED_FLAGS:
        walk.found.add("flags")
    for detail in REFUSAL_DETAILS:
        if detail in walk.found:
            raise PatternRefused(detail)
    if low_width == 0:
        raise PatternRefused("empty_match")
    if paths * (high_width + steps) > MAX_COMPLEXITY:
        raise PatternRefused("too_complex")


def _detector_id(prefix: str, slug: str) -> str:
    full = f"{prefix}.{slug}"
    if len(full) <= _ID_LIMIT:
        return full
    digest = hashlib.sha256(slug.encode("utf-8")).hexdigest()[:8]
    return f"{full[: _ID_LIMIT - 9]}-{digest}"


def _placeholder_spans(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in PLACEHOLDER_RE.finditer(text)]


def _clear_of_placeholders(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    """True unless the span cuts into a placeholder without covering it whole."""
    for p_start, p_end in spans:
        if start < p_end and p_start < end and not (start <= p_start and p_end <= end):
            return False
    return True


_CONFIG = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class CustomerDictionary(BaseModel):
    """Exact customer terms, matched case-folded and word-bounded.

    ``terms`` are stripped, must be 1..256 characters, at most 10,000, and are deduplicated
    by ``str.casefold`` (first spelling kept). Validation errors never echo a term
    (``hide_input_in_errors``). The model's own ``repr`` shows the configured terms: that is
    configuration, not captured content; detectors never print them.
    """

    model_config = _CONFIG

    dictionary_id: _Slug
    terms: tuple[str, ...] = Field(min_length=1, max_length=MAX_TERMS)
    sensitivity_category: SensitivityCategory
    confidence: Confidence = "high"

    @field_validator("terms", mode="after")
    @classmethod
    def _normalise_terms(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        seen: set[str] = set()
        out: list[str] = []
        for index, raw in enumerate(value):
            term = raw.strip()
            if not 1 <= len(term) <= MAX_TERM_CHARS:
                raise ValueError(f"term {index} must be 1..{MAX_TERM_CHARS} characters")
            key = term.casefold()
            if key not in seen:
                seen.add(key)
                out.append(term)
        return tuple(out)


class CustomerPattern(BaseModel):
    """One customer identifier pattern; refused at construction unless it is bounded."""

    model_config = _CONFIG

    pattern_id: _Slug
    pattern: str
    sensitivity_category: SensitivityCategory
    confidence: Confidence = "medium"

    @model_validator(mode="after")
    def _safe(self) -> CustomerPattern:
        check_pattern_safety(self.pattern)
        return self


def _is_word(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


_END: Final = "\x00end"


class CustomerDictionaryDetector:
    """Detector for one ``CustomerDictionary``.

    Matching: the text is case-folded one character at a time, keeping a map from each
    folded position back to its original character, so offsets always refer to the original
    text even when folding changes length (``ß`` -> ``ss``). Terms are folded into a character
    trie. A scan starts only at a word start (a word character not preceded by one) or at a
    non-word, non-space character, walks the trie as far as the text allows and keeps the
    longest term that ends on a word boundary and on a whole folded character; it then jumps
    past that match (leftmost-longest, non-overlapping).

    Cost: one dict step per walked character, and a walk never exceeds the longest folded
    term (at most 768 characters), so the scan is linear in the text length with that
    constant as the worst-case factor; ordinary text leaves the trie after one or two steps
    (about 35 ms per 64 KiB on the reference machine). The worst case is a long term built
    from a repeated token over text of that token, so every start position walks the whole
    term: a 255-character run of ``!`` plus ``x`` over 64 KiB of ``!`` takes about 1.3 s,
    ``"a a ... b"`` over ``"a a ..."`` about 0.7 s. Contract for the engine: **at most 2 s
    per 64 KiB per dictionary** on the reference machine. This avoids both a 10,000-way
    regex alternation (tried branch by branch at every position) and a new dependency.

    A term never matches inside a longer word. Matches that cut into a
    ``[[ns-redacted:...]]`` placeholder are dropped; only a term that covers the whole
    placeholder string (the customer listed it literally) can match one.
    """

    __slots__ = (
        "_confidence",
        "_root",
        "_sensitivity",
        "always_redact",
        "detector_id",
        "kinds",
        "version",
    )

    def __init__(self, dictionary: CustomerDictionary) -> None:
        self.detector_id: str = _detector_id("customer-dict", dictionary.dictionary_id)
        self.version: str = DETECTOR_VERSION
        self.kinds: frozenset[str] = frozenset({"customer_dictionary_term"})
        self.always_redact: bool = False
        self._sensitivity: str = dictionary.sensitivity_category
        self._confidence: Confidence = dictionary.confidence
        root: dict[str, Any] = {}
        for term in dictionary.terms:
            node = root
            for ch in term.casefold():
                node = node.setdefault(ch, {})
            node[_END] = True
        self._root = root

    def __repr__(self) -> str:
        return f"{type(self).__name__}(detector_id={self.detector_id!r}, version={self.version!r})"

    def find(self, text: str) -> tuple[Match, ...]:
        folded_chars: list[str] = []
        origin: list[int] = []  # folded index -> original index
        first: list[bool] = []  # folded index starts an original character's fold
        for index, ch in enumerate(text):
            piece = ch.casefold()
            for offset, part in enumerate(piece):
                folded_chars.append(part)
                origin.append(index)
                first.append(offset == 0)
        size = len(folded_chars)
        spans = _placeholder_spans(text) if "[[" in text else []
        matches: list[Match] = []
        pos = 0
        while pos < size:
            ch = folded_chars[pos]
            word = _is_word(ch)
            prev_word = pos > 0 and _is_word(folded_chars[pos - 1])
            startable = first[pos] and ((word and not prev_word) or (not word and not ch.isspace()))
            if not startable or ch not in self._root:
                pos += 1
                continue
            best_end = -1
            node: dict[str, Any] = self._root
            cursor = pos
            while cursor < size:
                child = node.get(folded_chars[cursor])
                if child is None:
                    break
                node = child
                cursor += 1
                if _END in node and (cursor == size or first[cursor]):
                    last_word = _is_word(folded_chars[cursor - 1])
                    next_word = cursor < size and _is_word(folded_chars[cursor])
                    if not (last_word and next_word):
                        best_end = cursor
            if best_end < 0:
                pos += 1
                continue
            start = origin[pos]
            end = origin[best_end - 1] + 1
            if _clear_of_placeholders(start, end, spans):
                matches.append(
                    Match(
                        start=start,
                        end=end,
                        category="customer_dictionary_term",
                        confidence=self._confidence,
                        detector_id=self.detector_id,
                        sensitivity_category=self._sensitivity,
                    )
                )
                pos = best_end
            else:
                pos += 1
        return tuple(matches)


class CustomerPatternDetector:
    """Detector for one ``CustomerPattern`` (already safety-checked at construction).

    ``find`` runs the compiled pattern with ``finditer`` over exactly the text it is given
    and skips zero-length matches. It does NOT chunk and does NOT time itself: the engine
    (item 5) passes bounded chunks and owns the per-part time budget, failing the part
    closed when it is spent. Matches that cut into a ``[[ns-redacted:...]]`` placeholder
    are dropped.
    """

    __slots__ = (
        "_compiled",
        "_confidence",
        "_sensitivity",
        "always_redact",
        "detector_id",
        "kinds",
        "version",
    )

    def __init__(self, pattern: CustomerPattern) -> None:
        check_pattern_safety(pattern.pattern)
        self.detector_id: str = _detector_id("customer-pattern", pattern.pattern_id)
        self.version: str = DETECTOR_VERSION
        self.kinds: frozenset[str] = frozenset({"customer_identifier_pattern"})
        self.always_redact: bool = False
        self._sensitivity: str = pattern.sensitivity_category
        self._confidence: Confidence = pattern.confidence
        self._compiled = re.compile(pattern.pattern)

    def __repr__(self) -> str:
        return (
            f"CustomerPatternDetector(detector_id={self.detector_id!r}, version={self.version!r})"
        )

    def find(self, text: str) -> tuple[Match, ...]:
        spans = _placeholder_spans(text) if "[[" in text else []
        return tuple(
            Match(
                start=m.start(),
                end=m.end(),
                category="customer_identifier_pattern",
                confidence=self._confidence,
                detector_id=self.detector_id,
                sensitivity_category=self._sensitivity,
            )
            for m in self._compiled.finditer(text)
            if m.end() > m.start() and _clear_of_placeholders(m.start(), m.end(), spans)
        )


def build_customer_detectors(
    dictionaries: Iterable[CustomerDictionary], patterns: Iterable[CustomerPattern]
) -> tuple[Detector, ...]:
    """Dictionary detectors first, then pattern detectors, in the given order."""
    built: list[Detector] = [CustomerDictionaryDetector(d) for d in dictionaries]
    built.extend(CustomerPatternDetector(p) for p in patterns)
    return tuple(built)
