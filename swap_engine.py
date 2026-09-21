import json
import time
import asyncio
from decimal import Decimal
from web3 import AsyncWeb3
from db_manager import log_trade
from referral_manager import calculate_fee_split
from tx_simulator import simulate_transaction

with open("config.json", "r") as f:
    CONFIG = json.load(f)

RPC_URL = CONFIG["RPC_URL"]
PRIVATE_RPC_URL = CONFIG.get("PRIVATE_RPC_URL", RPC_URL)
CHAIN_ID = CONFIG["CHAIN_ID"]
ROUTER_ADDRESS = AsyncWeb3.to_checksum_address(CONFIG["PANCAKESWAP_ROUTER"])
WBNB_ADDRESS = AsyncWeb3.to_checksum_address(CONFIG["WBNB_ADDRESS"])
FEE_PERCENTAGE = Decimal(str(CONFIG.get("FEE_PERCENTAGE", 1.0)))
SLIPPAGE_TOLERANCE = 0.05

w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(RPC_URL))
private_w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(PRIVATE_RPC_URL))

PANCAKE_ROUTER_ABI = [
    {
        "inputs": [
            {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
            {"internalType": "address[]", "name": "path", "type": "address[]"},
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "uint256", "name": "deadline", "type": "uint256"}
        ],
        "name": "swapExactETHForTokensSupportingFeeOnTransferTokens",
        "outputs": [],
        "stateMutability": "payable",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
            {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
            {"internalType": "address[]", "name": "path", "type": "address[]"},
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "uint256", "name": "deadline", "type": "uint256"}
        ],
        "name": "swapExactTokensForETHSupportingFeeOnTransferTokens",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
            {"internalType": "address[]", "name": "path", "type": "address[]"}
        ],
        "name": "getAmountsOut",
        "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
        "stateMutability": "view",
        "type": "function"
    }
]

ERC20_ABI = [
    {
        "constant": True, "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"
    },
    {
        "constant": False, "inputs": [{"name": "_spender", "type": "address"}, {"name": "_value", "type": "uint256"}],
        "name": "approve", "outputs": [{"name": "success", "type": "bool"}], "type": "function"
    },
    {
        "constant": True, "inputs": [{"name": "_owner", "type": "address"}, {"name": "_spender", "type": "address"}],
        "name": "allowance", "outputs": [{"name": "remaining", "type": "uint256"}], "type": "function"
    }
]

async def get_bnb_balance_async(address: str) -> float:
    balance_wei = await w3.eth.get_balance(AsyncWeb3.to_checksum_address(address))
    return float(w3.from_wei(balance_wei, "ether"))

async def execute_buy_async(private_key: str, token_address: str, amount_bnb: float, user_id: int = 0, use_private_rpc: bool = False):
    active_w3 = private_w3 if use_private_rpc else w3
    account = active_w3.eth.account.from_key(private_key)
    user_address = account.address
    token_address = AsyncWeb3.to_checksum_address(token_address)

    balance = await get_bnb_balance_async(user_address)
    if balance < amount_bnb:
        return {"success": False, "error": f"Insufficient balance. Balance: {balance:.4f} BNB"}

    total_amount_wei = active_w3.to_wei(amount_bnb, "ether")
    fee_amount_wei = int(total_amount_wei * (FEE_PERCENTAGE / Decimal("100")))
    swap_amount_wei = total_amount_wei - fee_amount_wei

    current_nonce = await active_w3.eth.get_transaction_count(user_address, "pending")
    gas_price = await active_w3.eth.gas_price

    router_contract = active_w3.eth.contract(address=ROUTER_ADDRESS, abi=PANCAKE_ROUTER_ABI)
    path = [WBNB_ADDRESS, token_address]
    
    try:
        amounts_out = await router_contract.functions.getAmountsOut(swap_amount_wei, path).call()
        expected_tokens = amounts_out[1]
        amount_out_min = int(expected_tokens * (1 - SLIPPAGE_TOLERANCE))
    except Exception:
        amount_out_min = 0

    deadline = int(time.time()) + 1200

    swap_txn = await router_contract.functions.swapExactETHForTokensSupportingFeeOnTransferTokens(
        amount_out_min, path, user_address, deadline
    ).build_transaction({
        "from": user_address, "value": swap_amount_wei,
        "gas": 300000, "gasPrice": gas_price, "nonce": current_nonce, "chainId": CHAIN_ID
    })

    sim_rpc = PRIVATE_RPC_URL if use_private_rpc else RPC_URL
    sim_result = await simulate_transaction(sim_rpc, swap_txn)
    if not sim_result["success"]:
        return {"success": False, "error": f"Simulation Failed: {sim_result['error']}"}

    signed_swap_tx = active_w3.eth.account.sign_transaction(swap_txn, private_key)
    tx_hash = await active_w3.eth.send_raw_transaction(signed_swap_tx.raw_transaction)
    
    await active_w3.eth.wait_for_transaction_receipt(tx_hash)

    fee_splits = calculate_fee_split(fee_amount_wei, user_id)
    current_nonce = await active_w3.eth.get_transaction_count(user_address, "pending")

    if fee_splits["owner_share"] > 0:
        owner_wallet = AsyncWeb3.to_checksum_address(CONFIG["OWNER_FEE_WALLET"])
        fee_tx_owner = {
            "nonce": current_nonce, "to": owner_wallet, "value": fee_splits["owner_share"],
            "gas": 21000, "gasPrice": gas_price, "chainId": CHAIN_ID
        }
        signed_owner = active_w3.eth.account.sign_transaction(fee_tx_owner, private_key)
        await active_w3.eth.send_raw_transaction(signed_owner.raw_transaction)
        current_nonce += 1

    if fee_splits["referrer_share"] > 0 and fee_splits["referrer_wallet"]:
        ref_wallet = AsyncWeb3.to_checksum_address(fee_splits["referrer_wallet"])
        fee_tx_ref = {
            "nonce": current_nonce, "to": ref_wallet, "value": fee_splits["referrer_share"],
            "gas": 21000, "gasPrice": gas_price, "chainId": CHAIN_ID
        }
        signed_ref = active_w3.eth.account.sign_transaction(fee_tx_ref, private_key)
        await active_w3.eth.send_raw_transaction(signed_ref.raw_transaction)

    fee_bnb_float = float(active_w3.from_wei(fee_amount_wei, "ether"))
    log_trade(user_id, "BUY", token_address, amount_bnb, fee_bnb_float, tx_hash.hex())

    return {"success": True, "tx_hash": tx_hash.hex(), "swapped_bnb": float(active_w3.from_wei(swap_amount_wei, "ether"))}

async def execute_sell_async(private_key: str, token_address: str, percent: float = 100.0, user_id: int = 0, use_private_rpc: bool = False):
    active_w3 = private_w3 if use_private_rpc else w3
    account = active_w3.eth.account.from_key(private_key)
    user_address = account.address
    token_address = AsyncWeb3.to_checksum_address(token_address)
    
    router_contract = active_w3.eth.contract(address=ROUTER_ADDRESS, abi=PANCAKE_ROUTER_ABI)
    token_contract = active_w3.eth.contract(address=token_address, abi=ERC20_ABI)

    balance_raw = await token_contract.functions.balanceOf(user_address).call()
    if balance_raw == 0:
        return {"success": False, "error": "Token balance is 0."}

    amount_to_sell = int(Decimal(balance_raw) * (Decimal(str(percent)) / Decimal("100")))
    current_nonce = await active_w3.eth.get_transaction_count(user_address, "pending")
    gas_price = await active_w3.eth.gas_price

    allowance = await token_contract.functions.allowance(user_address, ROUTER_ADDRESS).call()
    if allowance < amount_to_sell:
        approve_txn = await token_contract.functions.approve(ROUTER_ADDRESS, 2**256 - 1).build_transaction({
            "from": user_address, "nonce": current_nonce, "gas": 60000,
            "gasPrice": gas_price, "chainId": CHAIN_ID
        })
        signed_approve = active_w3.eth.account.sign_transaction(approve_txn, private_key)
        approve_tx = await active_w3.eth.send_raw_transaction(signed_approve.raw_transaction)
        await active_w3.eth.wait_for_transaction_receipt(approve_tx)
        current_nonce += 1

    initial_bnb = await active_w3.eth.get_balance(user_address)
    path = [token_address, WBNB_ADDRESS]

    try:
        amounts_out = await router_contract.functions.getAmountsOut(amount_to_sell, path).call()
        expected_bnb = amounts_out[1]
        amount_out_min = int(expected_bnb * (1 - SLIPPAGE_TOLERANCE))
    except Exception:
        amount_out_min = 0

    swap_txn = await router_contract.functions.swapExactTokensForETHSupportingFeeOnTransferTokens(
        amount_to_sell, amount_out_min, path, user_address, int(time.time()) + 1200
    ).build_transaction({
        "from": user_address, "nonce": current_nonce,
        "gas": 350000, "gasPrice": gas_price, "chainId": CHAIN_ID
    })

    sim_rpc = PRIVATE_RPC_URL if use_private_rpc else RPC_URL
    sim_result = await simulate_transaction(sim_rpc, swap_txn)
    if not sim_result["success"]:
        return {"success": False, "error": f"Simulation Failed: {sim_result['error']}"}

    signed_swap = active_w3.eth.account.sign_transaction(swap_txn, private_key)
    tx_hash = await active_w3.eth.send_raw_transaction(signed_swap.raw_transaction)
    
    receipt = await active_w3.eth.wait_for_transaction_receipt(tx_hash)
    gas_spent_wei = receipt['gasUsed'] * receipt.get('effectiveGasPrice', gas_price)
    
    final_bnb = await active_w3.eth.get_balance(user_address)
    received_bnb_wei = (final_bnb + gas_spent_wei) - initial_bnb

    fee_wei = 0
    if received_bnb_wei > 0:
        fee_wei = int(received_bnb_wei * (FEE_PERCENTAGE / Decimal("100")))
        if fee_wei > 0:
            fee_splits = calculate_fee_split(fee_wei, user_id)
            fee_nonce = await active_w3.eth.get_transaction_count(user_address, "pending")
            
            if fee_splits["owner_share"] > 0:
                fee_tx_owner = {
                    "nonce": fee_nonce, 
                    "to": AsyncWeb3.to_checksum_address(CONFIG["OWNER_FEE_WALLET"]), 
                    "value": fee_splits["owner_share"], 
                    "gas": 21000, 
                    "gasPrice": gas_price, 
                    "chainId": CHAIN_ID
                }
                signed_owner = active_w3.eth.account.sign_transaction(fee_tx_owner, private_key)
                await active_w3.eth.send_raw_transaction(signed_owner.raw_transaction)

    sold_amount_bnb = float(active_w3.from_wei(max(0, received_bnb_wei), "ether"))
    fee_bnb_float = float(active_w3.from_wei(fee_wei, "ether"))
    log_trade(user_id, "SELL", token_address, sold_amount_bnb, fee_bnb_float, tx_hash.hex())

    return {"success": True, "tx_hash": tx_hash.hex()}