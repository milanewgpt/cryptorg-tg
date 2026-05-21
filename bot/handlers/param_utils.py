"""Helpers for template parameter preview and editing."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

STRATEGY_EN = {"long": "Long", "short": "Short"}
# keep old name as alias so any leftover imports don't break
STRATEGY_RU = STRATEGY_EN


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
    strategy_en = STRATEGY_EN.get(str(params.get("strategy", "long")).lower(), "Long")

    def _v(key, default="—"):
        v = params.get(key)
        return v if v is not None else default

    lines = [
        f"*{strategy_en} {display_pair}*",
        f"Template: {title}",
        "",
        "Parameters:",
        f"• Entry {_v('volume')} USDT, leverage ×{_v('leverage')}",
        f"• Safety orders {_v('so_max')}, step {_v('so_step')}%",
        f"• Price step mult {_v('step_mult')}, volume mult {_v('vol_mult')}",
        f"• TP {_v('tp')}%",
    ]

    cycles = params.get("cycles")
    if cycles is not None:
        lines.append(f"• Cycles: {cycles}")

    return "\n".join(lines)


def make_edit_buttons(params: dict, tpl_id: int, pair: str) -> InlineKeyboardMarkup:
    """Inline keyboard for param editing: one button per editable field."""
    def _v(key, suffix=""):
        v = params.get(key)
        return f"{v}{suffix}" if v is not None else "—"

    strategy_en = STRATEGY_EN.get(str(params.get("strategy", "long")).lower(), "Long")
    cycles_str = str(params["cycles"]) if params.get("cycles") is not None else "∞"

    rows = [
        [InlineKeyboardButton(f"✏️ Strategy: {strategy_en}", callback_data="param:strategy")],
        [InlineKeyboardButton(f"✏️ Entry: {_v('volume')} USDT", callback_data="param:volume")],
        [InlineKeyboardButton(f"✏️ SO step: {_v('so_step')}%", callback_data="param:so_step")],
        [
            InlineKeyboardButton(f"✏️ Price mult: {_v('step_mult')}", callback_data="param:step_mult"),
            InlineKeyboardButton(f"✏️ Vol mult: {_v('vol_mult')}", callback_data="param:vol_mult"),
        ],
        [InlineKeyboardButton(f"✏️ TP: {_v('tp')}%", callback_data="param:tp")],
        [InlineKeyboardButton(f"✏️ Cycles: {cycles_str}", callback_data="param:cycles")],
        [
            InlineKeyboardButton("Launch ✅", callback_data=f"start:{tpl_id}:{pair}"),
            InlineKeyboardButton("Cancel ❌", callback_data="cancel_flow"),
        ],
    ]
    return InlineKeyboardMarkup(rows)
