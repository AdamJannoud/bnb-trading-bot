import base64
import base58
import aiohttp
from solders.keypair import Keypair
from solana.rpc.async_api import AsyncClient
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction

SOLANA_RPC = "https://api.mainnet-beta.solana.com"
JUPITER_QUOTE_API = "https://quote-api.jup.ag/v6/quote"
JUPITER_SWAP_API = "https://quote-api.jup.ag/v6/swap"

def generate_solana_wallet() -> dict:
    keypair = Keypair()
    return {
        "address": str(keypair.pubkey()),
        "private_key": base58.b58encode(keypair.secret()).decode('utf-8')
    }

async def get_sol_balance(wallet_address: str) -> float:
    try:
        async with AsyncClient(SOLANA_RPC) as client:
            pubkey = Pubkey.from_string(wallet_address)
            response = await client.get_balance(pubkey)
            return response.value / 1_000_000_000
    except Exception as e:
        print(f"Solana RPC Error: {e}")
        return 0.0

async def execute_solana_swap(private_key_b58: str, input_mint: str, output_mint: str, amount_lamports: int, slippage_bps: int = 200) -> dict:
    try:
        keypair = Keypair.from_bytes(base58.b58decode(private_key_b58))
        user_pubkey = str(keypair.pubkey())

        async with aiohttp.ClientSession() as session:
            quote_url = f"{JUPITER_QUOTE_API}?inputMint={input_mint}&outputMint={output_mint}&amount={amount_lamports}&slippageBps={slippage_bps}"
            async with session.get(quote_url) as resp:
                quote_res = await resp.json()
                if "error" in quote_res:
                    return {"success": False, "error": quote_res["error"]}

            swap_payload = {
                "quoteResponse": quote_res,
                "userPublicKey": user_pubkey,
                "wrapAndUnwrapSol": True,
                "dynamicComputeUnitLimit": True,
                "prioritizationFeeLamports": "auto"
            }
            async with session.post(JUPITER_SWAP_API, json=swap_payload) as resp:
                swap_res = await resp.json()
                if "error" in swap_res:
                    return {"success": False, "error": swap_res["error"]}

            swap_tx_b64 = swap_res["swapTransaction"]
            raw_tx = base64.b64decode(swap_tx_b64)
            tx = VersionedTransaction.from_bytes(raw_tx)
            
            signed_tx = VersionedTransaction(tx.message, [keypair])

            async with AsyncClient(SOLANA_RPC) as client:
                tx_id = await client.send_raw_transaction(bytes(signed_tx))
                return {"success": True, "tx_hash": str(tx_id.value)}

    except Exception as e:
        return {"success": False, "error": str(e)}