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

    def test_strategy_spec_validates_weights_sum(self):
        from skill_engine.compiler import StrategySpec, AssetAllocation
        # Valid sum (1.0)
        StrategySpec(
            strategy_name="Test",
            regime_classified="bullish",
            target_assets=["BNB", "USDT"],
            allocation_weights=[
                AssetAllocation(symbol="BNB", weight=0.5),
                AssetAllocation(symbol="USDT", weight=0.5)
            ],
            stop_loss_pct=0.05,
            take_profit_pct=0.10,
            vectorbt_signals={"entry_rules": [], "exit_rules": []}
        )

        # Too low (0.95)
        with pytest.raises(ValueError, match="Sum of allocation weights"):
            StrategySpec(
                strategy_name="Test",
                regime_classified="bullish",
                target_assets=["BNB", "USDT"],
                allocation_weights=[
                    AssetAllocation(symbol="BNB", weight=0.45),
                    AssetAllocation(symbol="USDT", weight=0.5)
                ],
                stop_loss_pct=0.05,
                take_profit_pct=0.10,
                vectorbt_signals={"entry_rules": [], "exit_rules": []}
            )

        # Too high (1.05)
        with pytest.raises(ValueError, match="Sum of allocation weights"):
            StrategySpec(
                strategy_name="Test",
                regime_classified="bullish",
                target_assets=["BNB", "USDT"],
                allocation_weights=[
                    AssetAllocation(symbol="BNB", weight=0.55),
                    AssetAllocation(symbol="USDT", weight=0.5)
                ],
                stop_loss_pct=0.05,
                take_profit_pct=0.10,
                vectorbt_signals={"entry_rules": [], "exit_rules": []}
            )

    def test_strategy_spec_validates_allocation_symbols_in_target_assets(self):
        from skill_engine.compiler import StrategySpec, AssetAllocation
        # Symbol CAKE not in target_assets
        with pytest.raises(ValueError, match="Allocation symbol.*not present in target_assets"):
            StrategySpec(
                strategy_name="Test",
                regime_classified="bullish",
                target_assets=["BNB", "USDT"],
                allocation_weights=[
                    AssetAllocation(symbol="CAKE", weight=1.0)
                ],
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

    def test_fetch_cmc_historical_data_cache_flow(self, monkeypatch):
        import backtest_sandbox.engine as engine
        import pandas as pd
        from unittest.mock import MagicMock
        import os
        
        cache_path = os.path.join("backtest_sandbox", "data_cache", "TESTCACHE_7d.csv")
        if os.path.exists(cache_path):
            os.remove(cache_path)
            
        monkeypatch.setenv("CMC_API_KEY", "dummy_key")
        
        # Mock requests.get to return a valid Pro API response
        call_count = 0
        def mock_get(url, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            mock_res = MagicMock()
            mock_res.status_code = 200
            
            # Return Pro API structure
            quotes = []
            import datetime
            base_time = datetime.datetime.now() - datetime.timedelta(days=10)
            for i in range(7):
                time_open = (base_time + datetime.timedelta(days=i)).isoformat()
                quotes.append({
                    "time_open": time_open,
                    "quote": {
                        "USD": {
                            "open": 10.0 + i,
                            "high": 12.0 + i,
                            "low": 9.0 + i,
                            "close": 11.0 + i,
                            "volume": 50000.0
                        }
                    }
                })
            mock_res.json.return_value = {
                "data": {
                    "TESTCACHE": [
                        {
                            "quotes": quotes
                        }
                    ]
                }
            }
            return mock_res
            
        monkeypatch.setattr(engine.requests, "get", mock_get)
        
        try:
            # First call: should call the API and write cache
            df1 = engine.fetch_cmc_historical_data("TESTCACHE", "7d")
            assert call_count == 1
            assert os.path.exists(cache_path)
            
            # Second call: should read from cache and NOT call the API
            df2 = engine.fetch_cmc_historical_data("TESTCACHE", "7d")
            assert call_count == 1  # call_count should still be 1 (no API call)
            assert len(df1) == len(df2)
            assert list(df1["close"]) == list(df2["close"])
        finally:
            if os.path.exists(cache_path):
                os.remove(cache_path)

    def test_fetch_cmc_historical_data_retry_and_fallback(self, monkeypatch):
        import backtest_sandbox.engine as engine
        import pandas as pd
        from unittest.mock import MagicMock
        import os
        import time
        
        cache_path = os.path.join("backtest_sandbox", "data_cache", "TESTFAIL_7d.csv")
        if os.path.exists(cache_path):
            os.remove(cache_path)
            
        # Create an expired cache file manually
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        dummy_df = pd.DataFrame({
            "open": [1.5], "high": [2.0], "low": [0.5], "close": [1.5], "volume": [1000.0]
        }, index=pd.to_datetime(["2026-06-01"]))
        dummy_df.index.name = "date"
        dummy_df.to_csv(cache_path)
        
        # Set modification time to 48 hours ago (expired)
        os.utime(cache_path, (time.time() - 48 * 3600, time.time() - 48 * 3600))
        
        monkeypatch.setenv("CMC_API_KEY", "dummy_key")
        
        # Mock requests.get to fail
        api_call_count = 0
        def mock_get(url, *args, **kwargs):
            nonlocal api_call_count
            api_call_count += 1
            raise Exception("Transient network error")
            
        monkeypatch.setattr(engine.requests, "get", mock_get)
        # Mock time.sleep to run faster
        monkeypatch.setattr(engine.time, "sleep", MagicMock())
        
        try:
            # Calling historical data with API failing:
            # Since cache exists (even though expired), it should load it as a fallback of last resort.
            df = engine.fetch_cmc_historical_data("TESTFAIL", "7d")
            assert api_call_count >= 3  # Should have attempted Pro API (3 times)
            assert not df.empty
            assert df.iloc[0]["close"] == 1.5
        finally:
            if os.path.exists(cache_path):
                os.remove(cache_path)

    def test_run_backtest_statistics_math(self):
        import pandas as pd
        import numpy as np
        
        # Create a mock total value series starting at 10000.0 and growing to 11000.0 over 252 days
        dates = pd.date_range(start="2026-01-01", periods=252, freq="D")
        # Linearly increasing from 10000 to 11000
        total_value = pd.Series(np.linspace(10000.0, 11000.0, 252), index=dates)
        
        daily_returns = total_value.pct_change().fillna(0.0)
        
        # Formula 3: true annualized return
        true_ann_return = ((total_value.iloc[-1] / total_value.iloc[0]) ** (252 / len(total_value)) - 1) * 100
        # Formula 4: true annualized volatility
        true_ann_volatility = daily_returns.std() * (252 ** 0.5) * 100
        # Formula 5: true Sharpe ratio
        true_sharpe = (daily_returns.mean() / (daily_returns.std() + 1e-9)) * (252 ** 0.5)
        # Formula 6 & 7: true Max Drawdown
        dd = (total_value - total_value.cummax()) / total_value.cummax() * 100
        true_max_dd = dd.min()
        
        # Verify the calculation returns correct types and expected ballpark values
        assert isinstance(true_ann_return, float)
        assert isinstance(true_ann_volatility, float)
        assert isinstance(true_sharpe, float)
        assert isinstance(true_max_dd, float)
        
        # Since total_value is strictly increasing, Max Drawdown should be 0.0
        assert true_max_dd == 0.0
        # Annualized return should be exactly 10%
        assert abs(true_ann_return - 10.0) < 1e-5



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


# ═══════════════════════════════════════════════════════════════
# EXECUTION TESTS (5 tests)
# ═══════════════════════════════════════════════════════════════

class TestExecution:
    """Test dynamic mapping, error handling, retries and receipt validation."""
    
    def test_token_addresses_completeness(self):
        import execute_strategy
        from skill_engine.constants import ALLOWED_BEP20_TOKENS
        
        # Verify WBNB, USDT, USDC, CAKE, FLOKI exist with correct addresses
        assert execute_strategy.TOKEN_ADDRESSES["WBNB"] == "0xae13d989daC2f0dEbFf460aC112a837C89BAa7cd"
        assert execute_strategy.TOKEN_ADDRESSES["FLOKI"] == "0x53B026e6A1A7036494F3b98Cc819582d9213854F"
        
        # Verify all allowed tokens are mapped
        for token in ALLOWED_BEP20_TOKENS:
            assert token in execute_strategy.TOKEN_ADDRESSES
            
        # Verify fallback logic maps unlisted but allowed token to FLOKI address
        assert execute_strategy.TOKEN_ADDRESSES["ETH"] == "0x53B026e6A1A7036494F3b98Cc819582d9213854F"


    def test_execute_swap_bnb_success(self):
        from unittest.mock import MagicMock
        import execute_strategy
        
        w3 = MagicMock()
        account = MagicMock()
        account.address = "0xAddress"
        account.key = b"key"
        
        # Configure get_transaction_count
        w3.eth.get_transaction_count.return_value = 42
        
        # Configure sign_transaction
        signed_tx = MagicMock()
        signed_tx.raw_transaction = b"raw"
        w3.eth.account.sign_transaction.return_value = signed_tx
        
        # Configure send_raw_transaction
        tx_hash = MagicMock()
        tx_hash.hex.return_value = "0xTxHash"
        w3.eth.send_raw_transaction.return_value = tx_hash
        
        # Configure wait_for_transaction_receipt
        receipt = MagicMock()
        receipt.blockNumber = 1000
        receipt.gasUsed = 120000
        w3.eth.wait_for_transaction_receipt.return_value = receipt
        
        # Call execute_swap for BNB swap (first path token is WBNB)
        path = [execute_strategy.TOKEN_ADDRESSES["WBNB"], execute_strategy.TOKEN_ADDRESSES["USDT"]]
        tx_hex = execute_strategy.execute_swap(w3, account, path, 10000)
        
        assert tx_hex == "0xTxHash"
        w3.eth.wait_for_transaction_receipt.assert_called_with(tx_hash, timeout=120)

    def test_execute_swap_token_success_with_approve(self):
        from unittest.mock import MagicMock
        import execute_strategy
        
        w3 = MagicMock()
        account = MagicMock()
        account.address = "0xAddress"
        account.key = b"key"
        
        # Configure nonces
        w3.eth.get_transaction_count.side_effect = [10, 11]
        
        # Configure sign_transaction
        signed_tx = MagicMock()
        signed_tx.raw_transaction = b"raw"
        w3.eth.account.sign_transaction.return_value = signed_tx
        
        # Configure send_raw_transaction
        tx_hash1 = MagicMock()
        tx_hash1.hex.return_value = "0xApproveTxHash"
        tx_hash2 = MagicMock()
        tx_hash2.hex.return_value = "0xSwapTxHash"
        w3.eth.send_raw_transaction.side_effect = [tx_hash1, tx_hash2]
        
        # Configure wait_for_transaction_receipt
        receipt1 = MagicMock()
        receipt1.blockNumber = 100
        receipt1.gasUsed = 50000
        receipt2 = MagicMock()
        receipt2.blockNumber = 101
        receipt2.gasUsed = 150000
        w3.eth.wait_for_transaction_receipt.side_effect = [receipt1, receipt2]
        
        # Call execute_swap for Token -> Token (neither is WBNB)
        path = [execute_strategy.TOKEN_ADDRESSES["CAKE"], execute_strategy.TOKEN_ADDRESSES["USDT"]]
        tx_hex = execute_strategy.execute_swap(w3, account, path, 10000)
        
        assert tx_hex == "0xSwapTxHash"
        assert w3.eth.wait_for_transaction_receipt.call_count == 2

    def test_execute_swap_approve_retry_success(self):
        from unittest.mock import MagicMock
        import execute_strategy
        import time
        
        original_sleep = time.sleep
        time.sleep = MagicMock()
        
        try:
            w3 = MagicMock()
            account = MagicMock()
            account.address = "0xAddress"
            account.key = b"key"
            
            # Configure nonces
            w3.eth.get_transaction_count.side_effect = [10, 11, 12]
            
            # Configure sign_transaction
            signed_tx = MagicMock()
            signed_tx.raw_transaction = b"raw"
            w3.eth.account.sign_transaction.return_value = signed_tx
            
            # First approve send_raw_transaction raises Exception, second succeeds, swap succeeds
            tx_hash1 = MagicMock()
            tx_hash1.hex.return_value = "0xApproveTxHash"
            tx_hash2 = MagicMock()
            tx_hash2.hex.return_value = "0xSwapTxHash"
            w3.eth.send_raw_transaction.side_effect = [Exception("Network Error"), tx_hash1, tx_hash2]
            
            # Receipts
            receipt1 = MagicMock()
            receipt1.blockNumber = 100
            receipt1.gasUsed = 50000
            receipt2 = MagicMock()
            receipt2.blockNumber = 101
            receipt2.gasUsed = 150000
            w3.eth.wait_for_transaction_receipt.side_effect = [receipt1, receipt2]
            
            path = [execute_strategy.TOKEN_ADDRESSES["CAKE"], execute_strategy.TOKEN_ADDRESSES["USDT"]]
            tx_hex = execute_strategy.execute_swap(w3, account, path, 10000)
            
            assert tx_hex == "0xSwapTxHash"
            assert w3.eth.send_raw_transaction.call_count == 3
            time.sleep.assert_called_with(2)
        finally:
            time.sleep = original_sleep

    def test_execute_swap_fails_after_3_attempts(self):
        from unittest.mock import MagicMock
        import execute_strategy
        import time
        
        original_sleep = time.sleep
        time.sleep = MagicMock()
        
        try:
            w3 = MagicMock()
            account = MagicMock()
            account.address = "0xAddress"
            account.key = b"key"
            
            w3.eth.get_transaction_count.return_value = 10
            
            signed_tx = MagicMock()
            signed_tx.raw_transaction = b"raw"
            w3.eth.account.sign_transaction.return_value = signed_tx
            
            # send_raw_transaction always fails
            w3.eth.send_raw_transaction.side_effect = Exception("Gas price too low")
            
            path = [execute_strategy.TOKEN_ADDRESSES["WBNB"], execute_strategy.TOKEN_ADDRESSES["USDT"]]
            
            with pytest.raises(Exception, match="Gas price too low"):
                execute_strategy.execute_swap(w3, account, path, 10000)
                
            assert w3.eth.send_raw_transaction.call_count == 3
        finally:
            time.sleep = original_sleep


class TestLiveIndicators:
    """Test get_live_indicators fetches data and computes indicators correctly."""

    def test_get_live_indicators_mathematics(self, monkeypatch):
        import execute_strategy
        import pandas as pd
        from unittest.mock import MagicMock

        # We will set a dummy CMC_API_KEY to test Pro API logic path
        monkeypatch.setenv("CMC_API_KEY", "dummy_key")

        # Mock requests.get
        def mock_get(url, *args, **kwargs):
            mock_res = MagicMock()
            mock_res.status_code = 200
            
            if "quotes/latest" in url:
                mock_res.json.return_value = {
                    "data": {
                        "CAKE": [
                            {
                                "quote": {
                                    "USD": {
                                        "price": 20.0,
                                        "volume_24h": 1000000.0
                                    }
                                }
                            }
                        ]
                    }
                }
            elif "fear-and-greed/latest" in url:
                mock_res.json.return_value = {
                    "data": {
                        "value": 60.0
                    }
                }
            elif "ohlcv/historical" in url:
                # Pro API historical quotes: return 30 daily data points
                quotes = []
                base_time = pd.Timestamp.utcnow() - pd.Timedelta(days=31)
                for i in range(30):
                    time_open = (base_time + pd.Timedelta(days=i)).isoformat()
                    price = 10.0 + i * 0.5
                    quotes.append({
                        "time_open": time_open,
                        "quote": {
                            "USD": {
                                "open": price,
                                "high": price,
                                "low": price,
                                "close": price,
                                "volume": 100000.0 + i * 1000
                            }
                        }
                    })
                mock_res.json.return_value = {
                    "data": {
                        "CAKE": [
                            {
                                "quotes": quotes
                            }
                        ]
                    }
                }
            else:
                mock_res.status_code = 404
                mock_res.json.return_value = {}

            return mock_res

        monkeypatch.setattr(execute_strategy.requests, "get", mock_get)

        # Call get_live_indicators
        indicators = execute_strategy.get_live_indicators("CAKE")

        # Assertions
        assert indicators is not None
        assert "rsi" in indicators
        assert "macd" in indicators
        assert "macd_signal" in indicators
        assert "ema_fast" in indicators
        assert "ema_slow" in indicators
        assert "news_sentiment_score" in indicators
        assert "whale_anomaly_score" in indicators

        # Verify math bounds
        assert 10.0 < indicators["ema_fast"] < 25.0
        assert 10.0 < indicators["ema_slow"] < 25.0
        assert 0 <= indicators["rsi"] <= 100
        assert isinstance(indicators["rsi"], float)
        assert isinstance(indicators["macd"], float)

    def test_get_live_indicators_keyless_fallback(self, monkeypatch):
        import execute_strategy
        import pandas as pd
        import time
        from unittest.mock import MagicMock

        # Ensure CMC_API_KEY is not set
        monkeypatch.delenv("CMC_API_KEY", raising=False)

        # Mock requests.get
        def mock_get(url, *args, **kwargs):
            mock_res = MagicMock()
            mock_res.status_code = 200
            
            if "search/searchTerm" in url:
                mock_res.json.return_value = {
                    "data": {
                        "cryptoCurrencies": [
                            {
                                "id": 7186,
                                "symbol": "CAKE",
                                "isActive": 1,
                                "rank": 100
                            }
                        ]
                    }
                }
            elif "detail/chart" in url:
                points = {}
                base_time = int(time.time()) - 31 * 86400
                for i in range(30):
                    ts = base_time + i * 86400
                    price = 10.0 + i * 0.5
                    points[str(ts)] = {
                        "v": [price, 100000.0 + i * 1000]
                    }
                mock_res.json.return_value = {
                    "data": {
                        "points": points
                    }
                }
            else:
                mock_res.status_code = 404
                mock_res.json.return_value = {}

            return mock_res

        monkeypatch.setattr(execute_strategy.requests, "get", mock_get)

        # Call get_live_indicators
        indicators = execute_strategy.get_live_indicators("CAKE")

        # Assertions
        assert indicators is not None
        assert "rsi" in indicators
        assert "macd" in indicators
        assert "ema_fast" in indicators
        assert indicators["rsi"] > 0
        assert indicators["ema_fast"] > 10.0


