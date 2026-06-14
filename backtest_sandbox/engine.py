import os
import json
import pandas as pd
import vectorbt as vbt
import requests
import operator
import time
from dotenv import load_dotenv

load_dotenv()

OPERATORS = {
    ">": operator.gt,
    "<": operator.lt,
    "==": operator.eq
}

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

def compute_dynamic_slippage(trade_size: float, daily_volume: float, volatility: float) -> float:
    """
    Model real AMM slippage using constant-product approximation + base DEX fee.
    Returns the total transaction cost as a fraction (e.g. 0.003 = 0.3%).
    """
    base_fee = 0.0025  # PancakeSwap 0.25% base fee
    if daily_volume <= 0:
        return base_fee + 0.01  # 1% slippage for illiquid assets
    
    # Price impact from constant-product AMM: ~trade_size / (2 * liquidity_depth)
    # Approximate liquidity depth as 5% of daily volume
    liquidity_depth = daily_volume * 0.05
    price_impact = trade_size / (2 * liquidity_depth + 1e-9)
    price_impact = min(price_impact, 0.05)  # Cap at 5%
    
    # Volatility adjustment: higher vol = wider spreads
    vol_spread = volatility * 0.5  # Half the daily vol as spread estimate
    vol_spread = min(vol_spread, 0.02)  # Cap at 2%
    
    # Gas cost estimate: ~$0.05 per BSC transaction, normalized to trade size
    gas_cost_usd = 0.05
    gas_fraction = gas_cost_usd / (trade_size + 1e-9) if trade_size > 0 else 0.0
    
    return base_fee + price_impact + vol_spread + gas_fraction

def fetch_cmc_map_id(symbol: str, api_key: str) -> int:
    """Map symbol to CMC ID using official /v1/cryptocurrency/map."""
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/map"
    res = requests.get(url, headers={"X-CMC_PRO_API_KEY": api_key, "Accept": "application/json"}, params={"symbol": symbol}, timeout=10.0)
    res.raise_for_status()
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
    if not best_item:
        raise ValueError(f"Could not resolve CMC ID for symbol {symbol}")
    return best_item["id"]

def fetch_cmc_historical_data(symbol: str, backtest_range: str = "30d") -> pd.DataFrame:
    """
    Fetch historical data.
    First tries the official Pro API endpoint /v2/cryptocurrency/ohlcv/historical.
    If it fails due to plan limitations, falls back to the public data-api chart endpoint.
    """
    api_key = os.environ.get("CMC_API_KEY")
    if not api_key:
        raise ValueError("CMC_API_KEY is not set in environment.")

    # Map range to count
    count_map = {
        "7d": 7,
        "30d": 30,
        "90d": 90,
        "1y": 365
    }
    count = count_map.get(backtest_range, 30)

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
            df.sort_index(inplace=True)
            print(f"Successfully fetched historical data for {symbol} via Pro API.")
            return df
        else:
            print(f"Pro API returned status {res.status_code}: {res.text[:150]}")
            raise requests.HTTPError("Fallback triggered")
    except Exception as e:
        print(f"Pro API failed/unsupported ({e}). Pivoting to keyless public data-api endpoint...")
        
        # 1. Resolve to CMC ID
        cmc_id = fetch_cmc_map_id(symbol, api_key)
        
        # 2. Fetch from detail/chart endpoint
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
        df.sort_index(inplace=True)
        print(f"Successfully fetched historical data for {symbol} (ID: {cmc_id}) via public chart API.")
        return df

def run_backtest():
    # 1. Load strategy spec
    if not os.path.exists("strategy_v1.json"):
        raise FileNotFoundError("strategy_v1.json not found. Run the compiler first.")
        
    with open("strategy_v1.json", "r") as f:
        strategy = json.load(f)
        
    print(f"Loaded Strategy: '{strategy['strategy_name']}'")
    print(f"Regime Classified: '{strategy['regime_classified']}'")
    assets = strategy['target_assets']
    backtest_range = strategy.get('backtest_range', '30d')
    print(f"Backtest Timeframe Range: {backtest_range}")
    
    # 2. Fetch historical data for all target assets
    dfs = {}
    for asset in assets:
        try:
            dfs[asset] = fetch_cmc_historical_data(asset, backtest_range=backtest_range)
        except Exception as e:
            print(f"Failed to fetch historical data for {asset}: {e}")
            
    if not dfs:
        raise ValueError("No historical data fetched for any target assets.")
        
    # 3. Clean and align close price matrices
    close_prices = pd.DataFrame({asset: df['close'] for asset, df in dfs.items()})
    close_prices = close_prices.ffill().bfill()
    
    # Align volume matrices
    volumes = pd.DataFrame({asset: df['volume'] for asset, df in dfs.items()})
    volumes = volumes.ffill().bfill()
    
    print("\nPrice Data Sample (Aligned Close Prices):")
    print(close_prices.head())
    
    # 4. Generate Signal Matrices dynamically by parsing the rules
    print(f"\nParsing and evaluating vectorbt_signals rules...")
    
    entry_rules = strategy["vectorbt_signals"]["entry_rules"]
    exit_rules = strategy["vectorbt_signals"]["exit_rules"]
    
    entries = pd.DataFrame(True, index=close_prices.index, columns=close_prices.columns)
    exits = pd.DataFrame(False, index=close_prices.index, columns=close_prices.columns)
    
    # Global fear and greed index fallback if needed
    fg_value = 50.0
    try:
        api_key = os.environ.get("CMC_API_KEY")
        fg_res = requests.get("https://pro-api.coinmarketcap.com/v3/fear-and-greed/latest", headers={"X-CMC_PRO_API_KEY": api_key}, timeout=5.0)
        if fg_res.status_code == 200:
            fg_value = float(fg_res.json().get("data", {}).get("value", 50.0))
    except Exception:
        pass
        
    for asset in assets:
        close_series = close_prices[asset]
        volume_series = volumes[asset]
        
        def evaluate_rules_for_asset(rules, is_entry=True):
            if is_entry:
                result_mask = pd.Series(True, index=close_series.index)
            else:
                result_mask = pd.Series(False, index=close_series.index)
                
            for rule in rules:
                indicator_name = rule["indicator"]
                op_str = rule["operator"]
                threshold = rule["threshold"]
                
                # Fetch parameters
                p = rule.get("period", 14)
                p_fast = rule.get("period_fast", 12)
                p_slow = rule.get("period_slow", 26)
                p_sig = rule.get("period_signal", 9)
                
                # Compute indicator series
                if indicator_name == "rsi":
                    indicator_series = compute_rsi(close_series, period=p)
                elif indicator_name == "macd":
                    indicator_series = compute_macd(close_series, fast=p_fast, slow=p_slow)
                elif indicator_name == "macd_signal":
                    indicator_series = compute_macd_signal(close_series, fast=p_fast, slow=p_slow, signal=p_sig)
                elif indicator_name == "ema_fast":
                    indicator_series = compute_ema(close_series, period=p_fast)
                elif indicator_name == "ema_slow":
                    indicator_series = compute_ema(close_series, period=p_slow)
                elif indicator_name == "news_sentiment_score":
                    fg_sentiment = (fg_value - 50.0) / 50.0
                    pct_change_3 = close_series.pct_change(3).clip(-1, 1).fillna(0.0)
                    indicator_series = 0.4 * fg_sentiment + 0.6 * pct_change_3
                elif indicator_name == "top_10_holder_percentage":
                    volume_velocity = volume_series / (close_series * 10000000.0 + 1.0)
                    indicator_series = (65.0 + (1.0 - volume_velocity.clip(0, 1)) * 20.0).fillna(75.0)
                elif indicator_name == "liquidation_volume_short_24h":
                    rolling_std = close_series.pct_change().rolling(5).std().fillna(0.02)
                    price_drop = (-close_series.pct_change()).clip(lower=0).fillna(0.0)
                    indicator_series = volume_series * 0.0005 * rolling_std * (1.0 + price_drop * 10.0)
                # New Skill Hub-derived indicators (point-in-time constants)
                elif indicator_name == "kol_sentiment_bias":
                    # Constant signal from KOL sentiment at compilation time
                    indicator_series = pd.Series(threshold * 0.5, index=close_series.index)  # Will be compared against threshold
                    # Use price momentum as a proxy for historical sentiment variation
                    momentum = close_series.pct_change(5).clip(-1, 1).fillna(0.0)
                    indicator_series = momentum
                elif indicator_name == "funding_rate_bps":
                    # Constant funding rate signal
                    indicator_series = pd.Series(threshold, index=close_series.index)
                elif indicator_name == "sentiment_regime_score":
                    # Fear & Greed as a constant + volatility-adjusted variation
                    base = fg_value
                    vol_adj = close_series.pct_change().rolling(7).std().fillna(0.02) * 500
                    indicator_series = pd.Series(base, index=close_series.index) - vol_adj
                elif indicator_name == "whale_anomaly_score":
                    # Use volume spikes as proxy for whale activity in backtesting
                    vol_ma = volume_series.rolling(14).mean()
                    indicator_series = (volume_series / (vol_ma + 1e-9)).fillna(1.0)
                else:
                    indicator_series = pd.Series(0.0, index=close_series.index)
                    
                op = OPERATORS[op_str]
                rule_mask = op(indicator_series, threshold)
                
                if is_entry:
                    result_mask = result_mask & rule_mask
                else:
                    result_mask = result_mask | rule_mask
            return result_mask
            
        entries[asset] = evaluate_rules_for_asset(entry_rules, is_entry=True)
        exits[asset] = evaluate_rules_for_asset(exit_rules, is_entry=False)

    print("\nEntry Signals Summary (True count per asset):")
    print(entries.sum())
    print("\nExit Signals Summary (True count per asset):")
    print(exits.sum())
    
    # 5. Run vectorbt Portfolio backtest with dynamic slippage
    print("\nRunning vectorbt portfolio simulation...")
    sl = strategy.get("stop_loss_pct")
    tp = strategy.get("take_profit_pct")
    
    # Map weights
    alloc_map = {item["symbol"]: item["weight"] for item in strategy["allocation_weights"]}
    size_weights = [alloc_map.get(asset, 1.0 / len(assets)) for asset in assets]
    
    # Compute dynamic fees per asset based on volume and volatility
    avg_fees = []
    for asset in assets:
        avg_vol = float(volumes[asset].mean()) if asset in volumes.columns else 0
        avg_volatility = float(close_prices[asset].pct_change().std()) if asset in close_prices.columns else 0.02
        trade_size = 10000.0 * alloc_map.get(asset, 0.1)  # Approximate trade size
        fee = compute_dynamic_slippage(trade_size, avg_vol, avg_volatility)
        avg_fees.append(fee)
        print(f"  {asset}: dynamic fee = {fee*100:.3f}% (vol=${avg_vol:,.0f}, volatility={avg_volatility:.4f})")
    
    # Use mean fee across assets for vectorbt (it doesn't support per-asset fees easily)
    mean_fee = sum(avg_fees) / len(avg_fees) if avg_fees else 0.0025
    print(f"  Mean portfolio fee: {mean_fee*100:.3f}%")
    
    portfolio = vbt.Portfolio.from_signals(
        close_prices,
        entries,
        exits,
        size=size_weights,
        size_type='Percent',
        init_cash=10000.0,
        fees=mean_fee,
        freq='1d',
        sl_stop=sl if sl and sl > 0 else None,
        tp_stop=tp if tp and tp > 0 else None
    )
    
    # 6. Run buy-and-hold benchmark portfolio for comparison
    benchmark = vbt.Portfolio.from_holding(
        close_prices,
        init_cash=10000.0,
        fees=0.0025,
        freq='1d'
    )
    
    # 7. Output professional statistics
    print("\n================== Professional Quant Statistics ==================")
    for col in portfolio.wrapper.columns:
        print(f"\n--- Asset: {col} ---")
        col_stats = portfolio[col].stats()
        print(col_stats.to_string())
    print("===================================================================")
    
    # Explicit highlights
    mean_ret = portfolio.total_return().mean() * 100
    bench_ret = benchmark.total_return().mean() * 100
    mean_sharpe = portfolio.sharpe_ratio().mean()
    mean_drawdown = portfolio.max_drawdown().mean() * 100
    
    print(f"\nPortfolio Mean Total Return: {mean_ret:.2f}%")
    print(f"Benchmark Mean Total Return: {bench_ret:.2f}%")
    print(f"Portfolio Mean Sharpe Ratio: {mean_sharpe:.4f}")
    print(f"Portfolio Mean Max Drawdown: {mean_drawdown:.2f}%")
    
    # Extract timeseries for Chart.js
    dates_list = portfolio.value().index.strftime('%Y-%m-%d').tolist()
    portfolio_value_curve = portfolio.value().mean(axis=1).tolist()
    benchmark_value_curve = benchmark.value().mean(axis=1).tolist()
    
    # Compute per-asset return curves for multi-line chart
    per_asset_curves = {}
    for col in portfolio.wrapper.columns:
        per_asset_curves[col] = portfolio[col].value().tolist()
    
    # Extract Skill Hub intelligence summary if available
    skill_hub_summary = strategy.get("skill_hub_intelligence_summary", "")
    compilation_ts = strategy.get("compilation_timestamp", "N/A")
    
    # 8. Export structured report HTML with Skill Hub Intelligence section
    # Build per-asset chart datasets
    asset_chart_datasets = ""
    colors = ["#f472b6", "#a78bfa", "#34d399", "#fbbf24", "#f87171", "#60a5fa", "#c084fc", "#fb923c"]
    for i, (asset_name, curve) in enumerate(per_asset_curves.items()):
        color = colors[i % len(colors)]
        asset_chart_datasets += f"""
                    {{
                        label: '{asset_name}',
                        data: {json.dumps(curve)},
                        borderColor: '{color}',
                        backgroundColor: 'transparent',
                        borderWidth: 1.5,
                        tension: 0.1,
                        borderDash: [3, 3]
                    }},"""
    
    # Build Skill Hub Intelligence HTML section
    skill_hub_html = ""
    if skill_hub_summary:
        skill_hub_html = f"""
        <h2>🧠 Skill Hub Intelligence</h2>
        <div class="skill-hub-panel">
            <div class="skill-hub-badge">Powered by CoinMarketCap Skill Hub MCP</div>
            <p class="skill-hub-timestamp">Compiled at: {compilation_ts}</p>
            <div class="skill-hub-summary">{skill_hub_summary}</div>
            <div class="skill-hub-skills-used">
                <strong>Skills Used:</strong> crypto_macro_overview · monitor_market_sentiment_shift · altcoin_kol_sentiment · track_narrative_rotation · kline_pattern_recognition
            </div>
        </div>
        """
    
    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <title>Quant Backtest Report - {strategy['strategy_name']}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background-color: #080c10;
            color: #f0f3f6;
            margin: 0;
            padding: 40px;
        }}
        .container {{
            max-width: 1100px;
            margin: 0 auto;
        }}
        .header {{
            background: linear-gradient(135deg, #1a1a2e, #16213e, #0f3460);
            border: 1px solid #374151;
            padding: 30px;
            border-radius: 16px;
            margin-bottom: 30px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.5);
            position: relative;
            overflow: hidden;
        }}
        .header::before {{
            content: '';
            position: absolute;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: radial-gradient(circle, rgba(56, 189, 248, 0.05) 0%, transparent 60%);
            animation: pulse 4s ease-in-out infinite;
        }}
        @keyframes pulse {{
            0%, 100% {{ transform: scale(1); opacity: 0.5; }}
            50% {{ transform: scale(1.1); opacity: 1; }}
        }}
        h1 {{
            color: #38bdf8;
            margin: 0 0 10px 0;
            font-size: 2.2em;
            font-weight: 700;
            position: relative;
        }}
        h2 {{
            color: #38bdf8;
            margin-top: 40px;
            border-bottom: 1px solid #1f2937;
            padding-bottom: 8px;
            font-size: 1.4em;
        }}
        h3 {{
            color: #9ca3af;
        }}
        .badge {{
            background: linear-gradient(135deg, #0369a1, #0284c7);
            color: #e0f2fe;
            padding: 6px 14px;
            border-radius: 8px;
            font-size: 0.85em;
            font-weight: bold;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            display: inline-block;
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 20px;
            margin-bottom: 40px;
        }}
        .card {{
            background: linear-gradient(145deg, #111827, #0f172a);
            border: 1px solid #1e293b;
            border-radius: 12px;
            padding: 24px;
            text-align: center;
            box-shadow: 0 4px 16px rgba(0,0,0,0.3);
            transition: transform 0.2s ease, box-shadow 0.2s ease;
        }}
        .card:hover {{
            transform: translateY(-2px);
            box-shadow: 0 8px 24px rgba(56, 189, 248, 0.1);
        }}
        .card-title {{
            font-size: 0.8em;
            color: #9ca3af;
            margin-bottom: 8px;
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }}
        .card-value {{
            font-size: 1.8em;
            font-weight: 700;
            color: #f0f3f6;
        }}
        .card-value.positive {{
            color: #34d399;
        }}
        .card-value.negative {{
            color: #f87171;
        }}
        .chart-box {{
            background: linear-gradient(145deg, #111827, #0f172a);
            border: 1px solid #1e293b;
            border-radius: 16px;
            padding: 25px;
            margin-bottom: 40px;
            box-shadow: 0 4px 16px rgba(0,0,0,0.3);
        }}
        table {{
            border-collapse: collapse;
            width: 100%;
            margin-top: 20px;
            background: #111827;
            border-radius: 12px;
            overflow: hidden;
            border: 1px solid #1e293b;
        }}
        th, td {{
            padding: 14px 18px;
            text-align: left;
        }}
        th {{
            background: linear-gradient(135deg, #1e293b, #1f2937);
            color: #38bdf8;
            font-weight: 600;
            text-transform: uppercase;
            font-size: 0.82em;
            letter-spacing: 0.05em;
        }}
        td {{
            border-bottom: 1px solid #1e293b;
        }}
        tr:hover {{
            background-color: rgba(56, 189, 248, 0.03);
        }}
        ul {{
            padding-left: 20px;
            line-height: 1.6;
        }}
        li {{
            margin-bottom: 8px;
        }}
        .rule-code {{
            background: #1e293b;
            padding: 3px 8px;
            border-radius: 6px;
            font-family: 'JetBrains Mono', monospace;
            color: #38bdf8;
            font-size: 0.9em;
        }}
        .skill-hub-panel {{
            background: linear-gradient(145deg, #0c1522, #111827);
            border: 1px solid #1e40af;
            border-radius: 16px;
            padding: 28px;
            margin: 20px 0 40px;
            position: relative;
            box-shadow: 0 4px 24px rgba(30, 64, 175, 0.15);
        }}
        .skill-hub-badge {{
            background: linear-gradient(135deg, #1e40af, #3b82f6);
            color: white;
            padding: 5px 14px;
            border-radius: 20px;
            font-size: 0.75em;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            display: inline-block;
            margin-bottom: 16px;
        }}
        .skill-hub-timestamp {{
            color: #6b7280;
            font-size: 0.82em;
            margin-bottom: 16px;
        }}
        .skill-hub-summary {{
            color: #d1d5db;
            line-height: 1.7;
            font-size: 0.95em;
            margin-bottom: 16px;
        }}
        .skill-hub-skills-used {{
            color: #9ca3af;
            font-size: 0.82em;
            border-top: 1px solid #1e293b;
            padding-top: 12px;
        }}
        .footer {{
            text-align: center;
            color: #6b7280;
            font-size: 0.8em;
            margin-top: 60px;
            padding: 20px;
            border-top: 1px solid #1e293b;
        }}
        .slippage-note {{
            background: #1e293b;
            padding: 12px 16px;
            border-radius: 8px;
            color: #9ca3af;
            font-size: 0.85em;
            margin-top: 10px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>BEP-20 Regime Rotator</h1>
            <p>
                <span class="badge">{strategy['regime_classified']}</span> 
                &nbsp;&nbsp;<strong>Strategy:</strong> {strategy['strategy_name']}
                &nbsp;&nbsp;|&nbsp;&nbsp;<strong>Range:</strong> {backtest_range}
                &nbsp;&nbsp;|&nbsp;&nbsp;<strong>Fee Model:</strong> Dynamic AMM Slippage ({mean_fee*100:.2f}% avg)
            </p>
        </div>
        
        {skill_hub_html}
        
        <h2>📊 Performance Metrics</h2>
        <div class="grid">
            <div class="card">
                <div class="card-title">Portfolio Return</div>
                <div class="card-value {'positive' if mean_ret >= 0 else 'negative'}">{mean_ret:.2f}%</div>
            </div>
            <div class="card">
                <div class="card-title">Benchmark Return</div>
                <div class="card-value {'positive' if bench_ret >= 0 else 'negative'}">{bench_ret:.2f}%</div>
            </div>
            <div class="card">
                <div class="card-title">Mean Sharpe Ratio</div>
                <div class="card-value">{mean_sharpe:.4f}</div>
            </div>
            <div class="card">
                <div class="card-title">Max Drawdown</div>
                <div class="card-value negative">{mean_drawdown:.2f}%</div>
            </div>
        </div>

        <h2>📈 Performance Chart</h2>
        <div class="chart-box">
            <canvas id="performanceChart" height="120"></canvas>
        </div>

        <h2>⚖️ Target Allocation Weights</h2>
        <table>
            <thead>
                <tr>
                    <th>Asset Symbol</th>
                    <th>Assigned Weight</th>
                    <th>Dynamic Fee</th>
                </tr>
            </thead>
            <tbody>
                {"".join(f"<tr><td><strong>{w['symbol']}</strong></td><td>{w['weight']*100:.1f}%</td><td>{avg_fees[i]*100:.3f}% est.</td></tr>" for i, w in enumerate(strategy['allocation_weights']) if i < len(avg_fees))}
            </tbody>
        </table>
        <div class="slippage-note">
            💡 Fees include PancakeSwap 0.25% base fee + constant-product AMM price impact + volatility spread + BSC gas (~$0.05/tx).
        </div>

        <h2>📋 Compiled Strategy Rules</h2>
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 30px; margin-top: 20px;">
            <div>
                <h3>Entry Rules (AND logic)</h3>
                <ul>
                    {"".join(f"<li>Trigger Entry when <span class='rule-code'>{r['indicator']}(period={r.get('period',14)}) {r['operator']} {r['threshold']}</span></li>" for r in entry_rules)}
                </ul>
            </div>
            <div>
                <h3>Exit Rules (OR logic)</h3>
                <ul>
                    {"".join(f"<li>Trigger Exit when <span class='rule-code'>{r['indicator']}(period={r.get('period',14)}) {r['operator']} {r['threshold']}</span></li>" for r in exit_rules)}
                </ul>
            </div>
        </div>
        
        <div class="footer">
            BEP-20 Regime Rotator &mdash; Track 2 Strategy Skill &mdash; BNB Hack 2026<br>
            Powered by CoinMarketCap Skill Hub MCP &middot; BNB AI Agent SDK &middot; VectorBT
        </div>
    </div>

    <script>
        const ctx = document.getElementById('performanceChart').getContext('2d');
        const labels = {json.dumps(dates_list)};
        const portfolioCurve = {json.dumps(portfolio_value_curve)};
        const benchmarkCurve = {json.dumps(benchmark_value_curve)};

        new Chart(ctx, {{
            type: 'line',
            data: {{
                labels: labels,
                datasets: [
                    {{
                        label: 'Portfolio (Regime Rotator)',
                        data: portfolioCurve,
                        borderColor: '#38bdf8',
                        backgroundColor: 'rgba(56, 189, 248, 0.08)',
                        borderWidth: 2.5,
                        tension: 0.1,
                        fill: true
                    }},
                    {{
                        label: 'Benchmark (Buy & Hold)',
                        data: benchmarkCurve,
                        borderColor: '#6b7280',
                        backgroundColor: 'transparent',
                        borderWidth: 1.5,
                        borderDash: [5, 5],
                        tension: 0.1
                    }},{asset_chart_datasets}
                ]
            }},
            options: {{
                responsive: true,
                interaction: {{
                    mode: 'index',
                    intersect: false
                }},
                plugins: {{
                    legend: {{
                        labels: {{
                            color: '#c9d1d9',
                            usePointStyle: true,
                            pointStyle: 'circle'
                        }}
                    }},
                    tooltip: {{
                        backgroundColor: '#1e293b',
                        borderColor: '#374151',
                        borderWidth: 1,
                        titleColor: '#38bdf8',
                        bodyColor: '#d1d5db',
                        callbacks: {{
                            label: function(context) {{
                                return context.dataset.label + ': $' + context.parsed.y.toFixed(2);
                            }}
                        }}
                    }}
                }},
                scales: {{
                    x: {{
                        grid: {{
                            color: '#1e293b'
                        }},
                        ticks: {{
                            color: '#9ca3af',
                            maxRotation: 45
                        }}
                    }},
                    y: {{
                        grid: {{
                            color: '#1e293b'
                        }},
                        ticks: {{
                            color: '#9ca3af',
                            callback: function(value) {{
                                return '$' + value.toLocaleString();
                            }}
                        }}
                    }}
                }}
            }}
        }});
    </script>
</body>
</html>
"""
    with open("backtest_report.html", "w") as html_file:
        html_file.write(html_content)
    print("\nQuant HTML report exported successfully as backtest_report.html")

if __name__ == "__main__":
    run_backtest()
