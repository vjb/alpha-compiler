"""
Strategy Publisher — Versioning, Diffing, and IPFS Publishing.

Tracks strategy iterations with structured diffs and optional IPFS pinning.
"""
import os
import json
import time
import hashlib
from typing import Dict, Any, Optional
from datetime import datetime


def compute_strategy_hash(strategy: dict) -> str:
    """Compute a deterministic hash of a strategy spec for versioning."""
    # Normalize by sorting keys and removing volatile fields
    stable = {k: v for k, v in strategy.items() if k not in ("compilation_timestamp",)}
    serialized = json.dumps(stable, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(serialized.encode()).hexdigest()[:16]


def diff_strategies(old: dict, new: dict) -> dict:
    """
    Produce a structured diff between two strategy specs.
    Returns a dict describing what changed between versions.
    """
    diff = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "old_hash": compute_strategy_hash(old),
        "new_hash": compute_strategy_hash(new),
        "changes": []
    }
    
    # Compare regime
    if old.get("regime_classified") != new.get("regime_classified"):
        diff["changes"].append({
            "field": "regime_classified",
            "type": "regime_shift",
            "old": old.get("regime_classified"),
            "new": new.get("regime_classified")
        })
    
    # Compare target assets
    old_assets = set(old.get("target_assets", []))
    new_assets = set(new.get("target_assets", []))
    if old_assets != new_assets:
        diff["changes"].append({
            "field": "target_assets",
            "type": "asset_change",
            "added": list(new_assets - old_assets),
            "removed": list(old_assets - new_assets)
        })
    
    # Compare allocation weights
    old_weights = {w["symbol"]: w["weight"] for w in old.get("allocation_weights", [])}
    new_weights = {w["symbol"]: w["weight"] for w in new.get("allocation_weights", [])}
    weight_changes = []
    all_symbols = set(list(old_weights.keys()) + list(new_weights.keys()))
    for sym in all_symbols:
        old_w = old_weights.get(sym, 0.0)
        new_w = new_weights.get(sym, 0.0)
        if abs(old_w - new_w) > 0.001:
            weight_changes.append({
                "symbol": sym,
                "old_weight": round(old_w, 4),
                "new_weight": round(new_w, 4),
                "delta": round(new_w - old_w, 4)
            })
    if weight_changes:
        diff["changes"].append({
            "field": "allocation_weights",
            "type": "weight_rebalance",
            "details": weight_changes
        })
    
    # Compare stop loss / take profit
    for field in ("stop_loss_pct", "take_profit_pct"):
        old_val = old.get(field, 0)
        new_val = new.get(field, 0)
        if abs(old_val - new_val) > 0.0001:
            diff["changes"].append({
                "field": field,
                "type": "risk_parameter_change",
                "old": old_val,
                "new": new_val
            })
    
    # Compare entry/exit rule counts
    old_entry_count = len(old.get("vectorbt_signals", {}).get("entry_rules", []))
    new_entry_count = len(new.get("vectorbt_signals", {}).get("entry_rules", []))
    old_exit_count = len(old.get("vectorbt_signals", {}).get("exit_rules", []))
    new_exit_count = len(new.get("vectorbt_signals", {}).get("exit_rules", []))
    
    if old_entry_count != new_entry_count or old_exit_count != new_exit_count:
        diff["changes"].append({
            "field": "vectorbt_signals",
            "type": "rule_change",
            "old_entry_rules": old_entry_count,
            "new_entry_rules": new_entry_count,
            "old_exit_rules": old_exit_count,
            "new_exit_rules": new_exit_count
        })
    
    # Compare intelligence summaries
    old_intel = old.get("skill_hub_intelligence_summary", "")
    new_intel = new.get("skill_hub_intelligence_summary", "")
    if old_intel != new_intel and new_intel:
        diff["changes"].append({
            "field": "skill_hub_intelligence_summary",
            "type": "intelligence_update",
            "new_summary": new_intel[:300]
        })
    
    diff["total_changes"] = len(diff["changes"])
    return diff


def load_changelog(path: str = "strategy_changelog.json") -> list:
    """Load existing changelog or return empty list."""
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return []


def save_changelog(entries: list, path: str = "strategy_changelog.json"):
    """Save changelog to disk."""
    with open(path, "w") as f:
        json.dump(entries, f, indent=2)


def record_strategy_version(new_strategy: dict, changelog_path: str = "strategy_changelog.json"):
    """
    Record a new strategy version in the changelog.
    If a previous version exists, compute and store the diff.
    """
    changelog = load_changelog(changelog_path)
    
    new_hash = compute_strategy_hash(new_strategy)
    version_number = len(changelog) + 1
    
    entry = {
        "version": version_number,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "hash": new_hash,
        "strategy_name": new_strategy.get("strategy_name", "Unknown"),
        "regime": new_strategy.get("regime_classified", "unknown"),
        "assets": new_strategy.get("target_assets", []),
        "intelligence_summary": new_strategy.get("skill_hub_intelligence_summary", "")[:200],
    }
    
    # Compute diff against previous version
    if changelog:
        last_entry = changelog[-1]
        # Load the previous strategy if available
        prev_strategy_path = f"strategy_v{version_number - 1}.json"
        if os.path.exists(prev_strategy_path):
            try:
                with open(prev_strategy_path, "r") as f:
                    old_strategy = json.load(f)
                diff = diff_strategies(old_strategy, new_strategy)
                entry["diff_from_previous"] = diff
            except Exception:
                entry["diff_from_previous"] = {"error": "Could not load previous strategy"}
        elif os.path.exists("strategy_v1.json"):
            try:
                with open("strategy_v1.json", "r") as f:
                    old_strategy = json.load(f)
                diff = diff_strategies(old_strategy, new_strategy)
                entry["diff_from_previous"] = diff
            except Exception:
                pass
    
    changelog.append(entry)
    save_changelog(changelog, changelog_path)
    
    print(f"[Publisher] Recorded strategy v{version_number} (hash: {new_hash})")
    if "diff_from_previous" in entry:
        diff = entry["diff_from_previous"]
        print(f"[Publisher]   Changes from previous: {diff.get('total_changes', 0)} modifications")
    
    return entry


def publish_to_ipfs(strategy: dict, report_html_path: str = "backtest_report.html") -> Optional[str]:
    """
    Publish strategy and report to IPFS via Pinata.
    Requires PINATA_API_KEY and PINATA_SECRET_KEY environment variables.
    Returns the IPFS CID or None if publishing fails.
    """
    api_key = os.environ.get("PINATA_API_KEY")
    secret_key = os.environ.get("PINATA_SECRET_KEY")
    
    if not api_key or not secret_key:
        print("[Publisher] IPFS publishing skipped: PINATA_API_KEY/PINATA_SECRET_KEY not set.")
        print("[Publisher] To enable IPFS publishing, sign up at https://pinata.cloud and add keys to .env")
        return None
    
    import requests
    
    # Create a combined publication payload
    publication = {
        "metadata": {
            "name": strategy.get("strategy_name", "BEP-20 Strategy"),
            "version": compute_strategy_hash(strategy),
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "track": "Track 2: Strategy Skills",
            "hackathon": "BNB Hack: AI Trading Agent Edition 2026"
        },
        "strategy": strategy,
    }
    
    try:
        url = "https://api.pinata.cloud/pinning/pinJSONToIPFS"
        headers = {
            "pinata_api_key": api_key,
            "pinata_secret_api_key": secret_key,
            "Content-Type": "application/json"
        }
        payload = {
            "pinataContent": publication,
            "pinataMetadata": {
                "name": f"regime-rotator-{compute_strategy_hash(strategy)}"
            }
        }
        
        res = requests.post(url, json=payload, headers=headers, timeout=30)
        res.raise_for_status()
        cid = res.json().get("IpfsHash")
        print(f"[Publisher] Published to IPFS! CID: {cid}")
        print(f"[Publisher] View at: https://gateway.pinata.cloud/ipfs/{cid}")
        return cid
    except Exception as e:
        print(f"[Publisher] IPFS publishing failed: {e}")
        return None


if __name__ == "__main__":
    # Demo: Load current strategy and record version
    if os.path.exists("strategy_v1.json"):
        with open("strategy_v1.json", "r") as f:
            strategy = json.load(f)
        
        entry = record_strategy_version(strategy)
        print(json.dumps(entry, indent=2))
        
        # Try IPFS publish
        cid = publish_to_ipfs(strategy)
        if cid:
            print(f"IPFS CID: {cid}")
    else:
        print("No strategy_v1.json found. Run the compiler first.")
