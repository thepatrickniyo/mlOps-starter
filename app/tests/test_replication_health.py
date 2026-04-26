from app import classify_trend


def test_classify_trend_growing():
    history = [
        {"lag_seconds": 1.1, "recorded_at": "2026-04-20T08:13:47Z"},
        {"lag_seconds": 1.8, "recorded_at": "2026-04-20T08:13:57Z"},
        {"lag_seconds": 2.9, "recorded_at": "2026-04-20T08:14:07Z"},
        {"lag_seconds": 3.6, "recorded_at": "2026-04-20T08:14:17Z"},
        {"lag_seconds": 4.2, "recorded_at": "2026-04-20T08:14:27Z"},
    ]
    assert classify_trend(history) == "growing"


def test_classify_trend_recovering():
    history = [
        {"lag_seconds": 15.0, "recorded_at": "2026-04-20T08:13:47Z"},
        {"lag_seconds": 12.8, "recorded_at": "2026-04-20T08:13:57Z"},
        {"lag_seconds": 10.2, "recorded_at": "2026-04-20T08:14:07Z"},
        {"lag_seconds": 7.4, "recorded_at": "2026-04-20T08:14:17Z"},
        {"lag_seconds": 4.1, "recorded_at": "2026-04-20T08:14:27Z"},
    ]
    assert classify_trend(history) == "recovering"
