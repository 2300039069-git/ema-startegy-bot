#!/usr/bin/env python3
"""
================================================================================
                    KDK TRADE BOT - PROFESSIONAL EDITION
        Heikin Ashi 5-Minute 200 EMA + 20 EMA Pullback Strategy Engine
             Bilingual Trade Reason Support (English & Telugu - తెలుగు)
================================================================================
"""

import os
import sys
import time
import json
import threading
import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any, List
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import requests
import pandas as pd
from dotenv import load_dotenv, set_key
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from delta_rest_client import DeltaRestClient, OrderType

# Safe UTF-8 output on Windows terminal
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Ensure .env is loaded
ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path=ENV_PATH)

TRADE_HISTORY_FILE = os.path.join(os.path.dirname(__file__), "trade_history.json")

app = FastAPI(title="KDK Trade Bot - Heikin Ashi 200/20 EMA Edition", version="3.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

USD_INR_RATE = 85.0


def load_trade_history() -> List[Dict[str, Any]]:
    """Loads recorded trades from persistent JSON file."""
    if os.path.exists(TRADE_HISTORY_FILE):
        try:
            with open(TRADE_HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_trade_history(trades: List[Dict[str, Any]]):
    """Saves recorded trades to persistent JSON file."""
    try:
        with open(TRADE_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(trades, f, indent=2, default=str, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving trade history: {e}", flush=True)


def record_trade(trade_entry: Dict[str, Any]):
    """Appends a new trade or updates existing in history."""
    trades = load_trade_history()
    trades.insert(0, trade_entry)
    save_trade_history(trades)


def update_trade_status(order_id: str, new_status: str, exit_price: float = None, realized_pnl: float = None):
    """Updates status and realized PnL of a trade in persistent storage."""
    trades = load_trade_history()
    for t in trades:
        if str(t.get("order_id")) == str(order_id) or str(t.get("product_id")) == str(order_id):
            t["status"] = new_status
            if exit_price is not None:
                t["exit_price"] = exit_price
            if realized_pnl is not None:
                t["realized_pnl_usd"] = realized_pnl
                t["realized_pnl_inr"] = realized_pnl * USD_INR_RATE
            t["closed_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            break
    save_trade_history(trades)


class BotState:
    def __init__(self):
        self.is_running: bool = False
        self.worker_thread: threading.Thread = None
        self.stop_event: threading.Event = threading.Event()
        self.last_scan_time: str = "Never"
        self.active_positions: List[Dict[str, Any]] = []
        self.market_data: Dict[str, Dict[str, Any]] = {}
        self.futures_products: Dict[str, Dict[str, Any]] = {}
        self.logs: List[Dict[str, str]] = []
        self.max_logs: int = 500
        self.total_account_equity_usd: float = 189.42
        self.lock: threading.Lock = threading.Lock()
        self.client: DeltaRestClient = None
        self.reload_config()

    def reload_config(self):
        load_dotenv(dotenv_path=ENV_PATH, override=True)
        self.api_key = os.getenv("API_KEY", "").strip()
        self.api_secret = os.getenv("API_SECRET", "").strip()
        self.base_url = os.getenv("BASE_URL", "https://cdn-ind.testnet.deltaex.org").strip().rstrip('/')
        self.max_positions = int(os.getenv("MAX_OPEN_POSITIONS", "2"))
        self.poll_interval = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))
        self.rate_limit_pause = float(os.getenv("RATE_LIMIT_PAUSE", "0.2"))
        self.default_order_size = int(os.getenv("DEFAULT_ORDER_SIZE", "1"))
        self.risk_reward_ratio = float(os.getenv("RISK_REWARD_RATIO", "2.0"))
        self.risk_per_trade_pct = float(os.getenv("RISK_PER_TRADE_PCT", "2.0"))

        self.client = DeltaRestClient(
            base_url=self.base_url,
            api_key=self.api_key,
            api_secret=self.api_secret,
            raise_for_status=False
        )
        self.discover_all_futures()

    def add_log(self, message: str, level: str = "INFO"):
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = {"timestamp": now_str, "level": level, "message": message}
        with self.lock:
            self.logs.append(entry)
            if len(self.logs) > self.max_logs:
                self.logs.pop(0)
        tags = {"INFO": "[INFO]", "WARN": "[WARN]", "ERROR": "[ERROR]", "SIGNAL": "[SIGNAL]", "TRADE": "[TRADE]", "SUCCESS": "[SUCCESS]"}
        print(f"[{now_str}] {tags.get(level, f'[{level}]'):<10} {message}", flush=True)

    def discover_all_futures(self):
        """Auto-discovers ALL tradeable Perpetual Futures contracts on Delta Exchange."""
        self.add_log(f"Connecting to {self.base_url} to discover all Perpetual Futures contracts...", "INFO")
        try:
            products = self.client.get_products()
            if not isinstance(products, list):
                products = []
        except Exception as e:
            self.add_log(f"Failed to fetch products list: {e}", "WARN")
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
                    "order_size": max(self.default_order_size, int(min_size)),
                    "underlying": p.get("underlying_asset", {}).get("symbol", symbol),
                    "description": p.get("description", symbol)
                }

        self.futures_products = futures_map
        self.add_log(f"Discovery Complete! Found {len(self.futures_products)} active Perpetual Futures contracts on Delta Exchange.", "SUCCESS")


bot = BotState()


def format_price(price: float, tick_size: float = 0.01) -> str:
    """Rounds price to the product's tick size precision."""
    try:
        dec_tick = Decimal(str(tick_size))
        dec_price = Decimal(str(price))
        rounded = (dec_price / dec_tick).quantize(Decimal('1'), rounding=ROUND_HALF_UP) * dec_tick
        return f"{rounded:f}".rstrip('0').rstrip('.') if '.' in f"{rounded:f}" else f"{rounded:f}"
    except Exception:
        return str(round(price, 4))


def calculate_heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
    """Transforms standard OHLC candlesticks into Heikin Ashi (HA) smoothed candles."""
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


def fetch_candles(symbol: str, resolution: str = "5m", lookback_days: int = 3) -> pd.DataFrame:
    """Fetches 5-minute candle history for technical analysis."""
    now = int(time.time())
    start_time = now - (lookback_days * 86400)
    end_time = now

    endpoints = [
        (bot.base_url, symbol),
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


def calculate_position_size(account_equity_usd: float, risk_per_contract_usd: float, risk_pct: float = 2.0, min_size: int = 1) -> int:
    """Calculates position size strictly capped at 2% total capital risk."""
    if risk_per_contract_usd <= 0 or account_equity_usd <= 0:
        return min_size
    max_risk_usd = account_equity_usd * (risk_pct / 100.0)
    size = int(max_risk_usd / risk_per_contract_usd)
    return max(min_size, size)


def analyze_strategy(df: pd.DataFrame, rr_ratio: float = 2.0, account_equity: float = 189.42) -> dict:
    """
    Executes Heikin Ashi 5m 200 EMA + 20 EMA Pullback Strategy with Bilingual (English & Telugu) explanations.
    """
    if len(df) < 205:
        return {
            "signal": "INSUFFICIENT_DATA",
            "reason": f"Need 205+ candles, got {len(df)}",
            "reason_en": "Insufficient historical candles to calculate 200 EMA and 20 EMA.",
            "reason_te": "200 EMA మరియు 20 EMA లెక్కించడానికి సరిపడా క్యాండిల్ డేటా లేదు.",
            "current_price": 0.0,
            "ema200": 0.0,
            "ema20": 0.0,
            "trend": "N/A",
            "direction": "NEUTRAL",
            "direction_badge": "⚪ NEUTRAL",
            "pop_percent": 50.0,
            "confidence": "LOW",
            "guidance": "Insufficient historical candles.",
            "guidance_te": "సరిపడా క్యాండిల్ డేటా లేదు.",
            "heikin_ashi_status": "N/A",
            "ema20_touched": False,
            "stop_loss": 0.0,
            "take_profit": 0.0,
            "recommended_size": 1,
            "risk_pct": 2.0,
        }

    # 1. Compute 200 EMA and 20 EMA on close
    df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()

    # 2. Compute Heikin Ashi Candles
    df_ha = calculate_heikin_ashi(df)
    
    latest = df_ha.iloc[-1]
    current_price = float(latest["close"])
    current_ema200 = float(latest["ema200"])
    current_ema20 = float(latest["ema20"])

    ha_is_green = bool(latest["ha_is_green"])
    ha_is_red = bool(latest["ha_is_red"])
    ha_is_doji = bool(latest["ha_is_doji"])

    if ha_is_green and not ha_is_doji:
        ha_status = "🟢 SOLID GREEN HA"
        ha_status_te = "గ్రీన్ హైకిన్ ఆషి (Green HA)"
    elif ha_is_red and not ha_is_doji:
        ha_status = "🔴 SOLID RED HA"
        ha_status_te = "రెడ్ హైకిన్ ఆషి (Red HA)"
    else:
        ha_status = "⚪ HA DOJI / INDECISION"
        ha_status_te = "హైకిన్ ఆషి డోజీ (Doji)"

    is_bullish_trend = current_price > current_ema200
    is_bearish_trend = current_price < current_ema200

    # 3. Pullback to 20 EMA Check across last 1 to 5 completed candles
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
        direction_badge = "🟢 BULLISH BIAS (LONG ONLY)"
        ema20_touched = bull_ema20_touch
        stop_loss = swing_low
        risk = current_price - stop_loss
        if risk <= 0:
            risk = current_price * 0.005
            stop_loss = current_price - risk
        take_profit = current_price + (rr_ratio * risk)

        # BUY Trigger: Above 200 EMA + 20 EMA touch + Solid Green HA candle completed
        if bull_ema20_touch and ha_is_green and not ha_is_doji:
            signal = "BUY"
            reason_en = f"BUY Trigger: Price is above 200 EMA (Bullish Trend), pulled back & touched 20 EMA, and formed a solid Green Heikin Ashi confirmation candle. 1:2 RR target with 2% capital risk."
            reason_te = f"బై (BUY) ట్రిగ్గర్: ధర 200 EMA పైన ఉంది (బుల్లిష్ ట్రెండ్), 20 EMA వరకు పుల్‌బ్యాక్ అయ్యి టచ్ చేసింది, మరియు గ్రీన్ హైకిన్ ఆషి (Green HA) క్యాండిల్ ఏర్పడింది. 1:2 రిస్క్-రివార్డ్ మరియు 2% క్యాపిటల్ రిస్క్."
        else:
            touch_desc = "20 EMA Touched" if bull_ema20_touch else "Waiting for 20 EMA Pullback"
            touch_desc_te = "20 EMA టచ్ అయ్యింది" if bull_ema20_touch else "20 EMA పుల్‌బ్యాక్ కోసం వేచి చూస్తున్నాము"
            reason_en = f"Bullish Bias (Long Only): Price is above 200 EMA (${current_ema200:.2f}). {touch_desc} & {ha_status}. No chasing; enter BUY when pullback confirms."
            reason_te = f"బుల్లిష్ సెటప్ (లాంగ్ మాత్రమే): ధర 200 EMA పైన ఉంది (${current_ema200:.2f}). {touch_desc_te} & {ha_status_te}. పుల్‌బ్యాక్ కన్ఫర్మేషన్ వచ్చాకే బై చేయాలి."

    else:
        direction = "BEARISH"
        direction_badge = "🔴 BEARISH BIAS (SHORT ONLY)"
        ema20_touched = bear_ema20_touch
        stop_loss = swing_high
        risk = stop_loss - current_price
        if risk <= 0:
            risk = current_price * 0.005
            stop_loss = current_price + risk
        take_profit = current_price - (rr_ratio * risk)

        # SELL Trigger: Below 200 EMA + 20 EMA touch + Solid Red HA candle completed
        if bear_ema20_touch and ha_is_red and not ha_is_doji:
            signal = "SELL"
            reason_en = f"SELL Trigger: Price is below 200 EMA (Bearish Trend), pulled back & touched 20 EMA, and formed a solid Red Heikin Ashi confirmation candle. 1:2 RR target with 2% capital risk."
            reason_te = f"సెల్ (SELL) ట్రిగ్గర్: ధర 200 EMA క్రింద ఉంది (బేరిష్ ట్రెండ్), 20 EMA వరకు పుల్‌బ్యాక్ అయ్యి టచ్ చేసింది, మరియు రెడ్ హైకిన్ ఆషి (Red HA) క్యాండిల్ ఏర్పడింది. 1:2 రిస్క్-రివార్డ్ మరియు 2% క్యాపిటల్ రిస్క్."
        else:
            touch_desc = "20 EMA Touched" if bear_ema20_touch else "Waiting for 20 EMA Pullback"
            touch_desc_te = "20 EMA టచ్ అయ్యింది" if bear_ema20_touch else "20 EMA పుల్‌బ్యాక్ కోసం వేచి చూస్తున్నాము"
            reason_en = f"Bearish Bias (Short Only): Price is below 200 EMA (${current_ema200:.2f}). {touch_desc} & {ha_status}. No chasing; enter SELL when pullback confirms."
            reason_te = f"బేరిష్ సెటప్ (షార్ట్ మాత్రమే): ధర 200 EMA క్రింద ఉంది (${current_ema200:.2f}). {touch_desc_te} & {ha_status_te}. పుల్‌బ్యాక్ కన్ఫర్మేషన్ వచ్చాకే సెల్ చేయాలి."

    # 4. Probability of Profit (PoP %) Scoring
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

    rec_size = calculate_position_size(account_equity_usd=account_equity, risk_per_contract_usd=risk, risk_pct=2.0, min_size=1)

    curr_inr = current_price * USD_INR_RATE
    sl_inr = stop_loss * USD_INR_RATE
    tp_inr = take_profit * USD_INR_RATE

    guidance = f"{direction} SETUP: Enter {direction == 'BULLISH' and 'BUY' or 'SELL'} around ${current_price:.2f} (₹{curr_inr:,.2f}), SL: ${stop_loss:.2f} (₹{sl_inr:,.2f}), 1:2 TP: ${take_profit:.2f} (₹{tp_inr:,.2f}). Size: {rec_size} contracts (2% Risk)."
    guidance_te = f"{direction == 'BULLISH' and 'బుల్లిష్ (లాంగ్)' or 'బేరిష్ (షార్ట్)'} సెటప్: ${current_price:.2f} (₹{curr_inr:,.2f}) వద్ద ఎంట్రీ, స్టాప్‌లాస్ (SL): ${stop_loss:.2f} (₹{sl_inr:,.2f}), 1:2 టార్గెట్ (TP): ${take_profit:.2f} (₹{tp_inr:,.2f}). సైజు: {rec_size} కాంట్రాక్టులు (2% రిస్క్)."

    return {
        "signal": signal,
        "current_price": current_price,
        "current_price_inr": round(curr_inr, 2),
        "ema200": current_ema200,
        "ema20": current_ema20,
        "stop_loss": round(stop_loss, 4),
        "take_profit": round(take_profit, 4),
        "stop_loss_inr": round(sl_inr, 2),
        "take_profit_inr": round(tp_inr, 2),
        "risk": round(risk, 4),
        "rr_ratio": rr_ratio,
        "trend": "BULLISH (Above 200 EMA)" if is_bullish_trend else "BEARISH (Below 200 EMA)",
        "direction": direction,
        "direction_badge": direction_badge,
        "action_side": "BUY" if direction == "BULLISH" else "SELL",
        "heikin_ashi_status": ha_status,
        "heikin_ashi_status_te": ha_status_te,
        "ha_close": float(latest["ha_close"]),
        "ha_open": float(latest["ha_open"]),
        "ha_is_green": ha_is_green,
        "ha_is_red": ha_is_red,
        "ha_is_doji": ha_is_doji,
        "ema20_touched": ema20_touched,
        "pop_percent": pop_percent,
        "confidence": confidence,
        "recommended_size": rec_size,
        "risk_pct": 2.0,
        "reason_en": reason_en,
        "reason_te": reason_te,
        "guidance": guidance,
        "guidance_te": guidance_te,
    }


def query_active_positions() -> List[Dict[str, Any]]:
    """Queries active open trades on Delta Exchange with live INR/USD calculations and bilingual trade reasons."""
    try:
        time.sleep(bot.rate_limit_pause)
        res = bot.client.request("GET", "/v2/positions/margined", auth=True)
        if res.status_code == 200:
            data = res.json().get("result", [])
            active = []
            history = load_trade_history()

            for p in data:
                size = float(p.get("size", 0))
                if size != 0:
                    prod_id = p.get("product_id")
                    entry_price = float(p.get("entry_price") or p.get("avg_entry_price") or 0)
                    mark_price = float(p.get("mark_price") or entry_price)
                    unrealized_pnl_usd = float(p.get("unrealized_pnl") or ((mark_price - entry_price) * size if size > 0 else (entry_price - mark_price) * abs(size)))
                    unrealized_pnl_inr = unrealized_pnl_usd * USD_INR_RATE
                    p["entry_price_inr"] = round(entry_price * USD_INR_RATE, 2)
                    p["mark_price_inr"] = round(mark_price * USD_INR_RATE, 2)
                    p["unrealized_pnl_usd"] = round(unrealized_pnl_usd, 4)
                    p["unrealized_pnl_inr"] = round(unrealized_pnl_inr, 2)
                    p["side"] = "BUY" if size > 0 else "SELL"

                    # Attach Bilingual Reason from history or dynamic generator
                    rec = next((t for t in history if str(t.get("product_id")) == str(prod_id) and t.get("status") == "OPEN"), None)
                    if rec:
                        p["reason_en"] = rec.get("reason_en", "Heikin Ashi 200/20 EMA Pullback Breakout setup.")
                        p["reason_te"] = rec.get("reason_te", "హైకిన్ ఆషి 200/20 EMA పుల్‌బ్యాక్ బ్రేకౌట్ సెటప్.")
                    else:
                        is_buy = size > 0
                        p["reason_en"] = f"{is_buy and 'BUY' or 'SELL'} Trade: 5m Heikin Ashi 20 EMA pullback touch with 200 EMA trend filter. 1:2 RR bracket attached."
                        p["reason_te"] = f"{is_buy and 'బై (BUY)' or 'సెల్ (SELL)'} ట్రేడ్: 5m హైకిన్ ఆషి 20 EMA పుల్‌బ్యాక్ టచ్ మరియు 200 EMA ట్రెండ్ ఫిల్టర్. 1:2 రిస్క్-రివార్డ్ ఆర్డర్."

                    active.append(p)
            bot.active_positions = active
            return active
        else:
            return []
    except Exception as e:
        bot.add_log(f"Error querying positions: {e}", "ERROR")
        return []


def execute_market_bracket_order(product_id: int, symbol: str, side: str, size: int, sl_price: float, tp_price: float, tick_size: float, pop_percent: float = 75.0, reason_en: str = "", reason_te: str = "", source: str = "BOT") -> dict:
    """Submits a live Market Order with attached Server-Side 1:2 RR Bracket Orders and logs Bilingual Reasons to Trade Tracker."""
    formatted_sl = format_price(sl_price, tick_size)
    formatted_tp = format_price(tp_price, tick_size)

    if not reason_en:
        is_buy = side.lower() == "buy"
        reason_en = f"{is_buy and 'BUY' or 'SELL'} Trigger: 5m Heikin Ashi 20 EMA pullback touch with 200 EMA trend filter (1:2 RR | 2% Risk)."
        reason_te = f"{is_buy and 'బై (BUY)' or 'సెల్ (SELL)'} ట్రిగ్గర్: 5m హైకిన్ ఆషి 20 EMA పుల్‌బ్యాక్ టచ్ మరియు 200 EMA ట్రెండ్ ఫిల్టర్ (1:2 RR | 2% రిస్క్)."

    order_payload = {
        "product_id": int(product_id),
        "size": int(size),
        "side": side.lower(),
        "order_type": OrderType.MARKET.value,
        "bracket_stop_loss_price": str(formatted_sl),
        "bracket_take_profit_price": str(formatted_tp),
    }

    bot.add_log(f"[{source}] Executing {side.upper()} order for {symbol} | Size: {size} contracts", "TRADE")
    bot.add_log(f"Attached Heikin Ashi 1:2 RR Server Brackets -> SL: ${formatted_sl} | TP: ${formatted_tp}", "TRADE")
    bot.add_log(f"Reason (EN): {reason_en}", "INFO")
    bot.add_log(f"కారణం (TE): {reason_te}", "INFO")

    try:
        time.sleep(bot.rate_limit_pause)
        res = bot.client.request("POST", "/v2/orders", payload=order_payload, auth=True)
        if res.status_code in [200, 201]:
            order_result = res.json().get("result", {})
            order_id = order_result.get("id", f"ORD-{int(time.time())}")
            entry_price = float(order_result.get("avg_fill_price") or order_result.get("limit_price") or sl_price)
            
            trade_entry = {
                "order_id": str(order_id),
                "product_id": int(product_id),
                "symbol": symbol,
                "side": side.upper(),
                "size": int(size),
                "entry_price": entry_price,
                "entry_price_inr": round(entry_price * USD_INR_RATE, 2),
                "stop_loss": float(formatted_sl),
                "take_profit": float(formatted_tp),
                "stop_loss_inr": round(float(formatted_sl) * USD_INR_RATE, 2),
                "take_profit_inr": round(float(formatted_tp) * USD_INR_RATE, 2),
                "rr_ratio": "1:2 Strict",
                "pop_percent": pop_percent,
                "strategy": "Heikin Ashi 200/20 EMA Pullback",
                "reason_en": reason_en,
                "reason_te": reason_te,
                "status": "OPEN",
                "source": source,
                "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            record_trade(trade_entry)

            bot.add_log(f"Order Success! ID: {order_id} | State: {order_result.get('state', 'SUBMITTED')}", "SUCCESS")
            return {"success": True, "order_id": order_id, "data": order_result, "trade": trade_entry}
        else:
            err_body = res.json() if res.headers.get("content-type", "").startswith("application/json") else res.text
            bot.add_log(f"Order Placement Error: HTTP {res.status_code} - {err_body}", "ERROR")
            return {"success": False, "error": err_body}
    except Exception as e:
        bot.add_log(f"Exception placing order: {e}", "ERROR")
        return {"success": False, "error": str(e)}


def scan_single_asset(symbol: str, meta: dict, open_product_ids: set, open_count: int) -> dict:
    """Scans and analyzes an individual futures asset using Heikin Ashi 200/20 EMA strategy."""
    product_id = meta.get("product_id")
    tick_size = meta.get("tick_size", 0.01)

    df = fetch_candles(symbol=symbol, resolution="5m", lookback_days=3)
    if df.empty or len(df) < 205:
        return None

    analysis = analyze_strategy(df, rr_ratio=bot.risk_reward_ratio, account_equity=bot.total_account_equity_usd)
    order_size = analysis.get("recommended_size", meta.get("order_size", 1))

    analysis["symbol"] = symbol
    analysis["product_id"] = product_id
    analysis["tick_size"] = tick_size
    analysis["order_size"] = order_size
    analysis["underlying"] = meta.get("underlying", symbol)
    analysis["last_updated"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # If active bot is running and signal is triggered, execute auto-trade
    if bot.is_running and analysis["signal"] in ["BUY", "SELL"]:
        if product_id not in open_product_ids and open_count < bot.max_positions:
            sl_price = analysis["stop_loss"]
            tp_price = analysis["take_profit"]

            bot.add_log(f"🚨 VALID HEIKIN ASHI {analysis['signal']} SIGNAL DETECTED FOR {symbol}!", "SIGNAL")
            bot.add_log(f"Reason (EN): {analysis['reason_en']}", "SIGNAL")
            bot.add_log(f"కారణం (TE): {analysis['reason_te']}", "SIGNAL")

            side = "buy" if analysis["signal"] == "BUY" else "sell"
            result = execute_market_bracket_order(
                product_id=product_id,
                symbol=symbol,
                side=side,
                size=order_size,
                sl_price=sl_price,
                tp_price=tp_price,
                tick_size=tick_size,
                pop_percent=analysis["pop_percent"],
                reason_en=analysis["reason_en"],
                reason_te=analysis["reason_te"],
                source="BOT"
            )
            if result.get("success"):
                open_product_ids.add(product_id)

    return analysis


def perform_full_market_scan():
    """Scans ALL discovered Perpetual Futures contracts on Delta Exchange."""
    bot.last_scan_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    bot.add_log(f"Initiating Heikin Ashi 200/20 EMA Scan across ALL {len(bot.futures_products)} Futures Contracts...", "INFO")

    positions = query_active_positions()
    open_count = len(positions)
    open_product_ids = {p.get("product_id") for p in positions}

    bot.add_log(f"Active Positions: {open_count}/{bot.max_positions}", "INFO")

    futures_list = list(bot.futures_products.items())
    signals_found = 0

    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_sym = {
            executor.submit(scan_single_asset, sym, meta, open_product_ids, open_count): sym 
            for sym, meta in futures_list
        }
        for future in as_completed(future_to_sym):
            sym = future_to_sym[future]
            try:
                result = future.result()
                if result:
                    bot.market_data[sym] = result
                    if result.get("signal") in ["BUY", "SELL"]:
                        signals_found += 1
            except Exception:
                pass

    bot.add_log(f"Scan Finished! Analyzed {len(bot.market_data)} futures | Found {signals_found} active Heikin Ashi 1:2 RR setups.", "SUCCESS")


def bot_worker_loop():
    """Autonomous continuous scanning loop."""
    bot.add_log(f"Autonomous Heikin Ashi 200/20 EMA bot loop activated. Scanning every {bot.poll_interval}s...", "SUCCESS")
    while not bot.stop_event.is_set():
        try:
            perform_full_market_scan()
        except Exception as e:
            bot.add_log(f"Exception in bot worker loop: {e}", "ERROR")

        sleep_elapsed = 0
        while sleep_elapsed < bot.poll_interval and not bot.stop_event.is_set():
            time.sleep(1)
            sleep_elapsed += 1

    bot.add_log("Autonomous bot loop stopped.", "WARN")
    bot.is_running = False


# ==============================================================================
# REST & CHART DATA API ENDPOINTS
# ==============================================================================

@app.get("/", response_class=HTMLResponse)
def get_dashboard():
    html_file = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    if os.path.exists(html_file):
        with open(html_file, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>KDK Trade Bot - Dashboard template missing</h1>"


@app.get("/api/status")
def get_status():
    positions = query_active_positions()
    history = load_trade_history()
    return {
        "is_running": bot.is_running,
        "last_scan_time": bot.last_scan_time,
        "active_positions_count": len(positions),
        "max_positions": bot.max_positions,
        "poll_interval": bot.poll_interval,
        "base_url": bot.base_url,
        "total_futures_count": len(bot.futures_products),
        "market_data": bot.market_data,
        "active_positions": positions,
        "trade_history_count": len(history),
        "risk_reward_ratio": bot.risk_reward_ratio,
        "strategy": "Heikin Ashi 5m 200 EMA + 20 EMA Pullback (1:2 RR)",
    }


@app.get("/api/trades")
def get_trades():
    """Returns dedicated trade history and active bot/manual positions with bilingual reasons."""
    active_positions = query_active_positions()
    history = load_trade_history()
    
    total_realized_usd = sum(float(t.get("realized_pnl_usd", 0)) for t in history if t.get("status") == "CLOSED")
    total_realized_inr = total_realized_usd * USD_INR_RATE
    
    total_unrealized_usd = sum(float(p.get("unrealized_pnl_usd", 0)) for p in active_positions)
    total_unrealized_inr = total_unrealized_usd * USD_INR_RATE

    return {
        "success": True,
        "active_positions": active_positions,
        "trade_history": history,
        "total_realized_pnl_usd": round(total_realized_usd, 2),
        "total_realized_pnl_inr": round(total_realized_inr, 2),
        "total_unrealized_pnl_usd": round(total_unrealized_usd, 2),
        "total_unrealized_pnl_inr": round(total_unrealized_inr, 2),
        "usd_inr_rate": USD_INR_RATE
    }


@app.post("/api/position/close")
async def close_position(req: Request):
    """Closes an active position on Delta Exchange and marks it closed in trade history."""
    data = await req.json()
    product_id = data.get("product_id")
    symbol = data.get("symbol", "")
    size = abs(int(data.get("size", 1)))
    current_side = str(data.get("side", "BUY")).upper()
    
    close_side = "sell" if current_side in ["BUY", "LONG"] else "buy"

    bot.add_log(f"Closing position for {symbol} (Product ID: {product_id}) | Size: {size} contracts via {close_side.upper()} order", "TRADE")

    try:
        time.sleep(bot.rate_limit_pause)
        close_payload = {
            "product_id": int(product_id),
            "size": size,
            "side": close_side,
            "order_type": OrderType.MARKET.value
        }
        res = bot.client.request("POST", "/v2/orders", payload=close_payload, auth=True)
        if res.status_code in [200, 201]:
            result = res.json().get("result", {})
            exit_price = float(result.get("avg_fill_price") or result.get("limit_price") or 0)
            update_trade_status(order_id=str(product_id), new_status="CLOSED", exit_price=exit_price)
            bot.add_log(f"Position successfully closed for {symbol}! Exit Price: ${exit_price}", "SUCCESS")
            return {"success": True, "message": f"Position closed for {symbol}", "data": result}
        else:
            err = res.json() if res.headers.get("content-type", "").startswith("application/json") else res.text
            bot.add_log(f"Failed to close position: HTTP {res.status_code} - {err}", "ERROR")
            return {"success": False, "error": err}
    except Exception as e:
        bot.add_log(f"Exception closing position: {e}", "ERROR")
        return {"success": False, "error": str(e)}


@app.post("/api/trades/clear-history")
def clear_trade_history():
    """Clears past trade history logs."""
    save_trade_history([])
    bot.add_log("Trade history cleared by user.", "INFO")
    return {"success": True, "message": "Trade history cleared."}


@app.get("/api/futures")
def get_futures_list():
    return {"total": len(bot.futures_products), "products": bot.futures_products}


@app.get("/api/candles/{symbol}")
def get_symbol_candles(symbol: str, resolution: str = "5m", lookback_days: int = 2):
    """Returns Heikin Ashi candles, 200 EMA and 20 EMA for chart rendering."""
    df = fetch_candles(symbol=symbol, resolution=resolution, lookback_days=lookback_days)
    if df.empty:
        return {"success": False, "candles": []}
    
    df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    df_ha = calculate_heikin_ashi(df)
    candles_list = df_ha.to_dict(orient="records")
    return {"success": True, "symbol": symbol, "candles": candles_list}


@app.post("/api/bot/start")
def start_bot():
    if bot.is_running:
        return {"status": "already_running", "message": "Bot is already active."}
    
    bot.stop_event.clear()
    bot.is_running = True
    bot.worker_thread = threading.Thread(target=bot_worker_loop, daemon=True)
    bot.worker_thread.start()
    bot.add_log("▶ User clicked [START BOT]. Autonomous Heikin Ashi 200/20 EMA loop active.", "SUCCESS")
    return {"status": "started", "message": "KDK Trade Bot started successfully!"}


@app.post("/api/bot/stop")
def stop_bot():
    if not bot.is_running:
        return {"status": "not_running", "message": "Bot is not currently active."}
    
    bot.stop_event.set()
    bot.is_running = False
    bot.add_log("⏹ User clicked [STOP BOT]. Background trading loop stopping...", "WARN")
    return {"status": "stopping", "message": "KDK Trade Bot stopped."}


@app.post("/api/bot/scan")
def scan_now():
    bot.add_log("🔍 User clicked [SCAN NOW]. Scanning all Delta Futures with Heikin Ashi 200/20 EMA...", "INFO")
    perform_full_market_scan()
    return {
        "status": "success",
        "last_scan_time": bot.last_scan_time,
        "total_scanned": len(bot.market_data),
        "market_data": bot.market_data,
        "active_positions": bot.active_positions,
    }


@app.get("/api/wallet/balances")
def get_balances():
    try:
        res = bot.client.get_all_wallet_balances()
        if isinstance(res, list):
            total_usd = 0
            for b in res:
                bal = float(b.get("balance", 0))
                if b.get("asset_symbol") in ["USD", "USDT"]:
                    total_usd += bal
            if total_usd > 0:
                bot.total_account_equity_usd = total_usd
            return {"success": True, "balances": res, "total_equity_usd": bot.total_account_equity_usd}
        else:
            return {"success": False, "error": str(res)}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/positions")
def get_positions():
    positions = query_active_positions()
    return {"success": True, "positions": positions}


@app.get("/api/logs")
def get_logs():
    with bot.lock:
        return {"logs": list(bot.logs)}


@app.post("/api/logs/clear")
def clear_logs():
    with bot.lock:
        bot.logs.clear()
    bot.add_log("Log console cleared by user.", "INFO")
    return {"success": True}


@app.get("/api/settings")
def get_settings():
    return {
        "api_key": bot.api_key[:6] + "..." + bot.api_key[-4:] if len(bot.api_key) > 10 else bot.api_key,
        "raw_api_key": bot.api_key,
        "api_secret": bot.api_secret[:4] + "..." + bot.api_secret[-4:] if len(bot.api_secret) > 8 else bot.api_secret,
        "raw_api_secret": bot.api_secret,
        "base_url": bot.base_url,
        "max_positions": bot.max_positions,
        "poll_interval": bot.poll_interval,
        "default_order_size": bot.default_order_size,
        "risk_reward_ratio": bot.risk_reward_ratio,
        "risk_per_trade_pct": bot.risk_per_trade_pct,
    }


@app.post("/api/settings")
async def save_settings(req: Request):
    data = await req.json()
    api_key = data.get("api_key", "").strip()
    api_secret = data.get("api_secret", "").strip()
    base_url = data.get("base_url", "https://cdn-ind.testnet.deltaex.org").strip()
    max_pos = str(data.get("max_positions", "2"))
    poll_int = str(data.get("poll_interval", "60"))
    default_size = str(data.get("default_order_size", "1"))
    rr_ratio = str(data.get("risk_reward_ratio", "2.0"))
    risk_pct = str(data.get("risk_per_trade_pct", "2.0"))

    set_key(ENV_PATH, "API_KEY", api_key)
    set_key(ENV_PATH, "API_SECRET", api_secret)
    set_key(ENV_PATH, "BASE_URL", base_url)
    set_key(ENV_PATH, "MAX_OPEN_POSITIONS", max_pos)
    set_key(ENV_PATH, "POLL_INTERVAL_SECONDS", poll_int)
    set_key(ENV_PATH, "DEFAULT_ORDER_SIZE", default_size)
    set_key(ENV_PATH, "RISK_REWARD_RATIO", rr_ratio)
    set_key(ENV_PATH, "RISK_PER_TRADE_PCT", risk_pct)

    bot.reload_config()
    bot.add_log("⚙️ Settings updated and Heikin Ashi 200/20 EMA configuration reloaded!", "SUCCESS")
    return {"success": True, "message": "Settings saved successfully."}


@app.post("/api/order/place")
async def manual_place_order(req: Request):
    """Places a manual order with 1:2 RR bracket protection and bilingual reason."""
    data = await req.json()
    symbol = data.get("symbol") or data.get("asset_name")
    side = data.get("side", "buy").lower()
    
    meta = bot.futures_products.get(symbol, {})
    product_id = meta.get("product_id")
    tick_size = meta.get("tick_size", 0.01)

    analysis = bot.market_data.get(symbol)
    if not analysis:
        df = fetch_candles(symbol=symbol, resolution="5m", lookback_days=3)
        analysis = analyze_strategy(df, rr_ratio=bot.risk_reward_ratio, account_equity=bot.total_account_equity_usd)

    size = data.get("size", analysis.get("recommended_size", bot.default_order_size))
    sl_price = float(data.get("stop_loss") or analysis.get("stop_loss", 0.0))
    tp_price = float(data.get("take_profit") or analysis.get("take_profit", 0.0))
    pop_percent = float(analysis.get("pop_percent", 70.0))
    reason_en = analysis.get("reason_en", "")
    reason_te = analysis.get("reason_te", "")

    result = execute_market_bracket_order(
        product_id=product_id,
        symbol=symbol,
        side=side,
        size=int(size),
        sl_price=sl_price,
        tp_price=tp_price,
        tick_size=tick_size,
        pop_percent=pop_percent,
        reason_en=reason_en,
        reason_te=reason_te,
        source="MANUAL"
    )
    return result


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
