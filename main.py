import asyncio
import logging
import os
import time

from dotenv import load_dotenv
from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

from db.database import init_db
from cryptorg.client import CryptorgClient, CryptorgError
from bybit.client import BybitClient
from bot.handlers.commands import (
    cmd_new, cmd_active, cmd_stop, cmd_close,
    cmd_cancel, cmd_status, cmd_templates, handle_text_input,
    handle_sel_status, handle_sel_stop, handle_sel_close, handle_sel_cancel,
)
from bot.handlers.callbacks import (
    handle_template_choice, handle_start_bot, handle_cancel_flow,
    handle_edit_params, handle_param_select, handle_set_strategy,
)
from bot.notifications import run_poller

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID", "0"))


def _auth_filter():
    if ALLOWED_USER_ID:
        return filters.User(user_id=ALLOWED_USER_ID)
    return filters.ALL


async def post_init(app: Application):
    await init_db()
    await app.bot.set_my_commands([
        BotCommand("new",       "Start a bot — /new DOGEUSDT"),
        BotCommand("active",    "List active bots"),
        BotCommand("status",    "Status & PnL — /status DOGEUSDT"),
        BotCommand("stop",      "Stop a bot — /stop DOGEUSDT"),
        BotCommand("close",     "Close position at market — /close DOGEUSDT"),
        BotCommand("cancel",    "Cancel deal — /cancel DOGEUSDT"),
        BotCommand("templates", "List templates"),
    ])
    client = CryptorgClient()
    app.bot_data["cryptorg"] = client
    bybit = BybitClient()
    app.bot_data["bybit"] = bybit
    try:
        await client._ensure_auth()
        logger.info("Cryptorg auth OK")
    except CryptorgError as e:
        logger.error("Cryptorg auth failed: %s", e)
        if ALLOWED_USER_ID:
            await app.bot.send_message(chat_id=ALLOWED_USER_ID,
                text=f"Cryptorg login failed:\n`{e}`", parse_mode="Markdown")
    asyncio.create_task(run_poller(app.bot, bybit, client, ALLOWED_USER_ID))


async def post_shutdown(app: Application):
    client: CryptorgClient = app.bot_data.get("cryptorg")
    if client:
        await client.close()
    bybit: BybitClient = app.bot_data.get("bybit")
    if bybit:
        await bybit.close()


def _is_disabled() -> bool:
    value = os.getenv("CRYPTORG_TG_ENABLED", os.getenv("BOT_ENABLED", "true"))
    return value.strip().lower() in {"0", "false", "no", "off", "disabled"}


def main():
    if _is_disabled():
        logger.warning("Cryptorg TG bot is disabled by CRYPTORG_TG_ENABLED/BOT_ENABLED; idling without Telegram polling or Cryptorg/Bybit calls")
        while True:
            time.sleep(3600)

    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_TOKEN is not set")

    auth = _auth_filter()

    app = (
        Application.builder()
        .token(token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("new", cmd_new, filters=auth))
    app.add_handler(CommandHandler("active", cmd_active, filters=auth))
    app.add_handler(CommandHandler("stop", cmd_stop, filters=auth))
    app.add_handler(CommandHandler("close", cmd_close, filters=auth))
    app.add_handler(CommandHandler("cancel", cmd_cancel, filters=auth))
    app.add_handler(CommandHandler("status", cmd_status, filters=auth))
    app.add_handler(CommandHandler("templates", cmd_templates, filters=auth))

    app.add_handler(CallbackQueryHandler(handle_template_choice, pattern=r"^tpl:"))
    app.add_handler(CallbackQueryHandler(handle_edit_params, pattern=r"^edit_params:"))
    app.add_handler(CallbackQueryHandler(handle_param_select, pattern=r"^param:"))
    app.add_handler(CallbackQueryHandler(handle_set_strategy, pattern=r"^set_strategy:"))
    app.add_handler(CallbackQueryHandler(handle_start_bot, pattern=r"^start:"))
    app.add_handler(CallbackQueryHandler(handle_cancel_flow, pattern=r"^cancel_flow$"))
    app.add_handler(CallbackQueryHandler(handle_sel_status, pattern=r"^sel_status:"))
    app.add_handler(CallbackQueryHandler(handle_sel_stop, pattern=r"^sel_stop:"))
    app.add_handler(CallbackQueryHandler(handle_sel_close, pattern=r"^sel_close:"))
    app.add_handler(CallbackQueryHandler(handle_sel_cancel, pattern=r"^sel_cancel:"))

    app.add_handler(MessageHandler(auth & filters.TEXT & ~filters.COMMAND, handle_text_input))

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
