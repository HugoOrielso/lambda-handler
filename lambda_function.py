import json
import os
import logging
from typing import Any, Dict, List

import boto3
import requests
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SPACEX_URL = os.environ.get("SPACEX_URL", "https://api.spacexdata.com/v4/launches")
TABLE_NAME = os.environ.get("TABLE_NAME", "spaces_launches")

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)


# ---------- LÓGICA DE NEGOCIO (pura / testeable) ----------

def fetch_launches() -> List[Dict[str, Any]]:
    """
    Llama a la API pública de SpaceX y devuelve la lista de lanzamientos.
    Lanza RuntimeError si algo sale mal.
    """
    try:
        resp = requests.get(SPACEX_URL, timeout=10)
        resp.raise_for_status()
        launches = resp.json()
        if not isinstance(launches, list):
            raise RuntimeError("SpaceX API did not return a list")
        return launches
    except RuntimeError:
        raise
    except Exception as exc:
        logger.error("Error calling SpaceX API: %s", exc, exc_info=True)
        raise RuntimeError("Failed to fetch launches from SpaceX") from exc


def map_status(raw: Dict[str, Any]) -> str:
    """
    Deriva un campo 'status' legible a partir de upcoming y success.
    upcoming=True           -> 'upcoming'
    upcoming=False, success=True  -> 'success'
    upcoming=False, success=False -> 'failed'
    upcoming=False, success=None  -> 'unknown'
    """
    if raw.get("upcoming"):
        return "upcoming"
    success = raw.get("success")
    if success is True:
        return "success"
    if success is False:
        return "failed"
    return "unknown"


def transform_launch(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normaliza un lanzamiento de la API de SpaceX al formato DynamoDB.
    Lanza ValueError si faltan campos obligatorios (id, date_utc).
    """
    if not raw.get("id"):
        raise ValueError("launch is missing required field: id")
    if not raw.get("date_utc"):
        raise ValueError("launch is missing required field: date_utc")

    links = raw.get("links") or {}
    patch = links.get("patch") or {}

    return {
        "launch_id":      raw["id"],
        "mission_name":   raw.get("name"),
        "flight_number":  raw.get("flight_number"),
        "date_utc":       raw["date_utc"],
        "date_local":     raw.get("date_local"),
        "status":         map_status(raw),
        "upcoming":       raw.get("upcoming"),
        "success":        raw.get("success"),
        "details":        raw.get("details"),
        "launchpad_id":   raw.get("launchpad"),
        "rocket_id":      raw.get("rocket"),
        "auto_update":    raw.get("auto_update"),
        "last_updated_at": raw.get("static_fire_date_utc"),
        "article":        links.get("article"),
        "webcast":        links.get("webcast"),
        "wikipedia":      links.get("wikipedia"),
        "patch_small":    patch.get("small"),
        "patch_large":    patch.get("large"),
    }


def upsert_launches(items: List[Dict[str, Any]]) -> int:
    """
    Inserta o actualiza una lista de lanzamientos en DynamoDB usando batch_writer.
    Retorna la cantidad de items escritos.
    """
    if not items:
        return 0

    try:
        with table.batch_writer() as batch:
            for item in items:
                batch.put_item(Item=item)
        return len(items)
    except (BotoCoreError, ClientError) as exc:
        logger.error("Error writing to DynamoDB: %s", exc, exc_info=True)
        raise


def process_launches() -> Dict[str, Any]:
    """
    Orquesta:
    - Llama a la API
    - Transforma cada lanzamiento
    - Hace upsert en DynamoDB
    Devuelve un resumen con conteos e IDs procesados.
    """
    summary: Dict[str, Any] = {
        "total_from_api": 0,
        "inserted_or_updated": 0,
        "skipped": 0,
        "processed_ids": [],
        "skipped_ids": [],
    }

    raw_launches = fetch_launches()
    summary["total_from_api"] = len(raw_launches)

    valid_items: List[Dict[str, Any]] = []
    for raw in raw_launches:
        try:
            item = transform_launch(raw)
            valid_items.append(item)
            summary["processed_ids"].append(item["launch_id"])
        except Exception as exc:
            logger.warning("Skipping launch %s due to transform error: %s", raw.get("id"), exc)
            summary["skipped"] += 1
            summary["skipped_ids"].append(raw.get("id"))

    if valid_items:
        upsert_launches(valid_items)
        summary["inserted_or_updated"] = len(valid_items)

    return summary


def is_http_event(event: Dict[str, Any]) -> bool:
    """
    Distingue entre invocación HTTP (Function URL / API Gateway)
    y ejecución programada (EventBridge).
    """
    return "httpMethod" in event or "requestContext" in event


def build_http_response(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


# ---------- HANDLER PRINCIPAL ----------

def lambda_handler(event, context):
    logger.info("Received event: %s", json.dumps(event))

    try:
        summary = process_launches()
    except RuntimeError as exc:
        logger.error("Processing failed: %s", exc)
        error_summary = {
            "total_from_api": 0,
            "inserted_or_updated": 0,
            "skipped": 0,
            "processed_ids": [],
            "skipped_ids": [],
            "error": str(exc),
        }
        if is_http_event(event):
            return build_http_response(500, error_summary)
        return error_summary

    if is_http_event(event):
        return build_http_response(200, summary)

    return summary