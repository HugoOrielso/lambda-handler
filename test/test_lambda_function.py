import json
from unittest.mock import MagicMock, patch

import pytest

import lambda_function as lf


# ---------- HELPERS ----------

def sample_launch(id="abc123", date_utc="2006-03-24T22:30:00.000Z"):
    return {
        "id": id,
        "name": "FalconSat",
        "flight_number": 1,
        "date_utc": date_utc,
        "date_local": "2006-03-25T10:30:00+12:00",
        "upcoming": False,
        "success": True,
        "details": "Test mission",
        "launchpad": "pad-1",
        "rocket": "rocket-1",
        "auto_update": True,
        "static_fire_date_utc": "2006-03-17T00:00:00.000Z",
        "links": {
            "article": "https://example.com/article",
            "webcast": "https://example.com/webcast",
            "wikipedia": "https://example.com/wiki",
            "patch": {
                "small": "https://example.com/small.png",
                "large": "https://example.com/large.png",
            },
        },
    }


# ---------- TEST map_status ----------

@pytest.mark.parametrize(
    "upcoming,success,expected",
    [
        (True, None, "upcoming"),
        (False, True, "success"),
        (False, False, "failed"),
        (False, None, "unknown"),
    ],
)
def test_map_status(upcoming, success, expected):
    launch = {"upcoming": upcoming, "success": success}
    assert lf.map_status(launch) == expected


# ---------- TEST transform_launch (antes parse_launch) ----------

def test_transform_launch_ok():
    raw = sample_launch()
    item = lf.transform_launch(raw)

    assert item["launch_id"] == "abc123"
    assert item["mission_name"] == "FalconSat"
    assert item["flight_number"] == 1
    assert item["date_utc"] == "2006-03-24T22:30:00.000Z"
    assert item["status"] == "success"
    assert item["article"] == "https://example.com/article"
    assert item["patch_small"].endswith("small.png")


def test_transform_launch_missing_fields_raises():
    raw = {"name": "FalconSat"}  # falta id y date_utc
    with pytest.raises(ValueError):
        lf.transform_launch(raw)


def test_transform_launch_handles_missing_links():
    raw = {"id": "abc123", "date_utc": "2006-03-24T22:30:00.000Z", "name": "No links"}
    item = lf.transform_launch(raw)
    assert item["article"] is None
    assert item["patch_small"] is None


# ---------- TEST upsert_launches (batch_writer) ----------

def test_upsert_launches_uses_batch_writer():
    fake_batch = MagicMock()
    fake_table = MagicMock()
    fake_table.batch_writer.return_value.__enter__.return_value = fake_batch

    items = [
        lf.transform_launch(sample_launch(id="a")),
        lf.transform_launch(sample_launch(id="b")),
    ]

    with patch.object(lf, "table", fake_table):
        count = lf.upsert_launches(items)

    assert count == 2
    assert fake_batch.put_item.call_count == 2


def test_upsert_launches_empty_list_returns_zero():
    count = lf.upsert_launches([])
    assert count == 0


# ---------- TEST process_launches ----------

def test_process_launches_ok():
    raw_items = [sample_launch(id="1"), sample_launch(id="2")]

    with patch.object(lf, "fetch_launches", return_value=raw_items), \
         patch.object(lf, "upsert_launches", return_value=2) as upsert_mock:

        summary = lf.process_launches()

    assert summary["total_from_api"] == 2
    assert summary["inserted_or_updated"] == 2
    assert summary["skipped"] == 0
    assert "1" in summary["processed_ids"]
    assert "2" in summary["processed_ids"]
    upsert_mock.assert_called_once()


def test_process_launches_skips_invalid():
    valid = sample_launch(id="1")
    invalid = {"id": "2"}  # falta date_utc -> ValueError en transform_launch

    with patch.object(lf, "fetch_launches", return_value=[valid, invalid]), \
         patch.object(lf, "upsert_launches", return_value=1) as upsert_mock:

        summary = lf.process_launches()

    assert summary["total_from_api"] == 2
    assert summary["inserted_or_updated"] == 1
    assert summary["skipped"] == 1
    assert "2" in summary["skipped_ids"]
    upsert_mock.assert_called_once()


# ---------- TEST fetch_launches ----------

@patch("lambda_function.requests.get")
def test_fetch_launches_http_error(mock_get):
    from requests.exceptions import HTTPError
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = HTTPError("500 error")
    mock_get.return_value = mock_resp

    with pytest.raises(RuntimeError) as excinfo:
        lf.fetch_launches()

    assert "Failed to fetch launches" in str(excinfo.value)


@patch("lambda_function.requests.get")
def test_fetch_launches_invalid_json_raises(mock_get):
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = {"not": "a list"}  # API devuelve dict en vez de list
    mock_get.return_value = mock_resp

    with pytest.raises(RuntimeError) as excinfo:
        lf.fetch_launches()

    assert "did not return a list" in str(excinfo.value)


# ---------- TEST lambda_handler ----------

@patch("lambda_function.fetch_launches")
def test_lambda_handler_handles_fetch_error_http_event(mock_fetch):
    mock_fetch.side_effect = RuntimeError("Boom")

    event = {"httpMethod": "GET"}
    response = lf.lambda_handler(event, None)

    assert response["statusCode"] == 500
    body = json.loads(response["body"])
    assert body["total_from_api"] == 0
    assert "error" in body


@patch("lambda_function.upsert_launches")
@patch("lambda_function.fetch_launches")
def test_lambda_handler_scheduled_event_returns_summary(mock_fetch, mock_upsert):
    mock_fetch.return_value = [sample_launch(id="1")]
    mock_upsert.return_value = 1

    event = {"source": "aws.events"}  # típico de EventBridge
    result = lf.lambda_handler(event, None)

    assert result["total_from_api"] == 1
    assert result["inserted_or_updated"] == 1
    assert result["skipped"] == 0


@patch("lambda_function.upsert_launches")
@patch("lambda_function.fetch_launches")
def test_lambda_handler_http_event_returns_200(mock_fetch, mock_upsert):
    mock_fetch.return_value = [sample_launch(id="1")]
    mock_upsert.return_value = 1

    event = {"httpMethod": "GET"}
    response = lf.lambda_handler(event, None)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["total_from_api"] == 1