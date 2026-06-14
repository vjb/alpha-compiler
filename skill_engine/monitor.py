"""
Regime Monitor — Architecture C: Living Strategy.

Monitors the market for regime shifts by polling Core MCP and Skill Hub.
When a shift is detected, re-compiles the strategy and produces a version diff.

Usage:
    # Single check (good for demos)
    python -m skill_engine.monitor --thesis "..." --assets CAKE,FLOKI --check-once
    
    # Continuous monitoring (every 4 hours)
    python -m skill_engine.monitor --thesis "..." --assets CAKE,FLOKI --interval 14400
"""
import os
import sys
import json
import time
import argparse
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


def get_current_regime() -> dict:
    """
    Quick regime check using Core MCP (fast) + Skill Hub sentiment (focused).
    Returns a dict with regime classification and key metrics.
    """
    from skill_engine.cmc_mcp_client import CoreMCPClient
    from skill_engine.skill_hub_client import SkillHubClient, extract_sentiment_metrics
    
    result = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "regime": "sideways",
        "fear_greed": 50.0,
        "fear_greed_label": "neutral",
        "sentiment_regime": "unknown",
        "avg_funding_bps": 0.0,
        "core_mcp_calls": 0,
        "skill_hub_calls": 0,
    }
    
    api_key = os.environ.get("CMC_API_KEY", "")
    
    # 1. Core MCP: get global metrics (fast, ~2s)
    try:
        core = CoreMCPClient(api_key)
        core.initialize()
        global_metrics = core.get_global_metrics()
        result["global_metrics_raw"] = global_metrics
        result["core_mcp_calls"] += 1
        print("[Monitor] Core MCP global metrics fetched.", file=sys.stderr)
    except Exception as e:
        print(f"[Monitor] Core MCP global metrics failed: {e}", file=sys.stderr)
    
    # 2. Skill Hub: sentiment regime (focused, ~10-30s)
    try:
        skill = SkillHubClient(api_key)
        skill.initialize()
        sentiment = skill.get_sentiment_regime()
        metrics = extract_sentiment_metrics(sentiment)
        
        result["fear_greed"] = metrics.get("fear_greed_value", 50.0)
        result["fear_greed_label"] = metrics.get("fear_greed_label", "neutral")
        result["sentiment_regime"] = metrics.get("sentiment_regime", "unknown")
        result["avg_funding_bps"] = metrics.get("avg_funding_bps", 0.0)
        result["skill_hub_calls"] += 1
        print(f"[Monitor] Skill Hub sentiment: F&G={result['fear_greed']}, regime={result['sentiment_regime']}", file=sys.stderr)
    except Exception as e:
        print(f"[Monitor] Skill Hub sentiment failed: {e}", file=sys.stderr)
    
    # 3. Classify regime from metrics
    fg = result["fear_greed"]
    sentiment = result["sentiment_regime"].lower()
    
    if fg >= 60 or "risk_on" in sentiment or "bullish" in sentiment:
        result["regime"] = "bullish"
    elif fg <= 35 or "defensive" in sentiment or "fear" in sentiment or "bearish" in sentiment:
        result["regime"] = "bearish"
    else:
        result["regime"] = "sideways"
    
    print(f"[Monitor] Classified regime: {result['regime']} (F&G={fg})", file=sys.stderr)
    return result


def load_last_regime(state_file: str = "monitor_state.json") -> Optional[dict]:
    """Load the last recorded regime state."""
    if os.path.exists(state_file):
        try:
            with open(state_file, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return None


def save_regime_state(state: dict, state_file: str = "monitor_state.json"):
    """Save the current regime state to disk."""
    with open(state_file, "w") as f:
        json.dump(state, f, indent=2)


def detect_regime_shift(current: dict, previous: Optional[dict]) -> dict:
    """
    Compare current regime to previous and determine if a shift occurred.
    Returns a dict describing the shift (or lack thereof).
    """
    if previous is None:
        return {
            "shifted": False,
            "reason": "No previous state — first check",
            "current_regime": current["regime"],
            "previous_regime": None,
        }
    
    prev_regime = previous.get("regime", "unknown")
    curr_regime = current["regime"]
    
    shifted = prev_regime != curr_regime
    
    # Also check for significant F&G moves even within same regime
    fg_delta = abs(current["fear_greed"] - previous.get("fear_greed", 50.0))
    significant_fg_move = fg_delta >= 15
    
    result = {
        "shifted": shifted,
        "significant_fg_move": significant_fg_move,
        "current_regime": curr_regime,
        "previous_regime": prev_regime,
        "fear_greed_delta": round(fg_delta, 1),
        "current_fg": current["fear_greed"],
        "previous_fg": previous.get("fear_greed", 50.0),
        "current_sentiment": current["sentiment_regime"],
        "previous_sentiment": previous.get("sentiment_regime", "unknown"),
    }
    
    if shifted:
        result["reason"] = f"Regime shifted: {prev_regime} → {curr_regime}"
    elif significant_fg_move:
        result["reason"] = f"Significant F&G move: {previous.get('fear_greed', 50.0)} → {current['fear_greed']} (Δ{fg_delta:.0f})"
    else:
        result["reason"] = "No significant change"
    
    return result


def recompile_strategy(thesis: str, assets: list, risk: str, backtest_range: str = "30d"):
    """
    Re-compile the strategy using the full pipeline.
    Returns the new spec and version entry.
    """
    from skill_engine.compiler import ThesisToCodeStrategyCompiler
    from skill_engine.publisher import record_strategy_version, publish_deliverables
    from backtest_sandbox.engine import run_backtest
    
    print(f"\n{'='*70}", file=sys.stderr)
    print("[Monitor] RE-COMPILING strategy after regime shift...", file=sys.stderr)
    print(f"{'='*70}", file=sys.stderr)
    
    compiler = ThesisToCodeStrategyCompiler()
    spec = compiler.compile(thesis, assets, risk, backtest_range)
    
    # Save strategy
    with open("strategy_v1.json", "w") as f:
        f.write(spec.model_dump_json(indent=2))
    
    # Run backtest
    run_backtest()
    
    # Record version and diff
    version_entry = record_strategy_version(spec.model_dump())
    
    # Publish
    try:
        storage_urls = publish_deliverables(spec.model_dump())
    except Exception:
        storage_urls = {"greenfield": None, "ipfs": None}
    
    return spec, version_entry


def run_monitor(thesis: str, assets: list, risk: str, backtest_range: str = "30d",
                interval: int = 14400, check_once: bool = False):
    """
    Main monitoring loop.
    
    Args:
        thesis: Investment thesis text
        assets: Target asset symbols
        risk: Risk tolerance
        backtest_range: Backtest range
        interval: Check interval in seconds (default: 4 hours)
        check_once: If True, check once and exit
    """
    print(f"\n{'='*70}")
    print("ALPHA COMPILER — REGIME MONITOR")
    print(f"{'='*70}")
    print(f"Thesis: {thesis}")
    print(f"Assets: {assets}")
    print(f"Risk: {risk}")
    print(f"Mode: {'single check' if check_once else f'continuous (every {interval}s)'}")
    print(f"{'='*70}\n")
    
    iteration = 0
    
    while True:
        iteration += 1
        print(f"\n{'─'*70}")
        print(f"[Monitor] Check #{iteration} at {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'─'*70}")
        
        # 1. Get current regime
        current = get_current_regime()
        
        # 2. Load previous state
        previous = load_last_regime()
        
        # 3. Detect shift
        shift = detect_regime_shift(current, previous)
        
        print(f"\n[Monitor] Shift analysis:")
        print(f"  Regime: {shift['previous_regime']} → {shift['current_regime']}")
        print(f"  Shifted: {shift['shifted']}")
        print(f"  Reason: {shift['reason']}")
        
        # 4. Save current state
        save_regime_state(current)
        
        # 5. Re-compile if shifted (or if first run)
        if shift["shifted"] or previous is None:
            if previous is None:
                print("\n[Monitor] First run — performing initial compilation...")
            else:
                print(f"\n[Monitor] ⚠️  REGIME SHIFT DETECTED: {shift['previous_regime']} → {shift['current_regime']}")
                print(f"[Monitor] Triggering re-compilation...")
            
            spec, version_entry = recompile_strategy(thesis, assets, risk, backtest_range)
            
            print(f"\n{'='*70}")
            print(f"[Monitor] Re-compilation complete!")
            print(f"  Strategy: {spec.strategy_name}")
            print(f"  Regime: {spec.regime_classified}")
            print(f"  Version: v{version_entry.get('version', '?')}")
            
            if "diff_from_previous" in version_entry:
                diff = version_entry["diff_from_previous"]
                print(f"  Changes: {diff.get('total_changes', 0)} modifications")
                for change in diff.get("changes", []):
                    if change["type"] == "regime_shift":
                        print(f"    🔄 Regime: {change['old']} → {change['new']}")
                    elif change["type"] == "weight_rebalance":
                        for w in change.get("details", []):
                            print(f"    ⚖️  {w['symbol']}: {w['old_weight']*100:.0f}% → {w['new_weight']*100:.0f}%")
                    elif change["type"] == "asset_change":
                        if change.get("added"):
                            print(f"    ➕ Added: {change['added']}")
                        if change.get("removed"):
                            print(f"    ➖ Removed: {change['removed']}")
            
            print(f"{'='*70}")
        else:
            print(f"\n[Monitor] No regime shift. Strategy unchanged.")
            if shift.get("significant_fg_move"):
                print(f"  (Note: significant F&G move detected — {shift['reason']})")
                print(f"  Consider re-compiling if trend continues.")
        
        if check_once:
            break
        
        print(f"\n[Monitor] Next check in {interval}s ({interval/3600:.1f} hours)...")
        time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description="Alpha Compiler Regime Monitor")
    parser.add_argument("--thesis", type=str, required=True, help="Investment thesis")
    parser.add_argument("--assets", type=str, required=True, help="Comma-separated target assets")
    parser.add_argument("--risk", type=str, default="medium", help="Risk tolerance")
    parser.add_argument("--range", type=str, default="30d", help="Backtest range")
    parser.add_argument("--interval", type=int, default=14400, help="Check interval in seconds (default: 4h)")
    parser.add_argument("--check-once", action="store_true", help="Check once and exit")
    args = parser.parse_args()
    
    assets = [a.strip() for a in args.assets.split(",")]
    
    run_monitor(
        thesis=args.thesis,
        assets=assets,
        risk=args.risk,
        backtest_range=args.range,
        interval=args.interval,
        check_once=args.check_once,
    )


if __name__ == "__main__":
    main()
