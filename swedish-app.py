#!/usr/bin/env python3
"""
Backend proxy server for Swedish insider trades application.
This server fetches data from Finansinspektionen's PDMR register.

Prerequisites:
    pip install flask flask-cors requests beautifulsoup4 lxml

Usage: python swedish-app.py
Then open http://localhost:5001 in your browser
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
import re
import json
import yfinance as yf

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

# Finansinspektionen PDMR search URL
FI_SEARCH_URL = "https://www.fi.se/en/our-registers/pdmr-transactions/"

@app.route('/')
def index():
    return app.send_static_file('swedish-insider-trades.html')

@app.route('/api/swedish-insider-trades')
def get_swedish_insider_trades():
    """
    Fetch Swedish insider trades from Finansinspektionen.
    Note: This is a simplified implementation that scrapes the FI website.
    For production use, consider using the insynsregistret Python library or TIC.io API.
    """
    from_date = request.args.get('fromDate')

    print(f"Received request for Swedish insider trades with fromDate={from_date}")

    if not from_date:
        # Default to 30 days ago
        default_date = datetime.now() - timedelta(days=30)
        from_date = default_date.strftime('%Y-%m-%d')
        print(f"Using default fromDate={from_date}")

    try:
        # Parse the date
        from_date_obj = datetime.strptime(from_date, '%Y-%m-%d')

        # For now, return mock data until we implement the actual scraping or library
        # This demonstrates the expected data structure
        mock_trades = generate_mock_swedish_trades(from_date_obj)

        print(f"Successfully generated {len(mock_trades)} mock trades")
        print("="*60)
        print("NOTE: This is mock data for demonstration purposes.")
        print("To get real data, you need to:")
        print("1. Install: pip install insynsregistret")
        print("2. Uncomment the real implementation below")
        print("3. Or use TIC.io API with your API key")
        print("="*60)

        return jsonify(mock_trades)

    except Exception as e:
        print(f"Error fetching data: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

def generate_mock_swedish_trades(from_date):
    """
    Generate mock Swedish insider trades data for demonstration.
    Replace this with real data from insynsregistret library or TIC.io API.
    """
    mock_companies = [
        {"name": "Volvo AB", "ticker": "VOLV-B"},
        {"name": "Ericsson AB", "ticker": "ERIC-B"},
        {"name": "H&M Hennes & Mauritz AB", "ticker": "HM-B"},
        {"name": "Atlas Copco AB", "ticker": "ATCO-A"},
        {"name": "Sandvik AB", "ticker": "SAND"},
        {"name": "Hexagon AB", "ticker": "HEXA-B"},
        {"name": "Investor AB", "ticker": "INVE-B"},
        {"name": "Swedbank AB", "ticker": "SWED-A"},
        {"name": "Nordea Bank AB", "ticker": "NDA-SE"},
        {"name": "SEB AB", "ticker": "SEB-A"}
    ]

    mock_insiders = [
        {"name": "Lars Andersson", "position": "CEO"},
        {"name": "Anna Svensson", "position": "CFO"},
        {"name": "Erik Johansson", "position": "Chairman"},
        {"name": "Maria Nilsson", "position": "Board Member"},
        {"name": "Johan Karlsson", "position": "Deputy CEO"}
    ]

    mock_trades = []
    trade_id = 1000

    # Generate trades for the last 30 days
    for i in range(25):  # Generate 25 mock trades
        days_ago = i
        trade_date = datetime.now() - timedelta(days=days_ago)

        if trade_date < from_date:
            continue

        company = mock_companies[i % len(mock_companies)]
        insider = mock_insiders[i % len(mock_insiders)]

        # Randomly alternate between buy and sell
        is_buy = i % 3 != 0  # Roughly 2/3 buys, 1/3 sells

        quantity = (1000 + (i * 500)) * (1 if is_buy else -1)
        price = 100 + (i * 10) + (i % 10)

        trade = {
            "id": str(trade_id + i),
            "publicationDate": trade_date.strftime('%Y-%m-%d'),
            "transactionDate": (trade_date - timedelta(days=1)).strftime('%Y-%m-%d'),
            "issuer": company["name"],
            "isin": f"SE000{i:07d}",
            "ticker": company["ticker"],  # Add ticker for stock data lookups
            "pdmr": insider["name"],
            "position": insider["position"],
            "closePerson": i % 5 == 0,  # 20% are close persons
            "instrumentName": "Share",
            "transactionNature": "Förvärv" if is_buy else "Avyttring",  # Acquisition or Disposal
            "quantity": abs(quantity),
            "price": price,
            "currency": "SEK",
            "tradingVenue": "Nasdaq Stockholm",
            "status": "Current"
        }

        mock_trades.append(trade)

    return mock_trades

# ============================================================================
# UNCOMMENT BELOW TO USE REAL DATA FROM FINANSINSPEKTIONEN
# You need to install: pip install insynsregistret
# ============================================================================

"""
# Real implementation using insynsregistret library
# Uncomment this section and comment out the mock_trades section above

try:
    from insynsregistret import Insynsregistret
    INSYNSREGISTRET_AVAILABLE = True
except ImportError:
    INSYNSREGISTRET_AVAILABLE = False
    print("WARNING: insynsregistret library not installed")
    print("Install with: pip install insynsregistret")

@app.route('/api/swedish-insider-trades-real')
def get_swedish_insider_trades_real():
    '''
    Fetch real Swedish insider trades using the insynsregistret library.
    '''
    if not INSYNSREGISTRET_AVAILABLE:
        return jsonify({"error": "insynsregistret library not installed"}), 500

    from_date = request.args.get('fromDate')

    if not from_date:
        default_date = datetime.now() - timedelta(days=30)
        from_date = default_date.strftime('%Y-%m-%d')

    try:
        # Initialize the insynsregistret client
        client = Insynsregistret()

        # Parse the from_date
        from_date_obj = datetime.strptime(from_date, '%Y-%m-%d')

        # Search for transactions
        # Note: The exact API depends on the insynsregistret library version
        # Check https://github.com/djonsson/insynsregistret for latest usage

        transactions = client.search(
            publication_date_from=from_date_obj,
            publication_date_to=datetime.now()
        )

        # Convert to our expected format
        trades = []
        for t in transactions:
            trade = {
                "id": getattr(t, 'id', ''),
                "publicationDate": getattr(t, 'publication_date', ''),
                "transactionDate": getattr(t, 'transaction_date', ''),
                "issuer": getattr(t, 'issuer', ''),
                "isin": getattr(t, 'isin', ''),
                "pdmr": getattr(t, 'pdmr', ''),
                "position": getattr(t, 'position', ''),
                "closePerson": getattr(t, 'close_person', False),
                "instrumentName": getattr(t, 'instrument_name', ''),
                "transactionNature": getattr(t, 'transaction_nature', ''),
                "quantity": getattr(t, 'quantity', 0),
                "price": getattr(t, 'price', 0),
                "currency": getattr(t, 'currency', 'SEK'),
                "tradingVenue": getattr(t, 'trading_venue', ''),
                "status": getattr(t, 'status', '')
            }
            trades.append(trade)

        return jsonify(trades)

    except Exception as e:
        print(f"Error fetching real data: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
"""

@app.route('/api/stock-data')
def get_stock_data():
    """
    Fetch stock price data for a given ticker (Swedish stocks)
    For Swedish stocks, tries to fetch both A and B share classes
    """
    ticker = request.args.get('ticker')
    trade_date = request.args.get('tradeDate')
    insider_price = request.args.get('insiderPrice')  # Optional: insider's purchase price

    if not ticker:
        return jsonify({"error": "Ticker required"}), 400

    try:
        # For Swedish stocks, try to fetch multiple share classes
        # Extract base ticker (remove -A, -B suffix if present)
        base_ticker = ticker
        if ticker.endswith('-A') or ticker.endswith('-B'):
            base_ticker = ticker[:-2]

        # Always try to fetch both A and B shares, plus the base ticker
        share_classes = [f"{base_ticker}-A", f"{base_ticker}-B", base_ticker]

        all_share_data = []

        for share_class in share_classes:
            try:
                yf_ticker = f"{share_class}.ST" if not share_class.endswith('.ST') else share_class
                print(f"Fetching stock data for {yf_ticker}, trade date: {trade_date}")

                stock = yf.Ticker(yf_ticker)

                # Get current price
                current_data = stock.history(period='1d')
                if current_data.empty:
                    continue

                current_price = current_data['Close'].iloc[-1]

                # Get historical data
                if trade_date:
                    trade_date_obj = datetime.strptime(trade_date, '%Y-%m-%d')
                    start_date = trade_date_obj - timedelta(days=60)
                else:
                    start_date = datetime.now() - timedelta(days=90)

                end_date = datetime.now()
                hist = stock.history(start=start_date, end=end_date)

                if hist.empty:
                    continue

                # Format historical prices
                historical_prices = []
                for date, row in hist.iterrows():
                    historical_prices.append({
                        'date': date.strftime('%Y-%m-%d'),
                        'close': float(row['Close']),
                        'open': float(row['Open']),
                        'high': float(row['High']),
                        'low': float(row['Low']),
                        'volume': int(row['Volume'])
                    })

                share_data = {
                    'ticker': share_class,
                    'currentPrice': float(current_price),
                    'historicalPrices': historical_prices
                }

                # Calculate gap if insider price provided
                if insider_price:
                    try:
                        insider_price_float = float(insider_price)
                        share_data['priceGap'] = abs(current_price - insider_price_float)
                    except:
                        pass

                all_share_data.append(share_data)
                print(f"Successfully fetched data for {share_class}: current price = {current_price}")

            except Exception as e:
                print(f"Could not fetch {share_class}: {str(e)}")
                continue

        if not all_share_data:
            return jsonify({"error": f"No stock data found for {ticker}"}), 404

        # If multiple share classes found, return all of them
        # The frontend will choose which one to display based on the smallest gap
        response_data = {
            'shareClasses': all_share_data,
            'baseTicker': base_ticker
        }

        return jsonify(response_data)

    except Exception as e:
        print(f"Error fetching stock data for {ticker}: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Failed to fetch stock data: {str(e)}"}), 500

if __name__ == '__main__':
    print("="*60)
    print("Swedish Insider Trades Server")
    print("="*60)
    print("Server running at http://localhost:5001")
    print("Open http://localhost:5001 in your browser")
    print("")
    print("NOTE: Currently serving MOCK DATA for demonstration")
    print("")
    print("To use real data:")
    print("1. Install: pip install insynsregistret")
    print("2. Edit swedish-app.py and uncomment the real implementation")
    print("   OR use TIC.io API (requires API key)")
    print("="*60)
    app.run(debug=True, port=5001, use_reloader=False)
