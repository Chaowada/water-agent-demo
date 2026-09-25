"""所有业务写入的唯一入口：参数、策略、执行三层安全边界。"""
from __future__ import annotations

import hashlib
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from .order_state import OrderStage, OrderState


class SafetyError(RuntimeError):
    pass


@dataclass
class InMemoryOrderGateway:
    """模拟后端。生产实现应由后端再次校验租户和幂等键。"""
    orders: dict[str, dict[str, Any]] = field(default_factory=dict)
    calls: int = 0

    def create_order(self, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        if idempotency_key in self.orders:
            return self.orders[idempotency_key]
        self.calls += 1
        suffix = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:8].upper()
        result = {**payload, "order_id": f"DEMO-{suffix}", "status": "created"}
        self.orders[idempotency_key] = result
        return result


class WorkflowExecutor:
    """执行三层边界，并通过幂等账本阻止重复订单。"""

    _STATION_RE = re.compile(r"^ST-\d{3}$")

    def __init__(self, gateway: InMemoryOrderGateway | None = None,
                 actor_stations: dict[str, set[str]] | None = None) -> None:
        self.gateway = gateway or InMemoryOrderGateway()
        self.actor_stations = actor_stations or {"demo-operator": {"ST-001"}}
        self._ledger: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def preview(self, state: OrderState) -> dict[str, Any]:
        self._validate_schema(state)
        self._authorize(state)
        return state.preview

    def execute(self, state: OrderState,
                emit: Callable[[str, dict[str, Any]], None] | None = None) -> OrderState:
        emit = emit or (lambda _event, _data: None)
        emit("validation", {"message": "第1层：参数校验"})
        self._validate_schema(state)
        emit("authorization", {"message": "第2层：站点权限与确认校验"})
        self._authorize(state)
        if state.stage != OrderStage.EXECUTING or not state.confirmed:
            raise SafetyError("写操作必须由用户确认后的 EXECUTING 状态触发")

        emit("idempotency", {"message": "第3层：幂等键与副作用闸门"})
        with self._lock:
            existing = self._ledger.get(state.request_id)
            if existing:
                emit("deduplicated", {"message": "命中幂等记录，返回原订单", **existing})
                return state.evolve(stage=OrderStage.COMPLETED,
                                    order_id=existing["order_id"],
                                    message="重复提交已拦截",
                                    audit=state.audit + ("deduplicated",))
            result = self.gateway.create_order(state.preview, state.request_id)
            self._ledger[state.request_id] = result

        emit("completed", {"message": "模拟订单已创建", **result})
        return state.evolve(stage=OrderStage.COMPLETED,
                            order_id=result["order_id"],
                            message="订单创建成功",
                            audit=state.audit + ("write_committed",))

    def _validate_schema(self, state: OrderState) -> None:
        if not (1 <= len(state.request_id) <= 128):
            raise SafetyError("request_id 长度必须为 1–128")
        if not self._STATION_RE.fullmatch(state.station_id):
            raise SafetyError("站点编号格式无效")
        if not state.product_id.startswith("P-") or not state.product_name.strip():
            raise SafetyError("商品信息无效")
        if type(state.quantity) is not int or not 1 <= state.quantity <= 20:
            raise SafetyError("数量必须为 1–20 的整数")
        if not (2 <= len(state.address.strip()) <= 120):
            raise SafetyError("配送地址长度必须为 2–120")

    def _authorize(self, state: OrderState) -> None:
        allowed = self.actor_stations.get(state.actor_id, set())
        if state.station_id not in allowed:
            raise SafetyError("拒绝跨站点操作")
