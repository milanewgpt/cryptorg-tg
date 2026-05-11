import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import select

from db.database import get_session_factory
from db.models import Template, RunningBot
from cryptorg.client import CryptorgClient, CryptorgError

logger = logging.getLogger(__name__)


def _factory():
    return get_session_factory()


async def handle_template_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback: tpl:<cryptorg_bot_id>:<pair>"""
    query = update.callback_query
    await query.answer()

    _, bot_id_str, pair = query.data.split(":", 2)
    cryptorg_bot_id = int(bot_id_str)

    client: CryptorgClient = context.bot_data["cryptorg"]
    try:
        bot_data = await client.get_bot(cryptorg_bot_id)
    except CryptorgError as e:
        await query.edit_message_text(f"Ошибка получения шаблона:\n`{e}`", parse_mode="Markdown")
        return

    title = bot_data.get("title", f"Bot {cryptorg_bot_id}")
    current_pairs = ", ".join(bot_data.get("pairs", ["—"]))

    text = (
        f"*{title}*\n"
        f"Текущая пара: {current_pairs}\n"
        f"Новая пара: *{pair}*\n\n"
        f"Запустить?"
    )
    buttons = [
        [
            InlineKeyboardButton("START ✅", callback_data=f"start:{cryptorg_bot_id}:{pair}"),
            InlineKeyboardButton("CANCEL ❌", callback_data="cancel_flow"),
        ]
    ]
    await query.edit_message_text(
        text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown"
    )


async def handle_start_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback: start:<template_bot_id>:<pair>

    Flow:
    1. Clone template → new bot with target pair (POST /crazy/api/bots)
    2. Activate new bot (start) — deal opens automatically
    3. GET deals to confirm deal_id
    4. Store RunningBot in DB
    """
    query = update.callback_query
    await query.answer()

    _, bot_id_str, pair = query.data.split(":", 2)
    template_bot_id = int(bot_id_str)
    user_id = update.effective_user.id

    await query.edit_message_text(f"Запускаю *{pair}*...", parse_mode="Markdown")

    client: CryptorgClient = context.bot_data["cryptorg"]
    new_bot_id = None
    try:
        # 1. Get template title
        tpl_config = await client.get_bot(template_bot_id)
        tpl_title = tpl_config.get("title", f"Bot {template_bot_id}")

        # 2. Clone template with new pair
        new_bot = await client.clone_bot(template_bot_id, pair)
        new_bot_id = new_bot["id"]

        # 3. Activate new bot (auto-opens deal)
        await client.start_bot(new_bot_id)

        # 4. Wait and fetch deal
        await asyncio.sleep(3)
        deals = await client.get_deals(bot_id=new_bot_id, active=True)
        deal = deals[0] if deals else {}
        deal_id = deal.get("id")
        actual_pair = deal.get("pair", pair)

        # 6. Find matching DB template (optional)
        async with _factory()() as session:
            db_tpl = (await session.execute(
                select(Template).where(Template.cryptorg_bot_id == template_bot_id)
            )).scalar_one_or_none()
            template_id = db_tpl.id if db_tpl else None

            running = RunningBot(
                telegram_user=user_id,
                template_id=template_id,
                cryptorg_bot_id=new_bot_id,
                deal_id=deal_id,
                pair=actual_pair,
                status="active",
            )
            session.add(running)
            await session.commit()

        await query.edit_message_text(
            f"*Бот запущен*\n"
            f"Пара: *{actual_pair}*\n"
            f"Шаблон: {tpl_title}\n"
            f"Bot ID: `{new_bot_id}`\n"
            f"Deal ID: `{deal_id or '—'}`",
            parse_mode="Markdown",
        )
    except CryptorgError as e:
        if new_bot_id:
            try:
                await client.delete_bot(new_bot_id)
            except Exception:
                pass
        await query.edit_message_text(
            f"*Ошибка Cryptorg*\n`{e}`", parse_mode="Markdown"
        )


async def handle_cancel_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Отменено.")
