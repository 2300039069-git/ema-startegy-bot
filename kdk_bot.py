#!/usr/bin/env python3
"""
================================================================================
                           KDK TRADE BOT (v2.0)
             All-Futures 200 EMA Pullback Strategy with 1:2 RR
                      Target: Delta Exchange Testnet
================================================================================
Strategy Overview:
- Automatically discovers & scans ALL Perpetual Futures on Delta Exchange.
- Timeframe: 5-minute candles.
- 200 EMA trend filtering on close prices using pandas.
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
        """Computes 200 EMA and 3-candle pullback breakout levels with 1:2 RR."""
        if len(df) < 205:
            return {
                "signal": "INSUFFICIENT_DATA",
                "reason": f"Need at least 205 candles, got {len(df)}",
                "current_price": 0.0,
                "ema200": 0.0,
                "pullback_high": 0.0,
                "pullback_low": 0.0,
                "trend": "N/A",
            }

        df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()

        current_candle = df.iloc[-1]
        current_price = float(current_candle["close"])
        current_ema200 = float(current_candle["ema200"])

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

        return {
            "signal": signal,
            "current_price": current_price,
            "ema200": current_ema200,
            "pullback_high": pullback_high,
            "pullback_low": pullback_low,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "risk": risk,
            "rr_ratio": rr_ratio,
            "trend": "BULLISH (Above 200 EMA)" if current_price > current_ema200 else "BEARISH (Below 200 EMA)",
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
            order_size = meta.get("order_size", 1)

            if product_id in open_product_ids:
                log(f"[{symbol}] Asset already has an active open position. Skipping scan.", "INFO")
                continue

            df = self.fetch_candles(symbol=symbol, resolution="5m", lookback_days=3)
            if df.empty or len(df) < 205:
                continue

            analysis = self.analyze_strategy(df)
            signal = analysis["signal"]
            current_price = analysis["current_price"]
            ema200 = analysis["ema200"]
            pb_high = analysis["pullback_high"]
            pb_low = analysis["pullback_low"]
            trend = analysis["trend"]

            # Print summary row
            sig_tag = f"🚨 {signal}" if signal in ["BUY", "SELL"] else "NEUTRAL"
            print(f"{symbol:<12} | Price: {current_price:<12.4f} | 200 EMA: {ema200:<12.4f} | PB-H: {pb_high:<10.4f} | PB-L: {pb_low:<10.4f} | {sig_tag}")

            if signal in ["BUY", "SELL"]:
                if open_count >= MAX_OPEN_POSITIONS:
                    log(f"Signal triggered for {symbol}, but max open positions ({MAX_OPEN_POSITIONS}) reached.", "WARN")
                    break

                sl_price = analysis["stop_loss"]
                tp_price = analysis["take_profit"]
                risk_dist = analysis["risk"]
                reward_dist = abs(tp_price - current_price)

                log(f"VALID {signal} BREAKOUT DETECTED FOR {symbol}!", "SIGNAL")
                log(f"Entry: {current_price:.4f} | SL: {sl_price:.4f} | TP: {tp_price:.4f} | 1:2 RR", "SIGNAL")

                side = "buy" if signal == "BUY" else "sell"
                result = self.place_bracket_market_order(
                    product_id=product_id,
                    symbol=symbol,
                    side=side,
                    size=order_size,
                    sl_price=sl_price,
                    tp_price=tp_price,
                    tick_size=tick_size
                )
                if result.get("success"):
                    open_count += 1
                    open_product_ids.add(product_id)

    def run_forever(self):
        """Starts continuous trading loop running every POLL_INTERVAL seconds."""
        print("""
================================================================================
  _  ______  _  __  _____              _         ____        _   
 | |/ /  _ \| |/ / |_   _| __ __ _  __| | ___   | __ )  ___ | |_ 
 | ' /| | | | ' /    | || '__/ _` |/ _` |/ _ \  |  _ \ / _ \| __|
 | . \| |_| | . \    | || | | (_| | (_| |  __/  | |_) | (_) | |_ 
 |_|\_\____/|_|\_\   |_||_|  \__,_|\__,_|\___|  |____/ \___/ \__|
                                                                 
         Professional All-Futures Delta Exchange Trading Bot
================================================================================
        """)
        log(f"Bot started successfully! Target Base URL: {self.base_url}", "SUCCESS")
        log(f"Monitoring All {len(self.futures_products)} Perpetual Futures Contracts", "INFO")
        log(f"Timeframe: 5-minute | Strategy: 200 EMA Pullback Breakout (1:2 RR)", "INFO")
        log(f"Polling Interval: {POLL_INTERVAL}s | Max Concurrent Trades: {MAX_OPEN_POSITIONS}", "INFO")

        while True:
            try:
                self.run_scan_cycle()
            except KeyboardInterrupt:
                print("\n")
                log("Bot shutdown signal received from user (Ctrl+C). Exiting cleanly...", "WARN")
                sys.exit(0)
            except Exception as e:
                log(f"Unexpected error in main execution loop: {e}", "ERROR")

            log(f"Sleeping for {POLL_INTERVAL} seconds until next market scan...", "INFO")
            try:
                time.sleep(POLL_INTERVAL)
            except KeyboardInterrupt:
                print("\n")
                log("Bot stopped by user. Goodbye!", "WARN")
                sys.exit(0)


def main():
    parser = argparse.ArgumentParser(description="KDK Trade Bot - All-Futures Delta Trader")
    parser.add_argument("--test-once", action="store_true", help="Run a single market scan cycle and exit")
    args = parser.parse_args()

    bot = KDKTradeBot(api_key=API_KEY, api_secret=API_SECRET, base_url=BASE_URL)

    if args.test_once:
        log("Running in single-cycle test mode (--test-once)...", "INFO")
        bot.run_scan_cycle()
        log("Single scan cycle finished.", "SUCCESS")
    else:
        bot.run_forever()


if __name__ == "__main__":
    main()
