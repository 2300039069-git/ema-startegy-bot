#!/usr/bin/env python3
"""
================================================================================
                           KDK TRADE BOT (v3.1)
         Heikin Ashi 5m 200 EMA + 20 EMA Pullback Strategy Engine
             Bilingual Trade Reason Support (English & Telugu)
                      Target: Delta Exchange Testnet
================================================================================
"""

import os
import sys
import time
import argparse
import datetime
from decimal import Decimal, ROUND_HALF_UP
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
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
RISK_PER_TRADE_PCT = float(os.getenv("RISK_PER_TRADE_PCT", "2.0"))
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


def calculate_heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
    """Computes Heikin Ashi OHLC candles from standard OHLC dataframe."""
    df_ha = df.copy()
    if len(df_ha) == 0:
        return df_ha

    ha_close = (df_ha["open"] + df_ha["high"] + df_ha["low"] + df_ha["close"]) / 4.0
    
    ha_open = np.zeros(len(df_ha))
    ha_open[0] = (df_ha["open"].iloc[0] + df_ha["close"].iloc[0]) / 2.0
    for i in range(1, len(df_ha)):
        ha_open[i] = (ha_open[i - 1] + ha_close.iloc[i - 1]) / 2.0
    
    df_ha["ha_open"] = ha_open
    df_ha["ha_close"] = ha_close.values
    df_ha["ha_high"] = np.maximum(df_ha["high"], np.maximum(df_ha["ha_open"], df_ha["ha_close"]))
    df_ha["ha_low"] = np.minimum(df_ha["low"], np.minimum(df_ha["ha_open"], df_ha["ha_close"]))
    
    body_size = (df_ha["ha_close"] - df_ha["ha_open"]).abs()
    candle_range = (df_ha["ha_high"] - df_ha["ha_low"]).replace(0, 1e-9)
    df_ha["ha_is_green"] = df_ha["ha_close"] > df_ha["ha_open"]
    df_ha["ha_is_red"] = df_ha["ha_close"] < df_ha["ha_open"]
    df_ha["ha_is_doji"] = (body_size / candle_range) < 0.15

    return df_ha


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
        self.total_account_equity_usd = 189.42
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

                futures_map[symbol] = {
                    "product_id": prod_id,
                    "symbol": symbol,
                    "contract_type": contract_type,
                    "tick_size": tick_size,
                    "min_size": min_size,
                    "order_size": max(DEFAULT_ORDER_SIZE, int(min_size)),
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
        """Fetches historical candles for 200 EMA and 20 EMA calculation."""
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
        """Computes Heikin Ashi 5m 200 EMA + 20 EMA strategy metrics with Bilingual reasons."""
        if len(df) < 205:
            return {
                "signal": "INSUFFICIENT_DATA",
                "reason": f"Need at least 205 candles, got {len(df)}",
                "reason_en": "Insufficient historical candles to calculate EMAs.",
                "reason_te": "EMAs లెక్కించడానికి సరిపడా క్యాండిల్ డేటా లేదు.",
                "current_price": 0.0,
                "ema200": 0.0,
                "ema20": 0.0,
                "trend": "N/A",
                "pop_percent": 50.0,
                "confidence": "LOW",
                "direction": "NEUTRAL",
            }

        df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
        df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()

        df_ha = calculate_heikin_ashi(df)
        latest = df_ha.iloc[-1]
        current_price = float(latest["close"])
        current_ema200 = float(latest["ema200"])
        current_ema20 = float(latest["ema20"])

        ha_is_green = bool(latest["ha_is_green"])
        ha_is_red = bool(latest["ha_is_red"])
        ha_is_doji = bool(latest["ha_is_doji"])

        is_bullish_trend = current_price > current_ema200
        is_bearish_trend = current_price < current_ema200

        lookback_candles = df_ha.iloc[-6:-1]
        bull_ema20_touch = any(
            (c["low"] <= c["ema20"] * 1.002 and c["high"] >= c["ema20"] * 0.998)
            for _, c in lookback_candles.iterrows()
        )
        bear_ema20_touch = any(
            (c["high"] >= c["ema20"] * 0.998 and c["low"] <= c["ema20"] * 1.002)
            for _, c in lookback_candles.iterrows()
        )

        recent_3 = df_ha.iloc[-4:-1]
        swing_low = float(recent_3["low"].min())
        swing_high = float(recent_3["high"].max())

        signal = "NEUTRAL"
        stop_loss = 0.0
        take_profit = 0.0
        risk = 0.0
        ema20_touched = False

        if is_bullish_trend:
            direction = "BULLISH"
            ema20_touched = bull_ema20_touch
            stop_loss = swing_low
            risk = current_price - stop_loss
            if risk <= 0:
                risk = current_price * 0.005
                stop_loss = current_price - risk
            take_profit = current_price + (rr_ratio * risk)

            if bull_ema20_touch and ha_is_green and not ha_is_doji:
                signal = "BUY"
                reason_en = "BUY Trigger: Above 200 EMA + 20 EMA pullback touch + Solid Green HA candle."
                reason_te = "బై (BUY) ట్రిగ్గర్: 200 EMA పైన ఉంది, 20 EMA పుల్‌బ్యాక్ టచ్ అయ్యింది, మరియు గ్రీన్ హైకిన్ ఆషి క్యాండిల్ వచ్చింది."
            else:
                reason_en = "Bullish Setup: Above 200 EMA. Waiting for 20 EMA pullback and Green HA confirmation."
                reason_te = "బుల్లిష్ సెటప్: 200 EMA పైన ఉంది. 20 EMA పుల్‌బ్యాక్ మరియు గ్రీన్ హైకిన్ ఆషి కోసం వేచి చూడండి."

        else:
            direction = "BEARISH"
            ema20_touched = bear_ema20_touch
            stop_loss = swing_high
            risk = stop_loss - current_price
            if risk <= 0:
                risk = current_price * 0.005
                stop_loss = current_price + risk
            take_profit = current_price - (rr_ratio * risk)

            if bear_ema20_touch and ha_is_red and not ha_is_doji:
                signal = "SELL"
                reason_en = "SELL Trigger: Below 200 EMA + 20 EMA pullback touch + Solid Red HA candle."
                reason_te = "సెల్ (SELL) ట్రిగ్గర్: 200 EMA క్రింద ఉంది, 20 EMA పుల్‌బ్యాక్ టచ్ అయ్యింది, మరియు రెడ్ హైకిన్ ఆషి క్యాండిల్ వచ్చింది."
            else:
                reason_en = "Bearish Setup: Below 200 EMA. Waiting for 20 EMA pullback and Red HA confirmation."
                reason_te = "బేరిష్ సెటప్: 200 EMA క్రింద ఉంది. 20 EMA పుల్‌బ్యాక్ మరియు రెడ్ హైకిన్ ఆషి కోసం వేచి చూడండి."

        pop_score = 40.0
        if (direction == "BULLISH" and current_price > current_ema200) or (direction == "BEARISH" and current_price < current_ema200):
            pop_score += 20.0
        if ema20_touched:
            pop_score += 20.0
        if (direction == "BULLISH" and ha_is_green and not ha_is_doji) or (direction == "BEARISH" and ha_is_red and not ha_is_doji):
            pop_score += 15.0
        elif ha_is_doji:
            pop_score -= 10.0
        if signal in ["BUY", "SELL"]:
            pop_score += 10.0

        pop_percent = round(max(35.0, min(92.0, pop_score)), 1)
        confidence = "HIGH PROBABILITY" if pop_percent >= 70 else ("MODERATE PROBABILITY" if pop_percent >= 55 else "LOW PROBABILITY")

        max_risk_usd = self.total_account_equity_usd * (RISK_PER_TRADE_PCT / 100.0)
        rec_size = max(1, int(max_risk_usd / (risk if risk > 0 else 1.0)))

        return {
            "signal": signal,
            "current_price": current_price,
            "current_price_inr": round(current_price * USD_INR_RATE, 2),
            "ema200": current_ema200,
            "ema20": current_ema20,
            "stop_loss": round(stop_loss, 4),
            "take_profit": round(take_profit, 4),
            "risk": round(risk, 4),
            "rr_ratio": rr_ratio,
            "trend": "BULLISH (Above 200 EMA)" if is_bullish_trend else "BEARISH (Below 200 EMA)",
            "direction": direction,
            "pop_percent": pop_percent,
            "confidence": confidence,
            "ema20_touched": ema20_touched,
            "ha_is_green": ha_is_green,
            "ha_is_red": ha_is_red,
            "ha_is_doji": ha_is_doji,
            "recommended_size": rec_size,
            "reason_en": reason_en,
            "reason_te": reason_te,
        }

    def place_bracket_market_order(self, product_id: int, symbol: str, side: str, size: int, sl_price: float, tp_price: float, tick_size: float, reason_en: str = "", reason_te: str = "") -> dict:
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

        log(f"Submitting {side.upper()} order for {symbol} | Size: {size} contracts", "TRADE")
        log(f"Attached Server-Side Brackets -> Stop Loss: {formatted_sl} | Take Profit: {formatted_tp} (1:2 RR)", "TRADE")
        if reason_en:
            log(f"Reason (EN): {reason_en}", "INFO")
        if reason_te:
            log(f"కారణం (TE): {reason_te}", "INFO")

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
        log(f"Initiating Heikin Ashi 200/20 EMA Scan ({len(self.futures_products)} Futures Contracts)...", "INFO")
        print("=" * 85)

        open_positions = self.get_open_positions()
        open_count = len(open_positions)
        open_product_ids = {p.get("product_id") for p in open_positions}

        log(f"Active Open Positions: {open_count}/{MAX_OPEN_POSITIONS}", "INFO")

        for symbol, meta in self.futures_products.items():
            product_id = meta.get("product_id")
            tick_size = meta.get("tick_size", 0.01)

            df = self.fetch_candles(symbol=symbol, resolution="5m", lookback_days=3)
            if df.empty or len(df) < 205:
                continue

            analysis = self.analyze_strategy(df, rr_ratio=RISK_REWARD_RATIO)
            curr = analysis["current_price"]
            ema200 = analysis["ema200"]
            ema20 = analysis["ema20"]
            sig = analysis["signal"]
            pop = analysis["pop_percent"]
            dir_bias = analysis["direction"]
            order_size = analysis.get("recommended_size", meta.get("order_size", DEFAULT_ORDER_SIZE))

            log(f"[{symbol:<10}] Price: ${curr:<9.4f} | 200 EMA: ${ema200:<8.2f} | 20 EMA: ${ema20:<8.2f} | Bias: {dir_bias:<7} | PoP: {pop:>4.1f}% | Signal: {sig}", "INFO")

            if sig in ["BUY", "SELL"]:
                if product_id in open_product_ids:
                    log(f"Signal ignored for {symbol}: Position already active.", "WARN")
                elif open_count >= MAX_OPEN_POSITIONS:
                    log(f"Signal ignored for {symbol}: Max positions reached ({open_count}/{MAX_OPEN_POSITIONS}).", "WARN")
                else:
                    sl = analysis["stop_loss"]
                    tp = analysis["take_profit"]
                    log(f"🚨 VALID HEIKIN ASHI {sig} TRIGGER! Entry: ${curr:.4f} | SL: ${sl:.4f} | TP: ${tp:.4f} (1:2 RR)", "SIGNAL")
                    log(f"Reason: {analysis['reason_en']}", "SIGNAL")
                    log(f"కారణం: {analysis['reason_te']}", "SIGNAL")
                    side = "buy" if sig == "BUY" else "sell"
                    res = self.place_bracket_market_order(
                        product_id=product_id,
                        symbol=symbol,
                        side=side,
                        size=order_size,
                        sl_price=sl,
                        tp_price=tp,
                        tick_size=tick_size,
                        reason_en=analysis["reason_en"],
                        reason_te=analysis["reason_te"]
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
    parser = argparse.ArgumentParser(description="KDK Trade Bot CLI - Heikin Ashi 200/20 EMA")
    parser.add_argument("--scan-once", action="store_true", help="Execute single scan and exit")
    args = parser.parse_args()

    bot_instance = KDKTradeBot(api_key=API_KEY, api_secret=API_SECRET, base_url=BASE_URL)
    if args.scan_once:
        bot_instance.run_scan_cycle()
    else:
        bot_instance.run()
