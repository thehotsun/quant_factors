"""Refresh manifest utilities for data update observability."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd


def frame_summary(df: Optional[pd.DataFrame]) -> Dict[str, Any]:
    if df is None:
        return {"rows": 0, "min_date": None, "max_date": None, "columns": []}
    summary = {
        "rows": int(len(df)),
        "min_date": None,
        "max_date": None,
        "columns": list(df.columns),
    }
    if "date" in df.columns and len(df) > 0:
        dates = pd.to_datetime(df["date"], errors="coerce").dropna()
        if not dates.empty:
            summary["min_date"] = dates.min().date().isoformat()
            summary["max_date"] = dates.max().date().isoformat()
    return summary


class RefreshManifest:
    def __init__(self, path: Path, job: str):
        self.path = Path(path)
        self.job = job
        self.started_at = datetime.now().isoformat()
        self.records: List[Dict[str, Any]] = []

    def record(self, *, name: str, filename: str, status: str,
               df: Optional[pd.DataFrame] = None, error: str = None,
               wrote: Optional[bool] = None):
        item = {
            "name": name,
            "filename": filename,
            "status": status,
            "wrote": wrote,
            "error": error,
        }
        item.update(frame_summary(df))
        self.records.append(item)

    def write(self) -> Dict[str, Any]:
        ended_at = datetime.now().isoformat()
        summary = {
            "total": len(self.records),
            "success": sum(1 for r in self.records if r["status"] == "success"),
            "skipped": sum(1 for r in self.records if r["status"] == "skipped"),
            "failed": sum(1 for r in self.records if r["status"] == "failed"),
            "written": sum(1 for r in self.records if r.get("wrote") is True),
        }
        payload = {
            "job": self.job,
            "started_at": self.started_at,
            "ended_at": ended_at,
            "summary": summary,
            "records": self.records,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)
        return payload
