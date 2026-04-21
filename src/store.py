import re
from pathlib import Path
from typing import Iterable

from src.habr import Article
from src.utils import normalize_url, escape_title, extract_habr_article_id

TASK_RE = re.compile(r"^(?P<indent>\s*)- \[(?P<done>[ xX])]\s+\[(?P<title>.+?)]\((?P<url>https?://[^)]+)\)\s*$")
URL_RE = re.compile(r"\((https?://[^)]+)\)")


class MarkdownStore:
    def __init__(self, file_path: Path):
        self.file_path = file_path
        # self.file_path.parent.mkdir(parents=True, exist_ok=True)
        # if not self.file_path.exists():
        #     self.file_path.write_text("", encoding="utf-8")

    def _read_text(self) -> str:
        return self.file_path.read_text(encoding="utf-8")

    def _write_text(self, content: str) -> None:
        self.file_path.write_text(content, encoding="utf-8")

    def existing_urls(self) -> set[str]:
        return {normalize_url(match.group(1)) for match in URL_RE.finditer(self._read_text())}

    def add_new_articles(self, articles: Iterable[Article]) -> int:
        new_articles = list(articles)
        if not new_articles:
            return 0
        current = self._read_text()
        block = "\n".join(f"- [ ]  [{escape_title(a.title)}]({a.url})" for a in new_articles)
        new_content = f"{block}\n{current}" if current else f"{block}\n"
        self._write_text(new_content)
        return len(new_articles)

    def first_unread(self) -> Article | None:
        for line in self._read_text().splitlines():
            match = TASK_RE.match(line)
            if match and match.group("done") == " ":
                return Article(title=match.group("title"), url=match.group("url"))
        return None

    def mark_read_by_habr_id(self, article_id: str) -> bool:
        lines = self._read_text().splitlines()
        changed = False
        for i, line in enumerate(lines):
            match = TASK_RE.match(line)
            if not match:
                continue

            current_id = extract_habr_article_id(match.group("url"))
            if current_id == article_id:
                lines[i] = f"{match.group('indent')}- [x]  [{match.group('title')}]({match.group('url')})"
                changed = True
                break
        if changed:
            self._write_text("\n".join(lines) + ("\n" if lines else ""))
        return changed
