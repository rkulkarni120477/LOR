"""Allowlist HTML sanitizer for rich-text content, and plain-text extraction for search.

Anything not on the allowlist is dropped. Text is re-escaped, so the output never contains a tag
or attribute that was not explicitly allowed. Content of script-like elements is discarded.
"""

import html
import re
from html.parser import HTMLParser
from urllib.parse import urlparse

ALLOWED_TAGS = {
    "p", "br", "strong", "b", "em", "i", "u", "h1", "h2", "h3",
    "ul", "ol", "li", "blockquote", "code", "pre", "a", "hr",
    "table", "thead", "tbody", "tr", "th", "td",
}  # fmt: skip
VOID_TAGS = {"br", "hr"}
# Elements whose text content must not appear anywhere in the output.
DISCARD_WITH_CONTENT = {
    "script",
    "style",
    "iframe",
    "object",
    "svg",
    "math",
    "template",
    "noscript",
    "title",
    "textarea",
}
SAFE_LINK_SCHEMES = {"http", "https", "mailto"}
MAX_HTML_CHARS = 200_000


def _safe_href(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip()
    if any(ord(c) < 32 for c in cleaned):
        return None
    scheme = urlparse(cleaned).scheme.lower()
    if scheme and scheme not in SAFE_LINK_SCHEMES:
        return None
    if not scheme and not cleaned.startswith(("/", "#")):
        return None
    return html.escape(cleaned, quote=True)


class _Sanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.open: list[str] = []
        self.discarding = 0

    def handle_starttag(self, tag, attrs):
        if tag in DISCARD_WITH_CONTENT:
            self.discarding += 1
            return
        if self.discarding or tag not in ALLOWED_TAGS:
            return
        if tag == "a":
            href = _safe_href(dict(attrs).get("href"))
            if href is None:
                return
            self.out.append(f'<a href="{href}" rel="noopener noreferrer">')
            self.open.append(tag)
            return
        self.out.append(f"<{tag}>")
        if tag not in VOID_TAGS:
            self.open.append(tag)

    def handle_startendtag(self, tag, attrs):
        if tag in VOID_TAGS and not self.discarding and tag in ALLOWED_TAGS:
            self.out.append(f"<{tag}>")

    def handle_endtag(self, tag):
        if tag in DISCARD_WITH_CONTENT:
            self.discarding = max(0, self.discarding - 1)
            return
        if self.discarding or tag not in self.open:
            return
        # Close any allowed elements opened inside this one, then this one.
        while self.open:
            current = self.open.pop()
            self.out.append(f"</{current}>")
            if current == tag:
                break

    def handle_data(self, data):
        if not self.discarding:
            self.out.append(html.escape(data, quote=False))

    def close(self):
        super().close()
        while self.open:
            self.out.append(f"</{self.open.pop()}>")


def sanitize_html(raw: str) -> str:
    if len(raw) > MAX_HTML_CHARS:
        raise ValueError("content is too large")
    parser = _Sanitizer()
    parser.feed(raw)
    parser.close()
    return "".join(parser.out)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.discarding = 0

    def handle_starttag(self, tag, attrs):
        if tag in DISCARD_WITH_CONTENT:
            self.discarding += 1

    def handle_endtag(self, tag):
        if tag in DISCARD_WITH_CONTENT:
            self.discarding = max(0, self.discarding - 1)

    def handle_data(self, data):
        if not self.discarding:
            self.parts.append(data)


_WHITESPACE = re.compile(r"\s+")


def plain_text(raw: str) -> str:
    extractor = _TextExtractor()
    extractor.feed(raw)
    extractor.close()
    return _WHITESPACE.sub(" ", " ".join(extractor.parts)).strip()


def search_text(*parts: str) -> str:
    """Lower-cased, whitespace-normalized text used for full-text matching."""
    text = _WHITESPACE.sub(" ", " ".join(p for p in parts if p)).strip().lower()
    return text[:20_000]
