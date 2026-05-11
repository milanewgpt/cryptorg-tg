import logging
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from sqlalchemy import select

from db.database import get_session_factory
from db.models import Template, RunningBot
from cryptorg.client import CryptorgClient, CryptorgError  # noqa: F401

logger = logging.getLogger(__name__)
IL_TZ = ZoneInfo("Asia/Jerusalem")


def _factory():
    return get_session_factory()


def _normalize_pair(raw: str) -> str:
    raw = raw.strip().upper()
    if not raw.endswith("USDT"):
        raw += "USDT"
    return raw


def _fmt_dt(dt: datetime) -> str:
    """Format datetime in Israel timezone."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IL_TZ).strftime("%d.%m %H:%M")


async def _active_bots_keyboard(user_id: int, cmd: str) -> InlineKeyboardMarkup | None:
    """Return inline keyboard of active bots, or None if empty."""
    async with _factory()() as session:
        bots = (await session.execute(
            select(RunningBot)
            .where(RunningBot.telegram_user == user_id, RunningBot.status == "active")
        )).scalars().all()

    if not bots:
        return None

    buttons = [
        [InlineKeyboardButton(b.pair, callback_data=f"sel_{cmd}:{b.id}")]
        for b in bots
    ]
    return InlineKeyboardMarkup(buttons)


async def cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Введите монету (например: DOGE или DOGEUSDT):")
        context.user_data["pending_cmd"] = "new"
        return

    pair = _normalize_pair(context.args[0])
    client: CryptorgClient = context.bot_data["cryptorg"]

    try:
        bots = await client.get_bots()
    except CryptorgError as e:
        await update.message.reply_text(f"Ошибка Cryptorg:\n`{e}`", parse_mode="Markdown")
        return

    # Only show template bots (not currently active clones)
    async with _factory()() as session:
        active_cbot_ids = set((await session.execute(
            select(RunningBot.cryptorg_bot_id)
            .where(RunningBot.status == "active")
        )).scalars().all())

    templates = [b for b in bots if b["id"] not in active_cbot_ids]

    if not templates:
        await update.message.reply_text("Нет доступных шаблонов.")
        return

    buttons = [
        [InlineKeyboardButton(
            b.get("title") or f"Bot {b['id']}",
            callback_data=f"tpl:{b['id']}:{pair}"
        )]
        for b in templates
    ]
    await update.message.reply_text(
        f"Пара: *{pair}*\nВыберите шаблон:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )


async def cmd_active(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    async with _factory()() as session:
        bots = (await session.execute(
            select(RunningBot)
            .where(RunningBot.telegram_user == user_id, RunningBot.status == "active")
        )).scalars().all()

    if not bots:
        await update.message.reply_text("Активных ботов нет.")
        return

    lines = [
        f"• *{b.pair}* — bot `{b.cryptorg_bot_id}` (с {_fmt_dt(b.created_at)})"
        for b in bots
    ]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def _find_active_bot(session, user_id: int, pair: str) -> RunningBot | None:
    return (await session.execute(
        select(RunningBot).where(
            RunningBot.telegram_user == user_id,
            RunningBot.pair == pair,
            RunningBot.status == "active",
        )
    )).scalar_one_or_none()


async def _find_active_bot_by_id(session, rb_id: int) -> RunningBot | None:
    rb = await session.get(RunningBot, rb_id)
    return rb if rb and rb.status == "active" else None


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        kb = await _active_bots_keyboard(user_id, "stop")
        if kb:
            await update.message.reply_text("Выберите бота для остановки:", reply_markup=kb)
        else:
            await update.message.reply_text("Активных ботов нет.")
        return

    pair = _normalize_pair(context.args[0])
    client: CryptorgClient = context.bot_data["cryptorg"]

    async with _factory()() as session:
        bot = await _find_active_bot(session, user_id, pair)
        if not bot:
            await update.message.reply_text(f"Активный бот для {pair} не найден.")
            return
        try:
            await client.stop_bot(bot.cryptorg_bot_id)
            bot.status = "stopped"
            bot.stopped_at = datetime.now(timezone.utc)
            await session.commit()
            await update.message.reply_text(f"*{pair}* — бот выключен.", parse_mode="Markdown")
        except CryptorgError as e:
            await update.message.reply_text(f"Ошибка Cryptorg:\n`{e}`", parse_mode="Markdown")


async def cmd_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        kb = await _active_bots_keyboard(user_id, "close")
        if kb:
            await update.message.reply_text("Выберите бота для закрытия позиции:", reply_markup=kb)
        else:
            await update.message.reply_text("Активных ботов нет.")
        return

    pair = _normalize_pair(context.args[0])
    client: CryptorgClient = context.bot_data["cryptorg"]

    async with _factory()() as session:
        bot = await _find_active_bot(session, user_id, pair)
        if not bot:
            await update.message.reply_text(f"Активный бот для {pair} не найден.")
            return
        if not bot.deal_id:
            await update.message.reply_text(f"У бота {pair} нет активной сделки.")
            return
        try:
            await client.kill_deal(bot.deal_id)
            bot.status = "closed"
            bot.stopped_at = datetime.now(timezone.utc)
            await session.commit()
            await update.message.reply_text(f"*{pair}* — позиция закрыта по рынку.", parse_mode="Markdown")
        except CryptorgError as e:
            await update.message.reply_text(f"Ошибка Cryptorg:\n`{e}`", parse_mode="Markdown")


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        kb = await _active_bots_keyboard(user_id, "cancel")
        if kb:
            await update.message.reply_text("Выберите бота для отмены сделки:", reply_markup=kb)
        else:
            await update.message.reply_text("Активных ботов нет.")
        return

    pair = _normalize_pair(context.args[0])
    client: CryptorgClient = context.bot_data["cryptorg"]

    async with _factory()() as session:
        bot = await _find_active_bot(session, user_id, pair)
        if not bot:
            await update.message.reply_text(f"Активный бот для {pair} не найден.")
            return
        if not bot.deal_id:
            await update.message.reply_text(f"У бота {pair} нет активной сделки.")
            return
        try:
            await client.cancel_deal(bot.deal_id)
            bot.status = "stopped"
            bot.stopped_at = datetime.now(timezone.utc)
            await session.commit()
            await update.message.reply_text(f"*{pair}* — сделка отменена.", parse_mode="Markdown")
        except CryptorgError as e:
            await update.message.reply_text(f"Ошибка Cryptorg:\n`{e}`", parse_mode="Markdown")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        kb = await _active_bots_keyboard(user_id, "status")
        if kb:
            await update.message.reply_text("Выберите бота:", reply_markup=kb)
        else:
            await update.message.reply_text("Активных ботов нет.")
        return

    pair = _normalize_pair(context.args[0])

    async with _factory()() as session:
        bot = await _find_active_bot(session, user_id, pair)
        if not bot:
            await update.message.reply_text(f"Активный бот для {pair} не найден.")
            return
        template = await session.get(Template, bot.template_id)

    await _send_status(update.message.reply_text, bot, template, context)


async def _send_status(reply_fn, bot: RunningBot, template, context: ContextTypes.DEFAULT_TYPE):
    try:
        from bybit.client import BybitClient
        bybit: BybitClient = context.bot_data["bybit"]
        positions = await bybit.get_positions(symbol=bot.pair)
        pos = positions[0] if positions else {}

        pnl_raw = pos.get("unrealisedPnl", "")
        try:
            pnl = f"{'+'if float(pnl_raw)>=0 else ''}{float(pnl_raw):.4f} USDT" if pnl_raw else "—"
        except (TypeError, ValueError):
            pnl = "—"

        entry = pos.get("avgPrice", "—")
        size = pos.get("size", "—")
        elapsed = datetime.now(timezone.utc) - bot.created_at.replace(tzinfo=timezone.utc)
        hours = int(elapsed.total_seconds() // 3600)
        minutes = int((elapsed.total_seconds() % 3600) // 60)

        text = (
            f"*{bot.pair}*\n"
            f"Шаблон: {template.name if template else '—'}\n"
            f"PnL: `{pnl}`\n"
            f"Entry: `{entry}`\n"
            f"Объём: `{size}`\n"
            f"Работает: {hours}ч {minutes}м"
        )
        await reply_fn(text, parse_mode="Markdown")
    except Exception as e:
        await reply_fn(f"Ошибка Bybit:\n`{e}`", parse_mode="Markdown")


async def cmd_templates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    client: CryptorgClient = context.bot_data["cryptorg"]
    try:
        bots = await client.get_bots()
    except CryptorgError as e:
        await update.message.reply_text(f"Ошибка Cryptorg:\n`{e}`", parse_mode="Markdown")
        return

    # Exclude bots currently in use as active running bots
    async with _factory()() as session:
        active_cbot_ids = set((await session.execute(
            select(RunningBot.cryptorg_bot_id)
            .where(RunningBot.status == "active")
        )).scalars().all())

    templates = [b for b in bots if b["id"] not in active_cbot_ids]

    if not templates:
        await update.message.reply_text("Нет доступных шаблонов.")
        return

    lines = [
        f"• *{b.get('title') or 'Bot ' + str(b['id'])}*\n"
        f"  ID: `{b['id']}` | Пара: {', '.join(b.get('pairs', ['—']))}"
        for b in templates
    ]
    await update.message.reply_text("\n\n".join(lines), parse_mode="Markdown")


async def handle_plain_ticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{2,10}(USDT)?", text):
        return

    pending = context.user_data.pop("pending_cmd", None)
    context.args = [text]

    if pending == "new":
        await cmd_new(update, context)


# ── Inline button handlers for bot selection ──────────────────────────────────

async def handle_sel_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    rb_id = int(query.data.split(":")[1])
    user_id = update.effective_user.id

    async with _factory()() as session:
        bot = await _find_active_bot_by_id(session, rb_id)
        if not bot or bot.telegram_user != user_id:
            await query.edit_message_text("Бот не найден.")
            return
        template = await session.get(Template, bot.template_id)

    await query.edit_message_text(f"Загружаю статус *{bot.pair}*...", parse_mode="Markdown")
    await _send_status(
        lambda text, **kw: query.edit_message_text(text, **kw),
        bot, template, context
    )


async def handle_sel_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    rb_id = int(query.data.split(":")[1])
    user_id = update.effective_user.id
    client: CryptorgClient = context.bot_data["cryptorg"]

    async with _factory()() as session:
        bot = await _find_active_bot_by_id(session, rb_id)
        if not bot or bot.telegram_user != user_id:
            await query.edit_message_text("Бот не найден.")
            return
        try:
            await client.stop_bot(bot.cryptorg_bot_id)
            bot.status = "stopped"
            bot.stopped_at = datetime.now(timezone.utc)
            await session.commit()
            await query.edit_message_text(f"*{bot.pair}* — бот выключен.", parse_mode="Markdown")
        except CryptorgError as e:
            await query.edit_message_text(f"Ошибка Cryptorg:\n`{e}`", parse_mode="Markdown")


async def handle_sel_close(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    rb_id = int(query.data.split(":")[1])
    user_id = update.effective_user.id
    client: CryptorgClient = context.bot_data["cryptorg"]

    async with _factory()() as session:
        bot = await _find_active_bot_by_id(session, rb_id)
        if not bot or bot.telegram_user != user_id:
            await query.edit_message_text("Бот не найден.")
            return
        if not bot.deal_id:
            await query.edit_message_text(f"У бота {bot.pair} нет активной сделки.")
            return
        try:
            await client.kill_deal(bot.deal_id)
            bot.status = "closed"
            bot.stopped_at = datetime.now(timezone.utc)
            await session.commit()
            await query.edit_message_text(f"*{bot.pair}* — позиция закрыта по рынку.", parse_mode="Markdown")
        except CryptorgError as e:
            await query.edit_message_text(f"Ошибка Cryptorg:\n`{e}`", parse_mode="Markdown")


async def handle_sel_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    rb_id = int(query.data.split(":")[1])
    user_id = update.effective_user.id
    client: CryptorgClient = context.bot_data["cryptorg"]

    async with _factory()() as session:
        bot = await _find_active_bot_by_id(session, rb_id)
        if not bot or bot.telegram_user != user_id:
            await query.edit_message_text("Бот не найден.")
            return
        if not bot.deal_id:
            await query.edit_message_text(f"У бота {bot.pair} нет активной сделки.")
            return
        try:
            await client.cancel_deal(bot.deal_id)
            bot.status = "stopped"
            bot.stopped_at = datetime.now(timezone.utc)
            await session.commit()
            await query.edit_message_text(f"*{bot.pair}* — сделка отменена.", parse_mode="Markdown")
        except CryptorgError as e:
            await query.edit_message_text(f"Ошибка Cryptorg:\n`{e}`", parse_mode="Markdown")
