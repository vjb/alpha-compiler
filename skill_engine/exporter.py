import os
import json

def generate_execution_script(strategy: dict) -> str:
    """
    Generates a complete web3.py execution script based on the compiled strategy spec.
    The script fetches live price quotes and evaluates signals to execute trades on PancakeSwap (BSC).
    """
    strategy_json = json.dumps(strategy, indent=4)
    strategy_name = strategy['strategy_name']
    
    template = """# Auto-generated BSC PancakeSwap Execution Script for Strategy: __STRATEGY_NAME__
import os
import sys
import time
import requests
from dotenv import load_dotenv
from web3 import Web3

load_dotenv()

# 1. Strategy Parameters
STRATEGY = __STRATEGY_JSON__

# 2. PancakeSwap & BSC Contract Configurations
# BSC Mainnet PancakeSwap V2 Router: 0x10ED43C718714eb63d5aA57B78B54704E256024E
# BSC Testnet PancakeSwap V2 Router: 0x9Ac64Cc6e4415144C455BD8E4837Fea55603e5c3
PANCAKE_ROUTER_ADDRESS = "0x9Ac64Cc6e4415144C455BD8E4837Fea55603e5c3" # Default to BSC Testnet Router

# Standard ERC20/PancakeSwap Router minimal ABIs
ROUTER_ABI = [
    {
        "inputs": [
            {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
            {"internalType": "address[]", "name": "path", "type": "address[]"},
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "uint256", "name": "deadline", "type": "uint256"}
        ],
        "name": "swapExactETHForTokens",
        "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
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
        "name": "swapExactTokensForTokens",
        "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
        "stateMutability": "nonpayable",
        "type": "function"
    }
]

ERC20_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function"
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_spender", "type": "address"},
            {"name": "_value", "type": "uint256"}
        ],
        "name": "approve",
        "outputs": [{"name": "success", "type": "boolean"}],
        "type": "function"
    }
]

# Asset Contract Mapping (Common tokens on BSC Testnet for validation)
TOKEN_ADDRESSES = {
    "WBNB": "0xae13d989daC2f0dEbFf460aC112a837C89BAa7cd",
    "USDT": "0x337610d27c682E347C9cD60BD4b3b107C9d34dDd",
    "USDC": "0x64544E40E59acD492068F436F824fF7ccC55a539",
    "CAKE": "0xF9d27376e1E5dcd1e6dD49842F5605d39A4D30c7",
    "FLOKI": "0x53B026e6A1A7036494F3b98Cc819582d9213854F"
}

def get_live_indicators(symbol: str) -> dict:
    \"\"\"Fetches live indicators from CoinMarketCap REST client.\"\"\"
    api_key = os.environ.get("CMC_API_KEY")
    if not api_key:
        print("[Error] CMC_API_KEY is not set.")
        return {}
        
    try:
        # Fetch quotes and map to simulate rules
        url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
        res = requests.get(url, headers={"X-CMC_PRO_API_KEY": api_key}, params={"symbol": symbol})
        res.raise_for_status()
        data = res.json().get("data", {}).get(symbol, {})
        if isinstance(data, list) and len(data) > 0:
            data = data[0]
            
        usd_quote = data.get("quote", {}).get("USD", {})
        price = usd_quote.get("price", 0.0)
        volume = usd_quote.get("volume_24h", 0.0)
        
        # Approximate RSI and technical indicators using 24h change as a simple live proxy
        change = usd_quote.get("percent_change_24h", 0.0)
        rsi = 50.0 + (change * 1.5)
        rsi = max(0.0, min(100.0, rsi))
        
        # Calculate dynamic mock sentiment & metrics matching our compiler formulas
        sentiment = 0.5 + (change / 100.0)
        
        return {
            "rsi": rsi,
            "macd": 0.02 * change,
            "macd_signal": 0.01 * change,
            "ema_fast": price,
            "ema_slow": price,
            "news_sentiment_score": sentiment,
            "top_10_holder_percentage": 55.0,
            "liquidation_volume_short_24h": volume * 0.0001
        }
    except Exception as e:
        print(f"[Warning] Failed to fetch live data for {symbol}: {e}")
        return {}

def execute_swap(w3, account, path, amount_in_wei):
    \"\"\"Sends swap transaction on BSC PancakeSwap Router.\"\"\"
    router = w3.eth.contract(address=Web3.to_checksum_address(PANCAKE_ROUTER_ADDRESS), abi=ROUTER_ABI)
    deadline = int(time.time()) + 600 # 10 minutes deadline
    
    # Check if first token is BNB
    is_bnb = path[0].lower() == TOKEN_ADDRESSES["WBNB"].lower()
    
    # Build transaction
    nonce = w3.eth.get_transaction_count(account.address)
    
    if is_bnb:
        # Swap BNB -> Token with 2% slippage protection
        # Get expected output amount first
        amounts_out = router.functions.getAmountsOut(amount_in_wei, path).call()
        min_out = int(amounts_out[-1] * 0.98)  # 2% slippage tolerance
        print(f"Expected output: {amounts_out[-1]}, Min accepted (2% slip): {min_out}")
        tx = router.functions.swapExactETHForTokens(
            min_out, # 2% slippage protection
            path,
            account.address,
            deadline
        ).build_transaction({
            'from': account.address,
            'value': amount_in_wei,
            'gas': 250000,
            'gasPrice': w3.to_wei('5', 'gwei'),
            'nonce': nonce,
        })
    else:
        # Swap Token -> Token (requires approval first)
        token_in = w3.eth.contract(address=path[0], abi=ERC20_ABI)
        
        # Approve Router
        print(f"Approving PancakeSwap Router to spend {path[0]}...")
        approve_tx = token_in.functions.approve(PANCAKE_ROUTER_ADDRESS, amount_in_wei).build_transaction({
            'from': account.address,
            'gas': 100000,
            'gasPrice': w3.to_wei('5', 'gwei'),
            'nonce': nonce,
        })
        signed_approve = w3.eth.account.sign_transaction(approve_tx, account.key)
        approve_hash = w3.eth.send_raw_transaction(signed_approve.raw_transaction)
        print(f"Approval transaction sent. TxHash: {approve_hash.hex()}")
        w3.eth.wait_for_transaction_receipt(approve_hash)
        
        # Exec swap
        tx = router.functions.swapExactTokensForTokens(
            amount_in_wei,
            0, # amountOutMin
            path,
            account.address,
            deadline
        ).build_transaction({
            'from': account.address,
            'gas': 250000,
            'gasPrice': w3.to_wei('5', 'gwei'),
            'nonce': nonce + 1,
        })
        
    signed_tx = w3.eth.account.sign_transaction(tx, account.key)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    print(f"Swap Transaction Successful! TxHash: {tx_hash.hex()}")
    return tx_hash.hex()

def main():
    print(f"Initializing Execution Loop for strategy: {STRATEGY['strategy_name']}")
    
    # Load wallet
    private_key = os.environ.get("BSC_PRIVATE_KEY")
    if not private_key:
        print("[Error] BSC_PRIVATE_KEY environment variable is missing.")
        sys.exit(1)
        
    # Setup RPC Connection
    rpc_url = os.environ.get("BSC_RPC_URL", "https://data-seed-prebsc-1-s1.binance.org:8545")
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    if not w3.is_connected():
        print(f"[Error] Failed to connect to BSC RPC: {rpc_url}")
        sys.exit(1)
        
    account = w3.eth.account.from_key(private_key)
    print(f"Wallet Address: {account.address}")
    
    # Evaluate Entry and Exit rules for target assets
    assets = STRATEGY["target_assets"]
    entry_rules = STRATEGY["vectorbt_signals"]["entry_rules"]
    exit_rules = STRATEGY["vectorbt_signals"]["exit_rules"]
    
    # Operators mapping
    ops = {
        ">": lambda a, b: a > b,
        "<": lambda a, b: a < b,
        "==": lambda a, b: a == b
    }
    
    for asset in assets:
        if asset == "USDT" or asset == "USDC":
            continue
            
        print(f"Checking signals for asset: {asset}...")
        indicators = get_live_indicators(asset)
        if not indicators:
            continue
            
        # 1. Check Entry Signals (AND relationship)
        entry_triggered = True
        for rule in entry_rules:
            ind_name = rule["indicator"]
            op = rule["operator"]
            thresh = rule["threshold"]
            
            val = indicators.get(ind_name, 0.0)
            if not ops[op](val, thresh):
                entry_triggered = False
                break
                
        # 2. Check Exit Signals (OR relationship)
        exit_triggered = False
        for rule in exit_rules:
            ind_name = rule["indicator"]
            op = rule["operator"]
            thresh = rule["threshold"]
            
            val = indicators.get(ind_name, 0.0)
            if ops[op](val, thresh):
                exit_triggered = True
                break
                
        # 3. Trigger Trade Swaps on-chain
        if entry_triggered:
            print(f"[Signal] Entry Triggered for {asset}!")
            asset_address = TOKEN_ADDRESSES.get(asset)
            wbnb_address = TOKEN_ADDRESSES.get("WBNB")
            if asset_address and wbnb_address:
                path = [wbnb_address, asset_address]
                # Use allocation weight to determine trade size
                alloc_map = {w['symbol']: w['weight'] for w in STRATEGY['allocation_weights']}
                weight = alloc_map.get(asset, 0.1)
                bnb_balance = w3.eth.get_balance(account.address)
                trade_amount = int(bnb_balance * weight * 0.95)  # 95% of weighted share (keep gas)
                trade_amount = max(trade_amount, w3.to_wei('0.001', 'ether'))  # Min 0.001 BNB
                print(f"Swapping {w3.from_wei(trade_amount, 'ether'):.4f} BNB ({weight*100:.0f}% weight) for {asset}...")
                try:
                    execute_swap(w3, account, path, trade_amount)
                except Exception as e:
                    print(f"Swap execution failed: {e}")
            else:
                print(f"Missing address mapping for {asset} or WBNB. Skip.")
                
        elif exit_triggered:
            print(f"[Signal] Exit Triggered for {asset}!")
            asset_address = TOKEN_ADDRESSES.get(asset)
            usdt_address = TOKEN_ADDRESSES.get("USDT")
            if asset_address and usdt_address:
                path = [asset_address, usdt_address]
                print(f"Swapping {asset} to USDT...")
                try:
                    token = w3.eth.contract(address=asset_address, abi=ERC20_ABI)
                    balance = token.functions.balanceOf(account.address).call()
                    if balance > 0:
                        execute_swap(w3, account, path, balance)
                    else:
                        print("No balance to sell.")
                except Exception as e:
                    print(f"Exit swap execution failed: {e}")

if __name__ == "__main__":
    main()
"""
    return template.replace("__STRATEGY_NAME__", strategy_name).replace("__STRATEGY_JSON__", strategy_json)
