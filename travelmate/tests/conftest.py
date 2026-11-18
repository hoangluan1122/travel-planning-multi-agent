import os
import tempfile
from pathlib import Path

# Keep test runs away from the developer's product database (travelmate.sqlite3).
_TMP = tempfile.mkdtemp(prefix="travelmate-tests-")
os.environ["TRAVELMATE_DB"] = str(Path(_TMP) / "test.sqlite3")


import pytest  # noqa: E402


class _NoHistory:
    """Past-years weather off by default: unit tests never call the real Open-Meteo archive."""

    async def typical(self, latitude, longitude, dates):
        return []


@pytest.fixture(autouse=True)
def _offline_weather_history(monkeypatch):
    # Tests of the history itself pass their own WeatherHistory(transport=...) to the provider.
    monkeypatch.setattr("app.tools.places.open_data_provider.WeatherHistory", _NoHistory)
