"""Proxy Salesforce Data Bridge API and persist Case / User Story rows."""

from __future__ import annotations

import json
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from . import config
from .db import SfCase, SfUserStory, User, get_db
from .deps import get_current_user, is_manager_or_admin

router = APIRouter(prefix="/api/bridge", tags=["salesforce-bridge"])

_token_cache: dict[str, Any] = {
    "accessToken": None,
    "refreshToken": None,
    "installationId": None,
}

CASE_OBJECTS = {"case"}
USER_STORY_OBJECTS = {"user_story__c", "copado__user_story__c"}


class BridgeDeleteBody(BaseModel):
    ids: list[int] = Field(default_factory=list)
    clearAll: bool = False


def require_bridge_viewer(user: User = Depends(get_current_user)) -> User:
    if not is_manager_or_admin(user):
        raise HTTPException(status_code=403, detail="Admin or Manager only")
    return user


def _bridge_base() -> str:
    return (config.SALESFORCE_BRIDGE_URL or "").rstrip("/")


def _credentials() -> tuple[str, str]:
    email = (config.SALESFORCE_BRIDGE_EMAIL or "").strip()
    password = config.SALESFORCE_BRIDGE_PASSWORD or ""
    if not email or not password:
        raise HTTPException(
            status_code=503,
            detail="Salesforce Bridge credentials are not configured",
        )
    return email, password


async def _login(client: httpx.AsyncClient) -> dict[str, Any]:
    email, password = _credentials()
    installation_id = _token_cache["installationId"] or str(uuid.uuid4())
    _token_cache["installationId"] = installation_id
    res = await client.post(
        f"{_bridge_base()}/v1/auth/login",
        json={
            "email": email,
            "password": password,
            "installationId": installation_id,
        },
        timeout=60.0,
    )
    if res.status_code >= 400:
        detail = (
            res.json().get("error")
            if res.headers.get("content-type", "").startswith("application/json")
            else res.text
        )
        raise HTTPException(
            status_code=502,
            detail=f"Bridge login failed: {detail or res.status_code}",
        )
    data = res.json()
    _token_cache["accessToken"] = data.get("accessToken")
    _token_cache["refreshToken"] = data.get("refreshToken")
    return data


async def _refresh(client: httpx.AsyncClient) -> bool:
    refresh = _token_cache.get("refreshToken")
    installation_id = _token_cache.get("installationId")
    if not refresh or not installation_id:
        return False
    res = await client.post(
        f"{_bridge_base()}/v1/auth/refresh",
        json={"refreshToken": refresh, "installationId": installation_id},
        timeout=60.0,
    )
    if res.status_code >= 400:
        _token_cache["accessToken"] = None
        _token_cache["refreshToken"] = None
        return False
    data = res.json()
    _token_cache["accessToken"] = data.get("accessToken")
    _token_cache["refreshToken"] = data.get("refreshToken")
    return True


async def bridge_request(
    method: str,
    path: str,
    *,
    retry: bool = True,
) -> Any:
    base = _bridge_base()
    if not base:
        raise HTTPException(
            status_code=503,
            detail="SALESFORCE_BRIDGE_URL is not configured",
        )

    async with httpx.AsyncClient() as client:
        if not _token_cache.get("accessToken"):
            await _login(client)

        headers = {
            "Authorization": f"Bearer {_token_cache['accessToken']}",
            "Accept": "application/json",
        }
        res = await client.request(
            method,
            f"{base}{path}",
            headers=headers,
            timeout=60.0,
        )

        if res.status_code == 401 and retry:
            refreshed = await _refresh(client)
            if not refreshed:
                await _login(client)
            return await bridge_request(method, path, retry=False)

        if res.status_code >= 400:
            detail: Any
            try:
                body = res.json()
                detail = body.get("error") or body.get("detail") or body
            except Exception:
                detail = res.text or f"HTTP {res.status_code}"
            raise HTTPException(status_code=502, detail=str(detail))

        if res.status_code == 204 or not res.content:
            return None
        return res.json()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _str(val: Any) -> Optional[str]:
    if val is None:
        return None
    text = str(val).strip()
    return text or None


def _bool(val: Any) -> Optional[bool]:
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "1", "yes")
    return bool(val)


def _classify_object(object_api_name: Optional[str]) -> Optional[str]:
    name = (object_api_name or "").strip().lower()
    if name in CASE_OBJECTS:
        return "case"
    if name in USER_STORY_OBJECTS:
        return "user_story"
    return None


def _case_stable_id(record: dict[str, Any]) -> Optional[str]:
    """Prefer Salesforce Id; fall back to CaseNumber for custom SOQL without Id."""
    sf_id = _str(record.get("Id"))
    if sf_id:
        return sf_id[:18]
    case_number = _str(record.get("CaseNumber"))
    if case_number:
        # Synthetic key stays within sf_cases.sf_id String(18).
        return f"CN{case_number}"[:18]
    return None


def _user_story_stable_id(record: dict[str, Any]) -> Optional[str]:
    sf_id = _str(record.get("Id"))
    if sf_id:
        return sf_id[:18]
    name = _str(record.get("Name"))
    if name:
        return f"US{name}"[:18]
    return None


def _upsert_case(
    db: Session,
    record: dict[str, Any],
    *,
    org_id: Optional[str],
    export_id: Optional[str],
) -> bool:
    case_number = _str(record.get("CaseNumber"))
    sf_id = _case_stable_id(record)
    if not sf_id:
        return False

    row = db.query(SfCase).filter(SfCase.sf_id == sf_id).one_or_none()
    if not row and case_number:
        # Re-link rows previously keyed only by CaseNumber / synthetic id.
        row = (
            db.query(SfCase)
            .filter(SfCase.case_number == case_number)
            .one_or_none()
        )
    if not row:
        row = SfCase(sf_id=sf_id)
        db.add(row)
    else:
        row.sf_id = sf_id
    row.org_id = org_id or _str(record.get("OrgId"))
    row.case_number = case_number
    row.subject = _str(record.get("Subject"))
    row.status = _str(record.get("Status"))
    row.priority = _str(record.get("Priority"))
    row.case_owner = _str(record.get("Case_Owner__c"))
    row.is_closed = _bool(record.get("IsClosed"))
    row.sf_created_date = _str(record.get("CreatedDate"))
    row.sf_last_modified = _str(record.get("LastModifiedDate"))
    row.export_id = export_id
    row.payload = json.dumps(record, default=str)
    row.synced_at = _now()
    return True


def _upsert_user_story(
    db: Session,
    record: dict[str, Any],
    *,
    org_id: Optional[str],
    export_id: Optional[str],
) -> bool:
    sf_id = _user_story_stable_id(record)
    if not sf_id:
        return False
    name = _str(record.get("Name"))
    row = db.query(SfUserStory).filter(SfUserStory.sf_id == sf_id).one_or_none()
    if not row and name:
        row = (
            db.query(SfUserStory)
            .filter(SfUserStory.name == name)
            .one_or_none()
        )
    if not row:
        row = SfUserStory(sf_id=sf_id)
        db.add(row)
    else:
        row.sf_id = sf_id
    row.org_id = org_id
    row.name = _str(record.get("Name"))
    row.title = _str(
        record.get("copado__User_Story_Title__c")
        or record.get("User_Story_Title__c")
        or record.get("Name")
    )
    row.status = _str(
        record.get("copado__Status__c") or record.get("Status__c")
    )
    row.priority = _str(
        record.get("copado__Priority__c") or record.get("Priority__c")
    )
    row.sf_created_date = _str(record.get("CreatedDate"))
    row.sf_last_modified = _str(record.get("LastModifiedDate"))
    row.export_id = export_id
    row.payload = json.dumps(record, default=str)
    row.synced_at = _now()
    return True


def _case_dict(row: SfCase) -> dict[str, Any]:
    return {
        "id": row.id,
        "sfId": row.sf_id,
        "orgId": row.org_id,
        "caseNumber": row.case_number,
        "subject": row.subject,
        "status": row.status,
        "priority": row.priority,
        "caseOwner": row.case_owner,
        "isClosed": row.is_closed,
        "createdDate": row.sf_created_date,
        "lastModified": row.sf_last_modified,
        "exportId": row.export_id,
        "syncedAt": row.synced_at.isoformat() if row.synced_at else None,
    }


def _user_story_dict(row: SfUserStory) -> dict[str, Any]:
    return {
        "id": row.id,
        "sfId": row.sf_id,
        "orgId": row.org_id,
        "name": row.name,
        "title": row.title,
        "status": row.status,
        "priority": row.priority,
        "createdDate": row.sf_created_date,
        "lastModified": row.sf_last_modified,
        "exportId": row.export_id,
        "syncedAt": row.synced_at.isoformat() if row.synced_at else None,
    }


@router.get("/status")
async def bridge_status(_user: User = Depends(require_bridge_viewer)):
    base = _bridge_base()
    if not base:
        return {
            "configured": False,
            "reachable": False,
            "url": "",
            "message": "Set SALESFORCE_BRIDGE_URL in .env",
        }
    try:
        async with httpx.AsyncClient() as client:
            health = await client.get(f"{base}/health", timeout=60.0)
            if health.status_code >= 400:
                return {
                    "configured": True,
                    "reachable": False,
                    "url": base,
                    "message": f"Bridge health returned HTTP {health.status_code}",
                }
            tokens = await _login(client)
        return {
            "configured": True,
            "reachable": True,
            "url": base,
            "message": "Connected",
            "userId": tokens.get("userId"),
        }
    except HTTPException as err:
        return {
            "configured": True,
            "reachable": False,
            "url": base,
            "message": str(err.detail),
        }
    except Exception as err:
        return {
            "configured": True,
            "reachable": False,
            "url": base,
            "message": str(err),
        }


@router.get("/jobs")
async def list_jobs(_user: User = Depends(require_bridge_viewer)):
    return await bridge_request("GET", "/v1/jobs")


@router.post("/sync")
async def sync_from_bridge(
    _user: User = Depends(require_bridge_viewer),
    db: Session = Depends(get_db),
):
    data = await bridge_request("GET", "/v1/jobs")
    jobs = data.get("jobs") if isinstance(data, dict) else []
    if not isinstance(jobs, list):
        jobs = []

    cases_upserted = 0
    stories_upserted = 0
    jobs_processed = 0
    jobs_found = len([j for j in jobs if isinstance(j, dict)])
    skipped = 0
    records_seen = 0
    records_skipped = 0
    errors: list[str] = []

    for job in jobs:
        if not isinstance(job, dict):
            continue
        status = (job.get("status") or "").lower()
        if status not in ("completed", "complete", "success", ""):
            # still try completed-ish jobs; skip failed
            if status in ("failed", "error", "running", "processing", "queued"):
                skipped += 1
                continue
        object_api = job.get("objectApiName") or ""
        kind = _classify_object(object_api)
        if not kind:
            skipped += 1
            continue
        export_id = job.get("exportId")
        if not export_id:
            skipped += 1
            continue
        try:
            batch_payload = await bridge_request(
                "GET", f"/v1/exports/{export_id}/batches"
            )
        except HTTPException as err:
            errors.append(f"{export_id}: {err.detail}")
            continue

        batches = (
            batch_payload.get("batches")
            if isinstance(batch_payload, dict)
            else []
        ) or []
        org_id = _str(job.get("orgId"))
        jobs_processed += 1
        for batch in batches:
            if not isinstance(batch, dict):
                continue
            for record in batch.get("records") or []:
                if not isinstance(record, dict):
                    continue
                records_seen += 1
                if kind == "case":
                    if _upsert_case(
                        db, record, org_id=org_id, export_id=str(export_id)
                    ):
                        cases_upserted += 1
                    else:
                        records_skipped += 1
                else:
                    if _upsert_user_story(
                        db, record, org_id=org_id, export_id=str(export_id)
                    ):
                        stories_upserted += 1
                    else:
                        records_skipped += 1

    db.commit()
    return {
        "ok": True,
        "jobsFound": jobs_found,
        "jobsProcessed": jobs_processed,
        "jobsSkipped": skipped,
        "recordsSeen": records_seen,
        "recordsSkipped": records_skipped,
        "casesUpserted": cases_upserted,
        "userStoriesUpserted": stories_upserted,
        "errors": errors[:10],
    }


@router.get("/cases")
def list_cases(
    _user: User = Depends(require_bridge_viewer),
    db: Session = Depends(get_db),
    status: Optional[str] = None,
    owner: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = Query(200, ge=1, le=1000),
):
    query = db.query(SfCase).order_by(SfCase.synced_at.desc())
    if status:
        query = query.filter(SfCase.status == status)
    if owner:
        query = query.filter(SfCase.case_owner == owner)
    term = (q or "").strip()
    if term:
        like = f"%{term}%"
        query = query.filter(
            or_(
                SfCase.case_number.ilike(like),
                SfCase.subject.ilike(like),
                SfCase.status.ilike(like),
                SfCase.priority.ilike(like),
                SfCase.case_owner.ilike(like),
                SfCase.sf_id.ilike(like),
            )
        )
    rows = query.limit(limit).all()
    return {"cases": [_case_dict(r) for r in rows], "count": len(rows)}


@router.post("/cases/delete")
def delete_cases(
    body: BridgeDeleteBody,
    _user: User = Depends(require_bridge_viewer),
    db: Session = Depends(get_db),
):
    if body.clearAll:
        deleted = db.query(SfCase).delete(synchronize_session=False)
        db.commit()
        return {"ok": True, "deleted": deleted, "clearAll": True}
    ids = sorted({int(i) for i in body.ids if int(i) > 0})
    if not ids:
        raise HTTPException(status_code=400, detail="Provide ids or clearAll")
    deleted = (
        db.query(SfCase)
        .filter(SfCase.id.in_(ids))
        .delete(synchronize_session=False)
    )
    db.commit()
    return {"ok": True, "deleted": deleted, "clearAll": False}


@router.get("/user-stories")
def list_user_stories(
    _user: User = Depends(require_bridge_viewer),
    db: Session = Depends(get_db),
    status: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = Query(200, ge=1, le=1000),
):
    query = db.query(SfUserStory).order_by(SfUserStory.synced_at.desc())
    if status:
        query = query.filter(SfUserStory.status == status)
    term = (q or "").strip()
    if term:
        like = f"%{term}%"
        query = query.filter(
            or_(
                SfUserStory.name.ilike(like),
                SfUserStory.title.ilike(like),
                SfUserStory.status.ilike(like),
                SfUserStory.priority.ilike(like),
                SfUserStory.sf_id.ilike(like),
            )
        )
    rows = query.limit(limit).all()
    return {"userStories": [_user_story_dict(r) for r in rows], "count": len(rows)}


@router.post("/user-stories/delete")
def delete_user_stories(
    body: BridgeDeleteBody,
    _user: User = Depends(require_bridge_viewer),
    db: Session = Depends(get_db),
):
    if body.clearAll:
        deleted = db.query(SfUserStory).delete(synchronize_session=False)
        db.commit()
        return {"ok": True, "deleted": deleted, "clearAll": True}
    ids = sorted({int(i) for i in body.ids if int(i) > 0})
    if not ids:
        raise HTTPException(status_code=400, detail="Provide ids or clearAll")
    deleted = (
        db.query(SfUserStory)
        .filter(SfUserStory.id.in_(ids))
        .delete(synchronize_session=False)
    )
    db.commit()
    return {"ok": True, "deleted": deleted, "clearAll": False}


@router.get("/dashboard")
def bridge_dashboard(
    _user: User = Depends(require_bridge_viewer),
    db: Session = Depends(get_db),
):
    cases = db.query(SfCase).all()
    stories = db.query(SfUserStory).all()

    case_by_status = Counter((c.status or "Unknown") for c in cases)
    case_by_priority = Counter((c.priority or "Unknown") for c in cases)
    case_by_owner = Counter((c.case_owner or "Unknown") for c in cases)
    open_cases = sum(1 for c in cases if c.is_closed is False)
    closed_cases = sum(1 for c in cases if c.is_closed is True)

    us_by_status = Counter((s.status or "Unknown") for s in stories)

    last_case = max((c.synced_at for c in cases), default=None)
    last_us = max((s.synced_at for s in stories), default=None)
    last_synced = max([t for t in (last_case, last_us) if t], default=None)

    return {
        "cases": {
            "total": len(cases),
            "open": open_cases,
            "closed": closed_cases,
            "byStatus": dict(case_by_status.most_common(20)),
            "byPriority": dict(case_by_priority.most_common(20)),
            "byOwner": dict(case_by_owner.most_common(20)),
        },
        "userStories": {
            "total": len(stories),
            "byStatus": dict(us_by_status.most_common(20)),
        },
        "lastSyncedAt": last_synced.isoformat() if last_synced else None,
    }
