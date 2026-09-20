import base58
from solders.keypair import Keypair
from solana.rpc.async_api import AsyncClient
from solders.pubkey import Pubkey

SOLANA_RPC = "https://api.mainnet-beta.solana.com"

def generate_solana_wallet() -> dict:
    keypair = Keypair()
    pubkey = str(keypair.pubkey())
    
    private_key_base58 = base58.b58encode(keypair.secret()).decode('utf-8')
    
    return {
        "address": pubkey,
        "private_key": private_key_base58
    }

async def get_sol_balance(wallet_address: str) -> float:
    try:
        async with AsyncClient(SOLANA_RPC) as client:
            pubkey = Pubkey.from_string(wallet_address)
            response = await client.get_balance(pubkey)
            balance_lamports = response.value
            return balance_lamports / 1_000_000_000
    except Exception as e:
        print(f"Solana RPC Error: {e}")