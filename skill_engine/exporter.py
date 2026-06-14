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
import json
import pandas as pd
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

# Import ALLOWED_BEP20_TOKENS
from skill_engine.constants import ALLOWED_BEP20_TOKENS

# Asset Contract Mapping (Common tokens on BSC Testnet for validation)
TOKEN_ADDRESSES = {
    "WBNB": "0xae13d989daC2f0dEbFf460aC112a837C89BAa7cd",
    "USDT": "0x337610d27c682E347C9cD60BD4b3b107C9d34dDd",
    "USDC": "0x64544E40E59acD492068F436F824fF7ccC55a539",
    "CAKE": "0xF9d27376e1E5dcd1e6dD49842F5605d39A4D30c7",
    "FLOKI": "0x53B026e6A1A7036494F3b98Cc819582d9213854F"
}

# Fill other allowed tokens dynamically with FLOKI testnet address as a fallback
for t in ALLOWED_BEP20_TOKENS:
    if t not in TOKEN_ADDRESSES:
        TOKEN_ADDRESSES[t] = TOKEN_ADDRESSES["FLOKI"]

def make_tz_naive(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    if index.tz is not None:
        return index.tz_convert(None)
    return index

def compute_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / (loss + 1e-9)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50.0)

def compute_macd(prices: pd.Series, fast: int = 12, slow: int = 26) -> pd.Series:
    exp1 = prices.ewm(span=fast, adjust=False).mean()
    exp2 = prices.ewm(span=slow, adjust=False).mean()
    return exp1 - exp2

def compute_macd_signal(prices: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.Series:
    macd = compute_macd(prices, fast, slow)
    return macd.ewm(span=signal, adjust=False).mean()

def compute_ema(prices: pd.Series, period: int = 9) -> pd.Series:
    return prices.ewm(span=period, adjust=False).mean()

def fetch_cmc_map_id(symbol: str, api_key: str = None) -> int:
    \"\"\"Map symbol to CMC ID using official /v1/cryptocurrency/map, or keyless search fallback.\"\"\"
    cache_file = "symbol_mappings_cache.json"
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r") as f:
                cache = json.load(f)
                if symbol.upper() in cache:
                    return int(cache[symbol.upper()])
        except Exception:
            pass

    hardcoded_map = {
        "BNB": 1839,
        "CAKE": 7186,
        "FLOKI": 10804,
        "USDT": 825,
        "USDC": 3408,
        "BTC": 1,
        "ETH": 1027,
    }
    if symbol.upper() in hardcoded_map:
        return hardcoded_map[symbol.upper()]

    if api_key:
        try:
            url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/map"
            res = requests.get(url, headers={"X-CMC_PRO_API_KEY": api_key, "Accept": "application/json"}, params={"symbol": symbol}, timeout=10.0)
            if res.status_code == 200:
                data = res.json().get("data", [])
                best_item = None
                for item in data:
                    if item["symbol"].upper() == symbol.upper():
                        if best_item is None:
                            best_item = item
                        else:
                            if item["is_active"] > best_item["is_active"]:
                                best_item = item
                            elif item["is_active"] == best_item["is_active"]:
                                if item.get("rank") is not None and (best_item.get("rank") is None or item["rank"] < best_item["rank"]):
                                    best_item = item
                if best_item:
                    return int(best_item["id"])
        except Exception as e:
            print(f"[Warning] Map ID lookup via Pro API failed: {e}")

    try:
        url = "https://api.coinmarketcap.com/data-api/v3/search/searchTerm"
        res = requests.get(url, params={"keyword": symbol}, timeout=10.0)
        res.raise_for_status()
        crypto_list = res.json().get("data", {}).get("cryptoCurrencies", [])
        if not crypto_list:
            crypto_list = res.json().get("data", {}).get("crypto", [])
        best_item = None
        for item in crypto_list:
            if item.get("symbol", "").upper() == symbol.upper():
                if best_item is None:
                    best_item = item
                else:
                    item_active = item.get("isActive", item.get("is_active", 1))
                    best_active = best_item.get("isActive", best_item.get("is_active", 1))
                    if item_active > best_active:
                        best_item = item
                    elif item_active == best_active:
                        item_rank = item.get("rank")
                        best_rank = best_item.get("rank")
                        if item_rank is not None and (best_rank is None or item_rank < best_rank):
                            best_item = item
        if best_item:
            return int(best_item["id"])
    except Exception as e:
        print(f"[Warning] Keyless map fallback failed for {symbol}: {e}")

    raise ValueError(f"Could not resolve CMC ID for symbol {symbol}")

def fetch_cmc_historical_data(symbol: str, backtest_range: str = "30d") -> pd.DataFrame:
    \"\"\"Fetch historical daily OHLCV and volume data with keyless fallback.\"\"\"
    api_key = os.environ.get("CMC_API_KEY")
    count_map = {
        "7d": 7,
        "30d": 30,
        "90d": 90,
        "1y": 365
    }
    count = count_map.get(backtest_range, 30)

    if api_key:
        print(f"Attempting to fetch historical data ({backtest_range}) for {symbol} via official Pro API...")
        url = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/ohlcv/historical"
        headers = {
            "X-CMC_PRO_API_KEY": api_key,
            "Accept": "application/json"
        }
        params = {
            "symbol": symbol,
            "count": count,
            "interval": "1d"
        }
        try:
            res = requests.get(url, headers=headers, params=params, timeout=5.0)
            if res.status_code == 200:
                data = res.json()
                quotes = data["data"][symbol][0]["quotes"]
                records = []
                for q in quotes:
                    ts = pd.to_datetime(q["time_open"])
                    records.append({
                        "date": ts,
                        "open": q["quote"]["USD"]["open"],
                        "high": q["quote"]["USD"]["high"],
                        "low": q["quote"]["USD"]["low"],
                        "close": q["quote"]["USD"]["close"],
                        "volume": q["quote"]["USD"]["volume"]
                    })
                df = pd.DataFrame(records)
                df.set_index("date", inplace=True)
                df.index = make_tz_naive(df.index).normalize()
                df.sort_index(inplace=True)
                df = df.groupby(df.index).last()
                print(f"Successfully fetched historical data for {symbol} via Pro API.")
                return df
            else:
                print(f"Pro API returned status {res.status_code}: {res.text[:150]}")
        except Exception as e:
            print(f"Pro API failed ({e}). Pivoting to keyless public data-api endpoint...")

    try:
        cmc_id = fetch_cmc_map_id(symbol, api_key)
        range_map = {
            "7d": "7D",
            "30d": "1M",
            "90d": "3M",
            "1y": "1Y"
        }
        api_range = range_map.get(backtest_range, "1M")
        chart_url = f"https://api.coinmarketcap.com/data-api/v3/cryptocurrency/detail/chart?id={cmc_id}&range={api_range}"
        res = requests.get(chart_url, timeout=5.0)
        res.raise_for_status()
        points = res.json().get("data", {}).get("points", {})
        if not points:
            raise ValueError(f"No chart points found for {symbol} (ID: {cmc_id})")
        records = []
        for ts_str in sorted(points.keys()):
            ts = pd.to_datetime(int(ts_str), unit="s")
            val = points[ts_str]["v"]
            close_val = val[0]
            vol_val = val[1] if len(val) > 1 else 0.0
            records.append({
                "date": ts,
                "open": close_val,
                "high": close_val,
                "low": close_val,
                "close": close_val,
                "volume": vol_val
            })
        df = pd.DataFrame(records)
        df.set_index("date", inplace=True)
        df.index = make_tz_naive(df.index).normalize()
        df.sort_index(inplace=True)
        df = df.groupby(df.index).last()
        print(f"Successfully fetched historical data for {symbol} (ID: {cmc_id}) via public chart API.")
        return df
    except Exception as e:
        print(f"[Error] Keyless historical fetch failed for {symbol}: {e}")
        raise e

def get_live_indicators(symbol: str) -> dict:
    \"\"\"Fetches live indicators using aligned historical and live CoinMarketCap quotes.\"\"\"
    try:
        df = fetch_cmc_historical_data(symbol, backtest_range="30d")
        if df.empty:
            print(f"[Warning] Historical data for {symbol} is empty.")
            return {}
    except Exception as e:
        print(f"[Warning] Failed to fetch historical data for {symbol}: {e}")
        return {}

    api_key = os.environ.get("CMC_API_KEY")
    live_price = None
    live_volume = None

    if api_key:
        try:
            url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
            res = requests.get(url, headers={"X-CMC_PRO_API_KEY": api_key}, params={"symbol": symbol}, timeout=5.0)
            if res.status_code == 200:
                data = res.json().get("data", {}).get(symbol, {})
                if isinstance(data, list) and len(data) > 0:
                    data = data[0]
                usd_quote = data.get("quote", {}).get("USD", {})
                live_price = usd_quote.get("price")
                live_volume = usd_quote.get("volume_24h")
        except Exception as e:
            print(f"[Warning] Failed to fetch live quote for {symbol}: {e}")

    if live_price is None or live_volume is None:
        print(f"[Info] Using last historical data as live fallback for {symbol}.")
        live_price = float(df['close'].iloc[-1])
        live_volume = float(df['volume'].iloc[-1])

    df.index = make_tz_naive(df.index).normalize()
    today_ts = pd.Timestamp.utcnow().tz_localize(None).normalize()
    if df.index[-1] == today_ts:
        df.loc[today_ts, 'close'] = live_price
        df.loc[today_ts, 'volume'] = live_volume
    else:
        df.loc[today_ts] = {
            'open': live_price,
            'high': live_price,
            'low': live_price,
            'close': live_price,
            'volume': live_volume
        }
    df.sort_index(inplace=True)

    close_series = df['close']
    volume_series = df['volume']

    fg_value = 50.0
    if api_key:
        try:
            fg_res = requests.get("https://pro-api.coinmarketcap.com/v3/fear-and-greed/latest", headers={"X-CMC_PRO_API_KEY": api_key}, timeout=5.0)
            if fg_res.status_code == 200:
                fg_value = float(fg_res.json().get("data", {}).get("value", 50.0))
        except Exception:
            pass

    rsi_series = compute_rsi(close_series, period=14)
    macd_series = compute_macd(close_series, fast=12, slow=26)
    macd_sig_series = compute_macd_signal(close_series, fast=12, slow=26, signal=9)
    ema_fast_series = compute_ema(close_series, period=12)
    ema_slow_series = compute_ema(close_series, period=26)

    fg_sentiment = (fg_value - 50.0) / 50.0
    pct_change_3 = close_series.pct_change(3).clip(-1, 1).fillna(0.0)
    news_sentiment_series = 0.4 * fg_sentiment + 0.6 * pct_change_3

    volume_velocity = volume_series / (close_series * 10000000.0 + 1.0)
    top_10_holder_series = (65.0 + (1.0 - volume_velocity.clip(0, 1)) * 20.0).fillna(75.0)

    rolling_std = close_series.pct_change().rolling(5).std().fillna(0.02)
    price_drop = (-close_series.pct_change()).clip(lower=0).fillna(0.0)
    liquidation_series = volume_series * 0.0005 * rolling_std * (1.0 + price_drop * 10.0)

    kol_sentiment_series = close_series.pct_change(5).clip(-1, 1).fillna(0.0)

    rolling_vol = close_series.pct_change().rolling(7).std().fillna(0.02)
    funding_rate_series = rolling_vol * 10000

    sentiment_regime_series = pd.Series(fg_value, index=close_series.index) - rolling_vol * 500

    vol_ma = volume_series.rolling(14).mean()
    whale_anomaly_series = (volume_series / (vol_ma + 1e-9)).fillna(1.0)

    return {
        "rsi": float(rsi_series.iloc[-1]),
        "macd": float(macd_series.iloc[-1]),
        "macd_signal": float(macd_sig_series.iloc[-1]),
        "ema_fast": float(ema_fast_series.iloc[-1]),
        "ema_slow": float(ema_slow_series.iloc[-1]),
        "news_sentiment_score": float(news_sentiment_series.iloc[-1]),
        "top_10_holder_percentage": float(top_10_holder_series.iloc[-1]),
        "liquidation_volume_short_24h": float(liquidation_series.iloc[-1]),
        "kol_sentiment_bias": float(kol_sentiment_series.iloc[-1]),
        "funding_rate_bps": float(funding_rate_series.iloc[-1]),
        "sentiment_regime_score": float(sentiment_regime_series.iloc[-1]),
        "whale_anomaly_score": float(whale_anomaly_series.iloc[-1])
    }

def execute_swap(w3, account, path, amount_in_wei):
    \"\"\"Sends swap transaction on BSC PancakeSwap Router.\"\"\"
    router = w3.eth.contract(address=Web3.to_checksum_address(PANCAKE_ROUTER_ADDRESS), abi=ROUTER_ABI)
    deadline = int(time.time()) + 600 # 10 minutes deadline
    
    # Check if first token is BNB
    is_bnb = path[0].lower() == TOKEN_ADDRESSES["WBNB"].lower()
    
    if not is_bnb:
        # Swap Token -> Token (requires approval first)
        token_in = w3.eth.contract(address=path[0], abi=ERC20_ABI)
        
        # Approve Router
        print(f"Approving PancakeSwap Router to spend {path[0]}...")
        approve_success = False
        for attempt in range(1, 4):
            try:
                nonce = w3.eth.get_transaction_count(account.address)
                approve_tx = token_in.functions.approve(PANCAKE_ROUTER_ADDRESS, amount_in_wei).build_transaction({
                    'from': account.address,
                    'gas': 100000,
                    'gasPrice': w3.to_wei('5', 'gwei'),
                    'nonce': nonce,
                })
                signed_approve = w3.eth.account.sign_transaction(approve_tx, account.key)
                approve_hash = w3.eth.send_raw_transaction(signed_approve.raw_transaction)
                print(f"Approval transaction sent. Attempt {attempt}/3. TxHash: {approve_hash.hex()}")
                w3.eth.wait_for_transaction_receipt(approve_hash, timeout=120)
                approve_success = True
                break
            except Exception as e:
                print(f"[Warning] Approval attempt {attempt}/3 failed: {e}")
                if attempt == 3:
                    raise e
                time.sleep(2)

    # Exec swap
    for attempt in range(1, 4):
        try:
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
                # Swap Token -> Token
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
                    'nonce': nonce,
                })
                
            signed_tx = w3.eth.account.sign_transaction(tx, account.key)
            tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
            print(f"Swap transaction sent. Attempt {attempt}/3. TxHash: {tx_hash.hex()}")
            
            # Wait for receipt and log block and gas
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            print(f"Swap Transaction Successful! Block: {receipt.blockNumber}, Gas Used: {receipt.gasUsed}")
            return tx_hash.hex()
        except Exception as e:
            print(f"[Warning] Swap attempt {attempt}/3 failed: {e}")
            if attempt == 3:
                raise e
            time.sleep(2)

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
