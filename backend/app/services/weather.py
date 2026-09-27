"""气象监测业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

import threading
from typing import Any

from app.store import store

MODULE = "weather"
REQUIRED_FIELDS = ["站点编号", "辐照度", "风速"]
FILL_FIELDS = ["辐照度", "风速", "风向"]
STATUS_ORDER = ["正常", "大风预警", "暴雨预警", "冰雹预警"]
ACTION_RULES = {"发布预警": "大风预警", "升级预警": "暴雨预警", "解除预警": "正常"}
NEGATIVE_ACTIONS = []
MAX_FILL_COMMITS = 256


def _missing_fields(row: dict[str, Any]) -> list[str]:
    """待补口径：辐照度、风速、风向任一为空即进入待补队列。"""
    return [field for field in FILL_FIELDS if not str(row.get(field) or "").strip()]


class WeatherService:
    def __init__(self) -> None:
        # request_id -> 首次提交结果；同键重复提交直接返回缓存，保证整组动作只生效一次
        self._fill_commits: dict[str, dict[str, Any]] = {}
        self._fill_lock = threading.Lock()

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("站点编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"气象数据 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于气象监测可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"气象数据已{action}"

    def fill_queue(self, *, station: str | None = None) -> dict[str, Any]:
        """按站点生成待补队列；剩余数量与异常数量始终是全模块口径，不过滤。"""
        rows = store.rows(MODULE)
        pending_rows = [row for row in rows if _missing_fields(row)]
        stations = sorted({str(row.get("站点编号") or "").strip() for row in pending_rows} - {""})
        if station:
            pending_rows = [
                row for row in pending_rows if str(row.get("站点编号") or "").strip() == station
            ]
        items = [
            {
                "id": row.get("id"),
                "站点编号": row.get("站点编号") or "",
                "辐照度": row.get("辐照度") or "",
                "风速": row.get("风速") or "",
                "风向": row.get("风向") or "",
                "记录时间": row.get("记录时间") or "",
                "缺项": _missing_fields(row),
            }
            for row in pending_rows
        ]
        return {
            "station": station or "",
            "stations": stations,
            "items": items,
            "remaining": sum(1 for row in rows if _missing_fields(row)),
            "abnormal": sum(1 for row in rows if row.get("abnormal")),
        }

    def commit_fill_queue(
        self, *, rows: list[dict[str, Any]], request_id: str | None = None
    ) -> dict[str, Any]:
        """整组补录：逐条写入，缺站点编号的行退回并标异常，其余行继续写入。

        同一 request_id 重复提交只保留首次结果；剩余数量与异常数量在处理完后一起重算。
        """
        key = (request_id or "").strip()
        with self._fill_lock:
            if key and key in self._fill_commits:
                cached = dict(self._fill_commits[key])
                cached["deduplicated"] = True
                cached["message"] = "同一整组动作已提交过，本次未重复写入"
                return cached
            written = 0
            rejected: list[dict[str, Any]] = []
            for row in rows:
                station = str(row.get("站点编号") or "").strip()
                entry = self._find_entry(row.get("id"))
                if not station:
                    if entry is not None:
                        entry["abnormal"] = True
                    rejected.append({"row": row, "reason": "缺站点编号，已退回该条并标记异常"})
                    continue
                if entry is None:
                    rejected.append({"row": row, "reason": "记录不存在或已归档，已退回该条"})
                    continue
                entry["站点编号"] = station
                for field in FILL_FIELDS:
                    value = row.get(field)
                    if value is not None and str(value).strip():
                        entry[field] = value
                if not _missing_fields(entry):
                    entry["pending"] = False
                written += 1
            all_rows = store.rows(MODULE)
            result = {
                "ok": True,
                "message": f"整组补录完成：写入 {written} 条，退回 {len(rejected)} 条",
                "written": written,
                "rejected": rejected,
                "remaining": sum(1 for row in all_rows if _missing_fields(row)),
                "abnormal": sum(1 for row in all_rows if row.get("abnormal")),
                "deduplicated": False,
            }
            if key:
                if len(self._fill_commits) >= MAX_FILL_COMMITS:
                    self._fill_commits.pop(next(iter(self._fill_commits)))
                self._fill_commits[key] = result
            return result

    @staticmethod
    def _find_entry(entry_id: Any) -> dict[str, Any] | None:
        if entry_id is None or not str(entry_id).strip():
            return None
        try:
            return store.find(MODULE, int(entry_id))
        except (TypeError, ValueError):
            return None
