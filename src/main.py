from app import AppState
from config import Config
from src.tg import TgApp


def main() -> None:
    cfg = Config.from_env()
    cfg.markdown_file.parent.mkdir(parents=True, exist_ok=True)
    state = AppState(cfg)

    tg_app = TgApp(state)
    tg_app.start()


if __name__ == "__main__":
    main()
