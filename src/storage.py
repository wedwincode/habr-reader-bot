import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from git import Repo

from config import Config, logger
from utils import normalize_url, escape_title

TASK_RE = re.compile(r"^(?P<indent>\s*)- \[(?P<done>[ xX])] \[(?P<title>.+?)]\((?P<url>https?://[^)]+)\)\s*$")
URL_RE = re.compile(r"\((https?://[^)]+)\)")


class GitSync:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def sync(self, reason: str) -> None:
        if not self.cfg.git_auto_commit or not self.cfg.git_repo_path:
            return
        repo = Repo(self.cfg.git_repo_path)
        repo.git.add(self.cfg.markdown_file.as_posix())
        if not repo.is_dirty(untracked_files=True):
            return
        repo.index.commit(f"bot: update Habr bookmarks ({reason})")
        try:
            repo.remote(self.cfg.git_remote).push(self.cfg.git_branch)
        except Exception:
            logger.exception("Git push failed")


@dataclass
class Article:
    title: str
    url: str


class MarkdownStore:
    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            self.file_path.write_text("", encoding="utf-8")

    def read_text(self) -> str:
        return self.file_path.read_text(encoding="utf-8")

    def write_text(self, content: str) -> None:
        self.file_path.write_text(content, encoding="utf-8")

    def existing_urls(self) -> set[str]:
        return {match.group(1) for match in URL_RE.finditer(self.read_text())}

    def prepend_articles(self, articles: Iterable[Article]) -> int:
        new_articles = list(articles)
        if not new_articles:
            return 0
        current = self.read_text()
        block = "\n".join(f"- [ ] [{escape_title(a.title)}]({a.url})" for a in new_articles)
        new_content = f"{block}\n{current}" if current else f"{block}\n"
        self.write_text(new_content)
        return len(new_articles)

    def first_unread(self) -> Article | None:
        for line in self.read_text().splitlines():
            match = TASK_RE.match(line)
            if match and match.group("done") == " ":
                return Article(title=match.group("title"), url=match.group("url"))
        return None

    def mark_read_by_url(self, url: str) -> bool:
        lines = self.read_text().splitlines()
        changed = False
        for i, line in enumerate(lines):
            match = TASK_RE.match(line)
            if not match:
                continue
            if normalize_url(match.group("url")) == normalize_url(url):
                lines[i] = f"{match.group('indent')}- [x] [{match.group('title')}]({match.group('url')})"
                changed = True
                break
        if changed:
            self.write_text("\n".join(lines) + ("\n" if lines else ""))
        return changed
