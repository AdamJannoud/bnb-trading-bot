"""Risk guard: the owner kill switch, position sizing and the daily loss cap.

Every check here applies to buying only. Selling is never blocked, so a stop or a
cap can never trap funds in a position.
"""
import json
import os
import time

from db_manager import get_flag, set_flag, get_open_exposure, get_realised_pnl_since

CONFIG_PATH = "config.json"
KILL_SWITCH_FLAG = "buying_stopped"
LOSS_WINDOW_SECONDS = 24 * 60 * 60

DEFAULT_LIMITS = {
    "MAX_TRADE_BNB": 0.1,
    "MAX_OPEN_EXPOSURE_BNB": 0.3,
    "DAILY_LOSS_CAP_BNB": 0.05,
}

def load_limits(path: str = CONFIG_PATH) -> dict:
    config = {}
    if os.path.exists(path):
        with open(path, "r") as f:
            config = json.load(f)
    limits = {}
    for key, default in DEFAULT_LIMITS.items():
        value = float(config.get(key, default))
        if value <= 0:
            raise ValueError(f"{key} must be a positive number of BNB, got {value}.")
        limits[key] = value
    return limits

LIMITS = load_limits()

def is_buying_stopped() -> bool:
    return get_flag(KILL_SWITCH_FLAG) == "1"

def set_buying_stopped(stopped: bool):
    set_flag(KILL_SWITCH_FLAG, "1" if stopped else "0")

def realised_loss_24h(user_id: int, now: float = None) -> float:
    """Net realised loss over the rolling window, in BNB (0 when the window is in profit)."""
    now = time.time() if now is None else now
    return max(0.0, -get_realised_pnl_since(user_id, now - LOSS_WINDOW_SECONDS))

def loss_cap_hit(user_id: int) -> bool:
    return realised_loss_24h(user_id) >= LIMITS["DAILY_LOSS_CAP_BNB"]

def check_buy(user_id: int, amount_bnb: float):
    """Return None if this buy may go ahead, otherwise the reason it is refused."""
    if is_buying_stopped():
        return "Buying is stopped by the owner. Selling stays open."
    if amount_bnb > LIMITS["MAX_TRADE_BNB"]:
        return f"Trade size {amount_bnb} BNB is over the per-trade cap of {LIMITS['MAX_TRADE_BNB']} BNB."
    exposure = get_open_exposure(user_id)
    if exposure + amount_bnb > LIMITS["MAX_OPEN_EXPOSURE_BNB"]:
        return (f"Open exposure would be {exposure + amount_bnb:.4f} BNB, over the cap of "
                f"{LIMITS['MAX_OPEN_EXPOSURE_BNB']} BNB. Close a position first.")
    if loss_cap_hit(user_id):
        return (f"Daily loss cap of {LIMITS['DAILY_LOSS_CAP_BNB']} BNB reached; buying is paused for this "
                f"rolling 24 hours. Selling stays open.")
    return None
