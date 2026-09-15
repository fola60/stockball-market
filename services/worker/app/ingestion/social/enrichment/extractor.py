from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html import unescape

from bs4 import BeautifulSoup, Tag

_SPACE = re.compile(r"\s+")
_MINIMUM_ARTICLE_CHARACTERS = 200
_MAXIMUM_ARTICLE_CHARACTERS = 100_000


@dataclass(frozen=True)
class ArticleExtraction:
    text: str
    method: str


def extract_article_text(content: bytes) -> ArticleExtraction | None:
    soup = BeautifulSoup(content, "html.parser")
    candidates: list[ArticleExtraction] = []
    candidates.extend(_json_ld_candidates(soup))
    for selector, method in (("article", "article_element"), ("main", "main_element")):
        for element in soup.select(selector):
            text = _paragraph_text(element)
            if text:
                candidates.append(ArticleExtraction(text, method))
    if not candidates:
        return None
    best = max(candidates, key=lambda candidate: len(candidate.text))
    if len(best.text) < _MINIMUM_ARTICLE_CHARACTERS:
        return None
    return ArticleExtraction(best.text[:_MAXIMUM_ARTICLE_CHARACTERS], best.method)


def _json_ld_candidates(soup: BeautifulSoup) -> list[ArticleExtraction]:
    candidates: list[ArticleExtraction] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            payload = json.loads(script.string or script.get_text())
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        for value in _walk_json(payload):
            body = value.get("articleBody")
            if isinstance(body, str):
                text = _normalize(body)
                if text:
                    candidates.append(ArticleExtraction(text, "json_ld_article_body"))
    return candidates


def _walk_json(value: object):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_json(child)


def _paragraph_text(element: Tag) -> str:
    copy = BeautifulSoup(str(element), "html.parser")
    for unwanted in copy.select(
        "script, style, nav, header, footer, aside, form, noscript, svg, "
        "[aria-hidden='true'], [data-component='ad-slot']"
    ):
        unwanted.decompose()
    paragraphs = [_normalize(paragraph.get_text(" ", strip=True)) for paragraph in copy.find_all("p")]
    return "\n".join(paragraph for paragraph in paragraphs if paragraph)


def _normalize(value: str) -> str:
    return _SPACE.sub(" ", unescape(value)).strip()
