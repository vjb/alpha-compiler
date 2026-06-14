import os
import json
import time
import asyncio
import sys
from typing import List, Literal, Dict, Any, Optional
from pydantic import BaseModel, Field, field_validator
from dotenv import load_dotenv
import pandas as pd
import requests

# Import BNBAgent SDK components
from bnbagent import BNBAgent
from skill_engine.constants import ALLOWED_BEP20_TOKENS
from skill_engine.skill_hub_client import (
    SkillHubClient,
    extract_regime_from_macro,
    extract_sentiment_metrics,
    extract_kol_sentiment_summary,
    summarize_intelligence_for_llm,
)

load_dotenv()

# List of common disallowed tokens to check in the thesis text
DISALLOWED_TOKENS_LOWER = {
    "btc", "bitcoin", "sol", "solana", "ada", "cardano", "xrp", "ripple", 
    "dot", "polkadot", "doge", "dogecoin", "shib", "shiba", "avax", "avalanche", 
    "trx", "tron", "matic", "polygon", "ltc", "litecoin", "near", "bch", "pepe", 
    "wif", "sui", "optimism", "op", "arbitrum", "arb"
}

class SignalRule(BaseModel):
    indicator: Literal[
        "rsi", 
        "macd", 
        "macd_signal", 
        "ema_fast", 
        "ema_slow", 
        "news_sentiment_score", 
        "top_10_holder_percentage", 
        "liquidation_volume_short_24h",
        # New Skill Hub-derived indicators
        "kol_sentiment_bias",
        "funding_rate_bps",
        "sentiment_regime_score",
        "whale_anomaly_score",
    ]
    operator: Literal[">", "<", "=="]
    threshold: float
    period: int = Field(default=14, description="Period for indicators like RSI or single EMA")
    period_fast: int = Field(default=12, description="Fast period for MACD or fast EMA")
    period_slow: int = Field(default=26, description="Slow period for MACD or slow EMA")
    period_signal: int = Field(default=9, description="Signal period for MACD")

class VectorBTSignals(BaseModel):
    entry_rules: List[SignalRule]
    exit_rules: List[SignalRule]

class AssetAllocation(BaseModel):
    symbol: str
    weight: float

class StrategySpec(BaseModel):
    strategy_name: str
    regime_classified: Literal["bullish", "bearish", "sideways"]
    target_assets: List[str]
    allocation_weights: List[AssetAllocation]
    stop_loss_pct: float
    take_profit_pct: float
    vectorbt_signals: VectorBTSignals
    backtest_range: Literal["7d", "30d", "90d", "1y"] = "30d"
    # New: Skill Hub intelligence metadata
    skill_hub_intelligence_summary: str = Field(default="", description="Summary of CMC Skill Hub intelligence used for compilation")
    compilation_timestamp: str = Field(default="", description="ISO timestamp when intelligence was gathered")

    @field_validator('target_assets')
    @classmethod
    def validate_target_assets(cls, assets: List[str]) -> List[str]:
        allowed_upper = {t.upper(): t for t in ALLOWED_BEP20_TOKENS}
        normalized = []
        for asset in assets:
            if asset.upper() not in allowed_upper:
                raise ValueError(f"Asset '{asset}' is not in the allowed BEP-20 token list.")
            normalized.append(allowed_upper[asset.upper()])
        return normalized

def validate_thesis_text(thesis: str):
    """Scan thesis for any disallowed assets and raise ValueError if found."""
    # Split text into words, clean them, and check against disallowed set
    words = thesis.lower().replace(",", " ").replace(".", " ").replace(";", " ").split()
    for word in words:
        if word in DISALLOWED_TOKENS_LOWER:
            raise ValueError(f"Thesis contains disallowed asset reference: '{word}'. Only allowed BEP-20 assets are permitted.")

class CoinMarketCapRESTClient:
    """
    Robust fallback data client using official REST endpoints and public chart endpoints.
    Fetches real-time price, volume, dominance and custom-range historical charts.
    """
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {
            "X-CMC_PRO_API_KEY": api_key,
            "Accept": "application/json"
        }
        self.cache_file = "symbol_mappings_cache.json"

    def _load_cache(self) -> Dict[str, int]:
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_cache(self, cache: Dict[str, int]):
        try:
            with open(self.cache_file, "w") as f:
                json.dump(cache, f, indent=2)
        except Exception:
            pass

    def get_token_mappings(self, symbols: List[str]) -> Dict[str, int]:
        """Map symbols to CMC IDs using official /v1/cryptocurrency/map, checking local cache first."""
        cache = self._load_cache()
        missing_symbols = [s for s in symbols if s.upper() not in cache]
        
        if missing_symbols:
            print(f"Fetching token mappings from CMC API for: {missing_symbols}...", file=sys.stderr)
            url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/map"
            res = requests.get(url, headers=self.headers, params={"symbol": ",".join(missing_symbols)})
            res.raise_for_status()
            data = res.json().get("data", [])
            
            best_items = {}
            for item in data:
                symbol = item["symbol"].upper()
                if symbol not in best_items:
                    best_items[symbol] = item
                else:
                    existing = best_items[symbol]
                    if item["is_active"] > existing["is_active"]:
                        best_items[symbol] = item
                    elif item["is_active"] == existing["is_active"]:
                        if item.get("rank") is not None and (existing.get("rank") is None or item["rank"] < existing["rank"]):
                            best_items[symbol] = item
                            
            for symbol, item in best_items.items():
                cache[symbol] = item["id"]
                
            self._save_cache(cache)
            
        return {s: cache[s.upper()] for s in symbols if s.upper() in cache}

    def get_latest_quotes(self, symbols: List[str]) -> Dict[str, Any]:
        """Fetch latest quotes using /v1/cryptocurrency/quotes/latest."""
        url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"
        res = requests.get(url, headers=self.headers, params={"symbol": ",".join(symbols)})
        res.raise_for_status()
        return res.json().get("data", {})

    def get_historical_prices(self, cmc_id: int, backtest_range: str = "30d") -> pd.DataFrame:
        """Fetch custom range chart from keyless data-api and extract close and volume."""
        range_map = {
            "7d": "7D",
            "30d": "1M",
            "90d": "3M",
            "1y": "1Y"
        }
        api_range = range_map.get(backtest_range, "1M")
        
        url = f"https://api.coinmarketcap.com/data-api/v3/cryptocurrency/detail/chart?id={cmc_id}&range={api_range}"
        res = requests.get(url)
        res.raise_for_status()
        points = res.json().get("data", {}).get("points", {})
        if not points:
            raise ValueError(f"No chart points found for CMC ID {cmc_id}")
        
        records = []
        for ts_str in sorted(points.keys()):
            ts = pd.to_datetime(int(ts_str), unit="s")
            v_list = points[ts_str]["v"]
            close_price = v_list[0]
            volume = v_list[1] if len(v_list) > 1 else 0.0
            records.append({
                "date": ts,
                "close": close_price,
                "volume": volume
            })
            
        df = pd.DataFrame(records)
        df.set_index("date", inplace=True)
        df.sort_index(inplace=True)
        return df

def calculate_technical_indicators(df: pd.DataFrame) -> Dict[str, float]:
    """Calculate RSI, MACD, and EMAs from price series."""
    prices = df["close"]
    if len(prices) < 14:
        return {
            "rsi": 50.0,
            "macd": 0.0,
            "macd_signal": 0.0,
            "ema_fast": prices.iloc[-1] if len(prices) > 0 else 0.0,
            "ema_slow": prices.iloc[-1] if len(prices) > 0 else 0.0
        }

    # 1. RSI (14)
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / (loss + 1e-9)
    rsi_series = 100 - (100 / (1 + rs))
    current_rsi = float(rsi_series.iloc[-1])
    if pd.isna(current_rsi):
        current_rsi = 50.0

    # 2. MACD (12, 26, 9)
    exp1 = prices.ewm(span=12, adjust=False).mean()
    exp2 = prices.ewm(span=26, adjust=False).mean()
    macd_series = exp1 - exp2
    macd_signal_series = macd_series.ewm(span=9, adjust=False).mean()
    current_macd = float(macd_series.iloc[-1])
    current_macd_signal = float(macd_signal_series.iloc[-1])

    # 3. EMA Fast (9) and EMA Slow (21)
    ema_fast_series = prices.ewm(span=9, adjust=False).mean()
    ema_slow_series = prices.ewm(span=21, adjust=False).mean()
    current_ema_fast = float(ema_fast_series.iloc[-1])
    current_ema_slow = float(ema_slow_series.iloc[-1])

    return {
        "rsi": round(current_rsi, 2),
        "macd": round(current_macd, 4),
        "macd_signal": round(current_macd_signal, 4),
        "ema_fast": round(current_ema_fast, 4),
        "ema_slow": round(current_ema_slow, 4)
    }

class ThesisToCodeStrategyCompiler:
    """Institutional-grade strategy compiler service powered by CMC Skill Hub MCP + bnbagent-sdk."""
    def __init__(self):
        # Instantiate BNBAgent from environment to manage configuration and identity
        self.sdk = BNBAgent.from_env()
        print(f"BNBAgent configured successfully. Network: {self.sdk.config.network}", file=sys.stderr)
        
        self.cmc_api_key = os.environ.get("CMC_API_KEY")
        if not self.cmc_api_key:
            raise ValueError("CMC_API_KEY environment variable is not set.")
        
        self.rest_client = CoinMarketCapRESTClient(self.cmc_api_key)
        
        # Initialize CMC Skill Hub MCP client
        self.skill_hub = SkillHubClient(self.cmc_api_key)
        self.skill_hub.initialize()
        print("[Compiler] CMC Skill Hub MCP client initialized.", file=sys.stderr)

    def compile(self, investment_thesis: str, target_assets: List[str], risk_tolerance: str, backtest_range: str = "30d") -> StrategySpec:
        # 1. Validate thesis text for disallowed tokens
        validate_thesis_text(investment_thesis)

        # 2. Validate target assets against allowlist
        allowed_upper = {t.upper(): t for t in ALLOWED_BEP20_TOKENS}
        normalized_assets = []
        for asset in target_assets:
            if asset.upper() not in allowed_upper:
                raise ValueError(f"Asset '{asset}' is not in the allowed BEP-20 token list.")
            normalized_assets.append(allowed_upper[asset.upper()])
        target_assets = normalized_assets

        # ═══════════════════════════════════════════════════════════════
        # 3. GATHER INTELLIGENCE FROM CMC SKILL HUB MCP
        # ═══════════════════════════════════════════════════════════════
        print("\n" + "="*70, file=sys.stderr)
        print("PHASE 1: Gathering intelligence from CMC Skill Hub MCP", file=sys.stderr)
        print("="*70, file=sys.stderr)
        
        intelligence = self.skill_hub.gather_compilation_intelligence(target_assets)
        
        # Extract regime classification from Skill Hub
        macro_result = intelligence.get("macro_regime", {})
        regime = extract_regime_from_macro(macro_result)
        
        # Cross-validate with sentiment regime
        sentiment = intelligence.get("sentiment_regime", {})
        sentiment_metrics = extract_sentiment_metrics(sentiment)
        fg_value = sentiment_metrics.get("fear_greed_value", 50.0)
        
        # If macro regime is ambiguous, fall back to sentiment metrics
        if regime == "sideways":
            if fg_value >= 60:
                regime = "bullish"
            elif fg_value <= 35:
                regime = "bearish"
        
        print(f"\n[Compiler] Classified market regime: '{regime}'", file=sys.stderr)
        print(f"[Compiler]   Fear & Greed: {fg_value} ({sentiment_metrics.get('fear_greed_label', 'N/A')})", file=sys.stderr)
        print(f"[Compiler]   Sentiment Regime: {sentiment_metrics.get('sentiment_regime', 'N/A')}", file=sys.stderr)
        print(f"[Compiler]   Avg Funding: {sentiment_metrics.get('avg_funding_bps', 'N/A')} bps", file=sys.stderr)

        # BEARISH STABLECOIN ROTATION:
        if regime == "bearish":
            print("[Compiler] [Stablecoin Rotation] Bearish regime detected! Appending USDT for capital preservation.", file=sys.stderr)
            if "USDT" not in target_assets:
                target_assets.append("USDT")

        # ═══════════════════════════════════════════════════════════════
        # 4. FETCH PRICE DATA (REST API - needed for backtesting)
        # ═══════════════════════════════════════════════════════════════
        print("\n" + "="*70, file=sys.stderr)
        print("PHASE 2: Fetching price data via REST API", file=sys.stderr)
        print("="*70, file=sys.stderr)
        
        print("Resolving symbols to CMC IDs...", file=sys.stderr)
        id_mappings = self.rest_client.get_token_mappings(target_assets)
        print(f"Symbol mappings: {id_mappings}", file=sys.stderr)

        print("Fetching latest market quotes...", file=sys.stderr)
        quotes_data = self.rest_client.get_latest_quotes(target_assets)

        token_contexts = {}
        for symbol in target_assets:
            cmc_id = id_mappings.get(symbol)
            if not cmc_id:
                print(f"Could not resolve CMC ID for {symbol}, skipping.", file=sys.stderr)
                continue

            print(f"Fetching chart data for {symbol} (ID: {cmc_id}) range={backtest_range}...", file=sys.stderr)
            try:
                hist_df = self.rest_client.get_historical_prices(cmc_id, backtest_range=backtest_range)
                ta_indicators = calculate_technical_indicators(hist_df)
            except Exception as e:
                print(f"Failed to fetch/compute TA for {symbol}: {e}", file=sys.stderr)
                ta_indicators = {
                    "rsi": 50.0, "macd": 0.0, "macd_signal": 0.0,
                    "ema_fast": 0.0, "ema_slow": 0.0
                }

            # Extract quote details
            quote = quotes_data.get(symbol, {})
            if isinstance(quote, list) and len(quote) > 0:
                quote = quote[0]
            
            usd_quote = quote.get("quote", {}).get("USD", {})
            price = usd_quote.get("price", 0.0)
            volume_24h = usd_quote.get("volume_24h", 0.0)
            price_change_24h = usd_quote.get("percent_change_24h", 0.0)

            # Enrich with Skill Hub intelligence (per-asset)
            asset_intel = intelligence.get("per_asset", {}).get(symbol, {})
            
            # KOL sentiment score: map bias to numeric
            kol_data = asset_intel.get("kol_sentiment", {})
            kol_summary = extract_kol_sentiment_summary(kol_data)
            kol_bias_map = {
                "bullish": 0.8, "constructive": 0.6, "use_as_context": 0.0,
                "cautious": -0.3, "bearish": -0.7, "defensive": -0.5,
                "unknown": 0.0
            }
            kol_sentiment_score = kol_bias_map.get(kol_summary.get("bias", "unknown"), 0.0)
            
            token_contexts[symbol] = {
                "price": price,
                "volume_24h": volume_24h,
                "price_change_24h": price_change_24h,
                # Technical indicators (computed from price history)
                "rsi": ta_indicators["rsi"],
                "macd": ta_indicators["macd"],
                "macd_signal": ta_indicators["macd_signal"],
                "ema_fast": ta_indicators["ema_fast"],
                "ema_slow": ta_indicators["ema_slow"],
                # Skill Hub-derived indicators (REAL data, not proxies)
                "kol_sentiment_bias": kol_sentiment_score,
                "kol_sentiment_conclusion": kol_summary.get("conclusion", "No data")[:150],
                "kol_confidence": kol_summary.get("confidence", "unknown"),
                "funding_rate_bps": sentiment_metrics.get("avg_funding_bps", 0.0),
                "sentiment_regime_score": fg_value,
                "sentiment_regime_label": sentiment_metrics.get("sentiment_regime", "unknown"),
            }

        print(f"\n[Compiler] Full computed market context for {len(token_contexts)} assets ready.", file=sys.stderr)

        # ═══════════════════════════════════════════════════════════════
        # 5. BUILD LLM CONTEXT WITH SKILL HUB INTELLIGENCE
        # ═══════════════════════════════════════════════════════════════
        print("\n" + "="*70, file=sys.stderr)
        print("PHASE 3: Compiling strategy via LLM with Skill Hub intelligence", file=sys.stderr)
        print("="*70, file=sys.stderr)
        
        # Generate the intelligence summary for the LLM
        intel_summary = summarize_intelligence_for_llm(intelligence)
        
        from openai import OpenAI
        openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        
        system_prompt = (
            "You are the Principal Quant AI Architect. Your task is to compile a natural language investment thesis "
            "into a machine-readable JSON trading strategy spec. "
            "You MUST classify the strategy for the given regime (bullish, bearish, sideways). "
            "You have access to REAL market intelligence from the CoinMarketCap Skill Hub MCP, including: "
            "macro regime analysis, KOL sentiment, funding rates, market sentiment regime, and narrative rotation data. "
            "Use this intelligence to make informed decisions about allocation and signal rules. "
            "\n\n"
            "Formulate the strategy spec including: "
            "1. strategy_name: a descriptive name for the strategy. "
            "2. regime_classified: must be the classified regime provided in the prompt. "
            "3. target_assets: the target assets to trade. "
            "4. allocation_weights: portfolio allocation weights for each asset, summing to exactly 1.0. "
            "   IMPORTANT BEARISH RULE: If the regime is 'bearish', allocate at least 70% (0.70) to USDT. "
            "5. stop_loss_pct: stop-loss percentage (e.g. 0.05 for 5%). "
            "6. take_profit_pct: take-profit percentage (e.g. 0.10 for 10%). "
            "7. vectorbt_signals: entry and exit rules using available indicators: "
            "   TECHNICAL: 'rsi' (period), 'macd' (period_fast, period_slow), 'macd_signal', 'ema_fast', 'ema_slow' "
            "   SKILL HUB: 'kol_sentiment_bias' (range: -1 to +1), 'funding_rate_bps', 'sentiment_regime_score' (0-100), 'whale_anomaly_score' "
            "   LEGACY: 'news_sentiment_score', 'top_10_holder_percentage', 'liquidation_volume_short_24h' "
            "8. backtest_range: must match the requested range. "
            "9. skill_hub_intelligence_summary: a one-paragraph summary of the key Skill Hub insights that shaped this strategy. "
            "10. compilation_timestamp: the provided timestamp."
        )
        
        user_prompt = f"""
Investment Thesis: "{investment_thesis}"
Target Assets: {target_assets}
Risk Tolerance: {risk_tolerance}
Classified Market Regime: {regime} (Fear & Greed index is {fg_value})
Requested Backtest Range: {backtest_range}
Compilation Timestamp: {intelligence.get('timestamp', time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))}

══════════════════════════════════════════
CMC SKILL HUB MCP INTELLIGENCE (REAL DATA)
══════════════════════════════════════════
{intel_summary}

══════════════════════════════════════════
PRICE & TECHNICAL INDICATOR CONTEXT
══════════════════════════════════════════
{json.dumps(token_contexts, indent=2)}

Formulate a precise StrategySpec JSON payload. Use the Skill Hub intelligence to inform your allocation weights,
entry/exit rule thresholds, and risk parameters. If regime is bearish, put >= 70% in USDT.
Include a skill_hub_intelligence_summary field summarizing how the intelligence shaped the strategy.
"""

        print("[Compiler] Calling OpenAI GPT-4o with enriched Skill Hub context...", file=sys.stderr)
        completion = openai_client.beta.chat.completions.parse(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format=StrategySpec
        )

        strategy_spec = completion.choices[0].message.parsed
        
        print(f"\n[Compiler] Strategy compiled: '{strategy_spec.strategy_name}'", file=sys.stderr)
        print(f"[Compiler] Regime: {strategy_spec.regime_classified}", file=sys.stderr)
        print(f"[Compiler] Assets: {strategy_spec.target_assets}", file=sys.stderr)
        print(f"[Compiler] Allocations: {[(a.symbol, a.weight) for a in strategy_spec.allocation_weights]}", file=sys.stderr)
        
        return strategy_spec

def compile_strategy_cli():
    import argparse
    parser = argparse.ArgumentParser(description="BEP-20 Regime Rotator Strategy Compiler")
    parser.add_argument("--thesis", type=str, required=True, help="Raw investment thesis text")
    parser.add_argument("--assets", type=str, required=True, help="Comma-separated target assets")
    parser.add_argument("--risk", type=str, default="medium", help="Risk tolerance (low, medium, high)")
    parser.add_argument("--range", type=str, default="30d", choices=["7d", "30d", "90d", "1y"], help="Backtest time range")
    args = parser.parse_args()

    assets = [a.strip() for a in args.assets.split(",")]
    
    compiler = ThesisToCodeStrategyCompiler()
    try:
        spec = compiler.compile(args.thesis, assets, args.risk, args.range)
        with open("strategy_v1.json", "w") as f:
            f.write(spec.model_dump_json(indent=2))
        print("Strategy Spec successfully compiled and saved to strategy_v1.json")
    except Exception as e:
        print(f"Compilation failed: {e}")
        raise e

if __name__ == "__main__":
    compile_strategy_cli()
