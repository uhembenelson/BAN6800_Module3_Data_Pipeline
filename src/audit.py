"""Privacy audit logging for every read, transformation and write.

Requirement: *"Implement Privacy Audit Logging for all data access and
transformations"*.

Every pipeline stage emits one JSON object per line to
``artifacts/privacy_audit.log``. The log deliberately records *what class of
data* was touched, how many records, and under which lawful basis - never the
customer values themselves, because an audit log that leaks PII is itself a
breach.
"""

from __future__ import annotations

import json
import logging
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

AUDIT_LOGGER_NAME = "ban6800.privacy.audit"


class JsonLineFormatter(logging.Formatter):
    """Render each record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: D102 - stdlib contract
        payload = getattr(record, "payload", None)
        if payload is None:
            payload = {"event": record.getMessage(), "level": record.levelname}
        payload.setdefault("level", record.levelname)
        payload.setdefault("logger", record.name)
        return json.dumps(payload, default=str, sort_keys=True)


class ConsoleAuditFormatter(logging.Formatter):
    """Compact one-line console view: action, dataset and record count."""

    def format(self, record: logging.LogRecord) -> str:
        payload = getattr(record, "payload", None)
        if not payload:
            return record.getMessage()
        records = payload.get("records_affected", 0)
        return f"{payload.get('action', '?'):<28} {payload.get('dataset', '-'):<48} rows={records}"


def build_audit_logger(log_path: Path, run_id: str) -> logging.Logger:
    """Create (or reset) the audit logger that writes the JSON-lines trail."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(AUDIT_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    file_handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    file_handler.setFormatter(JsonLineFormatter())
    logger.addHandler(file_handler)

    console = logging.StreamHandler()
    console.setFormatter(ConsoleAuditFormatter())
    logger.addHandler(console)
    logger.run_id = run_id  # type: ignore[attr-defined]
    return logger


def new_run_id() -> str:
    """Time-ordered, human-readable run identifier."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"run-{stamp}-{uuid.uuid4().hex[:6]}"


@dataclass
class AuditEvent:
    """One auditable interaction with customer data."""

    action: str
    dataset: str
    records: int = 0
    columns: tuple[str, ...] = ()
    legal_basis: str = "UK GDPR Art. 6(1)(f) legitimate interests"
    severity: str = "INFO"
    detail: dict[str, Any] | None = None

    def as_payload(self, run_id: str, actor: str) -> dict[str, Any]:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "run_id": run_id,
            "actor": actor,
            "action": self.action,
            "dataset": self.dataset,
            "records_affected": self.records,
            "columns_touched": list(self.columns),
            "legal_basis": self.legal_basis,
            "severity": self.severity,
            "detail": self.detail or {},
        }


class PrivacyAuditTrail:
    """Thin wrapper that stamps every event with the run id and actor."""

    def __init__(self, log_path: Path, run_id: str, actor: str, legal_basis: str) -> None:
        self.run_id = run_id
        self.actor = actor
        self.legal_basis = legal_basis
        self.log_path = log_path
        self.logger = build_audit_logger(log_path, run_id)
        self.events: list[dict[str, Any]] = []

    def record(
        self,
        action: str,
        dataset: str,
        records: int = 0,
        columns: tuple[str, ...] = (),
        severity: str = "INFO",
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = AuditEvent(
            action=action,
            dataset=dataset,
            records=records,
            columns=columns,
            legal_basis=self.legal_basis,
            severity=severity,
            detail=detail,
        )
        payload = event.as_payload(self.run_id, self.actor)
        self.events.append(payload)
        self.logger.info("", extra={"payload": payload})
        return payload

    @contextmanager
    def stage(self, action: str, dataset: str, legal_basis: str | None = None) -> Iterator[dict[str, Any]]:
        """Wrap a pipeline stage and log start, completion or failure.

        The yielded dict is mutable: a stage sets ``rows_in``, ``rows_out`` and
        ``columns`` and those values land in the audit line automatically.
        """
        context: dict[str, Any] = {"rows_in": 0, "rows_out": 0, "columns": (), "detail": {}}
        self.record(f"{action}.start", dataset, detail={"run_id": self.run_id})
        try:
            yield context
        except Exception as exc:  # noqa: BLE001 - we re-raise after logging
            self.record(
                f"{action}.failed",
                dataset,
                records=int(context.get("rows_in") or 0),
                columns=tuple(context.get("columns") or ()),
                severity="ERROR",
                detail={"error": f"{type(exc).__name__}: {exc}"},
            )
            raise
        self.record(
            f"{action}.complete",
            dataset,
            records=int(context.get("rows_out") or context.get("rows_in") or 0),
            columns=tuple(context.get("columns") or ()),
            detail={
                "rows_in": context.get("rows_in", 0),
                "rows_out": context.get("rows_out", 0),
                **(context.get("detail") or {}),
            },
        )

    def summary(self) -> dict[str, Any]:
        """Aggregate the trail for the run manifest and the deck."""
        by_action: dict[str, int] = {}
        for event in self.events:
            by_action[event["action"]] = by_action.get(event["action"], 0) + 1
        return {
            "run_id": self.run_id,
            "log_file": str(self.log_path),
            "event_count": len(self.events),
            "events_by_action": by_action,
            "distinct_datasets": sorted({event["dataset"] for event in self.events}),
            "errors": [e for e in self.events if e["severity"] == "ERROR"],
        }
