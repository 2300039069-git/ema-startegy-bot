# KDK Trade Bot ⚡ (Heikin Ashi 200/20 EMA Professional Edition)

[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Delta Exchange](https://img.shields.io/badge/Delta_Exchange-API_v2-00C087?style=for-the-badge)](https://www.delta.exchange/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/MIT)

An institutional-grade algorithmic trading platform built in Python for **Delta Exchange** (India & Global Testnet/Live). Features dynamic **All-Futures Market Scanning**, **5-Minute Heikin Ashi Candlestick smoothing**, **200 EMA trend filtering**, **20 EMA pullback touch confirmation**, automated **1:2 Risk-to-Reward server-side bracket orders**, and **2% Capital Risk Position Sizing**.

---

## 🌟 Strategy Rules & Specifications

### 1. Chart Setup & Indicators
- **Timeframe:** 5-minute candles (`5m`).
- **Candle Type:** **Heikin Ashi (HA)** Candles (filters market noise, rendering clean green and red trends).
- **Indicator 1 — 200 EMA:** Trend filter.
- **Indicator 2 — 20 EMA:** Pullback line.

---

### 2. Step-by-Step Entry Rules

#### 🟢 Buy (Long) Entry Protocol
1. **Trend Filter:** Price is trading **above the 200 EMA** (Bullish only).
2. **Avoid Chasing:** Never buy in the middle of an extended rally.
3. **Pullback Confirmation:** Wait for price to pull back downwards and **touch the 20 EMA line** ($\text{Low} \le 20\text{ EMA}$).
4. **Candle Signal:** Wait for a solid **Green Heikin Ashi confirmation candle** to form off the 20 EMA (non-doji).
5. **Execution:** Open BUY position once confirmation candle completes.
6. **Stop Loss (SL):** Positioned just below the recent swing low (1–3 candles back).
7. **Take Profit (TP):** Strict **1:2 Risk-to-Reward ratio** ($\text{Entry} + 2 \times \text{Risk}$).
8. **Position Sizing:** Strictly limits risk to **2% of total trading capital**.

#### 🔴 Sell (Short) Entry Protocol
1. **Trend Filter:** Price is trading **below the 200 EMA** (Bearish only).
2. **Avoid Chasing:** Never sell in the middle of an ongoing sharp price drop.
3. **Pullback Confirmation:** Wait for price to pull back upwards and **touch the 20 EMA line** ($\text{High} \ge 20\text{ EMA}$).
4. **Candle Signal:** Wait for a solid **Red Heikin Ashi confirmation candle** to form off the 20 EMA (non-doji).
5. **Execution:** Open SELL position once confirmation candle completes.
6. **Stop Loss (SL):** Positioned just above the recent swing high (1–3 candles back).
7. **Take Profit (TP):** Strict **1:2 Risk-to-Reward ratio** ($\text{Entry} - 2 \times \text{Risk}$).
8. **Position Sizing:** Strictly limits risk to **2% of total trading capital**.

---

## 🌟 Key Platform Features

- **🤖 Dedicated Bot Placed Trades Tracker:**
  - Real-time tracking of all trades placed by the bot & manual executions.
  - Live **Unrealized & Realized PnL in Indian Rupees (₹ INR)** and US Dollars ($ USD).
  - **1-Click Close Position Button** (`POST /api/position/close`).
  - Persistent trade history logging in `trade_history.json`.

- **🌐 All-Futures Dynamic Scanner:** Automatically discovers and scans **ALL Perpetual Futures contracts** on Delta Exchange (BTC, ETH, SOL, XRP, DOGE, ADA, BNB, and 200+ markets).

- **🎯 Probability of Profit (PoP %) Engine:**
  - Evaluates 200 EMA trend, 20 EMA touch status, and Heikin Ashi candle color.
  - Generates clear confidence ratings: `HIGH PROBABILITY (>70%)`, `MODERATE PROBABILITY (55-70%)`, `LOW PROBABILITY (<55%)`.

- **💻 Professional 100% Button-Operated Web Dashboard:**
  - **Dynamic Heikin Ashi Background Canvas:** Animated Heikin Ashi candles with glowing 200 EMA and 20 EMA lines.
  - **Interactive Chart Modal:** View 5m Heikin Ashi candles, 200 EMA, and 20 EMA.
  - **Filter Chips:** `All Assets`, `🚨 20 EMA Signals`, `🎯 20 EMA Touched`, `🟢 Bullish`, `🔴 Bearish`.
  - **Live INR (₹) Balances:** Real-time wallet tracking converted at live exchange rate.

---

## 📁 Project Architecture

```
├── .gitignore                # Protects credentials and local logs
├── .env.example              # Sample environment template
├── requirements.txt          # Python dependencies
├── README.md                 # Complete project documentation
├── app.py                    # FastAPI backend server & Heikin Ashi scanner
├── kdk_bot.py                # Standalone CLI Heikin Ashi bot engine
├── start_gui.py              # 1-Click web browser launcher
├── run_gui.bat               # Windows batch launcher
├── test_connection.py        # Diagnostic script for balance & auth
├── test_strategy.py          # Unit test suite for Heikin Ashi & 200/20 EMA
└── templates/
    └── index.html            # Dark-themed trading dashboard with Heikin Ashi visuals
```

---

## 🚀 Quick Start Guide

### 1. Clone Repository & Install Dependencies
```bash
git clone https://github.com/2300039069-git/ema-startegy-bot.git
cd ema-startegy-bot

pip install -r requirements.txt
```

### 2. Configure API Credentials
Create a `.env` file in the root directory (or copy from `.env.example`):
```ini
API_KEY=your_delta_api_key
API_SECRET=your_delta_api_secret
BASE_URL=https://cdn-ind.testnet.deltaex.org

MAX_OPEN_POSITIONS=2
POLL_INTERVAL_SECONDS=60
RATE_LIMIT_PAUSE=0.2
DEFAULT_ORDER_SIZE=1
RISK_REWARD_RATIO=2.0
RISK_PER_TRADE_PCT=2.0
```

---

## 🎮 Running the Platform

### Option A: Interactive Web Dashboard (Recommended)
```bash
python start_gui.py
```
*(Or double-click `run_gui.bat` on Windows. The dashboard will automatically open at `http://127.0.0.1:8000`)*

### Option B: Run Unit Tests
```bash
python -m unittest test_strategy.py
```

### Option C: Run Standalone CLI Trading Bot
```bash
python kdk_bot.py
```

---

## 🛡️ License

Distributed under the MIT License. See `LICENSE` for more information.
