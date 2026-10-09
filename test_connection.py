"""
====================================================================
KDK Trade Bot - Delta Exchange Testnet Connection & Balance Tester
====================================================================
This script tests your Delta Exchange Testnet API credentials, checks
account wallet balance, verifies target trading products, and queries
market tickers and active positions.
"""

import os
import sys
import time
from dotenv import load_dotenv
from delta_rest_client import DeltaRestClient, OrderType

# Ensure UTF-8 output on Windows terminal
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Load environment variables from .env
load_dotenv()

API_KEY = os.getenv("API_KEY", "").strip()
API_SECRET = os.getenv("API_SECRET", "").strip()
BASE_URL = os.getenv("BASE_URL", "https://testnet-api.delta.exchange").strip().rstrip('/')

# Target assets configuration
TARGET_ASSETS = [
    {"name": "BTCUSD", "configured_product_id": 27, "fallback_symbols": ["BTCUSD", "BTCUSDT", "BTC_USDT"]},
    {"name": "ETHUSD", "configured_product_id": 3136, "fallback_symbols": ["ETHUSD", "ETHUSDT", "ETH_USDT"]},
    {"name": "SOLUSD", "configured_product_id": 78, "fallback_symbols": ["SOLUSD", "SOLUSDT", "SOL_USDT"]},
]


def print_header(title: str):
    print("\n" + "=" * 65)
    print(f"  {title}")
    print("=" * 65)


def run_connection_test():
    print_header("KDK TRADE BOT - CONNECTION & DEMO BALANCE CHECK")
    print(f"[*] Base URL    : {BASE_URL}")
    print(f"[*] API Key     : {API_KEY[:6]}...{API_KEY[-4:] if len(API_KEY) > 10 else ''}")
    print(f"[*] API Secret  : {'*' * 10}...{'*' * 4}")
    
    if not API_KEY or not API_SECRET:
        print("\n[!] ERROR: API_KEY or API_SECRET is empty in .env file!")
        print("[!] Please check your .env file and configure your API credentials.")
        return False

    client = DeltaRestClient(
        base_url=BASE_URL,
        api_key=API_KEY,
        api_secret=API_SECRET,
        raise_for_status=False
    )

    # -------------------------------------------------------------
    # Step 1: Public Connectivity & Product Catalog
    # -------------------------------------------------------------
    print("\n[Step 1] Testing Public API & Product Catalog...")
    try:
        products = client.get_products()
        if isinstance(products, list) and len(products) > 0:
            print(f"[+] Successfully connected! Retrieved {len(products)} products from exchange.")
        else:
            print(f"[!] Warning: Received unexpected product response: {products}")
            products = []
    except Exception as e:
        print(f"[-] Failed to fetch products from {BASE_URL}: {e}")
        products = []

    # Map product info
    products_by_id = {p.get("id"): p for p in products if isinstance(p, dict) and "id" in p}
    products_by_symbol = {p.get("symbol"): p for p in products if isinstance(p, dict) and "symbol" in p}

    # -------------------------------------------------------------
    # Step 2: Authenticated Wallet Balances
    # -------------------------------------------------------------
    print("\n[Step 2] Testing API Authentication & Wallet Balances...")
    auth_success = False
    try:
        balances_res = client.get_all_wallet_balances()
        if isinstance(balances_res, list):
            auth_success = True
            print("[+] Authentication SUCCESSFUL! Active Testnet Wallet Balances:")
            print("-" * 75)
            print(f"{'Asset / Currency':<18} | {'Available Balance':<20} | {'Balance in INR (₹)':<25}")
            print("-" * 75)
            
            non_zero_count = 0
            for w in balances_res:
                symbol = w.get("asset_symbol") or w.get("asset", {}).get("symbol") or f"Asset ID {w.get('asset_id')}"
                balance = float(w.get("balance", 0.0) or 0.0)
                available = float(w.get("available_balance", 0.0) or balance)
                inr_balance = float(w.get("balance_inr", 0.0) or 0.0)
                available_inr = float(w.get("available_balance_inr", 0.0) or (available * 85.0))
                
                if balance > 0 or available > 0 or inr_balance > 0:
                    non_zero_count += 1
                    inr_str = f"₹ {available_inr:,.2f} INR" if available_inr > 0 else "₹ 0.00"
                    print(f"{symbol:<18} | {available:<20.4f} | {inr_str:<25}")
            
            if non_zero_count == 0:
                print("  (All asset balances are currently 0.00. You can request demo funds on Testnet)")
            print("-" * 65)
        else:
            print(f"[-] Authentication returned unexpected response: {balances_res}")
    except Exception as e:
        print(f"[-] Authentication FAILED: {e}")
        print("\n" + "!" * 65)
        print("  NOTICE: If you see 'invalid_api_key' or '401 HTTP Error',")
        print("  please generate your Demo API Key & Secret at:")
        print("  -> https://testnet.delta.exchange/ (or https://testnet-global.delta.exchange/)")
        print("  and update the API_KEY and API_SECRET in your .env file.")
        print("!" * 65)

    # -------------------------------------------------------------
    # Step 3: Verify Target Products & Live Tickers
    # -------------------------------------------------------------
    print("\n[Step 3] Checking Target Assets Configuration & Tickers...")
    print("-" * 65)
    print(f"{'Asset':<10} | {'Product ID':<12} | {'Contract Symbol':<16} | {'Tick Size':<10} | {'Latest Mark/Close'}")
    print("-" * 65)

    for target in TARGET_ASSETS:
        name = target["name"]
        configured_id = target["configured_product_id"]
        matched_prod = products_by_id.get(configured_id)

        # If not found by configured ID on this particular testnet environment, search by symbol
        if not matched_prod:
            for sym in target["fallback_symbols"]:
                if sym in products_by_symbol:
                    matched_prod = products_by_symbol[sym]
                    break

        if matched_prod:
            prod_id = matched_prod.get("id")
            symbol = matched_prod.get("symbol")
            tick_size = matched_prod.get("tick_size", "N/A")
            
            # Fetch latest ticker price
            try:
                time.sleep(0.1)  # small pause
                ticker = client.get_ticker(symbol)
                latest_price = ticker.get("mark_price") or ticker.get("close") or ticker.get("spot_price") or "N/A"
            except Exception:
                latest_price = "N/A"

            print(f"{name:<10} | {prod_id:<12} | {symbol:<16} | {str(tick_size):<10} | {latest_price}")
        else:
            print(f"{name:<10} | {configured_id:<12} | {'NOT FOUND':<16} | {'N/A':<10} | N/A")

    print("-" * 65)

    # -------------------------------------------------------------
    # Step 4: Check Open Positions
    # -------------------------------------------------------------
    if auth_success:
        print("\n[Step 4] Checking Active Open Positions...")
        try:
            positions_res = client.request("GET", "/v2/positions/margined", auth=True)
            active_positions = positions_res.json().get("result", []) if positions_res.status_code == 200 else []
            
            open_pos = [p for p in active_positions if float(p.get("size", 0)) != 0]
            print(f"[+] Total Open Positions: {len(open_pos)}")
            for p in open_pos:
                prod_sym = p.get("product_symbol", f"ID: {p.get('product_id')}")
                size = p.get("size")
                entry = p.get("entry_price")
                pnl = p.get("realized_pnl")
                print(f"    - {prod_sym}: Size={size}, Entry={entry}, Realized PnL={pnl}")
        except Exception as e:
            print(f"[-] Could not fetch positions: {e}")

    # Summary
    print_header("DIAGNOSTIC SUMMARY")
    if auth_success:
        print("[SUCCESS] Delta Exchange Testnet connection & auth verified successfully!")
        print("[READY]   You can now launch the bot with: python kdk_bot.py")
    else:
        print("[ACTION REQUIRED] Update your valid Demo API credentials in .env")
        print("                  Then run 'python test_connection.py' again.")
    print("=" * 65 + "\n")
    return auth_success


if __name__ == "__main__":
    run_connection_test()
