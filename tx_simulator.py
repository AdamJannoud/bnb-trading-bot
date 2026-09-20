import logging
from web3 import AsyncWeb3

async def simulate_transaction(rpc_url: str, tx_params: dict) -> dict:
    w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(rpc_url))
    try:
        result = await w3.eth.call(tx_params)
        return {
            "success": True, 
            "result_hex": result.hex(), 
            "error": None
        }
    except Exception as e:
        error_message = str(e)
        logging.warning(f"🛑 Simulation Failed (Revert): {error_message}")
        
        reason = "Unknown Error"
        if "insufficient funds" in error_message.lower():
            reason = "Insufficient BNB for swap and gas."
        elif "transfer from failed" in error_message.lower():
            reason = "Token transfer locked (Potential Honeypot)."
            
        return {
            "success": False, 
            "result_hex": None, 
            "error": reason
        }