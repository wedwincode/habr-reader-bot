import asyncio
import html
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional
from urllib.parse import urljoin, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup
from git import Repo
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("habr_reader_bot")

TASK_RE = re.compile(r"^(?P<indent>\s*)- \[(?P<done>[ xX])\] \[(?P<title>.+?)\]\((?P<url>https?://[^)]+)\)\s*$")
URL_RE = re.compile(r"\((https?://[^)]+)\)")


@dataclass
class Config:
    telegram_token: str
    telegram_chat_id: int
    markdown_file: Path
    habr_source_url: str
    reminder_hour: int = 20
    reminder_minute: int = 0
    timezone_name: str = "Europe/Berlin"
    sync_interval_minutes: int = 30
    git_repo_path: Optional[Path] = None
    git_auto_commit: bool = False
    git_branch: str = "main"
    git_remote: str = "origin"
    habr_cookie_header: Optional[str] = None
    user_agent: str = "Mozilla/5.0 (X11; Linux aarch64) HabrReaderBot/1.0"

    @classmethod
    def from_env(cls) -> "Config":
        telegram_token = required_env("TELEGRAM_BOT_TOKEN")
        telegram_chat_id = int(required_env("TELEGRAM_CHAT_ID"))
        markdown_file = Path(required_env("MARKDOWN_FILE")).expanduser().resolve()
        habr_source_url = required_env("HABR_SOURCE_URL")
        git_repo_raw = os.getenv("GIT_REPO_PATH", "").strip()
        git_repo_path = Path(git_repo_raw).expanduser().resolve() if git_repo_raw else None
        return cls(
            telegram_token=telegram_token,
            telegram_chat_id=telegram_chat_id,
            markdown_file=markdown_file,
            habr_source_url=habr_source_url,
            reminder_hour=int(os.getenv("REMINDER_HOUR", "20")),
            reminder_minute=int(os.getenv("REMINDER_MINUTE", "0")),
            timezone_name=os.getenv("TZ", "Europe/Berlin"),
            sync_interval_minutes=int(os.getenv("SYNC_INTERVAL_MINUTES", "30")),
            git_repo_path=git_repo_path,
            git_auto_commit=os.getenv("GIT_AUTO_COMMIT", "false").lower() == "true",
            git_branch=os.getenv("GIT_BRANCH", "main"),
            git_remote=os.getenv("GIT_REMOTE", "origin"),
            habr_cookie_header=os.getenv("HABR_COOKIE_HEADER", "").strip() or None,
            user_agent=os.getenv(
                "USER_AGENT",
                "Mozilla/5.0 (X11; Linux aarch64) HabrReaderBot/1.0",
            ),
        )


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Environment variable {name} is required")
    return value


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

    def first_unread(self) -> Optional[Article]:
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


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    return parsed._replace(query="", fragment="").geturl().rstrip("/")


def escape_title(title: str) -> str:
    return title.replace("]", r"\]")


class HabrSource:
    def __init__(self, source_url: str, cookie_header: Optional[str], user_agent: str):
        self.source_url = source_url
        self.cookie_header = cookie_header
        self.user_agent = user_agent

    def fetch_articles(self) -> List[Article]:
        if self._looks_like_feed(self.source_url):
            return self._fetch_rss(self.source_url)
        return self._fetch_html(self.source_url)

    @staticmethod
    def _looks_like_feed(url: str) -> bool:
        lower = url.lower()
        return any(token in lower for token in ["rss", "feed", ".xml", "atom"])

    def _headers(self) -> dict:
        headers = {"User-Agent": self.user_agent}
        if self.cookie_header:
            headers["Cookie"] = self.cookie_header
        return headers

    def _fetch_rss(self, url: str) -> List[Article]:
        parsed = feedparser.parse(url, request_headers=self._headers())
        articles: List[Article] = []
        for entry in parsed.entries:
            link = getattr(entry, "link", "")
            title = html.unescape(getattr(entry, "title", "")).strip()
            if link and title:
                articles.append(Article(title=title, url=link))
        return dedupe_articles(articles)

    def _fetch_html(self, url: str) -> List[Article]:
        response = requests.get(url, headers=self._headers(), timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        anchors = soup.select("a.tm-title__link, a.tm-article-snippet__title-link, h2 a, h1 a")
        articles: List[Article] = []
        for a in anchors:
            href = (a.get("href") or "").strip()
            title = a.get_text(" ", strip=True)
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


def dedupe_articles(articles: Iterable[Article]) -> List[Article]:
    seen: set[str] = set()
    result: List[Article] = []
    for article in articles:
        key = normalize_url(article.url)
        if key in seen:
            continue
        seen.add(key)
        result.append(Article(title=article.title, url=article.url))
    return result


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


class AppState:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.store = MarkdownStore(cfg.markdown_file)
        self.source = HabrSource(cfg.habr_source_url, cfg.habr_cookie_header, cfg.user_agent)
        self.git_sync = GitSync(cfg)

    def sync_habr(self) -> int:
        articles = self.source.fetch_articles()
        existing = {normalize_url(u) for u in self.store.existing_urls()}
        new_articles = [a for a in articles if normalize_url(a.url) not in existing]
        added = self.store.prepend_articles(new_articles)
        if added:
            self.git_sync.sync(reason=f"sync {added}")
        return added

    def get_next_article(self) -> Optional[Article]:
        return self.store.first_unread()

    def mark_article_as_read(self, url: str) -> bool:
        changed = self.store.mark_read_by_url(url)
        if changed:
            self.git_sync.sync(reason="mark-read")
        return changed


def build_article_message(article: Article) -> str:
    return f"Прочитай статью\n\n{article.title}\n{article.url}"


def build_article_keyboard(article: Article) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Я прочитал", callback_data=f"read|{article.url}")]]
    )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "Команды:\n"
        "/next - показать следующую непрочитанную статью\n"
        "/sync - подтянуть свежие закладки из Habr\n"
        "/done <url> - отметить статью прочитанной"
    )


async def cmd_next(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state: AppState = context.application.bot_data["state"]
    article = state.get_next_article()
    if not article:
        await update.effective_message.reply_text("Непрочитанных статей не осталось")
        return
    await update.effective_message.reply_text(
        build_article_message(article),
        reply_markup=build_article_keyboard(article),
        disable_web_page_preview=False,
    )


async def cmd_sync(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state: AppState = context.application.bot_data["state"]
    try:
        added = await asyncio.to_thread(state.sync_habr)
    except Exception as exc:
        logger.exception("sync failed")
        await update.effective_message.reply_text(f"Ошибка синхронизации: {exc}")
        return
    await update.effective_message.reply_text(f"Синхронизация завершена, добавлено: {added}")


async def cmd_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state: AppState = context.application.bot_data["state"]
    if not context.args:
        await update.effective_message.reply_text("Передай URL: /done https://habr.com/ru/articles/123/")
        return
    url = context.args[0]
    changed = await asyncio.to_thread(state.mark_article_as_read, url)
    if changed:
        await update.effective_message.reply_text("Отметил как прочитанное")
    else:
        await update.effective_message.reply_text("Статья в файле не найдена")


async def on_read_clicked(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    state: AppState = context.application.bot_data["state"]
    _, url = (query.data or "|").split("|", 1)
    changed = await asyncio.to_thread(state.mark_article_as_read, url)
    if not changed:
        await query.edit_message_text("Не удалось отметить статью: запись не найдена в markdown")
        return
    next_article = state.get_next_article()
    if next_article:
        await query.edit_message_text(
            "Отметил как прочитанное. Следующая статья:\n\n"
            f"{next_article.title}\n{next_article.url}",
            reply_markup=build_article_keyboard(next_article),
            disable_web_page_preview=False,
        )
    else:
        await query.edit_message_text("Готово. Непрочитанных статей больше нет")


async def reminder_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    state: AppState = context.application.bot_data["state"]
    article = await asyncio.to_thread(state.get_next_article)
    if not article:
        return
    await context.bot.send_message(
        chat_id=state.cfg.telegram_chat_id,
        text=build_article_message(article),
        reply_markup=build_article_keyboard(article),
        disable_web_page_preview=False,
    )


async def sync_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    state: AppState = context.application.bot_data["state"]
    try:
        added = await asyncio.to_thread(state.sync_habr)
        if added:
            logger.info("sync job added %s article(s)", added)
    except Exception:
        logger.exception("background sync failed")


async def post_init(app: Application) -> None:
    state: AppState = app.bot_data["state"]
    await asyncio.to_thread(state.sync_habr)
    app.job_queue.run_daily(
        reminder_job,
        time=datetime.now().astimezone().replace(
            hour=state.cfg.reminder_hour,
            minute=state.cfg.reminder_minute,
            second=0,
            microsecond=0,
        ).timetz(),
        chat_id=state.cfg.telegram_chat_id,
        name="daily-reminder",
    )
    app.job_queue.run_repeating(
        sync_job,
        interval=state.cfg.sync_interval_minutes * 60,
        first=30,
        name="habr-sync",
    )
    logger.info("jobs scheduled")


def main() -> None:
    cfg = Config.from_env()
    cfg.markdown_file.parent.mkdir(parents=True, exist_ok=True)
    state = AppState(cfg)

    app = (
        Application.builder()
        .token(cfg.telegram_token)
        .post_init(post_init)
        .build()
    )
    app.bot_data["state"] = state

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("next", cmd_next))
    app.add_handler(CommandHandler("sync", cmd_sync))
    app.add_handler(CommandHandler("done", cmd_done))
    app.add_handler(CallbackQueryHandler(on_read_clicked, pattern=r"^read\|"))

    logger.info("bot started")
    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
