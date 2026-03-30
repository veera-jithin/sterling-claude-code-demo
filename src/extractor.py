"""
HTML email body processor for the Email Job Extraction Agent.

Strips Outlook CSS/script noise from HTML email bodies while preserving
<table> structure — Gemini needs tables intact to parse key-value job layouts.
Block-level elements are converted to newlines so the output is readable as
plain text.

Main class:
    HtmlExtractor: strips and normalises an HTML email body string.
"""

import re

from bs4 import BeautifulSoup, Tag

# HTML attributes that are purely presentational — safe to remove
_STYLE_ATTRIBUTES: frozenset[str] = frozenset({
    "style", "class", "id", "width", "height", "bgcolor",
    "align", "valign", "cellpadding", "cellspacing", "border",
    "color", "face", "size",
})

# Block-level elements that should become newlines in plain-text output
# Note: tr is NOT here — table rows are preserved as HTML, not converted to newlines
_BLOCK_ELEMENTS: frozenset[str] = frozenset({
    "p", "div", "br", "h1", "h2", "h3", "h4", "h5", "h6",
    "li", "dt", "dd",
})

# Table tags whose subtree should be output as raw HTML (not walked as plain text)
_TABLE_TAGS: frozenset[str] = frozenset({"table"})

# Tags whose entire subtree should be removed (noise, not content)
_REMOVE_TAGS: frozenset[str] = frozenset({"style", "script", "head"})


class HtmlExtractor:
    """Strips presentational noise from Outlook HTML while preserving tables.

    Outlook emails are full of inline CSS, style blocks, and script tags that
    inflate token counts without adding meaning. This class removes that noise
    while keeping <table> structure intact so Gemini can parse key-value
    layouts that builders use for job orders.
    """

    def extract(self, html: str) -> str:
        """Strip noise from an HTML email body and return cleaned text.

        Args:
            html: Raw HTML string from the email body.

        Returns:
            Cleaned string with CSS/script noise removed, block elements
            converted to newlines, table HTML preserved, and whitespace
            normalised. Never truncated.
        """
        soup = BeautifulSoup(html, "html.parser")
        self._remove_noise_tags(soup)
        self._strip_style_attributes(soup)
        text = self._render_to_text(soup)
        return self._normalise_whitespace(text)

    def _remove_noise_tags(self, soup: BeautifulSoup) -> None:
        """Remove <style>, <script>, and <head> subtrees entirely.

        Args:
            soup: Parsed BeautifulSoup document, mutated in place.
        """
        for tag_name in _REMOVE_TAGS:
            for tag in soup.find_all(tag_name):
                tag.decompose()

    def _strip_style_attributes(self, soup: BeautifulSoup) -> None:
        """Remove presentational attributes from all remaining tags.

        Keeps structural attributes like href, src, colspan, rowspan.

        Args:
            soup: Parsed BeautifulSoup document, mutated in place.
        """
        for tag in soup.find_all(True):
            if not isinstance(tag, Tag):
                continue
            for attr in _STYLE_ATTRIBUTES:
                tag.attrs.pop(attr, None)

    def _render_to_text(self, soup: BeautifulSoup) -> str:
        """Convert the cleaned soup to a string, inserting newlines for blocks.

        When a <table> tag is encountered, the entire subtree is emitted as
        raw HTML — recursion stops there. This preserves key-value table layouts
        that Gemini needs to parse job order data from Outlook emails.

        All other block elements are replaced with newlines; inline elements
        are transparent (only their text content is emitted).

        Args:
            soup: Cleaned BeautifulSoup document.

        Returns:
            String with tables as HTML and all other content as plain text.
        """
        parts: list[str] = []
        self._walk(soup, parts)
        return "".join(parts)

    def _walk(self, node: BeautifulSoup | Tag, parts: list[str]) -> None:
        """Recursively walk a node, emitting text or HTML as appropriate.

        Args:
            node: The current BeautifulSoup node to process.
            parts: Accumulator list that rendered fragments are appended to.
        """
        from bs4 import NavigableString

        for child in node.children:
            if isinstance(child, NavigableString):
                parts.append(str(child))
                continue
            if not isinstance(child, Tag):
                continue

            tag_name = child.name.lower() if child.name else ""

            if tag_name in _TABLE_TAGS:
                # Emit the entire table as raw HTML — do not recurse into it
                parts.append("\n")
                parts.append(str(child))
                parts.append("\n")
            elif tag_name in ("li", "dt", "dd"):
                parts.append("\n- ")
                self._walk(child, parts)
            elif tag_name in _BLOCK_ELEMENTS:
                parts.append("\n")
                self._walk(child, parts)
            else:
                # Inline element — transparent, just walk children
                self._walk(child, parts)

    def _normalise_whitespace(self, text: str) -> str:
        """Collapse runs of spaces and limit consecutive newlines to two.

        Args:
            text: Raw rendered string.

        Returns:
            Normalised string with clean whitespace.
        """
        # Collapse multiple spaces (but not newlines) to a single space
        text = re.sub(r"[^\S\n]+", " ", text)
        # Limit to 2 consecutive newlines
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
