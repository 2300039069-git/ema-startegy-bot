"""
Unit tests and simulation verification for KDK Trade Bot:
Heikin Ashi 5-Minute 200 EMA + 20 EMA Pullback Strategy with Bilingual (English & Telugu) Trade Reasons.
"""

import os
import unittest
import pandas as pd
import numpy as np
from kdk_bot import KDKTradeBot, format_price, calculate_heikin_ashi
from app import analyze_strategy, calculate_position_size, load_trade_history, save_trade_history, record_trade, update_trade_status


class TestHeikinAshiStrategy(unittest.TestCase):
    def setUp(self):
        self.bot = KDKTradeBot(api_key="test_key", api_secret="test_secret", base_url="https://testnet-api.delta.exchange")

    def create_synthetic_candles(self, n=250, base_price=50000.0, trend="up"):
        """Generates synthetic OHLCV candle data."""
        np.random.seed(42)
        times = [1700000000 + i * 300 for i in range(n)]
        
        prices = [base_price]
        for _ in range(n - 1):
            change = (np.random.rand() - 0.48) * 60 if trend == "up" else (np.random.rand() - 0.52) * 60
            prices.append(prices[-1] + change)
        
        data = []
        for t, p in zip(times, prices):
            data.append({
                "time": t,
                "open": p - 10,
                "high": p + 25,
                "low": p - 25,
                "close": p,
                "volume": 150.0
            })
        return pd.DataFrame(data)

    def test_heikin_ashi_calculation(self):
        """Test Heikin Ashi transformation logic."""
        df = self.create_synthetic_candles(n=50, base_price=50000.0)
        df_ha = calculate_heikin_ashi(df)
        
        self.assertIn("ha_open", df_ha.columns)
        self.assertIn("ha_close", df_ha.columns)
        self.assertIn("ha_high", df_ha.columns)
        self.assertIn("ha_low", df_ha.columns)
        
        expected_ha_open_0 = (df["open"].iloc[0] + df["close"].iloc[0]) / 2.0
        self.assertAlmostEqual(df_ha["ha_open"].iloc[0], expected_ha_open_0, places=3)
        
        for i in range(len(df_ha)):
            self.assertGreaterEqual(df_ha["ha_high"].iloc[i], df_ha["ha_open"].iloc[i] - 1e-6)
            self.assertGreaterEqual(df_ha["ha_high"].iloc[i], df_ha["ha_close"].iloc[i] - 1e-6)
            self.assertLessEqual(df_ha["ha_low"].iloc[i], df_ha["ha_open"].iloc[i] + 1e-6)
            self.assertLessEqual(df_ha["ha_low"].iloc[i], df_ha["ha_close"].iloc[i] + 1e-6)

    def test_buy_signal_and_bilingual_reason(self):
        """Test BUY signal and English/Telugu trade reason."""
        df = self.create_synthetic_candles(n=220, base_price=50000.0, trend="up")
        df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
        df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()

        ema20_level = 51800.0
        for idx in range(len(df) - 5, len(df) - 1):
            df.loc[idx, ["open", "high", "low", "close"]] = [51900.0, 52000.0, ema20_level - 10, 51850.0]

        trigger_price = 52200.0
        df.loc[len(df) - 1, ["open", "high", "low", "close"]] = [51850.0, 52300.0, 51840.0, trigger_price]

        analysis = analyze_strategy(df, rr_ratio=2.0, account_equity=200.0)
        
        self.assertEqual(analysis["direction"], "BULLISH")
        self.assertTrue(analysis["ema20_touched"])
        self.assertEqual(analysis["signal"], "BUY")
        
        # Verify English Reason
        self.assertIn("BUY Trigger", analysis["reason_en"])
        self.assertIn("200 EMA", analysis["reason_en"])
        self.assertIn("20 EMA", analysis["reason_en"])
        
        # Verify Telugu Reason
        self.assertIn("బై", analysis["reason_te"])
        self.assertIn("200 EMA", analysis["reason_te"])
        self.assertIn("20 EMA", analysis["reason_te"])

    def test_sell_signal_and_bilingual_reason(self):
        """Test SELL signal and English/Telugu trade reason."""
        df = self.create_synthetic_candles(n=220, base_price=50000.0, trend="down")
        df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
        df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()

        ema20_level = 48200.0
        for idx in range(len(df) - 5, len(df) - 1):
            df.loc[idx, ["open", "high", "low", "close"]] = [48000.0, ema20_level + 15, 47950.0, 48100.0]

        trigger_price = 47800.0
        df.loc[len(df) - 1, ["open", "high", "low", "close"]] = [48100.0, 48110.0, 47750.0, trigger_price]

        analysis = analyze_strategy(df, rr_ratio=2.0, account_equity=200.0)
        
        self.assertEqual(analysis["direction"], "BEARISH")
        self.assertTrue(analysis["ema20_touched"])
        self.assertEqual(analysis["signal"], "SELL")
        
        # Verify English Reason
        self.assertIn("SELL Trigger", analysis["reason_en"])
        self.assertIn("200 EMA", analysis["reason_en"])
        
        # Verify Telugu Reason
        self.assertIn("సెల్", analysis["reason_te"])
        self.assertIn("200 EMA", analysis["reason_te"])

    def test_no_chase_rule(self):
        """Test that if price does NOT touch the 20 EMA, signal remains NEUTRAL."""
        df = self.create_synthetic_candles(n=220, base_price=50000.0, trend="up")
        df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
        df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()

        for idx in range(len(df) - 15, len(df)):
            df.loc[idx, ["open", "high", "low", "close"]] = [55000.0, 55500.0, 54800.0, 55200.0]

        analysis = analyze_strategy(df, rr_ratio=2.0)
        self.assertFalse(analysis["ema20_touched"])
        self.assertEqual(analysis["signal"], "NEUTRAL")

    def test_position_sizing_2pct_risk(self):
        """Test 2% capital risk position sizing formula."""
        size = calculate_position_size(account_equity_usd=1000.0, risk_per_contract_usd=10.0, risk_pct=2.0)
        self.assertEqual(size, 2)
        
        size_min = calculate_position_size(account_equity_usd=1000.0, risk_per_contract_usd=40.0, risk_pct=2.0)
        self.assertEqual(size_min, 1)

    def test_price_formatting(self):
        """Test price rounding to tick size."""
        self.assertEqual(format_price(81459.543, 0.1), "81459.5")
        self.assertEqual(format_price(2450.123, 0.05), "2450.1")


if __name__ == "__main__":
    unittest.main()
