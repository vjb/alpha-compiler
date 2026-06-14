"""
Unit tests for Alpha Compiler — 26 focused tests across all modules.
Run: python -m pytest tests/ -v
"""
import os
import sys
import json
import time
import pytest

# Ensure project root in path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ═══════════════════════════════════════════════════════════════
# SKILL HUB CLIENT TESTS (5 tests)
# ═══════════════════════════════════════════════════════════════

class TestSkillHubClient:
    """Test the CMC Skill Hub MCP client."""
    
    def test_client_initializes(self):
        from skill_engine.skill_hub_client import SkillHubClient
        client = SkillHubClient()
        client.initialize()
        assert client._initialized is True
    
    def test_find_skill_returns_candidates(self):
        from skill_engine.skill_hub_client import SkillHubClient
        client = SkillHubClient()
        client.initialize()
        candidates = client.find_skill("btc price")
        assert len(candidates) > 0
        assert "uniqueName" in candidates[0]
    
    def test_sentiment_regime_returns_metrics(self):
        from skill_engine.skill_hub_client import SkillHubClient, extract_sentiment_metrics
        client = SkillHubClient()
        client.initialize()
        result = client.get_sentiment_regime("7d")
        metrics = extract_sentiment_metrics(result)
        assert "fear_greed_value" in metrics
        assert isinstance(metrics["fear_greed_value"], (int, float))
    
    def test_macro_regime_extraction(self):
        from skill_engine.skill_hub_client import extract_regime_from_macro
        # Test bullish extraction
        assert extract_regime_from_macro({"data": {"action_guidance": {"bias": "risk_on"}}}) == "bullish"
        # Test bearish extraction
        assert extract_regime_from_macro({"data": {"action_guidance": {"bias": "defensive"}}}) == "bearish"
        # Test sideways fallback
        assert extract_regime_from_macro({"data": {"action_guidance": {"bias": "neutral"}}}) == "sideways"
    
    def test_kol_summary_extraction(self):
        from skill_engine.skill_hub_client import extract_kol_sentiment_summary
        kol_result = {
            "data": {
                "status": "ok",
                "confidence": "high",
                "decision_report": {"conclusion": "Test conclusion"},
                "action_guidance": {"bias": "use_as_context", "risk_note": "Test risk"}
            }
        }
        summary = extract_kol_sentiment_summary(kol_result)
        assert summary["status"] == "ok"
        assert summary["confidence"] == "high"
        assert summary["bias"] == "use_as_context"


# ═══════════════════════════════════════════════════════════════
# CORE MCP CLIENT TESTS (3 tests)
# ═══════════════════════════════════════════════════════════════

class TestCoreMCPClient:
    """Test the CMC Core MCP client."""
    
    def test_client_initializes(self):
        from skill_engine.cmc_mcp_client import CoreMCPClient
        client = CoreMCPClient()
        client.initialize()
        assert client._initialized is True

    def test_summarize_core_empty(self):
        from skill_engine.cmc_mcp_client import summarize_core_intelligence_for_llm
        result = summarize_core_intelligence_for_llm({"per_asset": {}})
        assert isinstance(result, str)
    
    def test_core_endpoint_configured(self):
        from skill_engine.cmc_mcp_client import CoreMCPClient
        client = CoreMCPClient()
        assert "mcp.coinmarketcap.com/mcp" in client.endpoint


# ═══════════════════════════════════════════════════════════════
# COMPILER TESTS (5 tests)
# ═══════════════════════════════════════════════════════════════

class TestCompiler:
    """Test the strategy compiler."""
    
    def test_validate_thesis_rejects_btc(self):
        from skill_engine.compiler import validate_thesis_text
        with pytest.raises(ValueError, match="disallowed"):
            validate_thesis_text("I want to buy BTC and hold")
    
    def test_validate_thesis_accepts_bnb(self):
        from skill_engine.compiler import validate_thesis_text
        # BNB is an allowed BEP-20 token, should not raise
        validate_thesis_text("I want to rotate BNB ecosystem tokens based on momentum")
    
    def test_signal_rule_validates(self):
        from skill_engine.compiler import SignalRule
        rule = SignalRule(indicator="rsi", operator=">", threshold=70.0)
        assert rule.indicator == "rsi"
        assert rule.threshold == 70.0
    
    def test_signal_rule_new_indicators(self):
        from skill_engine.compiler import SignalRule
        rule = SignalRule(indicator="kol_sentiment_bias", operator=">", threshold=0.5)
        assert rule.indicator == "kol_sentiment_bias"
        
        rule2 = SignalRule(indicator="funding_rate_bps", operator="<", threshold=50.0)
        assert rule2.indicator == "funding_rate_bps"
    
    def test_strategy_spec_validates_assets(self):
        from skill_engine.compiler import StrategySpec
        with pytest.raises(ValueError):
            StrategySpec(
                strategy_name="Test",
                regime_classified="bullish",
                target_assets=["INVALID_TOKEN"],
                allocation_weights=[],
                stop_loss_pct=0.05,
                take_profit_pct=0.10,
                vectorbt_signals={"entry_rules": [], "exit_rules": []}
            )


# ═══════════════════════════════════════════════════════════════
# CONSTANTS TESTS (3 tests)
# ═══════════════════════════════════════════════════════════════

class TestConstants:
    """Test the allowed BEP-20 token list."""
    
    def test_allowed_tokens_count(self):
        from skill_engine.constants import ALLOWED_BEP20_TOKENS
        assert len(ALLOWED_BEP20_TOKENS) >= 100
    
    def test_key_tokens_present(self):
        from skill_engine.constants import ALLOWED_BEP20_TOKENS
        key_tokens = ["BNB", "CAKE", "USDT", "FLOKI"]
        for token in key_tokens:
            assert token in ALLOWED_BEP20_TOKENS, f"{token} should be in allowed list"
    
    def test_no_non_bsc_tokens(self):
        from skill_engine.constants import ALLOWED_BEP20_TOKENS
        # Only check tokens that are definitively NOT bridged to BSC
        non_bsc = ["BTC", "SOL"]
        for token in non_bsc:
            assert token not in ALLOWED_BEP20_TOKENS, f"{token} should NOT be in BEP-20 list"


# ═══════════════════════════════════════════════════════════════
# PUBLISHER TESTS (5 tests)
# ═══════════════════════════════════════════════════════════════

class TestPublisher:
    """Test strategy versioning and diffing."""
    
    def test_strategy_hash_deterministic(self):
        from skill_engine.publisher import compute_strategy_hash
        strategy = {"strategy_name": "Test", "regime_classified": "bullish", "target_assets": ["BNB"]}
        h1 = compute_strategy_hash(strategy)
        h2 = compute_strategy_hash(strategy)
        assert h1 == h2
    
    def test_strategy_hash_changes_with_content(self):
        from skill_engine.publisher import compute_strategy_hash
        s1 = {"strategy_name": "Test", "regime_classified": "bullish"}
        s2 = {"strategy_name": "Test", "regime_classified": "bearish"}
        assert compute_strategy_hash(s1) != compute_strategy_hash(s2)
    
    def test_diff_detects_regime_shift(self):
        from skill_engine.publisher import diff_strategies
        old = {"regime_classified": "bullish", "target_assets": [], "allocation_weights": [], "vectorbt_signals": {"entry_rules": [], "exit_rules": []}}
        new = {"regime_classified": "bearish", "target_assets": [], "allocation_weights": [], "vectorbt_signals": {"entry_rules": [], "exit_rules": []}}
        diff = diff_strategies(old, new)
        assert diff["total_changes"] >= 1
        regime_changes = [c for c in diff["changes"] if c["type"] == "regime_shift"]
        assert len(regime_changes) == 1
        assert regime_changes[0]["old"] == "bullish"
        assert regime_changes[0]["new"] == "bearish"
    
    def test_diff_detects_asset_change(self):
        from skill_engine.publisher import diff_strategies
        old = {"regime_classified": "bullish", "target_assets": ["BNB"], "allocation_weights": [], "vectorbt_signals": {"entry_rules": [], "exit_rules": []}}
        new = {"regime_classified": "bullish", "target_assets": ["BNB", "CAKE"], "allocation_weights": [], "vectorbt_signals": {"entry_rules": [], "exit_rules": []}}
        diff = diff_strategies(old, new)
        asset_changes = [c for c in diff["changes"] if c["type"] == "asset_change"]
        assert len(asset_changes) == 1
        assert "CAKE" in asset_changes[0]["added"]
    
    def test_diff_detects_weight_rebalance(self):
        from skill_engine.publisher import diff_strategies
        old = {"regime_classified": "bullish", "target_assets": ["BNB"], "allocation_weights": [{"symbol": "BNB", "weight": 1.0}], "vectorbt_signals": {"entry_rules": [], "exit_rules": []}}
        new = {"regime_classified": "bullish", "target_assets": ["BNB"], "allocation_weights": [{"symbol": "BNB", "weight": 0.5}], "vectorbt_signals": {"entry_rules": [], "exit_rules": []}}
        diff = diff_strategies(old, new)
        weight_changes = [c for c in diff["changes"] if c["type"] == "weight_rebalance"]
        assert len(weight_changes) == 1


# ═══════════════════════════════════════════════════════════════
# ENGINE TESTS (3 tests)
# ═══════════════════════════════════════════════════════════════

class TestEngine:
    """Test backtest engine utility functions."""
    
    def test_dynamic_slippage_low_volume(self):
        from backtest_sandbox.engine import compute_dynamic_slippage
        # Very low volume should give high slippage
        fee = compute_dynamic_slippage(1000, 100, 0.02)
        assert fee > 0.01  # Should be over 1%
    
    def test_dynamic_slippage_high_volume(self):
        from backtest_sandbox.engine import compute_dynamic_slippage
        # Very high volume should give low slippage
        fee = compute_dynamic_slippage(1000, 1_000_000_000, 0.001)
        assert fee < 0.01  # Should be under 1%
    
    def test_dynamic_slippage_includes_base_fee(self):
        from backtest_sandbox.engine import compute_dynamic_slippage
        fee = compute_dynamic_slippage(1000, 1_000_000_000, 0.001)
        assert fee >= 0.0025  # PancakeSwap base fee minimum


# ═══════════════════════════════════════════════════════════════
# SERVER TESTS (2 tests)
# ═══════════════════════════════════════════════════════════════

class TestServer:
    """Test the FastAPI server models."""
    
    def test_compilation_request_defaults(self):
        from skill_engine.server import CompilationRequest
        req = CompilationRequest(
            investment_thesis="Test thesis",
            target_assets=["BNB"]
        )
        assert req.risk_tolerance == "medium"
        assert req.backtest_range == "30d"
        assert req.job_id is None
    
    def test_compilation_request_with_job(self):
        from skill_engine.server import CompilationRequest
        req = CompilationRequest(
            investment_thesis="Test thesis",
            target_assets=["BNB", "CAKE"],
            risk_tolerance="high",
            job_id=42
        )
        assert req.job_id == 42
        assert req.risk_tolerance == "high"


# ═══════════════════════════════════════════════════════════════
# MONITOR TESTS (3 tests)
# ═══════════════════════════════════════════════════════════════

class TestMonitor:
    """Test the regime monitor shift detection."""
    
    def test_detect_shift_first_run(self):
        from skill_engine.monitor import detect_regime_shift
        current = {"regime": "bearish", "fear_greed": 20.0, "sentiment_regime": "fear"}
        result = detect_regime_shift(current, None)
        assert result["shifted"] is False
        assert result["current_regime"] == "bearish"
        assert result["previous_regime"] is None
    
    def test_detect_shift_regime_changed(self):
        from skill_engine.monitor import detect_regime_shift
        current = {"regime": "bearish", "fear_greed": 20.0, "sentiment_regime": "fear"}
        previous = {"regime": "bullish", "fear_greed": 70.0, "sentiment_regime": "greed"}
        result = detect_regime_shift(current, previous)
        assert result["shifted"] is True
        assert result["current_regime"] == "bearish"
        assert result["previous_regime"] == "bullish"
    
    def test_detect_shift_no_change(self):
        from skill_engine.monitor import detect_regime_shift
        current = {"regime": "sideways", "fear_greed": 48.0, "sentiment_regime": "neutral"}
        previous = {"regime": "sideways", "fear_greed": 50.0, "sentiment_regime": "neutral"}
        result = detect_regime_shift(current, previous)
        assert result["shifted"] is False
        assert result["significant_fg_move"] is False

