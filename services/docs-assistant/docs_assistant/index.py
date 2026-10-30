"""Index built ONLY from a built-site artifact directory (HTML files).

Nothing here reads the repository tree. Only `*.html` files that resolve inside the site
directory are indexed; symlinks are skipped. Retrieval is local lexical BM25, no network.
"""

from __future__ import annotations

import math
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

_SKIP_TAGS = frozenset(
    {"script", "style", "nav", "header", "footer", "template", "svg", "button", "form", "noscript"}
)
_VOID_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "wbr"}
)
_HEADINGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_STOPWORDS = frozenset(
    "a an and are as at be by can do does for from how i in is it its me of on or "
    "that the this to was what when where which who why will with you your we our".split()
)
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_MAX_CHUNK_WORDS = 150
_SKIP_FILES = frozenset({"404.html"})


@dataclass(frozen=True, slots=True)
class Chunk:
    """One retrievable passage and the published docs URL it came from."""

    url: str
    page_title: str
    heading: str
    text: str


@dataclass(frozen=True, slots=True)
class Hit:
    chunk: Chunk
    score: float
    coverage: float


def tokenize(text: str) -> list[str]:
    """Lowercase alnum tokens, stopwords removed, trailing plural 's' stripped."""
    out: list[str] = []
    for tok in _TOKEN_RE.findall(text.lower()):
        if tok in _STOPWORDS:
            continue
        if len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss"):
            tok = tok[:-1]
        out.append(tok)
    return out


class _Section:
    __slots__ = ("anchor", "heading", "parts")

    def __init__(self, heading: str, anchor: str) -> None:
        self.heading = heading
        self.anchor = anchor
        self.parts: list[str] = []


class _PageParser(HTMLParser):
    def __init__(self, *, article_only: bool) -> None:
        super().__init__(convert_charrefs=True)
        self._article_only = article_only
        self._stack: list[str] = []
        self._skip = 0
        self._article = 0
        self._in_title = False
        self._title_parts: list[str] = []
        self._in_heading = False
        self._heading_parts: list[str] = []
        self._heading_anchor = ""
        self.h1 = ""
        self.sections: list[_Section] = [_Section("", "")]

    @property
    def title(self) -> str:
        return " ".join("".join(self._title_parts).split())

    def _capturing(self) -> bool:
        if self._skip:
            return False
        return self._article > 0 if self._article_only else True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._in_title = True
        if tag in _VOID_TAGS:
            return
        self._stack.append(tag)
        if tag in _SKIP_TAGS:
            self._skip += 1
        if tag == "article":
            self._article += 1
        if tag in _HEADINGS and self._capturing():
            self._in_heading = True
            self._heading_parts = []
            self._heading_anchor = dict(attrs).get("id") or ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag in _VOID_TAGS or tag not in self._stack:
            return
        while self._stack:
            top = self._stack.pop()
            if top in _SKIP_TAGS:
                self._skip -= 1
            if top == "article":
                self._article -= 1
            if top in _HEADINGS and self._in_heading:
                self._finish_heading(top)
            if top == tag:
                break

    def _finish_heading(self, tag: str) -> None:
        self._in_heading = False
        text = " ".join("".join(self._heading_parts).replace("¶", "").split())
        if tag == "h1" and not self.h1:
            self.h1 = text
        self.sections.append(_Section(text, self._heading_anchor))

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
            return
        if not self._capturing():
            return
        if self._in_heading:
            self._heading_parts.append(data)
        else:
            self.sections[-1].parts.append(data)


def _chunks_from_html(html: str, url: str) -> list[Chunk]:
    parser = _PageParser(article_only="<article" in html)
    parser.feed(html)
    parser.close()
    page_title = parser.h1 or parser.title
    chunks: list[Chunk] = []
    for section in parser.sections:
        body = " ".join("".join(section.parts).replace("¶", "").split())
        if not body:
            continue
        section_url = f"{url}#{section.anchor}" if section.anchor else url
        words = body.split(" ")
        for start in range(0, len(words), _MAX_CHUNK_WORDS):
            piece = " ".join(words[start : start + _MAX_CHUNK_WORDS])
            chunks.append(Chunk(section_url, page_title, section.heading, piece))
    return chunks


def _page_url(base_url: str, rel_posix: str) -> str:
    rel = rel_posix
    if rel == "index.html":
        rel = ""
    elif rel.endswith("/index.html"):
        rel = rel[: -len("index.html")]
    return base_url.rstrip("/") + "/" + rel


class DocsIndex:
    """In-memory BM25 index over chunks from a built site directory."""

    _K1 = 1.5
    _B = 0.75

    def __init__(self, chunks: list[Chunk]) -> None:
        self.chunks = chunks
        self._tfs: list[Counter[str]] = []
        self._lens: list[int] = []
        df: Counter[str] = Counter()
        for chunk in chunks:
            tokens = tokenize(f"{chunk.page_title} {chunk.heading} {chunk.text}")
            tf = Counter(tokens)
            self._tfs.append(tf)
            self._lens.append(len(tokens))
            df.update(tf.keys())
        n = len(chunks)
        self._avgdl = (sum(self._lens) / n) if n else 1.0
        self._idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    @classmethod
    def from_site_dir(cls, site_dir: Path, base_url: str) -> DocsIndex:
        root = site_dir.resolve()
        if not root.is_dir():
            msg = f"site directory does not exist: {site_dir}"
            raise FileNotFoundError(msg)
        chunks: list[Chunk] = []
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames.sort()
            for name in sorted(filenames):
                if not name.endswith(".html") or name in _SKIP_FILES:
                    continue
                path = Path(dirpath) / name
                if path.is_symlink():
                    continue
                resolved = path.resolve()
                if not resolved.is_relative_to(root):
                    continue
                rel = resolved.relative_to(root).as_posix()
                html = resolved.read_text(encoding="utf-8", errors="replace")
                chunks.extend(_chunks_from_html(html, _page_url(base_url, rel)))
        return cls(chunks)

    def search(self, question: str, top_k: int = 3) -> list[Hit]:
        terms = sorted(set(tokenize(question)))
        if not terms or not self.chunks:
            return []
        hits: list[Hit] = []
        for chunk, tf, dl in zip(self.chunks, self._tfs, self._lens, strict=True):
            matched = [t for t in terms if t in tf]
            if not matched:
                continue
            score = 0.0
            for t in matched:
                f = tf[t]
                norm = f + self._K1 * (1 - self._B + self._B * dl / self._avgdl)
                score += self._idf[t] * f * (self._K1 + 1) / norm
            hits.append(Hit(chunk, score, len(matched) / len(terms)))
        hits.sort(key=lambda h: (-h.score, h.chunk.url))
        return hits[:top_k]


def main(argv: list[str] | None = None) -> int:
    """CLI: `python -m docs_assistant.index SITE_DIR [BASE_URL] [QUESTION]` prints stats."""
    args = sys.argv[1:] if argv is None else argv
    if not args:
        sys.stderr.write("usage: python -m docs_assistant.index SITE_DIR [BASE_URL]\n")
        return 2
    base = args[1] if len(args) > 1 else "https://docs.example.invalid/"
    index = DocsIndex.from_site_dir(Path(args[0]), base)
    pages = sorted({c.url.split("#", 1)[0] for c in index.chunks})
    sys.stdout.write(f"chunks={len(index.chunks)} pages={len(pages)}\n")
    for page in pages:
        sys.stdout.write(f"{page}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
