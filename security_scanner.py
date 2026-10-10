import aiohttp

GOPLUS_BSC_URL = "https://api.gopluslabs.io/api/v1/token_security/56"

async def check_token_security(token_address: str) -> dict:
    try:
        url = f"{GOPLUS_BSC_URL}?contract_addresses={token_address.lower()}"
        async with aiohttp.ClientSession() as session, session.get(url, timeout=7) as resp:
            if resp.status != 200:
                return {"safe": False, "reason": "Security API unreachable. Transaction blocked to protect your funds."}
                
            data = await resp.json()
            result = data.get("result", {}).get(token_address.lower(), {})
                
            if not result:
                return {"safe": False, "reason": "No security data available. Contract might be unverified."}

            is_honeypot = bool(int(result.get("is_honeypot", 0)))
            cannot_sell = bool(int(result.get("cannot_sell_all", 0)))
            buy_tax = float(result.get("buy_tax", 0)) * 100
            sell_tax = float(result.get("sell_tax", 0)) * 100

            if is_honeypot or cannot_sell or sell_tax > 15.0 or buy_tax > 15.0:
                # One clause per trigger that actually fired, so the message
                # names the real cause instead of a fixed honeypot template.
                causes = []
                if is_honeypot:
                    causes.append("Honeypot detected")
                if cannot_sell:
                    causes.append("Cannot sell all tokens (unsellable)")
                if buy_tax > 15.0:
                    causes.append(f"Buy Tax {buy_tax:.1f}% exceeds 15.0%")
                if sell_tax > 15.0:
                    causes.append(f"Sell Tax {sell_tax:.1f}% exceeds 15.0%")
                return {
                    "safe": False,
                    "reason": "High Risk Detected! " + " | ".join(causes),
                    "buy_tax": buy_tax,
                    "sell_tax": sell_tax
                }

            return {
                "safe": True,
                "buy_tax": buy_tax,
                "sell_tax": sell_tax
            }
    except Exception as e:
        return {"safe": False, "reason": f"Security check failed: {e!s}"}