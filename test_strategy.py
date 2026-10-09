"""
Unit tests and simulation verification for KDK Trade Bot strategy logic,
pullback breakout detection, 1:2 Risk-to-Reward bracket calculations,
Probability of Profit (PoP %) scoring, and trade history tracking.
"""

import os
import unittest
import pandas as pd
import numpy as np
from kdk_bot import KDKTradeBot, format_price
from app import analyze_strategy, load_trade_history, save_trade_history, record_trade, update_trade_status, TRADE_HISTORY_FILE


class TestKDKStrategy(unittest.TestCase):
    def setUp(self):
        # Instantiate bot in offline mode
        self.bot = KDKTradeBot(api_key="test_key", api_secret="test_secret", base_url="https://testnet-api.delta.exchange")

    def create_synthetic_candles(self, n=250, base_price=50000.0, trend="up"):
        """Generates synthetic OHLCV candle data."""
        np.random.seed(42)
        times = [1700000000 + i * 300 for i in range(n)]
        
        prices = [base_price]
        for _ in range(n - 1):
            change = (np.random.rand() - 0.48) * 100 if trend == "up" else (np.random.rand() - 0.52) * 100
            prices.append(prices[-1] + change)
        
        data = []
        for t, p in zip(times, prices):
            data.append({
                "time": t,
                "open": p - 10,
                "high": p + 30,
                "low": p - 30,
                "close": p,
                "volume": 150.0
            })
        return pd.DataFrame(data)

    def test_buy_signal_trigger_and_pop(self):
        """Test BUY signal: Price > 200 EMA AND Price > 3-candle pullback high + PoP % calculation."""
        df = self.create_synthetic_candles(n=220, base_price=50000.0, trend="up")
        
        # Calculate EMA to know the baseline
        df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
        
        # Set pullback candles (last 3 completed: indices -4, -3, -2)
        df.loc[len(df) - 4, ["high", "low", "close"]] = [52000.0, 51500.0, 51800.0]
        df.loc[len(df) - 3, ["high", "low", "close"]] = [52100.0, 51600.0, 51900.0]
        df.loc[len(df) - 2, ["high", "low", "close"]] = [52050.0, 51700.0, 51850.0]
        
        # Trigger candle breaking above 52100 with price > EMA200
        breakout_price = 52500.0
        df.loc[len(df) - 1, ["open", "high", "low", "close"]] = [52000.0, 52600.0, 51900.0, breakout_price]

        analysis = analyze_strategy(df, rr_ratio=2.0)
        
        self.assertEqual(analysis["signal"], "BUY")
        self.assertEqual(analysis["direction"], "BULLISH")
        self.assertEqual(analysis["current_price"], breakout_price)
        self.assertEqual(analysis["pullback_high"], 52100.0)
        self.assertEqual(analysis["pullback_low"], 51500.0)
        self.assertEqual(analysis["stop_loss"], 51500.0)
        
        expected_risk = breakout_price - 51500.0  # 1000.0
        expected_tp = breakout_price + (2.0 * expected_risk)  # 52500 + 2000 = 54500.0
        self.assertAlmostEqual(analysis["risk"], expected_risk, places=2)
        self.assertAlmostEqual(analysis["take_profit"], expected_tp, places=2)
        
        # PoP should be in valid high probability range
        self.assertGreaterEqual(analysis["pop_percent"], 50.0)
        self.assertLessEqual(analysis["pop_percent"], 92.0)
        self.assertIn("BULLISH", analysis["guidance"])

    def test_sell_signal_trigger_and_pop(self):
        """Test SELL signal: Price < 200 EMA AND Price < 3-candle pullback low + PoP % calculation."""
        df = self.create_synthetic_candles(n=220, base_price=50000.0, trend="down")
        
        # Set pullback candles
        df.loc[len(df) - 4, ["high", "low", "close"]] = [48500.0, 48000.0, 48200.0]
        df.loc[len(df) - 3, ["high", "low", "close"]] = [48600.0, 47900.0, 48100.0]
        df.loc[len(df) - 2, ["high", "low", "close"]] = [48400.0, 48050.0, 48150.0]
        
        # Breakdown price
        breakdown_price = 47500.0
        df.loc[len(df) - 1, ["open", "high", "low", "close"]] = [48000.0, 48100.0, 47400.0, breakdown_price]

        analysis = analyze_strategy(df, rr_ratio=2.0)
        
        self.assertEqual(analysis["signal"], "SELL")
        self.assertEqual(analysis["direction"], "BEARISH")
        self.assertEqual(analysis["current_price"], breakdown_price)
        self.assertEqual(analysis["pullback_high"], 48600.0)
        self.assertEqual(analysis["pullback_low"], 47900.0)
        self.assertEqual(analysis["stop_loss"], 48600.0)
        
        expected_risk = 48600.0 - breakdown_price  # 1100.0
        expected_tp = breakdown_price - (2.0 * expected_risk)  # 47500 - 2200 = 45300.0
        self.assertAlmostEqual(analysis["risk"], expected_risk, places=2)
        self.assertAlmostEqual(analysis["take_profit"], expected_tp, places=2)
        
        self.assertGreaterEqual(analysis["pop_percent"], 50.0)
        self.assertLessEqual(analysis["pop_percent"], 92.0)
        self.assertIn("BEARISH", analysis["guidance"])

    def test_neutral_condition(self):
        """Test Neutral condition when price is within pullback range."""
        df = self.create_synthetic_candles(n=220, base_price=50000.0, trend="up")
        
        df.loc[len(df) - 4, ["high", "low", "close"]] = [52000.0, 51500.0, 51800.0]
        df.loc[len(df) - 3, ["high", "low", "close"]] = [52100.0, 51600.0, 51900.0]
        df.loc[len(df) - 2, ["high", "low", "close"]] = [52050.0, 51700.0, 51850.0]
        
        # Inside pullback range
        df.loc[len(df) - 1, ["open", "high", "low", "close"]] = [51800.0, 51900.0, 51750.0, 51800.0]

        analysis = analyze_strategy(df, rr_ratio=2.0)
        self.assertEqual(analysis["signal"], "NEUTRAL")
        self.assertGreaterEqual(analysis["pop_percent"], 35.0)

    def test_price_formatting_and_tick_sizes(self):
        """Test price formatting for different exchange tick sizes."""
        self.assertEqual(format_price(81459.543, 0.1), "81459.5")
        self.assertEqual(format_price(81459.567, 0.1), "81459.6")
        self.assertEqual(format_price(2450.123, 0.05), "2450.1")
        self.assertEqual(format_price(2450.134, 0.05), "2450.15")
        self.assertEqual(format_price(108.3854, 0.001), "108.385")
        self.assertEqual(format_price(108.3858, 0.001), "108.386")

    def test_trade_history_persistence(self):
        """Test recording and updating trades in trade_history.json."""
        test_trade = {
            "order_id": "TEST_ORDER_999",
            "product_id": 12345,
            "symbol": "BTCUSD",
            "side": "BUY",
            "size": 1,
            "entry_price": 50000.0,
            "stop_loss": 49000.0,
            "take_profit": 52000.0,
            "status": "OPEN",
            "source": "BOT"
        }
        record_trade(test_trade)
        trades = load_trade_history()
        found = any(t.get("order_id") == "TEST_ORDER_999" for t in trades)
        self.assertTrue(found)

        # Update status
        update_trade_status("TEST_ORDER_999", "CLOSED", exit_price=52000.0, realized_pnl=2000.0)
        trades_after = load_trade_history()
        updated_trade = next(t for t in trades_after if t.get("order_id") == "TEST_ORDER_999")
        self.assertEqual(updated_trade["status"], "CLOSED")
        self.assertEqual(updated_trade["exit_price"], 52000.0)
        self.assertEqual(updated_trade["realized_pnl_usd"], 2000.0)

        # Clean up test trade
        cleaned = [t for t in trades_after if t.get("order_id") != "TEST_ORDER_999"]
        save_trade_history(cleaned)


if __name__ == "__main__":
    unittest.main()
