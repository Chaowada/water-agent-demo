"""三分钟可运行演示：浏览器页面通过 SSE 展示完整安全订单流程。"""
from __future__ import annotations

import argparse
import json
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Iterator

from agent.order_graph import OrderGraph
from agent.order_state import OrderState
from agent.workflow_executor import SafetyError, WorkflowExecutor
from mcp.client import McpClient
from mcp.server import McpPermissionError, ReadOnlyMcpServer


def scenario_events() -> Iterator[dict[str, Any]]:
    graph = OrderGraph()
    executor = WorkflowExecutor()
    mcp = McpClient(ReadOnlyMcpServer({"demo-operator": {"ST-001"}}), "demo-operator")

    state = OrderState("demo-request-001", "ST-001", "demo-operator",
                       product_id="P-SPRING-19", product_name="山泉水18.9L", quantity=1)
    yield {"step": 1, "kind": "user", "message": "用户：订1桶山泉水18.9L（缺少地址）"}
    state = graph.update(state)
    yield {"step": 2, "kind": "agent", "message": f"Agent：{state.message}", "stage": state.stage.value}

    yield {"step": 3, "kind": "user", "message": "用户：送到演示路1号，改成3桶纯净水"}
    state = graph.update(state, address="演示路1号", product_id="P-PURE-19",
                         product_name="纯净水18.9L", quantity=3)
    yield {"step": 4, "kind": "preview", "message": "系统生成确认预览", "data": executor.preview(state)}

    state = graph.confirm(state)
    yield {"step": 5, "kind": "user", "message": "用户：确认提交"}
    progress: list[dict[str, Any]] = []
    completed = executor.execute(state, lambda event, data: progress.append({"event": event, **data}))
    for event in progress:
        yield {"step": 5, "kind": "progress", "message": event.pop("message"), "data": event}

    duplicate = executor.execute(state)
    yield {"step": 6, "kind": "security", "message": duplicate.message,
           "data": {"same_order_id": duplicate.order_id == completed.order_id,
                    "backend_write_count": executor.gateway.calls}}

    try:
        mcp.call("product.search", station_id="ST-002", query="专供水")
    except McpPermissionError as exc:
        yield {"step": 7, "kind": "security", "message": f"越权查询被拒绝：{exc}"}

    yield {"step": 8, "kind": "mcp", "message": "MCP 工具清单（全部只读）", "data": mcp.list_tools()}
    try:
        mcp.call("order.create", station_id="ST-001")
    except McpPermissionError as exc:
        yield {"step": 8, "kind": "security", "message": f"MCP 写入被拒绝：{exc}"}

    yield {"step": 9, "kind": "done", "message": "SSE 演示完成；所有订单与地址均为模拟数据。"}


PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Water Agent Demo</title><style>
:root{font-family:Inter,"Microsoft YaHei",sans-serif;color:#123;background:#eef6f8}
body{max-width:920px;margin:0 auto;padding:34px 18px}h1{margin-bottom:6px}.note{color:#52707a}
button{border:0;border-radius:10px;background:#087f8c;color:white;padding:12px 20px;font-size:16px;cursor:pointer}
#log{display:grid;gap:10px;margin-top:20px}.event{background:white;border-left:5px solid #78c6d0;border-radius:10px;padding:13px 16px;box-shadow:0 3px 16px #2342}
.security{border-color:#f0a23b}.done{border-color:#2fa36b}.step{font-size:12px;color:#678;text-transform:uppercase}pre{white-space:pre-wrap;margin:8px 0 0;color:#345}
</style></head><body><h1>水站订单 Agent · 脱敏演示</h1>
<p class="note">点击后由服务器实际执行状态编排、安全写入、幂等检查和只读 MCP。页面通过 SSE 接收进度。</p>
<button id="run">运行 9 步场景</button><div id="log"></div><script>
const btn=document.querySelector('#run'),log=document.querySelector('#log');
btn.onclick=()=>{log.innerHTML='';btn.disabled=true;const es=new EventSource('/events');
es.onmessage=(e)=>{const x=JSON.parse(e.data),d=document.createElement('div');d.className='event '+x.kind;
d.innerHTML=`<div class="step">步骤 ${x.step} · ${x.kind}</div><div>${x.message}</div>${x.data?`<pre>${JSON.stringify(x.data,null,2)}</pre>`:''}`;log.appendChild(d);window.scrollTo(0,document.body.scrollHeight);
if(x.kind==='done'){es.close();btn.disabled=false;}};es.onerror=()=>{es.close();btn.disabled=false;};};
</script></body></html>"""


class DemoHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/":
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            try:
                for event in scenario_events():
                    payload = json.dumps(event, ensure_ascii=False)
                    self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    time.sleep(0.18)
            except OSError:
                pass
            return
        self.send_error(404)

    def log_message(self, fmt: str, *args: Any) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="在终端执行一次场景，不启动网页")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if args.once:
        for event in scenario_events():
            print(json.dumps(event, ensure_ascii=False))
        return
    server = ThreadingHTTPServer(("127.0.0.1", args.port), DemoHandler)
    url = f"http://127.0.0.1:{args.port}"
    print(f"演示已启动：{url}（Ctrl+C 停止）")
    try:
        webbrowser.open(url)
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n演示已停止")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
