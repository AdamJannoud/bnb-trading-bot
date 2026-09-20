import aiohttp

DEXSCREENER_SEARCH_URL = "https://api.dexscreener.com/latest/dex/search?q=WBNB"


async def fetch_trending_signals():
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(DEXSCREENER_SEARCH_URL, timeout=10) as response:
                if response.status != 200:
                    return []
                data = await response.json()
                pairs = data.get("pairs", [])

                bsc_signals = []
                for pair in pairs:
                    if pair.get("chainId") == "bsc":
                        base_token = pair.get("baseToken", {})
                        base_addr = base_token.get("address")
                        base_name = base_token.get("name", "Unknown")
                        base_symbol = base_token.get("symbol", "UNKNOWN")
                        price_usd = pair.get("priceUsd", "N/A")
                        price_change = pair.get("priceChange", {}).get("h24", "0")
                        pair_url = pair.get("url", f"https://dexscreener.com/bsc/{base_addr}")

                        if base_addr.lower() == "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c":
                            continue

                        bsc_signals.append({
                            "name": base_name,
                            "symbol": base_symbol,
                            "address": base_addr,
                            "price_usd": price_usd,
                            "change_24h": price_change,
                            "url": pair_url
                        })

                        if len(bsc_signals) >= 4:
                            break

                return bsc_signals
    except Exception as e:
        print(f"Error fetching signals: {e}")
        return []