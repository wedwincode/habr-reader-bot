import asyncio

from src.config import Config
from src.habr import HabrSource
from src.sync import GitSync
from src.store import MarkdownStore, Article
from src.utils import normalize_url


class AppState:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.store = MarkdownStore(cfg.markdown_file)
        self.source = HabrSource(cfg.habr_source_url, cfg.user_agent)
        self.git_sync = GitSync(cfg)
        self._sync_lock = asyncio.Lock()

    async def sync_habr_safe(self) -> int:
        async with self._sync_lock:
            return await asyncio.to_thread(self.sync_habr)

    def sync_habr(self) -> int:
        articles = self.source.fetch_articles()
        existing = self.store.existing_urls()
        new_articles = [a for a in articles if normalize_url(a.url) not in existing]
        self.git_sync.pull()
        added = self.store.add_new_articles(new_articles)
        if added:
            self.git_sync.sync(reason=f"sync {added}")
        return added

    def get_next_article(self) -> Article | None:
        self.git_sync.pull()
        return self.store.first_unread()

    def mark_article_as_read(self, url: str) -> bool:
        self.git_sync.pull()
        changed = self.store.mark_read_by_url(url)
        if changed:
            self.git_sync.sync(reason="mark-read")
        return changed
