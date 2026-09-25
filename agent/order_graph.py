"""订单状态图。

图节点只做状态转换和路由；任何写入都必须交给 WorkflowExecutor。
这些纯函数可以直接作为 LangGraph 节点使用，演示默认用零依赖 runner，保证离线可跑。
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable

from .order_state import OrderStage, OrderState


def collect_order(state: OrderState, patch: dict[str, Any]) -> OrderState:
    allowed = {"product_id", "product_name", "quantity", "address"}
    unexpected = set(patch) - allowed
    if unexpected:
        raise ValueError(f"不允许更新字段: {sorted(unexpected)}")
    return state.evolve(**patch, confirmed=False, stage=OrderStage.DRAFT,
                        audit=state.audit + ("draft_updated",))


def route_draft(state: OrderState) -> OrderState:
    if not state.product_id or not state.product_name or state.quantity < 1:
        return state.evolve(stage=OrderStage.DRAFT, message="请补充有效商品和数量",
                            audit=state.audit + ("missing_product",))
    if not state.address.strip():
        return state.evolve(stage=OrderStage.WAITING_ADDRESS, message="请补充配送地址",
                            audit=state.audit + ("missing_address",))
    return state.evolve(stage=OrderStage.AWAITING_CONFIRMATION,
                        message="请核对订单预览并确认",
                        audit=state.audit + ("preview_ready",))


def confirm(state: OrderState) -> OrderState:
    if state.stage != OrderStage.AWAITING_CONFIRMATION:
        raise ValueError("订单尚未形成可确认预览")
    return state.evolve(confirmed=True, stage=OrderStage.EXECUTING,
                        message="确认已记录，等待安全执行器处理",
                        audit=state.audit + ("user_confirmed",))


class OrderGraph:
    """与 LangGraph 节点语义一致的确定性本地 runner。"""

    def update(self, state: OrderState, **patch: Any) -> OrderState:
        return route_draft(collect_order(state, patch))

    def confirm(self, state: OrderState) -> OrderState:
        return confirm(state)


def build_langgraph() -> Any:
    """可选构建真实 StateGraph；未安装 langgraph 时给出明确提示。"""
    try:
        from langgraph.graph import END, StateGraph
    except ImportError as exc:  # pragma: no cover - 可选集成
        raise RuntimeError("可选执行 `pip install -e .[langgraph]` 后构建 StateGraph") from exc

    graph = StateGraph(OrderState)
    graph.add_node("route_draft", route_draft)
    graph.set_entry_point("route_draft")
    graph.add_edge("route_draft", END)
    return graph.compile()
