import time

from git import Repo, GitCommandError

from src.config import Config, logger


class GitSync:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        repo_path = self.cfg.git_repo_path

        if repo_path is None:
            return

        auth_url = cfg.git_repo_url
        if cfg.git_token and cfg.git_repo_url:
            auth_url = cfg.git_repo_url.replace(
                "https://",
                f"https://{cfg.git_token}@"
            )

        if not repo_path.exists():
            logger.info("Cloning repository into new directory...")
            self.repo = Repo.clone_from(
                auth_url,
                repo_path,
                branch=cfg.git_branch,
            )
        elif (repo_path / ".git").exists():
            logger.info("Using existing repository...")
            self.repo = Repo(repo_path)
        else:
            entries = list(repo_path.iterdir())
            if entries:
                raise RuntimeError(
                    f"Directory '{repo_path}' exists, is not a git repository, "
                    f"and is not empty"
                )
            logger.info("Cloning repository into existing empty directory...")
            self.repo = Repo.clone_from(
                auth_url,
                repo_path,
                branch=cfg.git_branch,
            )

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

    def pull(self) -> bool:
        if not self.cfg.git_auto_commit or not self.cfg.git_repo_path:
            return True

        origin = self.repo.remote(self.cfg.git_remote)

        for attempt in range(1, 4):
            try:
                origin.pull(self.cfg.git_branch, rebase=True)
                return True
            except GitCommandError as e:
                text = str(e)
                is_temporary_resource_error = (
                        "cannot fork" in text
                        or "Resource temporarily unavailable" in text
                )

                if not is_temporary_resource_error or attempt == 3:
                    logger.exception("Git pull failed")
                    return False

                delay = 10 * attempt
                logger.warning(
                    "Git pull failed due to temporary resource issue, retrying in %s seconds",
                    delay,
                )
                time.sleep(delay)
            except Exception:
                logger.exception("Git pull failed")
                return False

        return False

    def sync(self, reason: str) -> None:
        if not self.cfg.git_auto_commit or not self.cfg.git_repo_path:
            return

        self.repo.git.add(self.cfg.markdown_file.as_posix())
        if not self.repo.is_dirty(untracked_files=True):
            return

        self.repo.index.commit(f"bot: update Habr bookmarks ({reason})")

        try:
            self.repo.remote(self.cfg.git_remote).push(self.cfg.git_branch)
        except Exception as e:
            logger.exception(f"Git push failed {e}")
