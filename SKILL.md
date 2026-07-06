---
name: astromind-praxis
version: "0.1.1"
description: >
  星知·笃行 — 面向成年人的综合学习引擎。代码固化流程 + 关键环节 LLM 调用。
  诊断→教学→评估→复习闭环，知行合一，学以致用。
  Do NOT use when: user asks for quick answers without structured learning,
  or when the topic is too simple for diagnosis→teaching→assessment flow.
allowed-tools:
  - Bash: execute astromind CLI commands
  - Write: create output files
metadata:
  version: 0.1
  stability: alpha
  owner: meta-learn team
  tags: [learning, teaching, sm2, diagnosis, spaced-repetition, praxis]
compatibility:
  requires: [python3, httpx, pyyaml, beautifulsoup4]
  database: ~/.astromind-praxis/astromind_praxis.db
  shared_config: ~/.astromind-praxis/config.yaml
---

# 星知·笃行 (Astromind Praxis) v0.1

程序驱动的教学引擎。关键环节调用 LLM，搜索走降级链，教学流程代码固化。

## 快速开始

```bash
# 独立 CLI 模式
python engine/__main__.py init                # 配置向导
python engine/__main__.py init --check         # 检查配置
python engine/__main__.py teach diagnose "量子计算"   # 诊断
python engine/__main__.py teach session 1             # 教学
python engine/__main__.py teach assess 1              # 评估
python engine/__main__.py teach status 1              # 状态

# Stdio 协议模式 (Agent 技能模式)
python engine/__main__.py --stdio              # 监听 [LLM_REQ] / [SEARCH_REQ]
```

## 架构概览

```
用户请求
  │
  ├─ CLI: astromind teach <子命令>
  └─ Agent: [LLM_REQ] / [SEARCH_REQ] Stdio 协议
       │
       ▼
  ┌─────────────────────────────┐
  │  TeachingOrchestrator       │  ← 固定流程，代码固化
  │  ┌───────────────────────┐  │
  │  │ 1. 诊断阶段            │  │  search → KG → LLM 诊断 → 建节点
  │  │ 2. 教学阶段            │  │  LLM 教学 → 出题 → 评估 → SM-2
  │  │ 3. 评估阶段            │  │  LLM 综合测试 → 报告
  │  └───────────────────────┘  │
  └──────────┬──────────────────┘
             │
     ┌───────┴───────┐
     ▼               ▼
  LLMClient      SearchClient
  双策略           降级链
  ┌──────┐      ┌──────────┐
  │直连API│      │AnySearch  │  Tier 1
  │Stdio │      │Bing API  │  Tier 2
  └──────┘      │WebFetch  │  Tier 3
                │Agent     │  Tier 4
                └──────────┘
```

## LLM Stdio 协议

当未配置 LLM API key 时，程序通过 Stdio 协议与 agent 通信：

**请求** (程序 → stdout):
```
[LLM_REQ] {"system_prompt": "...", "user_prompt": "...", "schema": {...}}
[SEARCH_REQ] {"query": "...", "max_results": 10}
```

**响应** (agent → stdin):
```
[LLM_RSP] {"key": "value", ...}
[SEARCH_RSP] [{"title": "...", "url": "...", "content": "..."}, ...]
```

Agent 必须：
1. 识别 stdout 中的 `[LLM_REQ]` 或 `[SEARCH_REQ]` 标记
2. 调用自己的模型/搜索能力处理请求
3. 将结果以 JSON 写入 stdin，带上对应标记前缀
4. 在同一个消息内返回（程序阻塞等待）

## 搜索降级链

```
SearchClient.search(query)
  │
  ├─ Tier 1: AnySearch API (匿名或带 key)
  ├─ Tier 2: Bing API (需 bing_key)
  ├─ Tier 3: WebFetch (爬百度/Bing/DuckDuckGo HTML)
  └─ Tier 4: Agent Stdio 协议 [SEARCH_REQ] (agent 自由搜索)
```

每个 tier 独立封装、按序尝试，前一个失败自动降级。

## 命令速查

| 命令 | 说明 |
|------|------|
| `astromind init` | 交互配置向导 |
| `astromind init --check` | 检查配置 |
| `astromind init --reset` | 重置配置 |
| `astromind teach diagnose <topic>` | 诊断主题 |
| `astromind teach session <id>` | 教学会话 |
| `astromind teach assess <id>` | 综合评估 |
| `astromind teach status <id>` | 会话状态 |
| `astromind teach next <id>` | 下一个节点 |

## 配置 (`~/.astromind-praxis/config.yaml`)

```yaml
llm:
  base_url: ""    # 配了=直连; 未配=Stdio协议
  api_key: ""
  model: ""
anysearch_api_key: ""   # 可选，提额度
bing_key: ""            # 可选，提额度
```

---

## Changelog

### v0.1.1 (2026-07-06)

- **fix**: `Database.conn` ??? `:memory:` ????? `ensure_db_dir()`
- **fix**: Stdio ?? `readline` ?? 120s ???`STDIO_TIMEOUT` ????????
- **fix**: ?? schema ?????? `schema_v5.sql` ???? `knowledge_edges` ???? `node_dependencies` ???????
- **fix**: ??????????????????? `return None`
- **chore**: ???? `str | None` ? `Optional[str]`?Python 3.8+ ???
