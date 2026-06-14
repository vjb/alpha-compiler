"""
CoinMarketCap Core MCP Client — 12 direct data tools via Streamable HTTP.

Connects to https://mcp.coinmarketcap.com/mcp for fast, structured data queries:
quotes, technical analysis, derivatives, news, global metrics, narratives, macro events.

Separate from the Skill Hub client (which runs cloud-executed analytical pipelines).
Core MCP tools return raw data; Skill Hub skills return evidence packs with analysis.
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


class CoreMCPError(Exception):
    """Raised when a Core MCP call fails."""
    def __init__(self, message: str, code: str = "UNKNOWN"):
        self.code = code
        super().__init__(f"[{code}] {message}")


class CoreMCPClient:
    """
    CoinMarketCap Core MCP client — 12 direct data tools.
    
    Endpoint: https://mcp.coinmarketcap.com/mcp
    Transport: Streamable HTTP
    Auth: X-CMC-MCP-API-KEY header
    
    Tools available:
      - search_cryptos: Resolve symbols to CMC IDs
      - get_crypto_quotes_latest: Real-time price, mcap, volume, % changes
      - get_crypto_info: Token metadata, links, contract addresses
      - get_crypto_metrics: Whale vs retail distribution
      - get_crypto_technical_analysis: SMA, EMA, MACD, RSI, Fibonacci
      - get_crypto_latest_news: Recent headlines per asset
      - get_global_market_metrics: Total market cap, BTC dom, F&G
      - get_trending_narratives: Hot trends and associated tokens
      - get_derivatives_data: OI, funding rates, liquidations
      - get_macro_events: Upcoming economic events
      - get_market_cap_ta: Overall market cap technicals
      - search_crypto_info: Semantic search for crypto concepts
    """
    
    ENDPOINT = "https://mcp.coinmarketcap.com/mcp"
    X402_ENDPOINT = "https://mcp.coinmarketcap.com/x402/mcp"
    
    def __init__(self, api_key: str = None, use_x402: bool = False):
        self.api_key = api_key or os.environ.get("CMC_API_KEY", "")
        self.use_x402 = use_x402
        self.endpoint = self.X402_ENDPOINT if use_x402 else self.ENDPOINT
        
        if not self.api_key and not use_x402:
            raise ValueError("CMC_API_KEY required for Core MCP (or use x402 mode).")
        
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"
        }
        if self.api_key and not use_x402:
            self.headers["X-CMC-MCP-API-KEY"] = self.api_key
        
        self._initialized = False
    
    # ─── Core MCP Transport ─────────────────────────────────────────
    
    def _send_jsonrpc(self, method: str, params: dict = None, timeout: int = 30) -> dict:
        """Send a JSON-RPC request to the Core MCP endpoint."""
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
        }
        if params:
            payload["params"] = params
        
        try:
            res = requests.post(
                self.endpoint,
                headers=self.headers,
                json=payload,
                timeout=timeout
            )
            res.raise_for_status()
        except requests.exceptions.Timeout:
            raise CoreMCPError(f"Timeout after {timeout}s", "TIMEOUT")
        except requests.exceptions.RequestException as e:
            raise CoreMCPError(f"HTTP error: {e}", "HTTP_ERROR")
        
        content_type = res.headers.get("Content-Type", "")
        if "text/event-stream" in content_type:
            for line in res.text.splitlines():
                if line.startswith("data:"):
                    data_str = line[len("data:"):].strip()
                    if data_str:
                        try:
                            return json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
            raise CoreMCPError("No valid JSON in SSE response", "PARSE_ERROR")
        else:
            try:
                return res.json()
            except json.JSONDecodeError:
                raise CoreMCPError(f"Invalid JSON: {res.text[:200]}", "PARSE_ERROR")
    
    def _call_tool(self, tool_name: str, arguments: dict, timeout: int = 30) -> dict:
        """Call a Core MCP tool and extract the result."""
        result = self._send_jsonrpc("tools/call", {
            "name": tool_name,
            "arguments": arguments
        }, timeout=timeout)
        
        if "result" in result:
            content = result["result"].get("content", [])
            for item in content:
                if item.get("type") == "text":
                    try:
                        return json.loads(item["text"])
                    except (json.JSONDecodeError, KeyError):
                        return {"raw_text": item["text"]}
            return result["result"]
        elif "error" in result:
            raise CoreMCPError(
                result["error"].get("message", str(result["error"])),
                result["error"].get("code", "TOOL_ERROR")
            )
        return result
    
    def initialize(self) -> dict:
        """Initialize the MCP session."""
        if self._initialized:
            return {}
        
        print("[CoreMCP] Initializing session...", file=sys.stderr)
        result = self._send_jsonrpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "alpha-compiler-core", "version": "3.0.0"}
        }, timeout=15)
        self._initialized = True
        print("[CoreMCP] Session initialized.", file=sys.stderr)
        return result
    
    def _ensure_initialized(self):
        if not self._initialized:
            self.initialize()
    
    # ─── Tool Methods ────────────────────────────────────────────────
    
    def search_cryptos(self, query: str) -> dict:
        """Search for cryptocurrencies by name or symbol."""
        self._ensure_initialized()
        return self._call_tool("search_cryptos", {"query": query})
    
    def get_quotes_latest(self, symbols: List[str]) -> dict:
        """Get latest quotes for one or more symbols."""
        self._ensure_initialized()
        return self._call_tool("get_crypto_quotes_latest", {
            "symbol": ",".join(symbols)
        })
    
    def get_technical_analysis(self, symbol: str) -> dict:
        """Get technical analysis (SMA, EMA, MACD, RSI, Fibonacci)."""
        self._ensure_initialized()
        return self._call_tool("get_crypto_technical_analysis", {
            "symbol": symbol
        })
    
    def get_latest_news(self, symbol: str = None) -> dict:
        """Get latest crypto news, optionally filtered by symbol."""
        self._ensure_initialized()
        args = {}
        if symbol:
            args["symbol"] = symbol
        return self._call_tool("get_crypto_latest_news", args)
    
    def get_global_metrics(self) -> dict:
        """Get global market metrics (total mcap, BTC dom, F&G)."""
        self._ensure_initialized()
        return self._call_tool("get_global_metrics_latest", {})
    
    def get_trending_narratives(self) -> dict:
        """Get trending narratives and associated tokens."""
        self._ensure_initialized()
        return self._call_tool("trending_crypto_narratives", {})
    
    def get_derivatives_data(self, symbol: str = None) -> dict:
        """Get derivatives data (OI, funding rates, liquidations)."""
        self._ensure_initialized()
        args = {}
        if symbol:
            args["symbol"] = symbol
        return self._call_tool("get_global_crypto_derivatives_metrics", args)
    
    def get_macro_events(self) -> dict:
        """Get upcoming macro economic events."""
        self._ensure_initialized()
        return self._call_tool("get_upcoming_macro_events", {})
    
    def get_crypto_info(self, symbol: str) -> dict:
        """Get token metadata, links, contract addresses."""
        self._ensure_initialized()
        return self._call_tool("get_crypto_info", {"symbol": symbol})
    
    def get_crypto_metrics(self, symbol: str) -> dict:
        """Get whale vs retail distribution metrics."""
        self._ensure_initialized()
        return self._call_tool("get_crypto_metrics", {"symbol": symbol})
    
    def get_market_cap_ta(self) -> dict:
        """Get overall market cap technical indicators."""
        self._ensure_initialized()
        return self._call_tool("get_crypto_marketcap_technical_analysis", {})
    
    def search_crypto_info(self, query: str) -> dict:
        """Semantic search for crypto concepts."""
        self._ensure_initialized()
        return self._call_tool("search_crypto_info", {"query": query})
    
    # ─── Bulk Intelligence Gathering ─────────────────────────────────
    
    def gather_core_intelligence(self, target_assets: List[str]) -> dict:
        """
        Gather structured data from Core MCP tools for strategy compilation.
        Faster than Skill Hub (~5s total) but returns raw data, not analysis.
        """
        self._ensure_initialized()
        
        print("[CoreMCP] Gathering core intelligence...", file=sys.stderr)
        start = time.time()
        
        intel = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "global_metrics": {},
            "trending_narratives": {},
            "macro_events": {},
            "per_asset": {},
            "tools_called": [],
        }
        
        # Global data
        try:
            intel["global_metrics"] = self.get_global_metrics()
            intel["tools_called"].append("get_global_metrics_latest")
        except CoreMCPError as e:
            print(f"[CoreMCP] get_global_metrics_latest failed: {e}", file=sys.stderr)
        
        try:
            intel["trending_narratives"] = self.get_trending_narratives()
            intel["tools_called"].append("trending_crypto_narratives")
        except CoreMCPError as e:
            print(f"[CoreMCP] trending_crypto_narratives failed: {e}", file=sys.stderr)
        
        try:
            intel["macro_events"] = self.get_macro_events()
            intel["tools_called"].append("get_upcoming_macro_events")
        except CoreMCPError as e:
            print(f"[CoreMCP] get_upcoming_macro_events failed: {e}", file=sys.stderr)
        
        # Per-asset data
        for symbol in target_assets:
            if symbol in ("USDT", "USDC", "DAI", "FDUSD", "TUSD", "USD1", "USDe", "USDD"):
                continue
            
            asset_data = {}
            
            try:
                asset_data["quotes"] = self.get_quotes_latest([symbol])
                intel["tools_called"].append(f"get_crypto_quotes_latest:{symbol}")
            except CoreMCPError as e:
                print(f"[CoreMCP] quotes for {symbol} failed: {e}", file=sys.stderr)
            
            try:
                asset_data["ta"] = self.get_technical_analysis(symbol)
                intel["tools_called"].append(f"get_crypto_technical_analysis:{symbol}")
            except CoreMCPError as e:
                print(f"[CoreMCP] TA for {symbol} failed: {e}", file=sys.stderr)
            
            try:
                asset_data["news"] = self.get_latest_news(symbol)
                intel["tools_called"].append(f"get_crypto_latest_news:{symbol}")
            except CoreMCPError as e:
                print(f"[CoreMCP] news for {symbol} failed: {e}", file=sys.stderr)
            
            try:
                asset_data["derivatives"] = self.get_derivatives_data(symbol)
                intel["tools_called"].append(f"get_global_crypto_derivatives_metrics:{symbol}")
            except CoreMCPError as e:
                print(f"[CoreMCP] derivatives for {symbol} failed: {e}", file=sys.stderr)
            
            intel["per_asset"][symbol] = asset_data
        
        elapsed = time.time() - start
        print(f"[CoreMCP] Core intelligence gathered in {elapsed:.1f}s ({len(intel['tools_called'])} calls)", file=sys.stderr)
        
        return intel


def summarize_core_intelligence_for_llm(intel: dict) -> str:
    """Convert Core MCP intelligence into a concise LLM prompt section."""
    lines = []
    
    # Global metrics
    gm = intel.get("global_metrics", {})
    if gm:
        lines.append("=== GLOBAL MARKET METRICS (from Core MCP) ===")
        lines.append(json.dumps(gm, indent=2)[:500])
        lines.append("")
    
    # Trending narratives
    tn = intel.get("trending_narratives", {})
    if tn:
        lines.append("=== TRENDING NARRATIVES (from Core MCP) ===")
        lines.append(json.dumps(tn, indent=2)[:500])
        lines.append("")
    
    # Macro events
    me = intel.get("macro_events", {})
    if me:
        lines.append("=== MACRO EVENTS (from Core MCP) ===")
        lines.append(json.dumps(me, indent=2)[:300])
        lines.append("")
    
    # Per-asset
    for symbol, data in intel.get("per_asset", {}).items():
        lines.append(f"=== {symbol} CORE DATA ===")
        
        ta = data.get("ta", {})
        if ta:
            lines.append(f"Technical Analysis: {json.dumps(ta, indent=2)[:300]}")
        
        news = data.get("news", {})
        if news:
            lines.append(f"Latest News: {json.dumps(news, indent=2)[:200]}")
        
        deriv = data.get("derivatives", {})
        if deriv:
            lines.append(f"Derivatives: {json.dumps(deriv, indent=2)[:200]}")
        
        lines.append("")
    
    tools_called = intel.get("tools_called", [])
    if tools_called:
        unique = set(t.split(":")[0] for t in tools_called)
        lines.append(f"=== Core MCP: {len(tools_called)} calls across {len(unique)} tools ===")
    
    return "\n".join(lines)


if __name__ == "__main__":
    client = CoreMCPClient()
    client.initialize()
    
    print("\n=== Global Metrics ===")
    try:
        gm = client.get_global_metrics()
        print(json.dumps(gm, indent=2)[:500])
    except CoreMCPError as e:
        print(f"Failed: {e}")
    
    print("\n=== Trending Narratives ===")
    try:
        tn = client.get_trending_narratives()
        print(json.dumps(tn, indent=2)[:500])
    except CoreMCPError as e:
        print(f"Failed: {e}")
    
    print("\nCore MCP Client verified.")
