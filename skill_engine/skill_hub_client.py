"""
CoinMarketCap Skill Hub MCP Client — Streamable HTTP transport.

Provides structured access to 33+ cloud-executed analytical skills
via the find_skill / execute_skill MCP tools at:
  https://mcp.coinmarketcap.com/skill-hub/stream

This replaces the legacy SSE connection attempt and all computed proxy indicators.
"""
import os
import json
import uuid
import sys
import time
from typing import Any, Dict, List, Optional
import requests
from dotenv import load_dotenv

load_dotenv()


class SkillHubError(Exception):
    """Raised when a Skill Hub MCP call fails."""
    def __init__(self, message: str, code: str = "UNKNOWN"):
        self.code = code
        super().__init__(f"[{code}] {message}")


class SkillHubClient:
    """
    CoinMarketCap Skill Hub MCP client using Streamable HTTP transport.
    
    Usage:
        client = SkillHubClient()
        client.initialize()
        
        # Discover skills
        candidates = client.find_skill("derivatives funding rate")
        
        # Execute a skill
        result = client.execute_skill("altcoin_kol_sentiment", {"symbol": "CAKE"})
    """
    
    ENDPOINT = "https://mcp.coinmarketcap.com/skill-hub/stream"
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.environ.get("CMC_API_KEY", "")
        if not self.api_key:
            raise ValueError("CMC_API_KEY is required for Skill Hub access.")
        
        self.headers = {
            "X-CMC-MCP-API-KEY": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"
        }
        self._initialized = False
        self._session_info = None
    
    # ─── Core MCP Transport ─────────────────────────────────────────
    
    def _send_jsonrpc(self, method: str, params: dict = None, timeout: int = 300) -> dict:
        """Send a JSON-RPC request via Streamable HTTP and parse the response."""
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
        }
        if params:
            payload["params"] = params
        
        try:
            res = requests.post(
                self.ENDPOINT,
                headers=self.headers,
                json=payload,
                timeout=timeout
            )
            res.raise_for_status()
        except requests.exceptions.Timeout:
            raise SkillHubError(f"Request timed out after {timeout}s for method '{method}'", "TIMEOUT")
        except requests.exceptions.RequestException as e:
            raise SkillHubError(f"HTTP request failed: {e}", "HTTP_ERROR")
        
        # Parse response — handle SSE-framed Streamable HTTP responses
        content_type = res.headers.get("Content-Type", "")
        
        if "text/event-stream" in content_type:
            # Streamable HTTP returns SSE-framed data
            for line in res.text.splitlines():
                if line.startswith("data:"):
                    data_str = line[len("data:"):].strip()
                    if data_str:
                        try:
                            return json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
            raise SkillHubError("No valid JSON data in SSE-framed response", "PARSE_ERROR")
        else:
            try:
                return res.json()
            except json.JSONDecodeError:
                raise SkillHubError(f"Invalid JSON response: {res.text[:200]}", "PARSE_ERROR")
    
    def initialize(self) -> dict:
        """Initialize the MCP session. Must be called before any tool calls."""
        if self._initialized:
            return self._session_info
        
        print("[SkillHub] Initializing MCP session...", file=sys.stderr)
        result = self._send_jsonrpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "thesis-to-code-regime-rotator", "version": "2.0.0"}
        }, timeout=30)
        
        self._initialized = True
        self._session_info = result
        print("[SkillHub] MCP session initialized successfully.", file=sys.stderr)
        return result
    
    # ─── MCP Tool Calls ─────────────────────────────────────────────
    
    def find_skill(self, query: str) -> List[dict]:
        """
        Search the Skills Marketplace for relevant skills.
        Returns a list of candidate skill descriptors.
        """
        self._ensure_initialized()
        
        result = self._send_jsonrpc("tools/call", {
            "name": "find_skill",
            "arguments": {"query": query}
        }, timeout=30)
        
        return self._extract_candidates(result)
    
    def execute_skill(self, skill_name: str, params: dict, timeout: int = 120) -> dict:
        """
        Execute a skill by unique name with given parameters.
        Returns the structured evidence pack or result.
        
        Skills can take 30-60+ seconds for cloud execution.
        """
        self._ensure_initialized()
        
        print(f"[SkillHub] Executing skill: {skill_name}...", file=sys.stderr)
        start = time.time()
        
        result = self._send_jsonrpc("tools/call", {
            "name": "execute_skill",
            "arguments": {
                "unique_name": skill_name,
                "parameters": params
            }
        }, timeout=timeout)
        
        elapsed = time.time() - start
        print(f"[SkillHub] Skill '{skill_name}' completed in {elapsed:.1f}s", file=sys.stderr)
        
        return self._extract_skill_result(result, skill_name)
    
    # ─── High-Level Convenience Methods ──────────────────────────────
    
    def get_macro_regime(self) -> dict:
        """
        Get the full crypto macro regime classification.
        Replaces simple Fear & Greed thresholding.
        
        Returns evidence pack with:
        - regime classification
        - confirmation/invalidation triggers
        - action guidance
        """
        try:
            return self.execute_skill("crypto_macro_overview", {"preview": True}, timeout=120)
        except SkillHubError as e:
            print(f"[SkillHub] crypto_macro_overview failed: {e}", file=sys.stderr)
            return self._fallback_macro_regime()
    
    def get_sentiment_regime(self, window: str = "7d") -> dict:
        """
        Get the multi-lane market sentiment regime.
        Returns fear/greed, funding rates, headline bias, leverage state.
        """
        try:
            return self.execute_skill("monitor_market_sentiment_shift", {"time_window": window}, timeout=60)
        except SkillHubError as e:
            print(f"[SkillHub] monitor_market_sentiment_shift failed: {e}", file=sys.stderr)
            return self._fallback_sentiment()
    
    def get_kol_sentiment(self, symbol: str) -> dict:
        """
        Get real KOL sentiment and social discussion analysis for a specific token.
        Replaces the fake news_sentiment_score proxy.
        """
        try:
            return self.execute_skill("altcoin_kol_sentiment", {"symbol": symbol}, timeout=120)
        except SkillHubError as e:
            print(f"[SkillHub] altcoin_kol_sentiment for {symbol} failed: {e}", file=sys.stderr)
            return {"status": "degraded", "symbol": symbol, "error": str(e)}
    
    def get_funding_rate_regime(self, symbol: str) -> dict:
        """
        Get real funding rate regime shift detection.
        Replaces the fake liquidation_volume_short_24h proxy.
        """
        try:
            return self.execute_skill("detect_funding_rate_regime_shift", {"symbol": symbol}, timeout=60)
        except SkillHubError as e:
            print(f"[SkillHub] detect_funding_rate_regime_shift for {symbol} failed: {e}", file=sys.stderr)
            return {"status": "degraded", "symbol": symbol, "error": str(e)}
    
    def get_holder_concentration(self, symbol: str, platform: str = "bnb-smart-chain", contract_address: str = "") -> dict:
        """
        Get real holder concentration risk scoring.
        Replaces the fake top_10_holder_percentage proxy.
        """
        try:
            params = {
                "token_id_or_symbol": symbol,
                "platform": platform,
            }
            if contract_address:
                params["contract_address"] = contract_address
            return self.execute_skill("score_holder_concentration_risk", params, timeout=60)
        except SkillHubError as e:
            print(f"[SkillHub] score_holder_concentration_risk for {symbol} failed: {e}", file=sys.stderr)
            return {"status": "degraded", "symbol": symbol, "error": str(e)}
    
    def get_whale_anomalies(self, symbol: str, chain: str = "bsc") -> dict:
        """Get real whale transfer anomaly monitoring."""
        try:
            return self.execute_skill("monitor_whale_transfer_anomalies", {
                "symbol": symbol,
                "chain": chain
            }, timeout=60)
        except SkillHubError as e:
            print(f"[SkillHub] monitor_whale_transfer_anomalies for {symbol} failed: {e}", file=sys.stderr)
            return {"status": "degraded", "symbol": symbol, "error": str(e)}
    
    def get_kline_patterns(self, symbol: str, interval: str = "1d") -> dict:
        """Get candlestick pattern recognition and chart analysis."""
        try:
            return self.execute_skill("kline_pattern_recognition", {
                "symbol": symbol,
                "interval": interval
            }, timeout=60)
        except SkillHubError as e:
            print(f"[SkillHub] kline_pattern_recognition for {symbol} failed: {e}", file=sys.stderr)
            return {"status": "degraded", "symbol": symbol, "error": str(e)}
    
    def get_narrative_rotation(self) -> dict:
        """Get trending narrative rotation analysis."""
        try:
            return self.execute_skill("track_narrative_rotation", {"time_window": "7d"}, timeout=60)
        except SkillHubError as e:
            print(f"[SkillHub] track_narrative_rotation failed: {e}", file=sys.stderr)
            return {"status": "degraded", "error": str(e)}
    
    def get_asset_structure(self, symbol: str) -> dict:
        """Get full asset structure assessment (security, holders, emissions)."""
        try:
            return self.execute_skill("assess_altcoin_asset_structure", {
                "token_id_or_symbol": symbol,
            }, timeout=60)
        except SkillHubError as e:
            print(f"[SkillHub] assess_altcoin_asset_structure for {symbol} failed: {e}", file=sys.stderr)
            return {"status": "degraded", "symbol": symbol, "error": str(e)}

    def get_daily_overview(self) -> dict:
        """Get the daily market overview brief with regime read."""
        try:
            return self.execute_skill("daily_market_overview", {"preview": True}, timeout=120)
        except SkillHubError as e:
            print(f"[SkillHub] daily_market_overview failed: {e}", file=sys.stderr)
            return {"status": "degraded", "error": str(e)}

    # ─── Bulk Intelligence Gathering ─────────────────────────────────
    
    def gather_compilation_intelligence(self, target_assets: List[str]) -> dict:
        """
        Gather all intelligence needed for strategy compilation.
        Calls ALL 10 Skill Hub skills and aggregates results.
        
        Returns a structured dict with:
        - daily_overview: Market overview brief
        - macro_regime: Full macro regime classification
        - sentiment_regime: Market sentiment state  
        - narrative_rotation: Trending themes
        - per_asset: {symbol: {kol_sentiment, funding_regime, holder_risk, 
                               whale_activity, asset_structure, kline_patterns}}
        """
        print("[SkillHub] ═══════════════════════════════════════════════", file=sys.stderr)
        print("[SkillHub] Gathering FULL compilation intelligence (10 skills)...", file=sys.stderr)
        print(f"[SkillHub] Target assets: {target_assets}", file=sys.stderr)
        print("[SkillHub] ═══════════════════════════════════════════════", file=sys.stderr)
        
        non_stable_assets = [a for a in target_assets if a not in ("USDT", "USDC", "DAI", "FDUSD", "TUSD", "USD1", "USDe", "USDD")]
        total_calls = 4 + len(non_stable_assets) * 5  # 4 global + 5 per-asset
        call_num = 0
        
        intelligence = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "daily_overview": {},
            "macro_regime": {},
            "sentiment_regime": {},
            "narrative_rotation": {},
            "per_asset": {},
            "skills_called": [],
        }
        
        # 1. Daily Market Overview (warm-up context)
        call_num += 1
        print(f"[SkillHub] [{call_num}/{total_calls}] daily_market_overview...", file=sys.stderr)
        intelligence["daily_overview"] = self.get_daily_overview()
        intelligence["skills_called"].append("daily_market_overview")
        
        # 2. Global macro regime
        call_num += 1
        print(f"[SkillHub] [{call_num}/{total_calls}] crypto_macro_overview...", file=sys.stderr)
        intelligence["macro_regime"] = self.get_macro_regime()
        intelligence["skills_called"].append("crypto_macro_overview")
        
        # 3. Market sentiment
        call_num += 1
        print(f"[SkillHub] [{call_num}/{total_calls}] monitor_market_sentiment_shift...", file=sys.stderr)
        intelligence["sentiment_regime"] = self.get_sentiment_regime()
        intelligence["skills_called"].append("monitor_market_sentiment_shift")
        
        # 4. Narrative rotation
        call_num += 1
        print(f"[SkillHub] [{call_num}/{total_calls}] track_narrative_rotation...", file=sys.stderr)
        intelligence["narrative_rotation"] = self.get_narrative_rotation()
        intelligence["skills_called"].append("track_narrative_rotation")
        
        # 5. Per-asset intelligence (5 skills per non-stablecoin asset)
        for symbol in target_assets:
            if symbol in ("USDT", "USDC", "DAI", "FDUSD", "TUSD", "USD1", "USDe", "USDD"):
                intelligence["per_asset"][symbol] = {"type": "stablecoin", "skipped": True}
                continue
            
            asset_intel = {}
            
            # 5a. KOL Sentiment
            call_num += 1
            print(f"[SkillHub] [{call_num}/{total_calls}] altcoin_kol_sentiment({symbol})...", file=sys.stderr)
            asset_intel["kol_sentiment"] = self.get_kol_sentiment(symbol)
            intelligence["skills_called"].append(f"altcoin_kol_sentiment:{symbol}")
            
            # 5b. Funding rate regime (for ALL assets, not just first)
            call_num += 1
            print(f"[SkillHub] [{call_num}/{total_calls}] detect_funding_rate_regime_shift({symbol})...", file=sys.stderr)
            asset_intel["funding_regime"] = self.get_funding_rate_regime(symbol)
            intelligence["skills_called"].append(f"detect_funding_rate_regime_shift:{symbol}")
            
            # 5c. Kline patterns
            call_num += 1
            print(f"[SkillHub] [{call_num}/{total_calls}] kline_pattern_recognition({symbol})...", file=sys.stderr)
            asset_intel["kline_patterns"] = self.get_kline_patterns(symbol)
            intelligence["skills_called"].append(f"kline_pattern_recognition:{symbol}")
            
            # 5d. Holder concentration risk
            call_num += 1
            print(f"[SkillHub] [{call_num}/{total_calls}] score_holder_concentration_risk({symbol})...", file=sys.stderr)
            asset_intel["holder_risk"] = self.get_holder_concentration(symbol)
            intelligence["skills_called"].append(f"score_holder_concentration_risk:{symbol}")
            
            # 5e. Whale transfer anomalies
            call_num += 1
            print(f"[SkillHub] [{call_num}/{total_calls}] monitor_whale_transfer_anomalies({symbol})...", file=sys.stderr)
            asset_intel["whale_activity"] = self.get_whale_anomalies(symbol)
            intelligence["skills_called"].append(f"monitor_whale_transfer_anomalies:{symbol}")
            
            intelligence["per_asset"][symbol] = asset_intel
        
        print("[SkillHub] ═══════════════════════════════════════════════", file=sys.stderr)
        print(f"[SkillHub] Intelligence gathering complete. {len(intelligence['skills_called'])} skill calls made.", file=sys.stderr)
        print("[SkillHub] ═══════════════════════════════════════════════", file=sys.stderr)
        
        return intelligence
    
    # ─── Internal Helpers ────────────────────────────────────────────
    
    def _ensure_initialized(self):
        if not self._initialized:
            self.initialize()
    
    def _extract_candidates(self, response: dict) -> List[dict]:
        """Extract skill candidates from a find_skill response."""
        if "result" not in response:
            return []
        content = response["result"].get("content", [])
        for item in content:
            if item.get("type") == "text":
                try:
                    data = json.loads(item["text"])
                    return data.get("candidates", [])
                except (json.JSONDecodeError, KeyError):
                    continue
        return []
    
    def _extract_skill_result(self, response: dict, skill_name: str) -> dict:
        """Extract the structured result from an execute_skill response."""
        if "error" in response and response.get("result") is None:
            error = response["error"]
            raise SkillHubError(
                error.get("message", str(error)),
                error.get("code", "SKILL_ERROR")
            )
        
        if "result" not in response:
            raise SkillHubError(f"No result in response for skill '{skill_name}'", "EMPTY_RESULT")
        
        result = response["result"]
        
        # Handle content-wrapped responses
        content = result.get("content", [])
        for item in content:
            if item.get("type") == "text":
                try:
                    data = json.loads(item["text"])
                    # Some skills wrap in result.output
                    if isinstance(data, dict):
                        if "result" in data and isinstance(data["result"], dict):
                            inner = data["result"]
                            # Handle double-wrapped output (some skills serialize JSON in output string)
                            if "output" in inner and isinstance(inner["output"], str):
                                try:
                                    parsed_output = json.loads(inner["output"])
                                    if isinstance(parsed_output, dict) and "result" in parsed_output:
                                        return parsed_output["result"]
                                    return parsed_output
                                except json.JSONDecodeError:
                                    pass
                            return inner
                        return data
                except (json.JSONDecodeError, KeyError):
                    continue
        
        # Direct result (no content wrapping)
        if isinstance(result, dict) and "ok" in result:
            return result
            
        return result
    
    def _fallback_macro_regime(self) -> dict:
        """Fallback macro regime using Fear & Greed REST API."""
        print("[SkillHub] Using F&G REST fallback for regime classification...", file=sys.stderr)
        try:
            headers = {"X-CMC_PRO_API_KEY": self.api_key, "Accept": "application/json"}
            res = requests.get(
                "https://pro-api.coinmarketcap.com/v3/fear-and-greed/latest",
                headers=headers, timeout=5.0
            )
            if res.status_code == 200:
                fg_value = float(res.json().get("data", {}).get("value", 50.0))
                if fg_value >= 60:
                    regime = "bullish"
                elif fg_value <= 40:
                    regime = "bearish"
                else:
                    regime = "sideways"
                return {
                    "status": "fallback",
                    "source": "fear_and_greed_rest_api",
                    "data": {
                        "fear_greed_value": fg_value,
                        "regime": regime
                    }
                }
        except Exception as e:
            print(f"[SkillHub] F&G fallback also failed: {e}", file=sys.stderr)
        
        return {
            "status": "degraded",
            "source": "default",
            "data": {"regime": "sideways", "fear_greed_value": 50.0}
        }
    
    def _fallback_sentiment(self) -> dict:
        """Fallback sentiment using Fear & Greed."""
        regime = self._fallback_macro_regime()
        return {
            "status": "fallback",
            "data": {
                "sentiment_regime": "unknown",
                "fear_greed_value": regime.get("data", {}).get("fear_greed_value", 50.0)
            }
        }


# ─── Convenience: Extract key metrics from skill results ────────────

def extract_regime_from_macro(macro_result: dict) -> str:
    """Extract a simple regime string (bullish/bearish/sideways) from macro overview."""
    data = macro_result.get("data", macro_result)
    
    # Try to find regime in the decision report
    report = data.get("decision_report", {})
    conclusion = report.get("conclusion", "").lower()
    
    # Try action_guidance
    guidance = data.get("action_guidance", {})
    bias = guidance.get("bias", "").lower()
    
    if any(w in conclusion for w in ["risk-on", "bullish", "constructive"]):
        return "bullish"
    elif any(w in conclusion for w in ["risk-off", "bearish", "defensive", "caution"]):
        return "bearish"
    elif any(w in bias for w in ["risk_on", "bullish"]):
        return "bullish"
    elif any(w in bias for w in ["risk_off", "bearish", "defensive", "avoid"]):
        return "bearish"
    
    return "sideways"


def extract_sentiment_metrics(sentiment_result: dict) -> dict:
    """Extract key sentiment metrics from monitor_market_sentiment_shift."""
    data = sentiment_result.get("data", sentiment_result)
    
    # Handle nested output format
    if "output" in data and isinstance(data["output"], str):
        try:
            parsed = json.loads(data["output"])
            data = parsed.get("result", parsed).get("data", parsed)
        except (json.JSONDecodeError, AttributeError):
            pass
    
    report = data.get("report", {})
    metrics = report.get("metrics", {})
    
    return {
        "sentiment_regime": report.get("sentiment_regime", data.get("summary", "unknown")),
        "inflection_direction": report.get("inflection_direction", "unknown"),
        "fear_greed_value": metrics.get("fear_greed_value", 50.0),
        "fear_greed_label": metrics.get("fear_greed_label", "neutral"),
        "fear_greed_7d_delta": metrics.get("fear_greed_7d_delta", 0.0),
        "avg_funding_bps": metrics.get("average_funding_bps_7d", 0.0),
    }


def extract_kol_sentiment_summary(kol_result: dict) -> dict:
    """Extract a concise sentiment summary from altcoin_kol_sentiment."""
    data = kol_result.get("data", kol_result)
    report = data.get("decision_report", {})
    guidance = data.get("action_guidance", {})
    
    return {
        "status": data.get("status", "unknown"),
        "confidence": data.get("confidence", "unknown"),
        "conclusion": report.get("conclusion", "No data"),
        "analysis": report.get("analysis", ""),
        "bias": guidance.get("bias", "unknown"),
        "risk_note": guidance.get("risk_note", ""),
    }


def summarize_intelligence_for_llm(intelligence: dict) -> str:
    """
    Convert the full intelligence gathering results into a concise
    text summary suitable for injection into the LLM compiler prompt.
    Covers all 10 Skill Hub skills.
    """
    lines = []
    
    # Daily overview
    daily = intelligence.get("daily_overview", {})
    daily_data = daily.get("data", daily)
    daily_report = daily_data.get("decision_report", daily_data.get("report", {}))
    if daily_report.get("conclusion"):
        lines.append("=== DAILY MARKET OVERVIEW (from daily_market_overview) ===")
        lines.append(f"Summary: {daily_report['conclusion'][:300]}")
        lines.append("")
    
    # Macro regime
    macro = intelligence.get("macro_regime", {})
    macro_data = macro.get("data", macro)
    macro_report = macro_data.get("decision_report", {})
    lines.append("=== MACRO REGIME (from crypto_macro_overview) ===")
    if macro_report.get("conclusion"):
        lines.append(f"Conclusion: {macro_report['conclusion']}")
    if macro_report.get("analysis"):
        lines.append(f"Analysis: {macro_report['analysis'][:500]}")
    macro_guidance = macro_data.get("action_guidance", {})
    if macro_guidance.get("bias"):
        lines.append(f"Bias: {macro_guidance['bias']}")
    lines.append("")
    
    # Sentiment regime
    sentiment = intelligence.get("sentiment_regime", {})
    metrics = extract_sentiment_metrics(sentiment)
    lines.append("=== MARKET SENTIMENT (from monitor_market_sentiment_shift) ===")
    lines.append(f"Regime: {metrics['sentiment_regime']}")
    lines.append(f"Fear & Greed: {metrics['fear_greed_value']} ({metrics['fear_greed_label']}), 7d delta: {metrics['fear_greed_7d_delta']}")
    lines.append(f"Avg Funding: {metrics['avg_funding_bps']} bps")
    lines.append(f"Inflection: {metrics['inflection_direction']}")
    lines.append("")
    
    # Narrative rotation
    narrative = intelligence.get("narrative_rotation", {})
    narrative_data = narrative.get("data", narrative)
    if isinstance(narrative_data, dict):
        narrative_report = narrative_data.get("decision_report", narrative_data.get("report", {}))
        if narrative_report.get("conclusion"):
            lines.append("=== NARRATIVE ROTATION (from track_narrative_rotation) ===")
            lines.append(f"Conclusion: {narrative_report['conclusion']}")
            lines.append("")
    
    # Per-asset intelligence
    per_asset = intelligence.get("per_asset", {})
    for symbol, asset_data in per_asset.items():
        if asset_data.get("type") == "stablecoin":
            continue
        
        lines.append(f"=== ASSET: {symbol} ===")
        
        # KOL sentiment
        kol = asset_data.get("kol_sentiment", {})
        kol_summary = extract_kol_sentiment_summary(kol)
        lines.append(f"KOL Sentiment: {kol_summary['conclusion'][:200]}")
        lines.append(f"  Confidence: {kol_summary['confidence']}, Bias: {kol_summary['bias']}")
        
        # Funding regime
        funding = asset_data.get("funding_regime", {})
        funding_data = funding.get("data", funding)
        funding_report = funding_data.get("decision_report", funding_data.get("report", {}))
        if funding_report.get("conclusion"):
            lines.append(f"Funding Regime: {funding_report['conclusion'][:200]}")
        
        # Kline patterns
        kline = asset_data.get("kline_patterns", {})
        kline_data = kline.get("data", kline)
        kline_report = kline_data.get("decision_report", {})
        if kline_report.get("conclusion"):
            lines.append(f"Chart Patterns: {kline_report['conclusion'][:200]}")
        
        # Holder concentration risk
        holder = asset_data.get("holder_risk", {})
        holder_data = holder.get("data", holder)
        holder_report = holder_data.get("decision_report", holder_data.get("report", {}))
        if holder_report.get("conclusion"):
            lines.append(f"Holder Risk: {holder_report['conclusion'][:200]}")
        elif holder_data.get("risk_score"):
            lines.append(f"Holder Risk Score: {holder_data['risk_score']}")
        
        # Whale transfer anomalies
        whale = asset_data.get("whale_activity", {})
        whale_data = whale.get("data", whale)
        whale_report = whale_data.get("decision_report", whale_data.get("report", {}))
        if whale_report.get("conclusion"):
            lines.append(f"Whale Activity: {whale_report['conclusion'][:200]}")
        elif whale_data.get("anomaly_detected") is not None:
            lines.append(f"Whale Anomaly Detected: {whale_data['anomaly_detected']}")
        
        lines.append("")
    
    # Skills called summary
    skills_called = intelligence.get("skills_called", [])
    if skills_called:
        unique_skills = set(s.split(":")[0] for s in skills_called)
        lines.append(f"=== TOTAL: {len(skills_called)} skill calls across {len(unique_skills)} unique skills ===")
    
    return "\n".join(lines)


if __name__ == "__main__":
    # Quick verification
    client = SkillHubClient()
    client.initialize()
    
    print("\n=== find_skill('btc price') ===")
    candidates = client.find_skill("btc price")
    for c in candidates[:3]:
        print(f"  {c['uniqueName']}: {c.get('skillDescription', '')[:80]}...")
    
    print("\n=== Sentiment Regime ===")
    sentiment = client.get_sentiment_regime()
    metrics = extract_sentiment_metrics(sentiment)
    print(f"  Regime: {metrics['sentiment_regime']}")
    print(f"  F&G: {metrics['fear_greed_value']} ({metrics['fear_greed_label']})")
    print(f"  Funding: {metrics['avg_funding_bps']} bps")
    
    print("\nSkill Hub Client verified successfully!")
