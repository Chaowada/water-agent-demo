# Water Agent Demo

一个可离线运行的脱敏水站订单 Agent 作品仓库，聚焦四个可以审查和复现的模块：订单状态编排、写操作安全边界、只读 MCP、混合 RAG 与120条评测集。

> 数据声明：仓库中的站点、商品、价格、地址、订单和知识内容全部是虚构或模拟数据；不包含真实客户信息、商业后端地址、访问令牌、内部提示词或生产日志。

## 业务问题与架构

水站客服下单看似简单，真正的风险集中在不完整参数、确认前后状态混淆、重复提交生成多单、跨站点越权，以及知识答案引用了旧版本。这个演示把“模型理解”与“业务写入”隔开：状态图收集信息并路由，确定性的执行器才有权触发模拟后端。

![系统架构](docs/architecture.png)

架构源文件在 [`docs/architecture.mmd`](docs/architecture.mmd)。

## 为什么 LangGraph 只负责状态编排

`agent/order_graph.py` 中的节点是纯状态转换：补字段、判断是否缺地址、生成确认态。它们不持有后端客户端，也不能创建订单。这样即使模型选错节点，仍无法绕过执行器的参数校验、站点授权、人工确认和幂等检查。

核心演示默认使用零依赖的 `OrderGraph` runner，三分钟内离线可跑；同一组纯函数可通过 `build_langgraph()` 接入可选的 LangGraph `StateGraph`。框架负责 checkpoint、路由和恢复，业务授权与副作用继续留在确定性代码和后端。

## 三层写操作安全边界

| 层 | 检查 | 失败行为 |
| --- | --- | --- |
| 1. 参数边界 | 站点格式、商品、数量1–20、地址、请求ID | 写入前拒绝 |
| 2. 策略边界 | 操作员可访问站点、状态必须已明确确认 | 跨站或未确认立即拒绝 |
| 3. 执行边界 | `request_id` 幂等账本、锁内检查、唯一后端入口 | 重复请求返回原订单 |

生产系统还应由业务后端再次校验租户与幂等键。演示的内存网关用于证明调用关系，不声称提供分布式 exactly-once。

## MCP 工具与权限

| 工具 | 能力 | 限制 |
| --- | --- | --- |
| `product.search` | 查询模拟商品 | 只读；按操作员站点过滤 |
| `order.preview` | 生成订单预览 | 只读；不会创建订单 |
| `order.get` | 读取模拟订单摘要 | 只读；按站点过滤 |
| `progress.list` | 读取执行进度 | 只读；按站点过滤 |

MCP server 通过 JSON-RPC 2.0 行协议实现 `initialize`、`tools/list`、`tools/call`。工具清单没有写方法，所有工具都在 `annotations` 声明 `readOnlyHint: true` 和 `destructiveHint: false`；调用 `order.create` 或跨站读取会返回权限错误。真实写入只经过 `WorkflowExecutor`。

## 一条命令启动

需要 Python 3.10+，核心路径不依赖网络或第三方服务。

```bash
python demo.py
```

浏览器会打开 `http://127.0.0.1:8000`。点击一次即可通过 SSE 查看缺地址追问、修改商品数量、确认预览、安全执行、重复提交拦截、越权拒绝和 MCP 禁写。无浏览器环境可运行 `python demo.py --once`。

## 一条命令测试

```bash
python -m unittest discover -s tests -v
```

测试覆盖未确认禁写、跨站禁写、幂等防重、MCP 只读边界、知识版本过滤和评测报告结构。

## RAG 评测方法与实测结果

`data/eval_cases.jsonl` 固定包含120条模拟题，每类15条：精确商品名、同义改写、错别字、多条件、无答案、跨站点越权、无意义/恶意输入、新旧知识冲突。评测不调用外部模型，便于复现；轻量 Dense 是256维 feature-hash cosine 基线，不等同于生产 embedding 模型。

```bash
python -m rag.evaluation --output docs/evaluation_results.json
```

2026-09-25 在本机单进程离线运行结果如下；完整报告见 [`docs/evaluation_results.json`](docs/evaluation_results.json)。

| 检索方案 | Recall@5 | MRR | nDCG@5 | OOD拒答率 | P50 | P95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| BM25 | 0.9867 | 0.9633 | 0.9692 | 1.0000 | 2.624ms | 4.595ms |
| Dense | 0.9467 | 0.9467 | 0.9467 | 1.0000 | 2.536ms | 4.220ms |
| Hybrid（RRF） | 0.9733 | 0.9633 | 0.9657 | 1.0000 | 2.297ms | 4.599ms |

这组小型模拟语料中，BM25 的 Recall@5 和 nDCG@5 最高；Hybrid 与 BM25 的 MRR 持平，P50 较低但 P95 略高。该负向消融结果保留在报告中，没有为了展示效果而改写结论。错误分布显示 Hybrid 有1条同义改写未召回、1条版本冲突未召回和1条同义改写误排序。OOD拒答率来自站点范围、恶意模式、领域门控和分数阈值共同作用；它不能代替更大规模真实业务盲测。延迟会随硬件和后台负载变化，不是生产 SLA。

## 目录

```text
water-agent-demo/
├── agent/                  # 状态、图节点、唯一写执行器
├── mcp/                    # 只读 JSON-RPC/MCP server 与 client
├── rag/                    # BM25、Dense、Hybrid 与评测
├── data/                   # 模拟知识和120条脱敏评测集
├── tests/                  # 安全、MCP、RAG 回归
├── docs/                   # 架构图、实测报告、录制脚本
├── demo.py                 # SSE 网页演示
└── README.md
```

## 三分钟视频

按 [`docs/demo-script.md`](docs/demo-script.md) 可在约2分45秒内录完要求的九个场景。录制完成后把视频链接补在这里，再将仓库地址加入简历页眉：

> GitHub：`github.com/你的账号/water-agent-demo`

只有实际公开并核对链接后再替换“你的账号”；本仓库不会虚构视频或 GitHub 地址。
