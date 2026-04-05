import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("habr_reader_bot")


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
            timezone_name=os.getenv("TZ", "Europe/Moscow"),
            sync_interval_minutes=int(os.getenv("SYNC_INTERVAL_MINUTES", "30")),
            git_repo_path=git_repo_path,
            git_auto_commit=os.getenv("GIT_AUTO_COMMIT", "false").lower() == "true",
            git_branch=os.getenv("GIT_BRANCH", "main"),
            git_remote=os.getenv("GIT_REMOTE", "origin"),
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
