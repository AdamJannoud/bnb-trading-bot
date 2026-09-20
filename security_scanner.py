import aiohttp

GOPLUS_BSC_URL = "https://api.gopluslabs.io/api/v1/token_security/56"


async def check_token_security(token_address: str) -> dict:
    """
    Checks token security on BSC (Chain ID 56) via GoPlus API.
    Returns safety status, honeypot risk, and buy/sell tax.
    """
    try:
        url = f"{GOPLUS_BSC_URL}?contract_addresses={token_address.lower()}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=7) as resp:
                if resp.status != 200:
                    return {"safe": True, "warning": "Security API unreachable, proceeding with caution."}
                data = await resp.json()
                result = data.get("result", {}).get(token_address.lower(), {})
                if not result:
                    return {"safe": True, "warning": "No security data available."}

                is_honeypot = bool(int(result.get("is_honeypot", 0)))
                cannot_sell = bool(int(result.get("cannot_sell_all", 0)))
                buy_tax = float(result.get("buy_tax", 0)) * 100
                sell_tax = float(result.get("sell_tax", 0)) * 100

                # Reject the contract if it is a honeypot, cannot be sold, or sell tax exceeds 15%
                if is_honeypot or cannot_sell or sell_tax > 15.0:
                    return {
                        "safe": False,
                        "reason": f"High Risk! Honeypot: {is_honeypot}, Buy Tax: {buy_tax:.1f}%, Sell Tax: {sell_tax:.1f}%",
                        "buy_tax": buy_tax,
                        "sell_tax": sell_tax
                    }

                return {
                    "safe": True,
                    "buy_tax": buy_tax,
                    "sell_tax": sell_tax
                }
    except Exception as e:
        return {"safe": True, "warning": f"Security check bypassed: {str(e)}"}