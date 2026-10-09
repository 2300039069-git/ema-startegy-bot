# KDK Trade Bot ⚡ (Delta Exchange Professional Edition)

[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Delta Exchange](https://img.shields.io/badge/Delta_Exchange-API_v2-00C087?style=for-the-badge)](https://www.delta.exchange/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/MIT)

An institutional-grade algorithmic trading platform built in Python for **Delta Exchange** (India & Global Testnet/Live). Features dynamic **All-Futures Market Scanning**, 200 EMA + 50 EMA trend filtering, 3-candle pullback breakout detection, **Probability of Profit (PoP %)** calculation engine, **Dedicated Bot Placed Trades Tracker with live INR (₹) PnL**, and a modern **Web Dashboard with an interactive Trade Chart background**.

---

## 🌟 Key Features

- **🤖 Dedicated Bot Placed Trades & Position Tracker:**
  - Real-time tracking of all positions placed autonomously by the bot & manual executions.
  - Live **Unrealized & Realized PnL in Indian Rupees (₹ INR)** and US Dollars ($ USD).
  - Shows Entry Price, Mark Price, Stop Loss, 1:2 Take Profit Target, and Probability of Profit (PoP %).
  - **1-Click Position Close Button** (`POST /api/position/close`) directly from the browser.
  - Persistent trade history logging in `trade_history.json`.

- **🎯 Probability of Profit (PoP %) Engine:**
  - Multi-indicator statistical model scoring every asset on Delta Exchange from **35% to 92% PoP**.
  - Analyzes 200 EMA & 50 EMA trend slope, RSI (14) momentum, ATR (14) target feasibility, and Volume surge.
  - Clear confidence ratings: `HIGH PROBABILITY (>70%)`, `MODERATE PROBABILITY (55-70%)`, `LOW PROBABILITY (<55%)`.

- **🧭 Actionable Directional Trade Guidance (BULLISH vs BEARISH):**
  - Explicit directional guidance for manual traders:
    - 🟢 **BULLISH BIAS (BUY SETUP):** Where to enter BUY, recommended SL, and 1:2 Take Profit target.
    - 🔴 **BEARISH BIAS (SELL SETUP):** Where to enter SELL, recommended SL, and 1:2 Take Profit target.
  - Interactive **1-Click Trade Setup Helper Modal** with pre-calculated 1:2 RR bracket targets.

- **🌐 All-Futures Dynamic Discovery:** Automatically discovers and scans **ALL tradeable Perpetual Futures contracts** on Delta Exchange (BTC, ETH, SOL, XRP, DOGE, ADA, BNB, and 200+ live markets).

- **🛡️ Strict 1:2 Risk-to-Reward Server Brackets:**
  - **Stop Loss:** Set at recent swing low (Buy) or swing high (Sell).
  - **Take Profit:** Strict **1:2 RR** target ($\text{Entry} \pm 2 \times \text{Risk}$).
  - Attached directly on Delta Exchange servers via `bracket_stop_loss_price` and `bracket_take_profit_price`.
  - Enforces a maximum limit of **2 concurrent open positions** across all markets.

- **💻 Professional 100% Button-Operated Web Dashboard:**
  - **Dynamic Trade Chart Background Canvas:** Animated candlestick visuals, glowing EMA trendlines, and gridlines.
  - **Interactive Candlestick Modal:** View historical 5-minute price action, 200 EMA, and 50 EMA.
  - **Search & Filter Chips:** `All Assets`, `🎯 High PoP (>70%)`, `🚨 Active Signals`, `🟢 Bullish`, `🔴 Bearish`.
  - **Live INR (₹) Demo Balances:** Converted at live/fixed exchange rate.

---

## 📁 Project Architecture

```
├── .gitignore                # Protects credentials and virtual envs
├── .env.example              # Sample environment template
├── requirements.txt          # Python dependencies
├── README.md                 # Complete project documentation
├── app.py                    # FastAPI backend server & all-futures scanner
├── kdk_bot.py                # Standalone CLI trading bot engine
├── start_gui.py              # 1-Click web browser launcher
├── run_gui.bat               # Windows batch launcher
├── test_connection.py        # Diagnostic script for balance, tickers & auth
├── test_strategy.py          # Unit test suite verifying 200 EMA, PoP % & 1:2 RR
└── templates/
    └── index.html            # Dark-themed trading dashboard with dynamic chart background
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
```

---

## 🎮 Running the Platform

### Option A: Interactive Web Dashboard (Recommended)
```bash
python start_gui.py
```
*(Or double-click `run_gui.bat` on Windows. The dashboard will automatically open at `http://127.0.0.1:8000`)*

### Option B: Verify Connection & Account Balance
```bash
python test_connection.py
```

### Option C: Run Strategy Unit Tests
```bash
python test_strategy.py
```

### Option D: Run Standalone CLI Trading Bot
```bash
python kdk_bot.py
```

---

## 📊 Strategy Rules & Mathematics

### Buy Trigger Logic:
$$\text{Price} > \text{EMA}_{200} \quad \text{AND} \quad \text{Price} > \max(\text{High}_{t-3}, \text{High}_{t-2}, \text{High}_{t-1})$$
- $\text{Stop Loss} = \min(\text{Low}_{t-3}, \text{Low}_{t-2}, \text{Low}_{t-1})$
- $\text{Risk} = \text{Entry Price} - \text{Stop Loss}$
- $\text{Take Profit} = \text{Entry Price} + (2 \times \text{Risk})$

### Sell Trigger Logic:
$$\text{Price} < \text{EMA}_{200} \quad \text{AND} \quad \text{Price} < \min(\text{Low}_{t-3}, \text{Low}_{t-2}, \text{Low}_{t-1})$$
- $\text{Stop Loss} = \max(\text{High}_{t-3}, \text{High}_{t-2}, \text{High}_{t-1})$
- $\text{Risk} = \text{Stop Loss} - \text{Entry Price}$
- $\text{Take Profit} = \text{Entry Price} - (2 \times \text{Risk})$

---

## 🛡️ License

Distributed under the MIT License. See `LICENSE` for more information.
