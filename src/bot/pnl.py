"""PnL calculation utility shared across bot components."""


def calculate_pnl(side: str, entry_price: float, exit_price: float, size: float) -> tuple[float, float]:
    """Calculate PnL and PnL percent for a closed trade.

    Returns:
        (pnl_absolute, pnl_percent)
    """
    if side.lower() == "long":
        pnl = (exit_price - entry_price) * size
    else:
        pnl = (entry_price - exit_price) * size
    pnl_percent = (pnl / (entry_price * size)) * 100 if (entry_price * size) else 0.0
    return pnl, pnl_percent
