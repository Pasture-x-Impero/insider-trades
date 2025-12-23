# Swedish Insider Trades Tracker

Track insider trading activity for companies listed on Nasdaq Stockholm using data from Finansinspektionen's PDMR (Persons Discharging Managerial Responsibilities) register.

## Features

- Real-time insider trading data from Swedish companies
- Filter by company name, ticker, or insider name
- Filter by trade type (Buy/Sell)
- Date range filtering
- Clean, responsive UI matching the Norwegian tracker
- Support for both PDMR and close persons trades

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements-swedish.txt
```

### 2. Run the Backend Server

```bash
python swedish-app.py
```

The server will start on http://localhost:5001

### 3. Open in Browser

Navigate to: http://localhost:5001

## Current Implementation

**Important:** The current implementation uses **MOCK DATA** for demonstration purposes. This allows you to see the interface and functionality without needing API keys or the full library setup.

## Getting Real Data

You have three options to get real Swedish insider trading data:

### Option 1: Use the insynsregistret Python Library (Recommended for Free Solution)

1. Install the library:
   ```bash
   pip install insynsregistret
   ```

2. Edit `swedish-app.py`:
   - Comment out the mock data section
   - Uncomment the "Real implementation" section at the bottom

3. Restart the server

**Note:** The Finansinspektionen website has rate limiting. Be respectful with your requests.

### Option 2: Use TIC.io API (Commercial)

1. Sign up for TIC.io API at https://tic.io
2. Get your API key
3. Modify `swedish-app.py` to use the TIC.io endpoint:
   ```python
   API_URL = "https://api.tic.io/datasets/se/finansinspektionen/insider-trading-extended"
   headers = {"x-api-key": "YOUR_API_KEY"}
   ```

**Pros:**
- Reliable, structured API
- Better performance
- Extended data

**Cons:**
- Requires paid subscription

### Option 3: Direct Web Scraping

For advanced users, you can implement direct scraping of the FI website:
- URL: https://www.fi.se/en/our-registers/pdmr-transactions/
- Warning: Subject to rate limiting and blocking

## Data Structure

The backend API returns an array of trade objects:

```json
[
  {
    "id": "12345",
    "publicationDate": "2025-01-15",
    "transactionDate": "2025-01-14",
    "issuer": "Volvo AB",
    "isin": "SE0000115420",
    "pdmr": "Lars Andersson",
    "position": "CEO",
    "closePerson": false,
    "instrumentName": "Share",
    "transactionNature": "Förvärv",
    "quantity": 5000,
    "price": 234.50,
    "currency": "SEK",
    "tradingVenue": "Nasdaq Stockholm",
    "status": "Current"
  }
]
```

## Comparison with Norwegian Tracker

| Feature | Norwegian (app.py) | Swedish (swedish-app.py) |
|---------|-------------------|--------------------------|
| Port | 5000 | 5001 |
| Data Source | Oslo Børs API | Finansinspektionen PDMR |
| API | Direct HTTP API | Library/Scraping |
| Currency | NOK | SEK |
| Rate Limiting | Minimal | Strict (FI limits) |

## Technical Details

### Frontend (`swedish-insider-trades.html`)
- Vanilla JavaScript (no framework dependencies)
- Uses same CSS as Norwegian version (`style.css`)
- Automatically formats Swedish currency (SEK)
- Swedish date formatting (sv-SE locale)

### Backend (`swedish-app.py`)
- Flask web server
- CORS enabled for development
- Mock data generation for testing
- Ready for real data integration

## Known Limitations

1. **Rate Limiting**: Finansinspektionen actively limits requests. Consider:
   - Implementing caching
   - Limiting refresh frequency
   - Using TIC.io API for production

2. **Mock Data**: Current version shows demo data. Follow "Getting Real Data" section to enable live data.

3. **ISIN Codes**: Some companies may not have ISIN codes in all data sources

## Troubleshooting

### Server won't start
- Check if port 5001 is already in use
- Verify Python dependencies are installed: `pip list | grep -i flask`

### No trades showing
- Check browser console for errors (F12)
- Verify backend is running: http://localhost:5001/api/swedish-insider-trades
- Check date range isn't too restrictive

### "insynsregistret not installed" error
- Install: `pip install insynsregistret`
- Or continue using mock data for testing

## Links

- **Finansinspektionen PDMR Register**: https://fi.se/en/our-registers/pdmr-transactions/
- **insynsregistret Python Library**: https://github.com/djonsson/insynsregistret
- **insynsregistret Java Library**: https://github.com/w3stling/insynsregistret
- **TIC.io API Docs**: https://docs.tic.io/api-industry/finansinspektionen/insider-trading-summary

## License

This is a demo application for educational purposes.
