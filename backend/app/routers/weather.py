"""气象监测接口：维护气象数据，覆盖发布预警、升级预警、解除预警等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, FillQueuePayload, PageResult
from app.services.weather import WeatherService

router = APIRouter(prefix="/api/weather", tags=["气象监测"])

service = WeatherService()

LIST_FIELDS = ["站点编号", "辐照度", "风速", "风向", "气温", "湿度", "降雨量", "记录时间"]
STATUSES = ["正常", "大风预警", "暴雨预警", "冰雹预警"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按站点编号检索"),
    status: str | None = Query(default=None, description="正常、大风预警、暴雨预警、冰雹预警"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按站点编号与状态过滤气象监测列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/fill-queue")
def fill_queue(
    station: str | None = Query(default=None, description="按站点编号过滤待补队列"),
) -> dict[str, Any]:
    """生成待补队列：缺辐照度、风速或风向的记录按站点归组，附剩余数量与异常数量。"""
    return service.fill_queue(station=station)


@router.post("/fill-queue/commit")
def commit_fill_queue(payload: FillQueuePayload) -> dict[str, Any]:
    """整组补录：逐条写入，缺站点编号的行退回、其余行继续；同一 request_id 只生效一次。"""
    return service.commit_fill_queue(rows=payload.rows, request_id=payload.request_id)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条气象数据明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"气象数据 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条气象数据，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="气象数据已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条气象数据执行发布预警、升级预警、解除预警；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出气象监测清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "weather", "total": total, "items": items}
