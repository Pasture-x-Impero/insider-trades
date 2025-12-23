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

if __name__ == '__main__':
    print("="*60)
    print("Server running at http://localhost:5000")
    print("Open http://localhost:5000 in your browser")
    print("="*60)
    app.run(debug=True, port=5000, use_reloader=False)
