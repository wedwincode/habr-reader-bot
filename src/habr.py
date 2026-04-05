from typing import Iterable
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from storage import Article
from utils import normalize_url


class HabrSource:
    def __init__(self, source_url: str, user_agent: str):
        self.source_url = source_url
        self.user_agent = user_agent

    def fetch_articles(self) -> list[Article]:
        response = requests.get(self.source_url, headers={"User-Agent": self.user_agent}, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        anchors = soup.select("a.tm-title__link, a.tm-article-snippet__title-link, h2 a, h1 a")
        articles: list[Article] = []
        for a in anchors:
            href = (a.get("href") or "").strip()
            title = a.get_text(separator=" ", strip=True) # todo
            if not href or not title:
                continue
            full_url = urljoin(response.url, href)
            parsed = urlparse(full_url)
            if "habr.com" not in parsed.netloc:
                continue
            if "/articles/" not in parsed.path:
                continue
            articles.append(Article(title=title, url=normalize_url(full_url) + "/"))
        return dedupe_articles(articles)


def dedupe_articles(articles: Iterable[Article]) -> list[Article]:
    seen: set[str] = set()
    result: list[Article] = []
    for article in articles:
        key = normalize_url(article.url)
        if key in seen:
            continue
        seen.add(key)
        result.append(Article(title=article.title, url=article.url))
    return result
