# Quick Task 260323-tm8 Summary

**Description:** 修复 planner 输出大写 `AND/ATOM` 时 router 报 `Unknown node type` 的 bug，并补测试与提交。  
**Date:** 2026-03-23  
**Status:** completed

## Root Cause

问题出在 planner 与 router 对 node type 的约定不一致：

- planner 侧 `PlanNode.from_dict()` 直接接受外部返回的 `type` 字段，没有做大小写标准化
- router 侧执行时只识别小写的 `atom` / `and` / `or`

因此当模型返回：

```json
{"type": "AND", "children": [{"type": "ATOM"}, {"type": "ATOM"}]}
```

解析阶段不会报错，但执行阶段会落到：

```text
Unknown node type: AND
```

## Fix

本次修复分两层：

1. 在 `nanobot/agent/planner.py` 中：
   - `PlanNode.from_dict()` 现在会把 `type` 统一标准化为小写
   - 非字符串类型会抛出 `TypeError`
   - 非法节点类型会抛出 `ValueError`
   - `TaskPlanner.plan()` 对 `ValueError` 也会走安全 fallback

2. 在 `nanobot/agent/router.py` 中：
   - `TreeRouter.execute()` 对 `node.node_type` 做小写标准化后再分发
   - `AND` 执行路径里所有 `atom` 判定也统一改为大小写无关
   - 这样即使存在历史/外部手工构造的大写 `PlanNode`，router 也能正常执行

## Tests

新增回归覆盖：

- `tests/test_opengui_p8_planning.py`
  - `test_plan_node_from_dict_normalizes_uppercase_node_types`
- `tests/test_opengui_agent_loop.py`
  - `test_router_executes_uppercase_plan_node_types`

验证结果：

```bash
uv run pytest tests/test_opengui_p8_planning.py tests/test_opengui_agent_loop.py -q
uv run python -m py_compile nanobot/agent/planner.py nanobot/agent/router.py tests/test_opengui_p8_planning.py tests/test_opengui_agent_loop.py
```

结果：

- `37 passed`
- `py_compile` 成功

## Outcome

现在 planner 即使收到大写 `AND/OR/ATOM`，也会被标准化并正常执行，不会再因为大小写问题中断到 `Unknown node type`。
