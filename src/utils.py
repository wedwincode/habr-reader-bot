import re
from urllib.parse import urlparse

HABR_ARTICLE_ID_RE = re.compile(r"/articles/(?P<id>\d+)/?$")

def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    return parsed._replace(query="", fragment="").geturl().rstrip("/")

def escape_title(title: str) -> str:
    return title.replace("]", r"\]")

def extract_habr_article_id(url: str) -> str | None:
    normalized = normalize_url(url)
    parsed = urlparse(normalized)
    match = HABR_ARTICLE_ID_RE.search(parsed.path)
    if not match:
        return None
    return match.group("id")