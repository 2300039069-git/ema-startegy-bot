# KDK Trade Bot ⚡ (Delta Exchange Professional Edition)

[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Delta Exchange](https://img.shields.io/badge/Delta_Exchange-API_v2-00C087?style=for-the-badge)](https://www.delta.exchange/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/MIT)

An institutional-grade algorithmic trading platform built in Python for **Delta Exchange** (India & Global Testnet/Live). Features dynamic **All-Futures Market Scanning**, 200 EMA trend filtering, 3-candle pullback breakout detection, automated **1:2 Risk-to-Reward server-side bracket orders**, and a modern **Web Dashboard with an interactive Trade Chart background**.

---

## 🌟 Key Features

- **🌐 All-Futures Dynamic Discovery:** Automatically discovers and scans **ALL tradeable Perpetual Futures contracts** on Delta Exchange (BTC, ETH, SOL, XRP, DOGE, ADA, BNB, and 200+ live markets).
- **📈 200 EMA Pullback Breakout Strategy (5m Timeframe):**
  - **Trend Filter:** 200 Exponential Moving Average computed on 5-minute close prices.
  - **BUY Breakout Trigger:** Price > 200 EMA **AND** Price breaks above 3-candle pullback high.
  - **SELL Breakdown Trigger:** Price < 200 EMA **AND** Price breaks below 3-candle pullback low.
- **🛡️ Strict 1:2 Risk-to-Reward Server Brackets:**
  - **Stop Loss:** Set at recent swing low (Buy) or swing high (Sell).
  - **Take Profit:** Strict **1:2 RR** target ($\text{Entry} \pm 2 \times \text{Risk}$).
  - Attached directly on Delta Exchange servers via `bracket_stop_loss_price` and `bracket_take_profit_price`.
- **🛡️ Risk Management:** Enforces a maximum limit of **2 concurrent open positions** across all markets.
- **💻 Professional Web GUI Dashboard:**
  - **Dynamic Trade Chart Background Canvas:** Animated candlestick visuals, glowing EMA trendlines, and gridlines.
  - **Interactive Candlestick Modal:** View historical 5-minute price action and 200 EMA for any asset.
  - **Search & Filtering:** Instant search bar and filter chips (`All Assets`, `Active Signals Only`, `Bullish`, `Bearish`).
  - **Live INR (₹) & USD Balances:** Real-time wallet tracking.
  - **100% Button-Operated:** Start/Stop Bot, Scan All Futures, Check Balances, and Settings.
- **⚡ 1-Click Manual Execution:** Place pre-calculated 1:2 RR bracket orders on any futures market directly from the UI.

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
├── test_strategy.py          # Unit test suite verifying 200 EMA & 1:2 RR
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

> **Supported Delta Exchange Base URLs:**
> - India Testnet: `https://cdn-ind.testnet.deltaex.org`
> - Global Testnet: `https://testnet-api.delta.exchange`
> - India Production: `https://api.india.delta.exchange`
> - Global Production: `https://api.delta.exchange`

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
