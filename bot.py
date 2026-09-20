import asyncio
import json
import logging
import re
import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiohttp import web
from web3 import Web3, AsyncWeb3

from wallet_manager import get_or_create_wallet, get_decrypted_private_key
from swap_engine import execute_buy_async, execute_sell_async, get_bnb_balance_async
from signals_scanner import fetch_trending_signals
from security_scanner import check_token_security
from db_manager import add_position, get_active_positions, close_position, add_whale_target
from dashboard import create_dashboard_app
from referral_manager import register_referral
from mempool_listener import track_mempool
from db_manager import add_whale_target, get_all_whale_addresses
from mempool_listener import track_mempool

CONFIG_PATH = "config.json"

def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)

def save_config(config_data):
    with open(CONFIG_PATH, "w") as f:
        json.dump(config_data, f, indent=4)

CONFIG = load_config()
BOT_TOKEN = CONFIG.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("Provide BOT_TOKEN in config.json")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

class AdminSetup(StatesGroup):
    waiting_for_fee_wallet = State()

def is_valid_evm_address(address: str) -> bool:
    return bool(re.match(r"^0x[a-fA-F0-9]{40}$", address))

async def get_live_token_price(token_address: str) -> float:
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=5) as r:
                if r.status == 200:
                    data = await r.json()
                    pairs = data.get("pairs", [])
                    if pairs:
                        return float(pairs[0].get("priceUsd", 0.0))
    except Exception:
        pass
    return 0.0

async def tpsl_monitor_task():
    while True:
        try:
            positions = get_active_positions()
            for pos in positions:
                token = pos["token_address"]
                current_price = await get_live_token_price(token)
                if current_price <= 0 or pos["entry_price"] <= 0:
                    continue

                change_pct = ((current_price - pos["entry_price"]) / pos["entry_price"]) * 100

                hit_tp = change_pct >= pos["tp_percent"]
                hit_sl = change_pct <= -abs(pos["sl_percent"])

                if hit_tp or hit_sl:
                    reason = "Take-Profit" if hit_tp else "Stop-Loss"
                    user_id = pos["user_id"]
                    pk = get_decrypted_private_key(user_id)
                    
                    res = await execute_sell_async(pk, token, 100.0, user_id, use_private_rpc=True)
                    close_position(pos["id"])

                    alert = (
                        f"🎯 *Auto {reason} Executed!*\n\n"
                        f"*Token:* `{token}`\n"
                        f"*Trigger PnL:* `{change_pct:+.2f}%`\n"
                        f"*Status:* {'Success' if res.get('success') else 'Failed'}\n"
                    )
                    if res.get("success"):
                        alert += f"🔗 [View on BscScan](https://bscscan.com/tx/{res['tx_hash']})"
                    await bot.send_message(user_id, alert, parse_mode="Markdown")

        except Exception as e:
            logging.error(f"Error in TP/SL monitor: {e}")
        await asyncio.sleep(10)

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext, command: CommandObject):
    global CONFIG
    CONFIG = load_config()
    user_id = message.from_user.id
    
    args = command.args
    if args and args.startswith("ref_"):
        try:
            referrer_id = int(args.split("_")[1])
            register_referral(user_id, referrer_id)
        except ValueError:
            pass

    owner_id = CONFIG.get("OWNER_TELEGRAM_ID")
    owner_wallet = CONFIG.get("OWNER_FEE_WALLET")

    if not owner_id or not owner_wallet:
        if not owner_id:
            CONFIG["OWNER_TELEGRAM_ID"] = user_id
            save_config(CONFIG)
            owner_id = user_id

        if user_id == owner_id:
            await state.set_state(AdminSetup.waiting_for_fee_wallet)
            setup_prompt = (
                "👑 *Owner Setup Required*\n\n"
                "Please send your *BNB payout wallet address*:"
            )
            await message.answer(setup_prompt, parse_mode="Markdown")
            return

    wallet = get_or_create_wallet(user_id, chain_type='EVM', is_master=1)
    address = wallet["address"]
    ref_link = f"https://t.me/{(await bot.me()).username}?start=ref_{user_id}"

    welcome_text = (
        "⚡ *BNB Chain Sniper & Auto-Trading Bot* ⚡\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "📥 *Your Deposit Address:*\n"
        f"`{address}`\n\n"
        "⚙️ *Quick Guide:*\n"
        "🔹 `/wallet` - View balance & export private key\n"
        "🔹 `/buy <token> <amount>` - Instant MEV-protected buy\n"
        "🔹 `/sell <token> <%>` - Instant sell\n"
        "🔹 `/autotrade <token> <amount> <tp%> <sl%>` - Automated trading\n"
        "🔹 `/addwhale <address> <amount>` - Copy-trade whale wallet\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🎁 *Referral Link (Earn 20%):*\n`{ref_link}`"
    )
    await message.answer(welcome_text, parse_mode="Markdown")

@dp.message(AdminSetup.waiting_for_fee_wallet)
async def process_fee_wallet(message: types.Message, state: FSMContext):
    wallet_address = message.text.strip()
    if not is_valid_evm_address(wallet_address):
        await message.answer("❌ Invalid EVM address. Please send a valid `0x` address:")
        return

    checksum = Web3.to_checksum_address(wallet_address)
    CONFIG["OWNER_FEE_WALLET"] = checksum
    save_config(CONFIG)
    await state.clear()
    await message.answer(f"✅ Fee address set to: `{checksum}`\nType `/start` to begin.", parse_mode="Markdown")

@dp.message(Command("dashboard"))
async def cmd_dashboard(message: types.Message):
    if message.from_user.id != CONFIG.get("OWNER_TELEGRAM_ID"):
        await message.answer("❌ Access denied. Owner only.")
        return
    await message.answer("📊 *Owner Web Dashboard:*\nhttp://localhost:8080", parse_mode="Markdown")

@dp.message(Command("buy"))
async def cmd_buy(message: types.Message):
    parts = message.text.strip().split()
    if len(parts) < 3:
        await message.answer("Usage: `/buy <token_address> <amount_bnb>`", parse_mode="Markdown")
        return

    token_address, amount_bnb = parts[1], float(parts[2])
    status_msg = await message.answer("🛡️ Running Security & Anti-MEV audit...")

    sec = await check_token_security(token_address)
    if not sec.get("safe"):
        await status_msg.edit_text(f"🛑 *Purchase Cancelled:*\n`{sec.get('reason')}`", parse_mode="Markdown")
        return

    await status_msg.edit_text(f"✅ Verified (Tax: Buy {sec.get('buy_tax', 0)}% / Sell {sec.get('sell_tax', 0)}%). Simulating & Swapping...")
    
    pk = get_decrypted_private_key(message.from_user.id)
    
    result = await execute_buy_async(pk, token_address, amount_bnb, message.from_user.id, use_private_rpc=True)

    if result.get("success"):
        tx_url = f"https://bscscan.com/tx/{result['tx_hash']}"
        await status_msg.edit_text(f"✅ *Buy Complete!*\n🔗 [View on BscScan]({tx_url})", parse_mode="Markdown")
    else:
        await status_msg.edit_text(f"❌ *Failed:*\n`{result.get('error')}`", parse_mode="Markdown")

@dp.message(Command("autotrade"))
async def cmd_autotrade(message: types.Message):
    parts = message.text.strip().split()
    if len(parts) < 5:
        await message.answer("Usage: `/autotrade <token> <amount_bnb> <tp%> <sl%>`\nExample: `/autotrade 0x... 0.05 50 15`", parse_mode="Markdown")
        return

    token_address = parts[1]
    amount_bnb = float(parts[2])
    tp_percent = float(parts[3])
    sl_percent = float(parts[4])

    status_msg = await message.answer("🛡️ Auditing token and fetching entry price...")
    sec = await check_token_security(token_address)
    if not sec.get("safe"):
        await status_msg.edit_text(f"🛑 *Refused:*\n`{sec.get('reason')}`", parse_mode="Markdown")
        return

    entry_price = await get_live_token_price(token_address)
    pk = get_decrypted_private_key(message.from_user.id)
    
    result = await execute_buy_async(pk, token_address, amount_bnb, message.from_user.id, use_private_rpc=True)

    if result.get("success"):
        add_position(message.from_user.id, token_address, entry_price, tp_percent, sl_percent)
        tx_url = f"https://bscscan.com/tx/{result['tx_hash']}"
        await status_msg.edit_text(
            f"✅ *Position Opened with Auto TP/SL!*\n\n"
            f"*Entry Price:* `${entry_price}`\n"
            f"*Take-Profit:* `+{tp_percent}%`\n"
            f"*Stop-Loss:* `-{sl_percent}%`\n"
            f"🔗 [BscScan]({tx_url})",
            parse_mode="Markdown"
        )
    else:
        await status_msg.edit_text(f"❌ *Failed:*\n`{result.get('error')}`", parse_mode="Markdown")

@dp.message(Command("sell"))
async def cmd_sell(message: types.Message):
    parts = message.text.strip().split()
    if len(parts) < 2:
        await message.answer("Usage: `/sell <token_address> <percent>`", parse_mode="Markdown")
        return
    token_address = parts[1]
    percent = float(parts[2]) if len(parts) >= 3 else 100.0
    status_msg = await message.answer("⏳ Executing sale...")

    pk = get_decrypted_private_key(message.from_user.id)
    
    res = await execute_sell_async(pk, token_address, percent, message.from_user.id, use_private_rpc=True)
    
    if res.get("success"):
        await status_msg.edit_text(f"✅ Sold {percent}%!\n🔗 [BscScan](https://bscscan.com/tx/{res['tx_hash']})", parse_mode="Markdown")
    else:
        await status_msg.edit_text(f"❌ *Failed:*\n`{res.get('error')}`", parse_mode="Markdown")

@dp.message(Command("addwhale"))
async def cmd_addwhale(message: types.Message):
    parts = message.text.strip().split()
    if len(parts) < 3:
        await message.answer("Usage: `/addwhale <whale_address> <buy_amount_bnb>`", parse_mode="Markdown")
        return
    
    whale_address = parts[1]
    try:
        buy_amount = float(parts[2])
    except ValueError:
        await message.answer("❌ Invalid BNB amount.")
        return
    
    if not is_valid_evm_address(whale_address):
        await message.answer("❌ Invalid EVM address.")
        return
        
    add_whale_target(message.from_user.id, whale_address, buy_amount)
    await message.answer(f"🎯 *Whale Added!*\nAddress: `{whale_address}`\nCopy Amount: `{buy_amount} BNB`", parse_mode="Markdown")

@dp.message(Command("wallet"))
async def cmd_wallet(message: types.Message):
    user_id = message.from_user.id
    wallet = get_or_create_wallet(user_id, chain_type='EVM', is_master=1)
    
    balance = await get_bnb_balance_async(wallet["address"])
    
    text = f"💼 *Wallet Dashboard*\n\n*Address:* `{wallet['address']}`\n*Balance:* `{balance:.4f} BNB`"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔑 Export Private Key", callback_data="show_pk")]])
    await message.answer(text, parse_mode="Markdown", reply_markup=kb)

@dp.callback_query(F.data == "show_pk")
async def show_pk(cq: types.CallbackQuery):
    pk = get_decrypted_private_key(cq.from_user.id)
    await cq.answer()
    await cq.message.answer(f"⚠️ *Private Key:*\n`{pk}`", parse_mode="Markdown")

async def set_bot_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="🚀 Main menu & deposit address"),
        BotCommand(command="wallet", description="💼 View balance & export private key"),
        BotCommand(command="buy", description="⚡ Instant buy (Anti-MEV)"),
        BotCommand(command="sell", description="📉 Instant sell"),
        BotCommand(command="autotrade", description="🤖 Automated trade with TP/SL"),
        BotCommand(command="addwhale", description="🎯 Add whale address for copy-trading"),
        BotCommand(command="dashboard", description="📊 Analytics dashboard (Owner)"),
    ]
    await bot.set_my_commands(commands)

async def main():
    app = create_dashboard_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()
    logging.info("Owner Dashboard running at http://localhost:8080")
    asyncio.create_task(tpsl_monitor_task())
    
    whale_addresses = get_all_whale_addresses()
    if whale_addresses:
        logging.info(f"Starting Mempool Listener for {len(whale_addresses)} whales...")
        asyncio.create_task(track_mempool(whale_addresses))

    await set_bot_commands(bot)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())