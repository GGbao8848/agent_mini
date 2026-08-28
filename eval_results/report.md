# 真实任务评估报告

## live_weather — Live weather QA (real HTTP tool) [实时工具/单跳问答] ✅ PASS
- status: completed, wall: 8493 ms, tokens: 6428 (in 6389 / out 39), model calls: 2, tool calls: 1
  - [PASS] real tool called — 1 live reading(s) captured
  - [PASS] reported temp matches live data (±3°C) — answer=18.4°C, live=18.4°C
- output: 北京当前气温 18.4°C，天气为阴。…

## orders_to_json — Business text → strict JSON [结构化抽取/指令遵循] ✅ PASS
- status: completed, wall: 10707 ms, tokens: 3520 (in 3342 / out 178), model calls: 1, tool calls: 0
  - [PASS] output parses as JSON — ok
  - [PASS] exactly 4 orders — [{'id': 'A-1001', 'customer': '张伟', 'amount': 299, 'date': '2025-03-05', 'status': '已发货'}, {'id': 'A-1002', 'customer': 
  - [PASS] all fields present — id/customer/amount/date/status
  - [PASS] total_amount == 2236 — 2236
  - [PASS] dates normalized to ISO — YYYY-MM-DD
- output: ```json {"orders": [{"id": "A-1001", "customer": "张伟", "amount": 299, "date": "2025-03-05", "status": "已发货"}, {"id": "A-1002", "customer": "李娜", "amount": 1299, "date": "2025-02-28", "status": "已取消"}, {"id": "A-1003", "c…

## bugfix_code — Fix an off-by-one bug (verified by execution) [代码能力/客观验证] ✅ PASS
- status: completed, wall: 1989 ms, tokens: 3357 (in 3253 / out 104), model calls: 1, tool calls: 0
  - [PASS] fixed code executes — ok
  - [PASS] chunk_list([1, 2, 3, 4, 5], 2) — got=[[1, 2], [3, 4], [5]], want=[[1, 2], [3, 4], [5]]
  - [PASS] chunk_list([1, 2, 3, 4, 5, 6, 7], 3) — got=[[1, 2, 3], [4, 5, 6], [7]], want=[[1, 2, 3], [4, 5, 6], [7]]
  - [PASS] chunk_list([], 3) — got=[], want=[]
  - [PASS] chunk_list([1, 2], 5) — got=[[1, 2]], want=[[1, 2]]
- output: bug 原因：循环步长和切片末尾都多加了 1，导致每块比 `size` 多 1 个元素，最后一块会被截断。  ```python def chunk_list(items, size):     """把列表按 size 切块，例如 chunk_list([1,2,3,4,5], 2) -> [[1,2],[3,4],[5]]"""     return [items[i:i + size] for i in range(0, len(…

## fx_briefing — Multi-source FX briefing (orchestration comparison) [编排对比/实时数据/并行/single] ✅ PASS
- status: completed, wall: 11451 ms, tokens: 6782 (in 6560 / out 222), model calls: 2, tool calls: 3
  - [PASS] USD→CNY rate plausible — found=6.7209, expected in [5.5, 9.5]
  - [PASS] EUR→CNY rate plausible — found=7.8251, expected in [6.5, 11.5]
  - [PASS] JPY→CNY rate plausible — found=0.04209, expected in [0.015, 0.09]
- output: # 主要货币兑人民币汇率简报  **数据日期：2026-08-28**  | 货币 | 兑 CNY 汇率 | |------|------------| | 美元 USD | 6.7209 | | 欧元 EUR | 7.8251 | | 日元 JPY | 0.04209（100 日元 ≈ 4.21 元人民币） |  **趋势提示：** 当前人民币对美元和日元相对走强（汇率数值低于欧元），欧元仍为三者中最贵；近期需关注美联储与欧央行政策动…

## fx_briefing — Multi-source FX briefing (orchestration comparison) [编排对比/实时数据/并行/team] ❌ FAIL
- status: completed, wall: 14643 ms, tokens: 22987 (in 22200 / out 787), model calls: 8, tool calls: 6
  - [FAIL] USD→CNY rate plausible — found=16.4, expected in [5.5, 9.5]
  - [FAIL] EUR→CNY rate plausible — found=16.4, expected in [6.5, 11.5]
  - [FAIL] JPY→CNY rate plausible — found=None, expected in [0.015, 0.09]
- output: 三个 worker 已并行返回结果，日期一致（2026-08-28），数据完整。下面汇总撰写简报：  ---  # 主要货币兑人民币汇率简报  **数据日期：2026-08-28**  | 货币对 | 汇率（1 单位兑 CNY） | |---|---| | **USD / CNY** | 1 美元 = **6.7209** 元人民币 | | **EUR / CNY** | 1 欧元 = **7.8251** 元人民币 | | **JPY…

## fx_briefing — Multi-source FX briefing (orchestration comparison) [编排对比/实时数据/并行/fanout] ✅ PASS
- status: completed, wall: 12658 ms, tokens: 21463 (in 21087 / out 376), model calls: 7, tool calls: 3
  - [PASS] USD→CNY rate plausible — found=6.7209, expected in [5.5, 9.5]
  - [PASS] EUR→CNY rate plausible — found=7.8251, expected in [6.5, 11.5]
  - [PASS] JPY→CNY rate plausible — found=0.04209, expected in [0.015, 0.09]
- output: ## 汇率简报（日期：2026-08-28）  | 货币 | 兑 CNY 汇率 | |------|-------------| | **USD（美元）** | 1 USD = 6.7209 CNY | | **EUR（欧元）** | 1 EUR = 7.8251 CNY | | **JPY（日元）** | 1 JPY = 0.04209 CNY |  **趋势提示**：当日欧元兑人民币（7.8251）> 美元兑人民币（6.7209）>…

## holiday_planner — Holiday planning with tool chain + calculator [多步规划/工具链/计算] ✅ PASS
- status: completed, wall: 8612 ms, tokens: 10445 (in 10020 / out 425), model calls: 3, tool calls: 2
  - [PASS] mentions a real 2026 holiday — keyword search
  - [PASS] gives a concrete day count — 'N 天' pattern
- output: ## 2026年10月拼假方案  **10月法定假日**：仅10月1日（国庆节）1天。  **拼连休方案（用5天年假）**：  10月1日是周四，最优方案是**向两端延伸**，形成长假：  | 日期 | 星期 | 性质 | |------|------|------| | 9月30日 | 周三 | 年假 | | 10月1日 | 周四 | 国庆节 | | 10月2日 | 周五 | 年假 | | 10月3日 | 周六 | 周末 | | 10…

