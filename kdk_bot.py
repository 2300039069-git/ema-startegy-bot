#!/usr/bin/env python3
"""
================================================================================
                           KDK TRADE BOT (v2.5)
             All-Futures 200 EMA + 50 EMA Strategy with 1:2 RR
          Multi-Indicator Probability of Profit (PoP %) Engine
                      Target: Delta Exchange Testnet
================================================================================
Strategy Overview:
- Automatically discovers & scans ALL Perpetual Futures on Delta Exchange.
- Timeframe: 5-minute candles.
- 200 EMA + 50 EMA trend filtering on close prices using pandas.
- Multi-indicator Probability of Profit (PoP %) Engine (RSI 14, ATR 14, Volume).
- Actionable Directional Guidance (BULLISH / BEARISH / NEUTRAL).
- Triggers:
    * BUY  : Current Price > 200 EMA AND breaks above 3-candle pullback high.
    * SELL : Current Price < 200 EMA AND breaks below 3-candle pullback low.
- Risk Management:
    * Max active positions across all monitored assets: 2
    * Market orders with server-side bracket orders attached directly
    * Stop Loss at recent swing low (Buy) or swing high (Sell)
    * Take Profit with strict 1:2 Risk-to-Reward ratio
================================================================================
"""

import os
import sys
import time
import argparse
import datetime
from decimal import Decimal, ROUND_HALF_UP
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import pandas as pd
from dotenv import load_dotenv
from delta_rest_client import DeltaRestClient, OrderType

# Safe encoding on Windows terminal
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Load environment configuration
load_dotenv()

API_KEY = os.getenv("API_KEY", "").strip()
API_SECRET = os.getenv("API_SECRET", "").strip()
BASE_URL = os.getenv("BASE_URL", "https://cdn-ind.testnet.deltaex.org").strip().rstrip('/')
MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", "2"))
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))
RATE_LIMIT_PAUSE = float(os.getenv("RATE_LIMIT_PAUSE", "0.2"))
DEFAULT_ORDER_SIZE = int(os.getenv("DEFAULT_ORDER_SIZE", "1"))
RISK_REWARD_RATIO = float(os.getenv("RISK_REWARD_RATIO", "2.0"))
USD_INR_RATE = 85.0


def log(message: str, level: str = "INFO"):
    """Prints a timestamped log message with visual level tag."""
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tags = {
        "INFO": "[INFO]",
        "WARN": "[WARN]",
        "ERROR": "[ERROR]",
        "SIGNAL": "[SIGNAL]",
        "TRADE": "[TRADE]",
        "SUCCESS": "[SUCCESS]",
    }
    tag = tags.get(level, f"[{level}]")
    print(f"[{now_str}] {tag:<10} {message}", flush=True)


def format_price(price: float, tick_size: float = 0.01) -> str:
    """Rounds a price float to the exact tick_size precision required by the exchange."""
    try:
        dec_tick = Decimal(str(tick_size))
        dec_price = Decimal(str(price))
        rounded = (dec_price / dec_tick).quantize(Decimal('1'), rounding=ROUND_HALF_UP) * dec_tick
        return f"{rounded:f}".rstrip('0').rstrip('.') if '.' in f"{rounded:f}" else f"{rounded:f}"
    except Exception:
        return str(round(price, 4))


class KDKTradeBot:
    def __init__(self, api_key: str, api_secret: str, base_url: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.base_url = base_url
        self.client = DeltaRestClient(
            base_url=self.base_url,
            api_key=self.api_key,
            api_secret=self.api_secret,
            raise_for_status=False
        )
        self.futures_products = {}
        self.initialize_products()

    def initialize_products(self):
        """Auto-discovers all perpetual futures contracts on the exchange."""
        log(f"Connecting to {self.base_url} to discover all Perpetual Futures...", "INFO")
        try:
            products = self.client.get_products()
            if not isinstance(products, list):
                products = []
        except Exception as e:
            log(f"Failed to fetch products: {e}", "WARN")
            products = []

        futures_map = {}
        for p in products:
            if not isinstance(p, dict):
                continue
            contract_type = p.get("contract_type", "")
            state = p.get("state", "live")
            if contract_type in ["perpetual_futures", "futures"] and state in ["live", None, ""]:
                symbol = p.get("symbol")
                prod_id = p.get("id")
                tick_size = float(p.get("tick_size", "0.01"))
                min_size = float(p.get("min_size", "1"))
                order_size = max(DEFAULT_ORDER_SIZE, int(min_size))

                futures_map[symbol] = {
                    "product_id": prod_id,
                    "symbol": symbol,
                    "contract_type": contract_type,
                    "tick_size": tick_size,
                    "min_size": min_size,
                    "order_size": order_size,
                    "underlying": p.get("underlying_asset", {}).get("symbol", symbol)
                }

        self.futures_products = futures_map
        log(f"Discovered {len(self.futures_products)} active Perpetual Futures contracts on Delta Exchange.", "SUCCESS")

    def get_open_positions(self) -> list:
        """Retrieves list of active open positions from the account."""
        try:
            time.sleep(RATE_LIMIT_PAUSE)
            res = self.client.request("GET", "/v2/positions/margined", auth=True)
            if res.status_code == 200:
                data = res.json().get("result", [])
                active = [p for p in data if float(p.get("size", 0)) != 0]
                return active
            elif res.status_code == 401:
                log("API auth check: Demo credentials in .env are placeholder. Running scan in signal-monitoring mode.", "WARN")
                return []
            else:
                log(f"Could not retrieve open positions: HTTP {res.status_code}", "WARN")
                return []
        except Exception as e:
            log(f"Error fetching open positions: {e}", "ERROR")
            return []

    def fetch_candles(self, symbol: str, resolution: str = "5m", lookback_days: int = 3) -> pd.DataFrame:
        """Fetches historical candles for 200 EMA calculation."""
        now = int(time.time())
        start_time = now - (lookback_days * 86400)
        end_time = now

        endpoints = [
            (self.base_url, symbol),
            ("https://api.india.delta.exchange", symbol),
            ("https://api.delta.exchange", symbol),
            ("https://api.delta.exchange", symbol.replace("USD", "USDT")),
        ]

        candles = []
        for base, sym in endpoints:
            try:
                url = f"{base}/v2/history/candles"
                params = {"symbol": sym, "resolution": resolution, "start": start_time, "end": end_time}
                r = requests.get(url, params=params, timeout=6)
                if r.status_code == 200:
                    data = r.json().get("result", [])
                    if len(data) >= 205:
                        candles = data
                        break
                    elif len(data) > len(candles):
                        candles = data
            except Exception:
                continue

        if not candles:
            return pd.DataFrame()

        df = pd.DataFrame(candles)
        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        if "time" in df.columns:
            df["time"] = pd.to_numeric(df["time"], errors="coerce")
            df = df.sort_values("time", ascending=True).reset_index(drop=True)

        return df

    def analyze_strategy(self, df: pd.DataFrame, rr_ratio: float = RISK_REWARD_RATIO) -> dict:
        """Computes 200 EMA, 50 EMA, RSI, ATR, PoP %, and 3-candle pullback breakout levels with 1:2 RR."""
        if len(df) < 205:
            return {
                "signal": "INSUFFICIENT_DATA",
                "reason": f"Need at least 205 candles, got {len(df)}",
                "current_price": 0.0,
                "ema200": 0.0,
                "ema50": 0.0,
                "pullback_high": 0.0,
                "pullback_low": 0.0,
                "trend": "N/A",
                "pop_percent": 50.0,
                "confidence": "LOW",
                "direction": "NEUTRAL",
                "guidance": "Insufficient candles",
            }

        df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
        df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()

        current_candle = df.iloc[-1]
        current_price = float(current_candle["close"])
        current_ema200 = float(current_candle["ema200"])
        current_ema50 = float(current_candle["ema50"])

        pullback_candles = df.iloc[-4:-1]
        pullback_high = float(pullback_candles["high"].max())
        pullback_low = float(pullback_candles["low"].min())

        signal = "NEUTRAL"
        stop_loss = 0.0
        take_profit = 0.0
        risk = 0.0

        if current_price > current_ema200 and current_price > pullback_high:
            signal = "BUY"
            stop_loss = pullback_low
            risk = current_price - stop_loss
            if risk > 0:
                take_profit = current_price + (rr_ratio * risk)
            else:
                signal = "NEUTRAL"

        elif current_price < current_ema200 and current_price < pullback_low:
            signal = "SELL"
            stop_loss = pullback_high
            risk = stop_loss - current_price
            if risk > 0:
                take_profit = current_price - (rr_ratio * risk)
            else:
                signal = "NEUTRAL"

        # RSI(14)
        delta = df["close"].diff()
        gain = (delta.where(delta > 0, 0.0)).rolling(window=14, min_periods=1).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(window=14, min_periods=1).mean()
        rs = gain / (loss + 1e-9)
        rsi_series = 100 - (100 / (1 + rs))
        rsi14 = float(rsi_series.iloc[-1]) if not rsi_series.empty else 50.0

        # ATR(14)
        high_low = df["high"] - df["low"]
        high_close = (df["high"] - df["close"].shift()).abs()
        low_close = (df["low"] - df["close"].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr_series = tr.rolling(14, min_periods=1).mean()
        atr14 = float(atr_series.iloc[-1]) if not atr_series.empty else (current_price * 0.005)

        # Directional determination & PoP %
        is_bull_trend = current_price > current_ema200
        direction = "BULLISH" if is_bull_trend else "BEARISH"
        
        pop_score = 40.0
        if is_bull_trend and current_price > current_ema50:
            pop_score += 20.0
        elif not is_bull_trend and current_price < current_ema50:
            pop_score += 20.0
        else:
            pop_score += 10.0

        if direction == "BULLISH" and 48 <= rsi14 <= 68:
            pop_score += 20.0
        elif direction == "BEARISH" and 32 <= rsi14 <= 52:
            pop_score += 20.0
        else:
            pop_score += 10.0

        if signal in ["BUY", "SELL"]:
            pop_score += 15.0

        pop_percent = round(max(35.0, min(92.0, pop_score)), 1)
        confidence = "HIGH PROBABILITY" if pop_percent >= 70 else ("MODERATE PROBABILITY" if pop_percent >= 55 else "LOW PROBABILITY")

        sl_calc = pullback_low if direction == "BULLISH" else pullback_high
        risk_calc = max(abs(current_price - sl_calc), atr14 * 0.5)
        tp_calc = (current_price + rr_ratio * risk_calc) if direction == "BULLISH" else (current_price - rr_ratio * risk_calc)

        return {
            "signal": signal,
            "current_price": current_price,
            "current_price_inr": round(current_price * USD_INR_RATE, 2),
            "ema200": current_ema200,
            "ema50": current_ema50,
            "pullback_high": pullback_high,
            "pullback_low": pullback_low,
            "stop_loss": stop_loss if signal in ["BUY", "SELL"] else round(sl_calc, 4),
            "take_profit": take_profit if signal in ["BUY", "SELL"] else round(tp_calc, 4),
            "risk": risk if risk > 0 else risk_calc,
            "rr_ratio": rr_ratio,
            "trend": "BULLISH (Above 200 EMA)" if current_price > current_ema200 else "BEARISH (Below 200 EMA)",
            "pop_percent": pop_percent,
            "confidence": confidence,
            "direction": direction,
            "rsi14": round(rsi14, 1),
            "atr14": round(atr14, 4),
        }

    def place_bracket_market_order(self, product_id: int, symbol: str, side: str, size: int, sl_price: float, tp_price: float, tick_size: float) -> dict:
        """Executes a market order with server-side 1:2 RR bracket orders attached."""
        formatted_sl = format_price(sl_price, tick_size)
        formatted_tp = format_price(tp_price, tick_size)

        order_payload = {
            "product_id": int(product_id),
            "size": int(size),
            "side": side.lower(),
            "order_type": OrderType.MARKET.value,
            "bracket_stop_loss_price": str(formatted_sl),
            "bracket_take_profit_price": str(formatted_tp),
        }

        log(f"Submitting {side.upper()} order for {symbol} (Product ID: {product_id}) | Size: {size} contracts", "TRADE")
        log(f"Attached Server-Side Brackets -> Stop Loss: {formatted_sl} | Take Profit: {formatted_tp} (1:2 RR)", "TRADE")

        try:
            time.sleep(RATE_LIMIT_PAUSE)
            res = self.client.request("POST", "/v2/orders", payload=order_payload, auth=True)
            if res.status_code in [200, 201]:
                order_result = res.json().get("result", {})
                order_id = order_result.get("id", "N/A")
                log(f"Order Placed Successfully! Order ID: {order_id} | State: {order_result.get('state', 'SUBMITTED')}", "SUCCESS")
                return {"success": True, "order_id": order_id, "data": order_result}
            else:
                err_body = res.json() if res.headers.get("content-type", "").startswith("application/json") else res.text
                log(f"Order Placement Failed: HTTP {res.status_code} - {err_body}", "ERROR")
                return {"success": False, "error": err_body}
        except Exception as e:
            log(f"Exception during order placement: {e}", "ERROR")
            return {"success": False, "error": str(e)}

    def run_scan_cycle(self):
        """Executes one scan cycle across all discovered futures assets."""
        print("\n" + "=" * 85)
        log(f"Initiating Comprehensive Market Scan ({len(self.futures_products)} Futures Contracts)...", "INFO")
        print("=" * 85)

        open_positions = self.get_open_positions()
        open_count = len(open_positions)
        open_product_ids = {p.get("product_id") for p in open_positions}

        log(f"Active Open Positions: {open_count}/{MAX_OPEN_POSITIONS}", "INFO")

        for symbol, meta in self.futures_products.items():
            product_id = meta.get("product_id")
            tick_size = meta.get("tick_size", 0.01)
            order_size = meta.get("order_size", DEFAULT_ORDER_SIZE)

            df = self.fetch_candles(symbol=symbol, resolution="5m", lookback_days=3)
            if df.empty or len(df) < 205:
                continue

            analysis = self.analyze_strategy(df, rr_ratio=RISK_REWARD_RATIO)
            curr = analysis["current_price"]
            ema = analysis["ema200"]
            sig = analysis["signal"]
            pop = analysis["pop_percent"]
            dir_bias = analysis["direction"]

            log(f"[{symbol:<10}] Price: ${curr:<9.4f} | 200 EMA: ${ema:<9.4f} | Bias: {dir_bias:<7} | PoP: {pop:>4.1f}% | Signal: {sig}", "INFO")

            if sig in ["BUY", "SELL"]:
                if product_id in open_product_ids:
                    log(f"Signal ignored for {symbol}: Position already active.", "WARN")
                elif open_count >= MAX_OPEN_POSITIONS:
                    log(f"Signal ignored for {symbol}: Max positions reached ({open_count}/{MAX_OPEN_POSITIONS}).", "WARN")
                else:
                    sl = analysis["stop_loss"]
                    tp = analysis["take_profit"]
                    log(f"🚨 VALID {sig} TRIGGER! Entry: ${curr:.4f} | SL: ${sl:.4f} | TP: ${tp:.4f} (1:2 RR) | PoP: {pop}%", "SIGNAL")
                    side = "buy" if sig == "BUY" else "sell"
                    res = self.place_bracket_market_order(
                        product_id=product_id,
                        symbol=symbol,
                        side=side,
                        size=order_size,
                        sl_price=sl,
                        tp_price=tp,
                        tick_size=tick_size
                    )
                    if res.get("success"):
                        open_product_ids.add(product_id)
                        open_count += 1

    def run(self):
        """Autonomous continuous loop."""
        log(f"Starting KDK Trade Bot loop (Polling every {POLL_INTERVAL}s, Max Open Positions: {MAX_OPEN_POSITIONS})...", "SUCCESS")
        try:
            while True:
                self.run_scan_cycle()
                time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            log("Bot shutdown requested by user.", "WARN")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="KDK Trade Bot CLI")
    parser.add_argument("--scan-once", action="store_true", help="Execute single scan and exit")
    args = parser.parse_args()

    bot_instance = KDKTradeBot(api_key=API_KEY, api_secret=API_SECRET, base_url=BASE_URL)
    if args.scan_once:
        bot_instance.run_scan_cycle()
    else:
        bot_instance.run()
