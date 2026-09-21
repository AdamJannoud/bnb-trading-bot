import asyncio
import json
import logging
import re
import os
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
from db_manager import add_position, get_active_positions, close_position, add_whale_target, get_all_whale_addresses
from dashboard import create_dashboard_app
from referral_manager import register_referral
from mempool_listener import track_mempool

CONFIG_PATH = "config.json"

def load_config():
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError("config.json file is missing! Please copy config.example.json to config.json and fill in the details.")
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

def is_valid_evm_address(address: str) -> bool:
    return bool(re.match(r"^0x[a-fA-F0-9]{40}$", address))

def escape_md(text: str) -> str:
    escape_chars = r"_*[]()~`>#+-=|{}.!"
    return re.sub(f"([{re.escape(escape_chars)}])", r"\\\1", str(text))

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
                    
                    if res.get("success"):
                        close_position(pos["id"])
                        alert = (
                            f"🎯 *Auto {reason} Executed!*\n\n"
                            f"• *Token:* `{token}`\n"
                            f"• *Trigger PnL:* `{change_pct:+.2f}%`\n"
                            f"🔗 [View on BscScan](https://bscscan.com/tx/{res['tx_hash']})"
                        )
                    else:
                        error_msg = escape_md(res.get('error', 'Execution reverted'))
                        alert = (
                            f"⚠️ *Auto {reason} Failed!*\n\n"
                            f"• *Token:* `{token}`\n"
                            f"• *Error:* `{error_msg}`\n"
                            f"Bot will retry next tick."
                        )
                    
                    await bot.send_message(user_id, alert, parse_mode="Markdown")

        except Exception as e:
            logging.error(f"Error in TP/SL monitor: {e}")
        await asyncio.sleep(10)

@dp.message(Command("start"))
async def cmd_start(message: types.Message, command: CommandObject):
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
        if user_id == owner_id:
            await message.answer("⚠️ *System Warning:* Owner setup is incomplete. Please configure `OWNER_TELEGRAM_ID` and `OWNER_FEE_WALLET` in `config.json` manually.", parse_mode="Markdown")

    wallet = get_or_create_wallet(user_id, chain_type='EVM', is_master=1)
    address = wallet["address"]
    ref_link = f"https://t.me/{(await bot.me()).username}?start=ref_{user_id}"

    welcome_text = (
        "⚡ *Universal Sniper & Auto-Trading Bot (BSC | SOL | BASE)* ⚡\n"
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
        f"🎁 *Referral Link (Earn 20%):*\n`{escape_md(ref_link)}`"
    )
    await message.answer(welcome_text, parse_mode="Markdown")

@dp.message(Command("dashboard"))
async def cmd_dashboard(message: types.Message):
    if message.from_user.id != CONFIG.get("OWNER_TELEGRAM_ID"):
        return await message.answer("❌ Access denied. Owner only.")
    
    await message.answer("📊 *Owner Web Dashboard:*\nhttp://<YOUR_SERVER_IP>:8080\n_(Make sure to protect your port!)_", parse_mode="Markdown")

@dp.message(Command("buy"))
async def cmd_buy(message: types.Message):
    parts = message.text.strip().split()
    if len(parts) < 3:
        return await message.answer("Usage: `/buy <token_address> <amount_bnb>`\nExample: `/buy 0x... 0.1`", parse_mode="Markdown")

    token_address = parts[1]
    if not is_valid_evm_address(token_address):
        return await message.answer("❌ Invalid EVM token address.")

    try:
        amount_bnb = float(parts[2])
        if amount_bnb <= 0: raise ValueError
    except ValueError:
        return await message.answer("❌ Amount must be a valid positive number.")

    status_msg = await message.answer("🛡️ Running Security & Anti-MEV audit...")

    sec = await check_token_security(token_address)
    if not sec.get("safe"):
        return await status_msg.edit_text(f"🛑 *Purchase Cancelled:*\n`{escape_md(sec.get('reason'))}`", parse_mode="Markdown")

    await status_msg.edit_text(f"✅ Verified (Tax: Buy {sec.get('buy_tax', 0)}% / Sell {sec.get('sell_tax', 0)}%). Simulating & Swapping...")
    
    pk = get_decrypted_private_key(message.from_user.id)
    result = await execute_buy_async(pk, token_address, amount_bnb, message.from_user.id, use_private_rpc=True)

    if result.get("success"):
        tx_url = f"https://bscscan.com/tx/{result['tx_hash']}"
        await status_msg.edit_text(f"✅ *Buy Complete!*\n🔗 [View on BscScan]({tx_url})", parse_mode="Markdown")
    else:
        await status_msg.edit_text(f"❌ *Failed:*\n`{escape_md(result.get('error'))}`", parse_mode="Markdown")

@dp.message(Command("autotrade"))
async def cmd_autotrade(message: types.Message):
    parts = message.text.strip().split()
    if len(parts) < 5:
        return await message.answer("Usage: `/autotrade <token> <amount_bnb> <tp%> <sl%>`\nExample: `/autotrade 0x... 0.05 50 15`", parse_mode="Markdown")

    token_address = parts[1]
    if not is_valid_evm_address(token_address):
        return await message.answer("❌ Invalid EVM token address.")

    try:
        amount_bnb = float(parts[2])
        tp_percent = float(parts[3])
        sl_percent = float(parts[4])
        if amount_bnb <= 0 or tp_percent <= 0 or sl_percent <= 0: raise ValueError
    except ValueError:
        return await message.answer("❌ Parameters must be valid positive numbers.")

    status_msg = await message.answer("🛡️ Auditing token and fetching entry price...")
    
    sec = await check_token_security(token_address)
    if not sec.get("safe"):
        return await status_msg.edit_text(f"🛑 *Refused:*\n`{escape_md(sec.get('reason'))}`", parse_mode="Markdown")

    entry_price = await get_live_token_price(token_address)
    if entry_price <= 0:
        return await status_msg.edit_text("❌ Failed to fetch accurate token price from DexScreener.")

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
        await status_msg.edit_text(f"❌ *Failed:*\n`{escape_md(result.get('error'))}`", parse_mode="Markdown")

@dp.message(Command("sell"))
async def cmd_sell(message: types.Message):
    parts = message.text.strip().split()
    if len(parts) < 2:
        return await message.answer("Usage: `/sell <token_address> <percent>`", parse_mode="Markdown")
    
    token_address = parts[1]
    if not is_valid_evm_address(token_address):
        return await message.answer("❌ Invalid EVM token address.")

    try:
        percent = float(parts[2]) if len(parts) >= 3 else 100.0
        if not (0 < percent <= 100): raise ValueError
    except ValueError:
        return await message.answer("❌ Percentage must be between 0.1 and 100.")

    status_msg = await message.answer("⏳ Executing sale...")
    pk = get_decrypted_private_key(message.from_user.id)
    
    res = await execute_sell_async(pk, token_address, percent, message.from_user.id, use_private_rpc=True)
    
    if res.get("success"):
        await status_msg.edit_text(f"✅ Sold {percent}%!\n🔗 [BscScan](https://bscscan.com/tx/{res['tx_hash']})", parse_mode="Markdown")
    else:
        await status_msg.edit_text(f"❌ *Failed:*\n`{escape_md(res.get('error'))}`", parse_mode="Markdown")

@dp.message(Command("addwhale"))
async def cmd_addwhale(message: types.Message):
    parts = message.text.strip().split()
    if len(parts) < 3:
        return await message.answer("Usage: `/addwhale <whale_address> <buy_amount_bnb>`", parse_mode="Markdown")
    
    whale_address = parts[1]
    if not is_valid_evm_address(whale_address):
        return await message.answer("❌ Invalid EVM address.")

    try:
        buy_amount = float(parts[2])
        if buy_amount <= 0: raise ValueError
    except ValueError:
        return await message.answer("❌ Invalid BNB amount.")
        
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
    try:
        msg = await bot.send_message(
            chat_id=cq.from_user.id,
            text=f"⚠️ *Private Key (Confidential):*\n`{pk}`\n\n_This message will self-destruct in 30 seconds._", 
            parse_mode="Markdown"
        )
        await cq.answer("Key sent to your private chat 🔒", show_alert=True)
        
        await asyncio.sleep(30)
        try:
            await msg.delete()
        except Exception:
            pass
    except Exception:
        await cq.answer("⚠️ Please start a private chat with the bot first to receive the key securely.", show_alert=True)

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
    logging.info("Owner Dashboard running at http://0.0.0.0:8080")
    
    asyncio.create_task(tpsl_monitor_task())
    
    whale_addresses = get_all_whale_addresses()
    if whale_addresses:
        logging.info(f"Starting Mempool Listener for {len(whale_addresses)} whales...")
        asyncio.create_task(track_mempool(whale_addresses))

    await set_bot_commands(bot)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())