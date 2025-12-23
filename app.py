#!/usr/bin/env python3
"""
Backend proxy server for the insider trades application.
This server acts as a proxy to avoid CORS issues.

Usage: python app.py
Then open http://localhost:5000 in your browser
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
from datetime import datetime, timedelta
import os
import yfinance as yf

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

API_URL = "https://api3.oslo.oslobors.no/v1/newsreader/list"
MESSAGE_DETAIL_URL = "https://api3.oslo.oslobors.no/v1/newsreader/message"

@app.route('/')
def index():
    return app.send_static_file('insider-trades.html')

@app.route('/api/insider-trades')
def get_insider_trades():
    # Get fromDate parameter from query string
    from_date = request.args.get('fromDate')

    print(f"Received request for insider trades with fromDate={from_date}")

    if not from_date:
        # Default to 30 days ago
        default_date = datetime.now() - timedelta(days=30)
        from_date = default_date.strftime('%Y-%m-%d')
        print(f"Using default fromDate={from_date}")

    try:
        # Make request to Oslo Stock Exchange API for list of messages
        url = f"{API_URL}?category=1102&fromDate={from_date}"
        print(f"Fetching list from: {url}")

        headers = {
            "accept": "*/*",
            "content-type": "application/json"
        }

        response = requests.post(url, headers=headers, timeout=10)
        response.raise_for_status()

        data = response.json()
        messages = data.get('data', {}).get('messages', [])
        print(f"Successfully fetched {len(messages)} messages")

        # Fetch detailed information for each message (including body text)
        # Limit to first 50 messages to avoid too many requests
        detailed_messages = []
        for i, msg in enumerate(messages[:50]):
            message_id = msg.get('messageId')
            if message_id:
                try:
                    detail_url = f"{MESSAGE_DETAIL_URL}?messageId={message_id}"
                    detail_response = requests.post(detail_url, headers=headers, timeout=5)
                    if detail_response.ok:
                        detail_data = detail_response.json()
                        detailed_msg = detail_data.get('data', {}).get('message', {})
                        # Merge detailed data with list data
                        msg['body'] = detailed_msg.get('body', '')
                        print(f"  [{i+1}/{len(messages[:50])}] Fetched details for {msg.get('issuerName', 'Unknown')}")
                except Exception as e:
                    print(f"  Warning: Could not fetch details for message {message_id}: {str(e)}")
                    msg['body'] = ''

            detailed_messages.append(msg)

        # Update the data with detailed messages
        data['data']['messages'] = detailed_messages
        print(f"Completed fetching details for {len(detailed_messages)} messages")

        return jsonify(data)

    except requests.exceptions.RequestException as e:
        print(f"Error fetching data: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/stock-data')
def get_stock_data():
    """
    Fetch stock price data for a given ticker
    """
    ticker = request.args.get('ticker')
    trade_date = request.args.get('tradeDate')

    if not ticker:
        return jsonify({"error": "Ticker required"}), 400

    try:
        # Convert Oslo ticker format to Yahoo Finance format
        # Oslo tickers typically end with .OL
        yf_ticker = f"{ticker}.OL" if not ticker.endswith('.OL') else ticker

        print(f"Fetching stock data for {yf_ticker}, trade date: {trade_date}")

        stock = yf.Ticker(yf_ticker)

        # Get current price
        try:
            current_data = stock.history(period='1d')
            if current_data.empty:
                return jsonify({"error": f"No current data for {ticker}"}), 404

            current_price = current_data['Close'].iloc[-1]
        except Exception as e:
            print(f"Error getting current price: {str(e)}")
            return jsonify({"error": f"Could not fetch current price for {ticker}"}), 404

        # Get historical data
        # Fetch from 60 days before trade date to today
        if trade_date:
            trade_date_obj = datetime.strptime(trade_date, '%Y-%m-%d')
            start_date = trade_date_obj - timedelta(days=60)
        else:
            start_date = datetime.now() - timedelta(days=90)

        end_date = datetime.now()

        hist = stock.history(start=start_date, end=end_date)

        if hist.empty:
            return jsonify({"error": f"No historical data for {ticker}"}), 404

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

        response_data = {
            'ticker': ticker,
            'currentPrice': float(current_price),
            'historicalPrices': historical_prices
        }

        print(f"Successfully fetched data for {ticker}: current price = {current_price}")
        return jsonify(response_data)

    except Exception as e:
        print(f"Error fetching stock data for {ticker}: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Failed to fetch stock data: {str(e)}"}), 500

if __name__ == '__main__':
    print("="*60)
    print("Server running at http://localhost:5000")
    print("Open http://localhost:5000 in your browser")
    print("="*60)
    app.run(debug=True, port=5000, use_reloader=False)
