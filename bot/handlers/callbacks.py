import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import select

from db.database import get_session_factory
from db.models import Template, RunningBot
from cryptorg.client import CryptorgClient, CryptorgError
from bot.handlers.param_utils import (
    extract_params, get_display_params,
    format_params_text, make_edit_buttons, STRATEGY_RU,
)

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
    original_params = extract_params(bot_data)

    context.user_data["edit_state"] = {
        "template_id": cryptorg_bot_id,
        "pair": pair,
        "title": title,
        "original_params": original_params,
        "custom_overrides": {},
    }

    display_params = get_display_params(context.user_data["edit_state"])
    text = format_params_text(title, pair, display_params)
    text += "\n\nЗапустить или изменить параметры?"

    buttons = [
        [
            InlineKeyboardButton("Запустить ✅", callback_data=f"start:{cryptorg_bot_id}:{pair}"),
            InlineKeyboardButton("Изменить ⚙️", callback_data=f"edit_params:{cryptorg_bot_id}:{pair}"),
        ],
        [InlineKeyboardButton("Отмена ❌", callback_data="cancel_flow")],
    ]
    await query.edit_message_text(
        text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown"
    )


async def handle_edit_params(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback: edit_params:<tpl_id>:<pair> — show param edit keyboard."""
    query = update.callback_query
    await query.answer()

    state = context.user_data.get("edit_state", {})
    tpl_id = state.get("template_id")
    pair = state.get("pair")
    title = state.get("title", "")

    if not tpl_id or not pair:
        await query.edit_message_text("Ошибка: состояние не найдено.")
        return

    display_params = get_display_params(state)
    text = format_params_text(title, pair, display_params)
    text += "\n\nВыберите параметр для изменения:"
    kb = make_edit_buttons(display_params, tpl_id, pair)
    await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")


async def handle_param_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback: param:<field> — prompt for new value or show strategy buttons."""
    query = update.callback_query
    await query.answer()

    field = query.data.split(":", 1)[1]
    state = context.user_data.get("edit_state", {})

    if field == "strategy":
        tpl_id = state.get("template_id")
        pair = state.get("pair")
        buttons = [
            [
                InlineKeyboardButton("📈 Лонг", callback_data=f"set_strategy:{tpl_id}:{pair}:long"),
                InlineKeyboardButton("📉 Шорт", callback_data=f"set_strategy:{tpl_id}:{pair}:short"),
            ]
        ]
        await query.edit_message_text("Выберите стратегию:", reply_markup=InlineKeyboardMarkup(buttons))
        return

    FIELD_LABELS = {
        "volume":    "Вход (USDT) — объём первого и страховочных ордеров",
        "so_step":   "Шаг страховочных ордеров (%)",
        "step_mult": "Множитель шага цены СО",
        "vol_mult":  "Множитель объёма СО (Martingale)",
        "tp":        "Тейк Профит (%)",
        "cycles":    "Количество циклов (целое число, 0 = без лимита)",
    }
    label = FIELD_LABELS.get(field, field)
    context.user_data["editing_field"] = field

    await query.edit_message_text(f"Введите значение для:\n*{label}*", parse_mode="Markdown")


async def handle_set_strategy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback: set_strategy:<tpl_id>:<pair>:<strategy>"""
    query = update.callback_query
    await query.answer()

    parts = query.data.split(":")
    # set_strategy:<tpl_id>:<pair>:<strategy>
    _, tpl_id_str, pair, strategy = parts[0], parts[1], parts[2], parts[3]
    tpl_id = int(tpl_id_str)

    state = context.user_data.get("edit_state", {})
    state.setdefault("custom_overrides", {})["strategy"] = strategy
    title = state.get("title", f"Bot {tpl_id}")

    display_params = get_display_params(state)
    text = format_params_text(title, pair, display_params)
    text += "\n\nВыберите параметр для изменения:"
    kb = make_edit_buttons(display_params, tpl_id, pair)
    await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")


async def handle_start_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback: start:<template_bot_id>:<pair>"""
    query = update.callback_query
    await query.answer()

    _, bot_id_str, pair = query.data.split(":", 2)
    template_bot_id = int(bot_id_str)
    user_id = update.effective_user.id

    await query.edit_message_text(f"Запускаю *{pair}*...", parse_mode="Markdown")

    state = context.user_data.get("edit_state", {})
    overrides = state.get("custom_overrides") or {}

    client: CryptorgClient = context.bot_data["cryptorg"]
    new_bot_id = None
    try:
        tpl_config = await client.get_bot(template_bot_id)
        tpl_title = tpl_config.get("title", f"Bot {template_bot_id}")

        new_bot = await client.clone_bot(template_bot_id, pair, overrides=overrides or None)
        new_bot_id = new_bot["id"]

        await client.start_bot(new_bot_id)

        await asyncio.sleep(3)
        deals = await client.get_deals(bot_id=new_bot_id, active=True)
        deal = deals[0] if deals else {}
        deal_id = deal.get("id")
        actual_pair = deal.get("pair", pair)

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

        context.user_data.pop("edit_state", None)

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
    context.user_data.pop("edit_state", None)
    context.user_data.pop("editing_field", None)
    await query.edit_message_text("Отменено.")
