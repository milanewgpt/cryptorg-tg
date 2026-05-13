"""
Background poller: every POLL_INTERVAL seconds fetches open positions from Bybit directly,
sends Telegram notifications on state changes.
"""
import asyncio
import logging
import os
from datetime import datetime, timezone

from sqlalchemy import select
from telegram import Bot

from bybit.client import BybitClient
from db.database import get_session_factory
from db.models import RunningBot

logger = logging.getLogger(__name__)
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "30"))

# { running_bot_db_id: {"size": str, "avgPrice": str} }
_last_state: dict[int, dict] = {}


def _fmt_float(val) -> str:
    try:
        f = float(val)
        return f"{'+'if f >= 0 else ''}{f:.4f} USDT"
    except (TypeError, ValueError):
        return "—"


def _so_notify_text(pair: str, prev_size: float, new_size: float, pos: dict) -> str:
    avg = pos.get("avgPrice", "—")
    mark = pos.get("markPrice", "—")
    unrealised = _fmt_float(pos.get("unrealisedPnl"))
    cum_realised = _fmt_float(pos.get("cumRealisedPnl"))
    return (
        f"*Safety Order Filled*\n{pair}\n\n"
        f"Объём: {prev_size} → {new_size}\n"
        f"Avg Entry: `{avg}`\n"
        f"Mark Price: `{mark}`\n"
        f"Позиция PnL: `{unrealised}`\n"
        f"Реализовано всего: `{cum_realised}`"
    )


async def _notify(bot: Bot, user_id: int, text: str):
    try:
        await bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")
    except Exception as e:
        logger.warning("notify failed uid=%s: %s", user_id, e)


async def _poll_once(bot: Bot, bybit: BybitClient):
    factory = get_session_factory()
    async with factory() as session:
        active_bots = (await session.execute(
            select(RunningBot).where(RunningBot.status == "active")
        )).scalars().all()

    if not active_bots:
        return

    try:
        positions = await bybit.get_positions()
    except Exception as e:
        logger.error("poll: get_positions failed: %s", e)
        return

    # Index by symbol (DOGEUSDT → position dict)
    pos_by_symbol: dict[str, dict] = {p["symbol"]: p for p in positions if float(p.get("size", "0")) > 0}

    async with factory() as session:
        for rb in active_bots:
            pos = pos_by_symbol.get(rb.pair)
            prev = _last_state.get(rb.id)

            if pos:
                curr_size = pos.get("size", "0")
                curr_avg = pos.get("avgPrice", "")

                if prev:
                    prev_size = float(prev.get("size", "0"))
                    new_size = float(curr_size)
                    if new_size > prev_size:
                        await _notify(bot, rb.telegram_user,
                            _so_notify_text(rb.pair, prev_size, new_size, pos)
                        )

                _last_state[rb.id] = {
                    "size": curr_size,
                    "avgPrice": curr_avg,
                    "cumRealisedPnl": pos.get("cumRealisedPnl", ""),
                }

            else:
                # Position gone → closed (TP or SL)
                if prev is not None:
                    cum = _fmt_float(prev.get("cumRealisedPnl"))
                    await _notify(bot, rb.telegram_user,
                        f"*Position Closed*\n{rb.pair}\n\nРеализовано: `{cum}`"
                    )
                    async with factory() as s2:
                        bot_row = await s2.get(RunningBot, rb.id)
                        if bot_row:
                            bot_row.status = "stopped"
                            bot_row.stopped_at = datetime.now(timezone.utc)
                            await s2.commit()
                    _last_state.pop(rb.id, None)


async def sync_active_deals(bybit: BybitClient, telegram_user_id: int):
    """Import open Bybit positions into DB if not already tracked."""
    factory = get_session_factory()
    positions = None
    for attempt in range(5):
        try:
            positions = await bybit.get_positions()
            break
        except Exception as e:
            logger.warning("sync: attempt %d failed: %s", attempt + 1, e)
            await asyncio.sleep(5)
    if positions is None:
        logger.error("sync: all attempts failed, skipping")
        return

    async with factory() as session:
        for pos in positions:
            symbol = pos.get("symbol", "")
            size = float(pos.get("size", "0"))
            if not symbol or size == 0:
                continue

            existing = (await session.execute(
                select(RunningBot).where(
                    RunningBot.pair == symbol,
                    RunningBot.status == "active",
                )
            )).scalar_one_or_none()

            if existing is None:
                session.add(RunningBot(
                    telegram_user=telegram_user_id,
                    template_id=None,
                    cryptorg_bot_id=0,
                    deal_id=None,
                    pair=symbol,
                    status="active",
                ))
                logger.info("sync: imported position pair=%s size=%s", symbol, size)

        await session.commit()


async def run_poller(bot: Bot, bybit: BybitClient, telegram_user_id: int = 0):
    logger.info("Poller started (Bybit API, interval=%ss)", POLL_INTERVAL)
    await asyncio.sleep(5)  # wait for network to be ready on cold start
    if telegram_user_id:
        await sync_active_deals(bybit, telegram_user_id)
    while True:
        try:
            await _poll_once(bot, bybit)
        except Exception as e:
            logger.exception("Poller error: %s", e)
        await asyncio.sleep(POLL_INTERVAL)
