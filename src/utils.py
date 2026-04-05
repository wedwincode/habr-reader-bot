from urllib.parse import urlparse


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    return parsed._replace(query="", fragment="").geturl().rstrip("/")

def escape_title(title: str) -> str:
    return title.replace("]", r"\]")
