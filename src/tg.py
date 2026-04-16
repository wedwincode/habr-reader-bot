import asyncio
from datetime import datetime

from telegram import InlineKeyboardMarkup, InlineKeyboardButton, Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ContextTypes, Application, CommandHandler, CallbackQueryHandler

from src.config import logger
from src.app import AppState
from src.habr import Article


class TgApp:
    def __init__(self, state: AppState):
        self._state = state
        self._build_app()
        self._init_handlers()

    def start(self):
        self._app.run_polling(close_loop=False)
        logger.info("bot started")

    def stop(self):
        self._app.stop_running()
        logger.info("bot stopped")

    def _build_app(self):
        self._app = (Application.builder()
                     .token(self._state.cfg.telegram_token)
                     .post_init(schedule)
                     .build())
        self._app.bot_data["state"] = self._state

    def _init_handlers(self):
        self._app.add_handler(CommandHandler("start", cmd_start))
        self._app.add_handler(CommandHandler("next", cmd_next))
        self._app.add_handler(CommandHandler("sync", cmd_sync))
        self._app.add_handler(CommandHandler("done", cmd_done))
        self._app.add_handler(CallbackQueryHandler(on_read_clicked, pattern=r"^read\|"))


def build_article_message(article: Article) -> str:
    return f"Прочитай статью\n\n{article.title}\n{article.url}"


def build_article_inline_keyboard(article: Article) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Я прочитал", callback_data=f"read|{article.url}")]]
    )

def build_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([
            [KeyboardButton("/next"), KeyboardButton("/sync")],
        ],
        resize_keyboard=True
    )

async def cmd_start(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "Команды:\n"
        "/next - показать следующую непрочитанную статью\n"
        "/sync - подтянуть свежие закладки из Habr\n"
        "/done <url> - отметить статью прочитанной",
        reply_markup=build_main_keyboard()
    )


async def cmd_next(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state: AppState = context.application.bot_data["state"]

    status_message = await update.effective_message.reply_text("Получаю следующую статью...")

    article = state.get_next_article()
    if not article:
        await status_message.edit_text("Непрочитанных статей не осталось")
        return
    await status_message.edit_text(
        build_article_message(article),
        reply_markup=build_article_inline_keyboard(article),
        disable_web_page_preview=False,
    )


async def cmd_sync(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state: AppState = context.application.bot_data["state"]

    status_message = await update.effective_message.reply_text("Синхронизируюсь...")

    try:
        added = await state.sync_habr_safe()
    except Exception as exc:
        logger.exception("sync failed")
        await status_message.edit_text(f"Ошибка синхронизации: {exc}")
        return
    await status_message.edit_text(f"Синхронизация завершена, добавлено: {added}")


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
    state: AppState = context.application.bot_data["state"]

    query = update.callback_query
    await query.edit_message_reply_markup(reply_markup=None)
    await query.answer()

    status_message = await update.effective_message.reply_text("Отмечаю статью как прочитанную...")

    _, url = (query.data or "|").split("|", 1)
    changed = await asyncio.to_thread(state.mark_article_as_read, url)
    if not changed:
        await status_message.edit_text("Не удалось отметить статью: запись не найдена в markdown")
        return
    next_article = state.get_next_article()
    if next_article:
        await status_message.edit_text("Готово. Статья отмечена как прочитанная.")
        await context.bot.send_message(
            chat_id=state.cfg.telegram_chat_id,
            text="Если хочешь получить еще одну статью, отправь /next",
        )
    else:
        await status_message.edit_text("Готово. Непрочитанных статей больше нет")


async def reminder_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    state: AppState = context.application.bot_data["state"]
    article = await asyncio.to_thread(state.get_next_article)  # todo lock
    if not article:
        return
    await context.bot.send_message(
        chat_id=state.cfg.telegram_chat_id,
        text=build_article_message(article),
        reply_markup=build_article_inline_keyboard(article),
        disable_web_page_preview=False,
    )


async def sync_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    state: AppState = context.application.bot_data["state"]
    try:
        added = await state.sync_habr_safe()
        if added:
            logger.info("sync job added %s article(s)", added)
    except Exception as e:
        logger.exception(f"background sync failed: {e}")


async def schedule(app: Application) -> None:
    state: AppState = app.bot_data["state"]
    await state.sync_habr_safe()
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
