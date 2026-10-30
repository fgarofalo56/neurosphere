from __future__ import annotations

from pathlib import Path

from docs_assistant.index import DocsIndex

BASE = "https://docs.example.invalid/"


def _all_text(index: DocsIndex) -> str:
    return " ".join(c.text + c.heading + c.page_title for c in index.chunks)


def test_files_outside_site_dir_are_not_retrievable(repo: Path) -> None:
    index = DocsIndex.from_site_dir(repo / "site", BASE)
    text = _all_text(index)
    for token in ("ZEBRAEVIDENCE", "ZEBRALEAK", "ZEBRASECRET", "ZEBRASOURCE"):
        assert token not in text
        assert index.search(token.lower()) == []


def test_non_html_files_inside_site_dir_are_not_indexed(repo: Path) -> None:
    index = DocsIndex.from_site_dir(repo / "site", BASE)
    text = _all_text(index)
    assert "ZEBRAINSITE" not in text
    assert "ZEBRAMD" not in text


def test_site_chrome_is_stripped_and_urls_are_published_urls(repo: Path) -> None:
    index = DocsIndex.from_site_dir(repo / "site", BASE)
    text = _all_text(index)
    assert "NAVJUNK" not in text
    assert "FOOTERJUNK" not in text
    urls = {c.url for c in index.chunks}
    assert f"{BASE}adr/0008-docs-site-tool/#adr-0008" in urls
    assert f"{BASE}#home" in urls
    assert all(u.startswith(BASE) for u in urls)


def test_relevant_page_is_retrieved(repo: Path) -> None:
    index = DocsIndex.from_site_dir(repo / "site", BASE)
    hits = index.search("Which tool builds the documentation site?")
    assert hits
    assert hits[0].chunk.url.startswith(f"{BASE}adr/0008-docs-site-tool/")


def test_symlink_escaping_site_dir_is_skipped(repo: Path) -> None:
    link = repo / "site" / "linked.html"
    try:
        link.symlink_to(repo / "docs" / "leak.html")
    except (OSError, NotImplementedError):
        return  # symlinks unavailable on this platform
    index = DocsIndex.from_site_dir(repo / "site", BASE)
    assert "ZEBRALEAK" not in _all_text(index)
