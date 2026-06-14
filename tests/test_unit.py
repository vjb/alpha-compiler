"""
Unit tests for Alpha Compiler components.
Run with: python -m pytest tests/ -v
"""
import pytest
import json
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestStrategySpecValidation:
    """Test the Pydantic StrategySpec model validation."""
    
    def test_valid_spec(self):
        from skill_engine.compiler import StrategySpec, SignalRule, VectorBTSignals, AssetAllocation
        spec = StrategySpec(
            strategy_name="Test Strategy",
            regime_classified="bullish",
            target_assets=["CAKE", "BNB"],
            allocation_weights=[
                AssetAllocation(symbol="CAKE", weight=0.6),
                AssetAllocation(symbol="BNB", weight=0.4),
            ],
            stop_loss_pct=0.05,
            take_profit_pct=0.10,
            vectorbt_signals=VectorBTSignals(
                entry_rules=[SignalRule(indicator="rsi", operator="<", threshold=30)],
                exit_rules=[SignalRule(indicator="rsi", operator=">", threshold=70)],
            ),
        )
        assert spec.strategy_name == "Test Strategy"
        assert spec.regime_classified == "bullish"
        assert len(spec.target_assets) == 2
    
    def test_invalid_asset_rejected(self):
        from skill_engine.compiler import StrategySpec, SignalRule, VectorBTSignals, AssetAllocation
        with pytest.raises(ValueError, match="not in the allowed BEP-20"):
            StrategySpec(
                strategy_name="Bad Strategy",
                regime_classified="bullish",
                target_assets=["INVALIDTOKEN"],
                allocation_weights=[AssetAllocation(symbol="INVALIDTOKEN", weight=1.0)],
                stop_loss_pct=0.05,
                take_profit_pct=0.10,
                vectorbt_signals=VectorBTSignals(
                    entry_rules=[SignalRule(indicator="rsi", operator="<", threshold=30)],
                    exit_rules=[SignalRule(indicator="rsi", operator=">", threshold=70)],
                ),
            )
    
    def test_asset_normalization(self):
        from skill_engine.compiler import StrategySpec, SignalRule, VectorBTSignals, AssetAllocation
        spec = StrategySpec(
            strategy_name="Case Test",
            regime_classified="sideways",
            target_assets=["cake", "bnb"],  # lowercase input
            allocation_weights=[
                AssetAllocation(symbol="CAKE", weight=0.5),
                AssetAllocation(symbol="BNB", weight=0.5),
            ],
            stop_loss_pct=0.03,
            take_profit_pct=0.06,
            vectorbt_signals=VectorBTSignals(
                entry_rules=[SignalRule(indicator="rsi", operator="<", threshold=40)],
                exit_rules=[SignalRule(indicator="rsi", operator=">", threshold=60)],
            ),
        )
        assert spec.target_assets == ["CAKE", "BNB"]  # Normalized to uppercase


class TestThesisValidation:
    """Test the thesis text validator."""
    
    def test_clean_thesis_passes(self):
        from skill_engine.compiler import validate_thesis_text
        validate_thesis_text("Rotate into stablecoins when fear is extreme")
    
    def test_btc_mention_rejected(self):
        from skill_engine.compiler import validate_thesis_text
        with pytest.raises(ValueError, match="disallowed asset reference"):
            validate_thesis_text("Buy BTC when RSI is oversold")
    
    def test_solana_mention_rejected(self):
        from skill_engine.compiler import validate_thesis_text
        with pytest.raises(ValueError, match="disallowed asset reference"):
            validate_thesis_text("Long solana ecosystem tokens")
    
    def test_allowed_bep20_passes(self):
        from skill_engine.compiler import validate_thesis_text
        # "cake" and "floki" should NOT be in the disallowed list
        validate_thesis_text("Buy CAKE and FLOKI when market sentiment is bullish")


class TestDynamicSlippage:
    """Test the dynamic AMM slippage calculator."""
    
    def test_base_fee_included(self):
        from backtest_sandbox.engine import compute_dynamic_slippage
        fee = compute_dynamic_slippage(1000.0, 1000000.0, 0.02)
        assert fee >= 0.0025  # PancakeSwap base fee
    
    def test_illiquid_asset_higher_slippage(self):
        from backtest_sandbox.engine import compute_dynamic_slippage
        liquid = compute_dynamic_slippage(1000.0, 10000000.0, 0.02)
        illiquid = compute_dynamic_slippage(1000.0, 1000.0, 0.02)
        assert illiquid > liquid
    
    def test_zero_volume_fallback(self):
        from backtest_sandbox.engine import compute_dynamic_slippage
        fee = compute_dynamic_slippage(1000.0, 0.0, 0.02)
        assert fee >= 0.01  # Should use high fallback
    
    def test_high_volatility_wider_spread(self):
        from backtest_sandbox.engine import compute_dynamic_slippage
        low_vol = compute_dynamic_slippage(1000.0, 1000000.0, 0.01)
        high_vol = compute_dynamic_slippage(1000.0, 1000000.0, 0.10)
        assert high_vol > low_vol


class TestSkillHubHelpers:
    """Test the Skill Hub intelligence extraction helpers."""
    
    def test_extract_regime_bullish(self):
        from skill_engine.skill_hub_client import extract_regime_from_macro
        result = extract_regime_from_macro({
            "data": {
                "decision_report": {"conclusion": "Risk-on regime confirmed"},
                "action_guidance": {"bias": "risk_on"}
            }
        })
        assert result == "bullish"
    
    def test_extract_regime_bearish(self):
        from skill_engine.skill_hub_client import extract_regime_from_macro
        result = extract_regime_from_macro({
            "data": {
                "decision_report": {"conclusion": "Defensive positioning recommended"},
                "action_guidance": {"bias": "avoid_leverage_chasing"}
            }
        })
        assert result == "bearish"
    
    def test_extract_regime_sideways_default(self):
        from skill_engine.skill_hub_client import extract_regime_from_macro
        result = extract_regime_from_macro({
            "data": {
                "decision_report": {"conclusion": "Mixed signals across lanes"},
                "action_guidance": {"bias": "balanced_wait"}
            }
        })
        assert result == "sideways"
    
    def test_extract_sentiment_metrics(self):
        from skill_engine.skill_hub_client import extract_sentiment_metrics
        result = extract_sentiment_metrics({
            "data": {
                "report": {
                    "sentiment_regime": "neutral_chop",
                    "inflection_direction": "mixed",
                    "metrics": {
                        "fear_greed_value": 25.0,
                        "fear_greed_label": "fear",
                        "fear_greed_7d_delta": -20.0,
                        "average_funding_bps_7d": 30.0,
                    }
                }
            }
        })
        assert result["sentiment_regime"] == "neutral_chop"
        assert result["fear_greed_value"] == 25.0
        assert result["avg_funding_bps"] == 30.0
    
    def test_extract_kol_summary(self):
        from skill_engine.skill_hub_client import extract_kol_sentiment_summary
        result = extract_kol_sentiment_summary({
            "data": {
                "status": "ok",
                "confidence": "high",
                "decision_report": {
                    "conclusion": "CAKE social discussion is mixed",
                    "analysis": "Thin KOL coverage"
                },
                "action_guidance": {
                    "bias": "use_as_context",
                    "risk_note": "Low signal density"
                }
            }
        })
        assert result["status"] == "ok"
        assert result["confidence"] == "high"
        assert result["bias"] == "use_as_context"


class TestStrategyPublisher:
    """Test strategy versioning and diffing."""
    
    def test_compute_hash_deterministic(self):
        from skill_engine.publisher import compute_strategy_hash
        strategy = {"strategy_name": "test", "regime_classified": "bullish"}
        h1 = compute_strategy_hash(strategy)
        h2 = compute_strategy_hash(strategy)
        assert h1 == h2
    
    def test_diff_detects_regime_change(self):
        from skill_engine.publisher import diff_strategies
        old = {"regime_classified": "bullish", "target_assets": ["CAKE"]}
        new = {"regime_classified": "bearish", "target_assets": ["CAKE"]}
        diff = diff_strategies(old, new)
        regime_changes = [c for c in diff["changes"] if c["field"] == "regime_classified"]
        assert len(regime_changes) == 1
        assert regime_changes[0]["old"] == "bullish"
        assert regime_changes[0]["new"] == "bearish"
    
    def test_diff_detects_asset_change(self):
        from skill_engine.publisher import diff_strategies
        old = {"regime_classified": "bullish", "target_assets": ["CAKE"]}
        new = {"regime_classified": "bullish", "target_assets": ["CAKE", "USDT"]}
        diff = diff_strategies(old, new)
        asset_changes = [c for c in diff["changes"] if c["field"] == "target_assets"]
        assert len(asset_changes) == 1
        assert "USDT" in asset_changes[0]["added"]


class TestAllowedTokens:
    """Test the allowed tokens list integrity."""
    
    def test_no_duplicates(self):
        from skill_engine.constants import ALLOWED_BEP20_TOKENS
        assert len(ALLOWED_BEP20_TOKENS) == len(set(t.upper() for t in ALLOWED_BEP20_TOKENS)), \
            "Duplicate tokens found in ALLOWED_BEP20_TOKENS"
    
    def test_bnb_included(self):
        from skill_engine.constants import ALLOWED_BEP20_TOKENS
        assert "BNB" in ALLOWED_BEP20_TOKENS
    
    def test_usdt_included(self):
        from skill_engine.constants import ALLOWED_BEP20_TOKENS
        assert "USDT" in ALLOWED_BEP20_TOKENS
    
    def test_cake_included(self):
        from skill_engine.constants import ALLOWED_BEP20_TOKENS
        assert "CAKE" in ALLOWED_BEP20_TOKENS


class TestIndicatorComputation:
    """Test technical indicator calculations."""
    
    def test_rsi_range(self):
        import pandas as pd
        from backtest_sandbox.engine import compute_rsi
        prices = pd.Series([100 + i * 0.5 for i in range(30)])
        rsi = compute_rsi(prices, 14)
        assert (rsi >= 0).all() and (rsi <= 100).all()
    
    def test_macd_returns_series(self):
        import pandas as pd
        from backtest_sandbox.engine import compute_macd
        prices = pd.Series([100 + i * 0.1 for i in range(30)])
        macd = compute_macd(prices, 12, 26)
        assert len(macd) == 30
    
    def test_ema_smooths(self):
        import pandas as pd
        from backtest_sandbox.engine import compute_ema
        prices = pd.Series([100, 110, 90, 105, 95, 100, 102, 98, 101, 99])
        ema = compute_ema(prices, 3)
        # EMA should be smoother than raw prices
        assert ema.std() < prices.std()
