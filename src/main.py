from src.app import AppState
from src.config import Config
from src.tg import TgApp


def main() -> None:
    cfg = Config.from_env()
    state = AppState(cfg)

    tg_app = TgApp(state)
    tg_app.start()


if __name__ == "__main__":
    main()
