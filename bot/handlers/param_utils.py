"""Helpers for template parameter preview and editing."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

STRATEGY_RU = {"long": "Лонг", "short": "Шорт"}


def extract_params(bot_data: dict) -> dict:
    """Flatten relevant bot params for display/editing."""
    params = bot_data.get("parameters", {})
    open_p = params.get("open", {})
    close_p = params.get("close", {})
    dca_p = params.get("dca", {})

    cycles_restr = open_p.get("self_opening_restrictions", {}).get("cycles", {})
    cycles = cycles_restr.get("limit") if cycles_restr.get("is_active") else None

    return {
        "strategy": bot_data.get("strategy", "long"),
        "tp":        close_p.get("tp_value"),
        "volume":    open_p.get("order_volume"),
        "leverage":  open_p.get("leverage"),
        "so_step":   dca_p.get("so_percent"),
        "vol_mult":  dca_p.get("so_multiplier_volume"),
        "step_mult": dca_p.get("so_multiplier_price"),
        "so_max":    dca_p.get("so_max"),
        "cycles":    cycles,
    }


def get_display_params(state: dict) -> dict:
    """Merge original template params with user overrides."""
    p = state.get("original_params", {}).copy()
    p.update(state.get("custom_overrides", {}))
    return p


def format_params_text(title: str, pair: str, params: dict) -> str:
    """Build the params preview message."""
    display_pair = pair.removesuffix("USDT")
    strategy_ru = STRATEGY_RU.get(str(params.get("strategy", "long")).lower(), "Лонг")

    def _v(key, default="—"):
        v = params.get(key)
        return v if v is not None else default

    lines = [
        f"*{strategy_ru} {display_pair}*",
        f"Шаблон: {title}",
        "",
        "Параметры:",
        f"• Вход {_v('volume')} USDT, плечо ×{_v('leverage')}",
        f"• Усреднений {_v('so_max')}, шаг {_v('so_step')}%",
        f"• Множитель шага {_v('step_mult')}, объёма {_v('vol_mult')}",
        f"• ТП {_v('tp')}%",
    ]

    cycles = params.get("cycles")
    if cycles is not None:
        lines.append(f"• Циклов: {cycles}")

    return "\n".join(lines)


def make_edit_buttons(params: dict, tpl_id: int, pair: str) -> InlineKeyboardMarkup:
    """Inline keyboard for param editing: one button per editable field."""
    def _v(key, suffix=""):
        v = params.get(key)
        return f"{v}{suffix}" if v is not None else "—"

    strategy_ru = STRATEGY_RU.get(str(params.get("strategy", "long")).lower(), "Лонг")
    cycles_str = str(params["cycles"]) if params.get("cycles") is not None else "∞"

    rows = [
        [InlineKeyboardButton(f"✏️ Стратегия: {strategy_ru}", callback_data="param:strategy")],
        [InlineKeyboardButton(f"✏️ Вход: {_v('volume')} USDT", callback_data="param:volume")],
        [InlineKeyboardButton(f"✏️ Шаг: {_v('so_step')}%", callback_data="param:so_step")],
        [
            InlineKeyboardButton(f"✏️ Множ. шага: {_v('step_mult')}", callback_data="param:step_mult"),
            InlineKeyboardButton(f"✏️ Множ. объёма: {_v('vol_mult')}", callback_data="param:vol_mult"),
        ],
        [InlineKeyboardButton(f"✏️ ТП: {_v('tp')}%", callback_data="param:tp")],
        [InlineKeyboardButton(f"✏️ Циклов: {cycles_str}", callback_data="param:cycles")],
        [
            InlineKeyboardButton("Запустить ✅", callback_data=f"start:{tpl_id}:{pair}"),
            InlineKeyboardButton("Отмена ❌", callback_data="cancel_flow"),
        ],
    ]
    return InlineKeyboardMarkup(rows)
