# ⚡ Universal Sniper & Auto-Trading Bot (BSC / EVM)

An asynchronous Telegram trading bot built with Python, Web3, and Aiogram[cite: 1, 10]. Designed for automated token swapping, copy-trading via mempool listener, take-profit/stop-loss automation, and referral-based fee management on BNB Smart Chain[cite: 1, 5, 6].

---

## 🚀 Key Features

* **Telegram Bot Interface (`bot.py`)**: Manage wallets, balances, and trading directly via Telegram commands[cite: 1].
* **Instant Swaps & Anti-MEV Simulation (`swap_engine.py` & `tx_simulator.py`)**: PancakeSwap router integration with pre-execution `eth_call` simulation[cite: 10, 11].
* **Automated TP/SL Engine**: Continuous price monitoring via DexScreener API with auto-sell triggers[cite: 1].
* **Mempool Sniping & Copy Trading (`mempool_listener.py`)**: WebSocket listener tracking pending transactions for designated whale addresses[cite: 5].
* **Security & Rug-Pull Scanner (`security_scanner.py`)**: Integrated GoPlus API check to detect honeypots, transfer locks, and high taxes[cite: 7].
* **Multi-Wallet Support (`wallet_manager.py`)**: Local Fernet encryption for generated EVM and Solana keypairs[cite: 12].
* **Owner Analytics Dashboard (`dashboard.py`)**: Built-in HTTP dashboard serving metrics for total volume, fees, and trades[cite: 3].
* **Referral System (`referral_manager.py`)**: Dynamic referral tracking and commission distribution[cite: 6].

---

## 📁 Repository Structure

```text
├── bot.py                  # Main entry point and Telegram command handlers[cite: 1]
├── swap_engine.py          # PancakeSwap routing, execution, and fee logic[cite: 10]
├── mempool_listener.py     # WSS listener for whale tracking and copy trading[cite: 5]
├── tx_simulator.py         # Transaction pre-flight simulation[cite: 11]
├── wallet_manager.py       # Local wallet generation and Fernet key encryption[cite: 12]
├── security_scanner.py     # GoPlus token security auditor[cite: 7]
├── signals_scanner.py      # DexScreener trending signals retriever[cite: 8]
├── db_manager.py           # SQLite database schema and operations[cite: 4]
├── referral_manager.py     # Referral reward calculator and registry[cite: 6]
├── dashboard.py            # Basic-auth web dashboard[cite: 3]
├── solana_engine.py        # Experimental Solana/Jupiter integration[cite: 9]
├── risk.py                 # Kill switch, position caps and daily loss cap
├── wallet_tools.py         # Server-side wallet tools (private-key export)
├── tests/                  # Offline pytest suite
├── config.example.json     # Configuration template[cite: 2]
├── .env.example            # Environment variables (WALLET_ENCRYPTION_KEY)
└── requirements.txt        # Python dependency manifest
```

---

## 🛠️ Installation & Setup

### 1. Clone the Repository
```bash
git clone [https://github.com/AdamJannoud/bnb-trading-bot.git](https://github.com/AdamJannoud/bnb-trading-bot.git)
cd bnb-trading-bot
```

### 2. Configure Environment
Install dependencies:
```bash
pip install -r requirements.txt
```

### 3. Setup Configuration
Copy the sample config file to `config.json`[cite: 2]:
```bash
cp config.example.json config.json
```

Edit `config.json` and provide your credentials[cite: 2]:
* `BOT_TOKEN`: Your Telegram Bot API token from @BotFather[cite: 2].
* `OWNER_TELEGRAM_ID`: Your Telegram numeric user ID[cite: 2].
* `OWNER_FEE_WALLET`: EVM address for collecting platform commissions[cite: 2].
* `RPC_URL` & `WSS_RPC_URL`: Reliable RPC and WebSocket endpoints[cite: 2].
* `SLIPPAGE_TOLERANCE` (default `0.05`): the fraction below the router's quote that a swap may fill at. Values above `0.15` (or at or below `0`) are refused at startup, because a floor that wide protects nothing.

* `MAX_TRADE_BNB` (default `0.1`): the largest single buy, in BNB, for `/buy`, `/autotrade` and copy-trades.
* `MAX_OPEN_EXPOSURE_BNB` (default `0.3`): the most BNB one user can have in open positions at once.
* `DAILY_LOSS_CAP_BNB` (default `0.05`): net realised loss over a rolling 24 hours after which buying pauses for that user.

> **Price protection fails closed.** If the router cannot quote a trade, the trade is not sent: the user is told why and nothing is signed. The quote is taken a second time immediately before signing, and the trade is abandoned if the price has moved past `SLIPPAGE_TOLERANCE` in between.

### 4. Set the Wallet Encryption Key
Every stored wallet private key is encrypted with a Fernet key supplied in the `WALLET_ENCRYPTION_KEY` environment variable (see `.env.example`). It is never read from, or written to, a file next to the database.

* **First start, empty database:** leave it unset. The bot generates a key, prints it to the terminal once, and exits. Store it somewhere safe, export it, and start again.
* **Missing key with wallets in the database:** the bot refuses to start. It will never generate a replacement key over existing wallets.
* **Wrong key:** at startup the bot decrypts a stored wallet as a self-test, and refuses to start if that fails.
* **Upgrading from a version that used `secret.key`:** the file is no longer read. Put its contents into `WALLET_ENCRYPTION_KEY` and move the file out of the database directory; until then the bot refuses to start.

```bash
export WALLET_ENCRYPTION_KEY="<your key>"
```

### 5. Run the Bot
```bash
python bot.py
```

### 6. Run the Tests
The suite is fully offline (web3 is stubbed, sockets are blocked) and needs no `config.json`, keys or `.env`:
```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

---

## 🤖 Available Bot Commands

| Command | Description |
| :--- | :--- |
| `/start` | Open the main menu, show deposit wallet, and get referral link[cite: 1]. |
| `/wallet` | View your deposit address and current BNB balance. |
| `/buy <token> <amount>` | Execute an instant swap via PancakeSwap[cite: 1]. |
| `/sell <token> <percent>` | Sell a percentage (or 100%) of held tokens[cite: 1]. |
| `/autotrade <token> <bnb> <tp%> <sl%>` | Enter a position with automated Take-Profit and Stop-Loss[cite: 1]. |
| `/addwhale <address> <amount>` | Add a target wallet to copy trade on mempool events[cite: 1]. |
| `/dashboard` | View owner analytics dashboard credentials[cite: 1]. |
| `/stop` | Owner only. Stop all buying, including copy-trades. Survives restarts. |
| `/resume` | Owner only. Re-enable buying after `/stop`. |

### Risk Controls
Every buy path (`/buy`, `/autotrade` and the copy-trader) passes the same guard (`risk.py`) before anything is signed. Selling is never blocked, so a stop or a cap cannot trap funds.

* **Kill switch:** `/stop` and `/resume`, owner only, stored in the database.
* **Per-trade cap:** a buy larger than `MAX_TRADE_BNB` is refused.
* **Open exposure cap:** a buy that would take the user's open positions above `MAX_OPEN_EXPOSURE_BNB` is refused. Every buy opens a position at its BNB cost, and selling closes it.
* **Daily loss cap:** once realised losses (net of gains, from the trade log) over the last 24 hours reach `DAILY_LOSS_CAP_BNB`, buying pauses for that user until the losses age out of the window, and the owner is messaged.
* **Positions know their size:** each position records the token amount its buy delivered. A TP/SL exit sells exactly that amount, never the wallet's whole balance. Positions opened before this change have no recorded amount; when their TP/SL triggers they are taken off auto-management and the user is told to exit with `/sell`.

### Exporting a private key (server only)
The bot never sends a private key through Telegram; there is no button or command that produces one. If a user needs their key, the owner exports it on the host itself, in an interactive terminal:
```bash
python wallet_tools.py export --user-id <telegram_user_id> [--chain EVM|SOLANA]
```
The key is printed to that terminal only. The command refuses to run when its output is redirected to a file or a pipe, so it cannot end up in a log by accident.

---

## ⚠️ Disclaimer

> **Educational and Research Purposes Only**: This codebase is published as a proof-of-concept open-source repository. Cryptocurrency trading, MEV sniping, and automated scripts carry significant financial risk. The authors are not responsible for any financial losses, slippage, failed transactions, or security breaches resulting from the use or deployment of this software. Use at your own risk.

---

## 👤 Maintainer & Attribution

Maintained by **AdamJannoud** (<jannoud-adam@hotmail.com>). Released under the MIT License; see [`LICENSE`](LICENSE).

The maintainer commits to keeping this release's security fixes intact: fail-closed price quotes with a re-quote at signing, no private-key export through Telegram, a required `WALLET_ENCRYPTION_KEY` with refuse-to-start when it is missing or wrong, and the risk controls above. Changes that weaken any of them will not be accepted.
