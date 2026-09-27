"""气象监测业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from app.store import store

MODULE = "weather"
REQUIRED_FIELDS = ["站点编号", "辐照度", "风速"]
BACKFILL_FIELDS = ["辐照度", "风速", "风向"]
STATUS_ORDER = ["正常", "大风预警", "暴雨预警", "冰雹预警"]
ACTION_RULES = {"发布预警": "大风预警", "升级预警": "暴雨预警", "解除预警": "正常"}
NEGATIVE_ACTIONS = []


class WeatherService:
    def __init__(self) -> None:
        # 最近一次整组补录的（指纹, 结果）：连续重复提交只保留一份结果
        self._last_backfill: tuple[str, dict[str, Any]] | None = None

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

    @staticmethod
    def _missing_fields(row: dict[str, Any]) -> list[str]:
        return [field for field in BACKFILL_FIELDS if not str(row.get(field) or "").strip()]

    def _summary(self) -> dict[str, int]:
        """剩余待补数量与异常数量：同一份数据上一起算，保证两个数字出自同一时刻。"""
        rows = store.rows(MODULE)
        return {
            "remaining": sum(1 for row in rows if self._missing_fields(row)),
            "abnormal": sum(1 for row in rows if row.get("abnormal")),
        }

    def build_backfill_queue(self) -> dict[str, Any]:
        """按站点把缺辐照度、风速或风向的记录归成待补队列。"""
        groups: dict[str, list[dict[str, Any]]] = {}
        for row in store.rows(MODULE):
            missing = self._missing_fields(row)
            if not missing:
                continue
            station = str(row.get("站点编号") or "").strip() or "未填写站点"
            item = {field: row.get(field) for field in ["id", "站点编号", *BACKFILL_FIELDS, "记录时间"]}
            item["missing"] = missing
            groups.setdefault(station, []).append(item)
        queue = [{"站点编号": station, "items": items} for station, items in sorted(groups.items())]
        return {"groups": queue, **self._summary()}

    def apply_backfill_group(self, values: dict[str, Any]) -> dict[str, Any]:
        """整组补录：逐条写入；缺站点编号的只退回该条；连续重复提交只保留首次结果。"""
        station = str(values.get("站点编号") or "").strip()
        rows = values.get("rows")
        rows = rows if isinstance(rows, list) else []
        fingerprint = hashlib.sha256(
            json.dumps({"站点编号": station, "rows": rows}, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
        ).hexdigest()
        if self._last_backfill and self._last_backfill[0] == fingerprint:
            return {**self._last_backfill[1], "deduplicated": True}

        written: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                rejected.append({"站点编号": "", "reason": "补录内容不是有效的记录行"})
                continue
            row_station = str(row.get("站点编号") or "").strip()
            if not row_station:
                rejected.append({"站点编号": "", "reason": "缺少站点编号，已退回该条"})
                continue
            entry = self._find_by_id(row.get("id"))
            if entry is None:
                rejected.append({"站点编号": row_station, "reason": "气象数据不存在或已归档"})
                continue
            for field in BACKFILL_FIELDS:
                value = str(row.get(field) or "").strip()
                if value:
                    entry[field] = value
            written.append(entry)

        result: dict[str, Any] = {
            "站点编号": station,
            "written": len(written),
            "rejected": rejected,
            "deduplicated": False,
            **self._summary(),
        }
        self._last_backfill = (fingerprint, result)
        return result

    @staticmethod
    def _find_by_id(raw_id: Any) -> dict[str, Any] | None:
        try:
            entry_id = int(raw_id)
        except (TypeError, ValueError):
            return None
        return store.find(MODULE, entry_id)
