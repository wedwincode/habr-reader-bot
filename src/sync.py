from git import Repo

from src.config import Config, logger


class GitSync:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        repo_path = self.cfg.git_repo_path

        auth_url = cfg.git_repo_url
        if cfg.git_token and cfg.git_repo_url:
            auth_url = cfg.git_repo_url.replace(
                "https://",
                f"https://{cfg.git_token}@"
            )

        if not repo_path.exists() or not (repo_path / ".git").exists():
            logger.info("Cloning repository...")
            self.repo = Repo.clone_from(
                auth_url,
                repo_path,
                branch=cfg.git_branch,
            )
        else:
            self.repo = Repo(repo_path)

        with self.repo.config_writer() as cw:
            cw.set_value("user", "name", "habr-bot")
            cw.set_value("user", "email", "bot@wedwin.ru")

        try:
            self.repo.git.remote(
                "set-url",
                self.cfg.git_remote,
                auth_url
            )
        except Exception:
            self.repo.git.remote(
                "add",
                self.cfg.git_remote,
                auth_url
            )

    def sync(self, reason: str) -> None:
        if not self.cfg.git_auto_commit or not self.cfg.git_repo_path:
            return
        origin = self.repo.remote(self.cfg.git_remote)

        try:
            origin.pull(self.cfg.git_branch, rebase=True)
        except Exception as e:
            logger.exception(f"Git pull failed {e}")
            return

        self.repo.git.add(self.cfg.markdown_file.as_posix())
        if not self.repo.is_dirty(untracked_files=True):
            return
        self.repo.index.commit(f"bot: update Habr bookmarks ({reason})")
        try:
            self.repo.remote(self.cfg.git_remote).push(self.cfg.git_branch)
        except Exception as e:
            logger.exception(f"Git push failed {e}")
