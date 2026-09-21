import logging
from web3 import AsyncWeb3

async def simulate_transaction(rpc_url: str, tx_params: dict) -> dict:
    w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(rpc_url))
    
    sim_params = tx_params.copy()
    if 'chainId' in sim_params:
        del sim_params['chainId']
        
    try:
        result = await w3.eth.call(sim_params)
        return {
            "success": True, 
            "result_hex": result.hex(), 
            "error": None
        }
    except Exception as e:
        error_message = str(e)
        logging.warning(f"🛑 Simulation Failed (Revert): {error_message}")
        
        reason = "Execution Reverted (Unknown Error)"
        lower_err = error_message.lower()
        
        if "insufficient funds" in lower_err:
            reason = "Insufficient BNB for swap and gas."
        elif "transfer from failed" in lower_err:
            reason = "Token transfer locked (Potential Honeypot)."
        elif "insufficient_output_amount" in lower_err:
            reason = "High Slippage Protection: Transaction reverted to prevent MEV/Sandwich attack loss."
            
        return {
            "success": False, 
            "result_hex": None, 
            "error": reason
        }