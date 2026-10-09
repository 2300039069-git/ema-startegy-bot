"""
Unit tests and simulation verification for KDK Trade Bot strategy logic,
pullback breakout detection, 1:3 Risk-to-Reward bracket calculations,
and tick size formatting.
"""

import unittest
import pandas as pd
import numpy as np
from kdk_bot import KDKTradeBot, format_price


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
                "volume": 100.0
            })
        return pd.DataFrame(data)

    def test_buy_signal_trigger(self):
        """Test BUY signal: Price > 200 EMA AND Price > 3-candle pullback high."""
        df = self.create_synthetic_candles(n=220, base_price=50000.0, trend="up")
        
        # Calculate EMA to know the baseline
        df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
        ema_val = float(df["ema200"].iloc[-1])
        
        # Set pullback candles (last 3 completed: indices -4, -3, -2)
        df.loc[len(df) - 4, ["high", "low", "close"]] = [52000.0, 51500.0, 51800.0]
        df.loc[len(df) - 3, ["high", "low", "close"]] = [52100.0, 51600.0, 51900.0]
        df.loc[len(df) - 2, ["high", "low", "close"]] = [52050.0, 51700.0, 51850.0]
        
        # Pullback High = 52100.0, Pullback Low = 51500.0
        # Trigger candle (in-progress, index -1) breaking above 52100 with price > EMA200
        breakout_price = 52500.0
        df.loc[len(df) - 1, ["open", "high", "low", "close"]] = [52000.0, 52600.0, 51900.0, breakout_price]

        analysis = self.bot.analyze_strategy(df)
        
        self.assertEqual(analysis["signal"], "BUY")
        self.assertEqual(analysis["current_price"], breakout_price)
        self.assertEqual(analysis["pullback_high"], 52100.0)
        self.assertEqual(analysis["pullback_low"], 51500.0)
        self.assertEqual(analysis["stop_loss"], 51500.0)
        
        expected_risk = breakout_price - 51500.0  # 1000.0
        expected_tp = breakout_price + (2.0 * expected_risk)  # 52500 + 2000 = 54500.0
        self.assertAlmostEqual(analysis["risk"], expected_risk, places=2)
        self.assertAlmostEqual(analysis["take_profit"], expected_tp, places=2)

    def test_sell_signal_trigger(self):
        """Test SELL signal: Price < 200 EMA AND Price < 3-candle pullback low."""
        df = self.create_synthetic_candles(n=220, base_price=50000.0, trend="down")
        
        # Calculate EMA
        df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
        
        # Set pullback candles
        df.loc[len(df) - 4, ["high", "low", "close"]] = [48500.0, 48000.0, 48200.0]
        df.loc[len(df) - 3, ["high", "low", "close"]] = [48600.0, 47900.0, 48100.0]
        df.loc[len(df) - 2, ["high", "low", "close"]] = [48400.0, 48050.0, 48150.0]
        
        # Pullback High = 48600.0, Pullback Low = 47900.0
        # Trigger candle breaking below 47900.0
        breakdown_price = 47500.0
        df.loc[len(df) - 1, ["open", "high", "low", "close"]] = [48000.0, 48100.0, 47400.0, breakdown_price]

        analysis = self.bot.analyze_strategy(df)
        
        self.assertEqual(analysis["signal"], "SELL")
        self.assertEqual(analysis["current_price"], breakdown_price)
        self.assertEqual(analysis["pullback_high"], 48600.0)
        self.assertEqual(analysis["pullback_low"], 47900.0)
        self.assertEqual(analysis["stop_loss"], 48600.0)
        
        expected_risk = 48600.0 - breakdown_price  # 1100.0
        expected_tp = breakdown_price - (2.0 * expected_risk)  # 47500 - 2200 = 45300.0
        self.assertAlmostEqual(analysis["risk"], expected_risk, places=2)
        self.assertAlmostEqual(analysis["take_profit"], expected_tp, places=2)

    def test_neutral_condition(self):
        """Test Neutral condition when price is within pullback range."""
        df = self.create_synthetic_candles(n=220, base_price=50000.0, trend="up")
        
        df.loc[len(df) - 4, ["high", "low", "close"]] = [52000.0, 51500.0, 51800.0]
        df.loc[len(df) - 3, ["high", "low", "close"]] = [52100.0, 51600.0, 51900.0]
        df.loc[len(df) - 2, ["high", "low", "close"]] = [52050.0, 51700.0, 51850.0]
        
        # Price is inside the pullback range (51800)
        df.loc[len(df) - 1, ["open", "high", "low", "close"]] = [51800.0, 51900.0, 51750.0, 51800.0]

        analysis = self.bot.analyze_strategy(df)
        self.assertEqual(analysis["signal"], "NEUTRAL")

    def test_price_formatting_and_tick_sizes(self):
        """Test price formatting for different exchange tick sizes."""
        # BTCUSD (tick_size = 0.1)
        self.assertEqual(format_price(81459.543, 0.1), "81459.5")
        self.assertEqual(format_price(81459.567, 0.1), "81459.6")
        
        # ETHUSD (tick_size = 0.05)
        self.assertEqual(format_price(2450.123, 0.05), "2450.1")
        self.assertEqual(format_price(2450.134, 0.05), "2450.15")
        
        # SOLUSD (tick_size = 0.001)
        self.assertEqual(format_price(108.3854, 0.001), "108.385")
        self.assertEqual(format_price(108.3858, 0.001), "108.386")


if __name__ == "__main__":
    unittest.main()
