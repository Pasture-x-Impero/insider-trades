import json
from pathlib import Path

import httpx
import pytest

from insider_trades.config import Settings
from insider_trades.store import Store

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        db_path=tmp_path / "test.db", sync_on_startup=False, sync_interval_minutes=-1,
        initial_lookback_days=30, http_timeout=5, max_detail_fetch=200, user_agent="test",
    )


@pytest.fixture
def store(settings) -> Store:
    return Store(settings.db_path)


def fake_handler(request: httpx.Request) -> httpx.Response:
    """Serve recorded responses for every upstream the app talks to."""
    url = str(request.url)
    if "oslobors.no/v1/newsreader/list" in url:
        return httpx.Response(200, content=(FIXTURES / "oslo_list_2025-09-01.json").read_bytes())
    if "oslobors.no/v1/newsreader/message" in url:
        mid = request.url.params.get("messageId")
        if mid == "654802":
            return httpx.Response(200, content=(FIXTURES / "oslo_detail_654802.json").read_bytes())
        return httpx.Response(200, json={"data": {"message": {"messageId": int(mid), "body": "", "attachments": [
            {"id": 1, "name": "form.pdf"}]}}})
    if "marknadssok.fi.se" in url:
        return httpx.Response(200, content=(FIXTURES / "fi_export_sample.csv").read_bytes(),
                              headers={"content-type": "text/csv"})
    if "finance/search" in url:
        return httpx.Response(200, json={"quotes": [
            {"symbol": "VOLV-B.ST", "quoteType": "EQUITY", "exchange": "STO"}]})
    if "finance/chart" in url:
        return httpx.Response(200, json={"chart": {"result": [{
            "meta": {"currency": "NOK", "shortName": "Test", "regularMarketPrice": 0.70},
            "timestamp": [1756684800, 1756771200, 1756857600, 1757030400, 1757376000],
            "indicators": {"quote": [{"close": [0.60, 0.62, None, 0.64, 0.70]}]},
        }], "error": None}})
    return httpx.Response(404)


@pytest.fixture
def client() -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(fake_handler))


@pytest.fixture
def oslo_list() -> dict:
    return json.loads((FIXTURES / "oslo_list_2025-09-01.json").read_text())
