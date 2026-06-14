"""
End-to-end test: Compile strategy with Core MCP + Skill Hub MCP, run backtest,
record version, publish deliverables. Captures output for README examples.
"""
import json
import sys
import time
import os

def run_example(thesis: str, assets: list, risk: str, backtest_range: str = "30d", label: str = ""):
    print(f"\n{'='*70}")
    print(f"EXAMPLE: {label}")
    print(f"{'='*70}")
    print(f"Thesis: {thesis}")
    print(f"Assets: {assets}")
    print(f"Risk: {risk}")
    print(f"Range: {backtest_range}")
    print(f"{'='*70}\n")
    
    start = time.time()
    
    from skill_engine.compiler import ThesisToCodeStrategyCompiler
    compiler = ThesisToCodeStrategyCompiler()
    
    try:
        spec = compiler.compile(thesis, assets, risk, backtest_range)
        elapsed = time.time() - start
        
        # Save strategy
        with open("strategy.json", "w") as f:
            f.write(spec.model_dump_json(indent=2))
        
        print(f"\n{'='*70}")
        print(f"COMPILATION RESULT ({elapsed:.1f}s)")
        print(f"{'='*70}")
        print(f"Strategy: {spec.strategy_name}")
        print(f"Regime: {spec.regime_classified}")
        print(f"Assets: {spec.target_assets}")
        print(f"Allocations: {[(a.symbol, f'{a.weight*100:.0f}%') for a in spec.allocation_weights]}")
        print(f"Stop Loss: {spec.stop_loss_pct*100:.1f}%")
        print(f"Take Profit: {spec.take_profit_pct*100:.1f}%")
        print(f"Entry Rules: {len(spec.vectorbt_signals.entry_rules)}")
        print(f"Exit Rules: {len(spec.vectorbt_signals.exit_rules)}")
        if spec.skill_hub_intelligence_summary:
            print(f"\nSkill Hub Intelligence:")
            print(f"  {spec.skill_hub_intelligence_summary[:300]}")
        
        # Run backtest
        print(f"\n{'='*70}")
        print("RUNNING BACKTEST...")
        print(f"{'='*70}")
        from backtest_sandbox.engine import run_backtest
        run_backtest()
        
        # Record strategy version (publisher)
        print(f"\n{'='*70}")
        print("RECORDING VERSION & PUBLISHING...")
        print(f"{'='*70}")
        from skill_engine.publisher import record_strategy_version, publish_deliverables
        version_entry = record_strategy_version(spec.model_dump())
        print(f"Version: v{version_entry.get('version', '?')}")
        print(f"Hash: {version_entry.get('hash', '?')}")
        if "diff_from_previous" in version_entry:
            diff = version_entry["diff_from_previous"]
            print(f"Changes from previous: {diff.get('total_changes', 0)} modifications")
            for change in diff.get("changes", []):
                print(f"  - {change['type']}: {change.get('field', '')}")
        
        # Publish deliverables (Greenfield + IPFS — will gracefully skip if keys not set)
        storage_urls = publish_deliverables(spec.model_dump())
        if storage_urls.get("greenfield") or storage_urls.get("ipfs"):
            print(f"Published to: {json.dumps(storage_urls)}")
        
        print(f"\n{'='*70}")
        print(f"EXAMPLE '{label}' COMPLETE — All deliverables generated")
        print(f"{'='*70}")
        
        return spec
        
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        return None

def main():
    print("="*70)
    print("ALPHA COMPILER — END-TO-END VALIDATION")
    print("Core MCP (12 tools) + Skill Hub MCP (10 skills) + VectorBT + Publisher")
    print("="*70)
    
    # Example 1: Bearish defensive rotation
    spec1 = run_example(
        thesis="Rotate into defensive positions during high fear regimes, overweight stablecoins when market sentiment turns bearish",
        assets=["CAKE", "FLOKI"],
        risk="medium",
        backtest_range="30d",
        label="Bearish Defensive Rotation"
    )
    
    if spec1:
        print("\n\n✅ E2E TEST PASSED")
        print(f"  Deliverables: strategy.json, backtest_report.html, strategy_changelog.json")
    else:
        print("\n\n❌ E2E TEST FAILED")
        sys.exit(1)

if __name__ == "__main__":
    main()
