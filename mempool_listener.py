import asyncio
import json
import logging
import websockets
from web3 import AsyncWeb3

WSS_URL = "wss://bsc-ws-node.example.com/"
HTTP_RPC_URL = "https://bsc-dataseed.binance.org/"

logging.basicConfig(level=logging.INFO)

async def track_mempool(target_wallets: set):
    async with websockets.connect(WSS_URL) as ws:
        await ws.send(json.dumps({
            "id": 1,
            "method": "eth_subscribe",
            "params": ["newPendingTransactions"]
        }))
        
        subscription_response = await ws.recv()
        logging.info(f"Mempool Subscription Active: {subscription_response}")

        w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(HTTP_RPC_URL))

        while True:
            try:
                message = await asyncio.wait_for(ws.recv(), timeout=15)
                data = json.loads(message)
                if "params" in data:
                    tx_hash = data["params"]["result"]
                    asyncio.create_task(process_pending_tx(w3, tx_hash, target_wallets))
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logging.error(f"WSS Error: {e}")

async def process_pending_tx(w3: AsyncWeb3, tx_hash: str, target_wallets: set):
    try:
        tx = await w3.eth.get_transaction(tx_hash)
        if tx and tx['from'].lower() in target_wallets:
            logging.info(f"🚨 Target Wallet Activity Detected: {tx['from']}")
            logging.info(f"Transaction Hash: {tx_hash}")
            
            # asyncio.create_task(execute_copy_trade(tx))
    except Exception:
        pass