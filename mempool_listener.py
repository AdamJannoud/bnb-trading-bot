import asyncio
import json
import logging
import websockets
from web3 import AsyncWeb3
from db_manager import get_whale_followers
from wallet_manager import get_decrypted_private_key
from swap_engine import execute_buy_async

logging.basicConfig(level=logging.INFO)

with open("config.json", "r") as f:
    CONFIG = json.load(f)

WSS_URL = CONFIG.get("WSS_RPC_URL", "wss://bsc-ws-node.nodedata.com/")
HTTP_RPC_URL = CONFIG.get("RPC_URL", "https://bsc-dataseed.binance.org/")
ROUTER_ADDRESS = CONFIG.get("PANCAKESWAP_ROUTER", "").lower()

ROUTER_ABI = [
    {
        "inputs": [
            {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
            {"internalType": "address[]", "name": "path", "type": "address[]"},
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "uint256", "name": "deadline", "type": "uint256"}
        ],
        "name": "swapExactETHForTokens",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
            {"internalType": "address[]", "name": "path", "type": "address[]"},
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "uint256", "name": "deadline", "type": "uint256"}
        ],
        "name": "swapExactETHForTokensSupportingFeeOnTransferTokens",
        "type": "function"
    }
]

w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(HTTP_RPC_URL))
router_contract = w3.eth.contract(address=AsyncWeb3.to_checksum_address(CONFIG["PANCAKESWAP_ROUTER"]), abi=ROUTER_ABI)

async def track_mempool(target_wallets: set):
    if not target_wallets:
        return
        
    async with websockets.connect(WSS_URL) as ws:
        await ws.send(json.dumps({
            "id": 1,
            "method": "eth_subscribe",
            "params": ["newPendingTransactions"]
        }))
        
        subscription_response = await ws.recv()
        logging.info(f"Mempool Subscription Active for Whales: {subscription_response}")

        while True:
            try:
                message = await asyncio.wait_for(ws.recv(), timeout=15)
                data = json.loads(message)
                if "params" in data:
                    tx_hash = data["params"]["result"]
                    asyncio.create_task(process_pending_tx(tx_hash, target_wallets))
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logging.error(f"WSS Error: {e}")
                await asyncio.sleep(2)

async def process_pending_tx(tx_hash: str, target_wallets: set):
    try:
        tx = await w3.eth.get_transaction(tx_hash)
        if tx and tx['from'].lower() in target_wallets and tx['to'] and tx['to'].lower() == ROUTER_ADDRESS:
            logging.info(f"🚨 Target Whale Activity Detected: {tx['from']}")
            
            func_obj, func_params = router_contract.decode_function_input(tx['input'])
            
            if 'path' in func_params and len(func_params['path']) >= 2:
                token_address = func_params['path'][-1]
                logging.info(f"Whale is buying token: {token_address}. Executing Copy Trade...")
                
                asyncio.create_task(execute_copy_trade(tx['from'].lower(), token_address))
                
    except Exception:
        pass

async def execute_copy_trade(whale_address: str, token_address: str):
    followers = get_whale_followers(whale_address)
    if not followers:
        return
        
    tasks = []
    for follower in followers:
        user_id = follower['user_id']
        buy_amount = follower['buy_amount']
        
        private_key = get_decrypted_private_key(user_id)
        if private_key:
            tasks.append(
                execute_buy_async(private_key, token_address, buy_amount, user_id, use_private_rpc=True)
            )
            
    if tasks:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, res in enumerate(results):
            if isinstance(res, dict) and res.get('success'):
                logging.info(f"✅ Copy Trade Success for user {followers[i]['user_id']} | TX: {res['tx_hash']}")
            else:
                logging.error(f"❌ Copy Trade Failed for user {followers[i]['user_id']} | Error: {res}")