"""订单状态契约。

这里只保存编排所需的最小状态，不保存真实客户、手机号或支付信息。
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any


class OrderStage(str, Enum):
    DRAFT = "draft"
    WAITING_ADDRESS = "waiting_address"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    EXECUTING = "executing"
    COMPLETED = "completed"
    REJECTED = "rejected"


@dataclass(frozen=True)
class OrderState:
    request_id: str
    station_id: str
    actor_id: str
    product_id: str = ""
    product_name: str = ""
    quantity: int = 0
    address: str = ""
    confirmed: bool = False
    stage: OrderStage = OrderStage.DRAFT
    revision: int = 0
    order_id: str | None = None
    message: str = ""
    audit: tuple[str, ...] = field(default_factory=tuple)

    def evolve(self, **changes: Any) -> "OrderState":
        """返回新状态，避免节点在确认前偷偷执行副作用。"""
        changes.setdefault("revision", self.revision + 1)
        return replace(self, **changes)

    @property
    def preview(self) -> dict[str, Any]:
        return {
            "station_id": self.station_id,
            "product_id": self.product_id,
            "product_name": self.product_name,
            "quantity": self.quantity,
            "address": self.address,
            "request_id": self.request_id,
        }
