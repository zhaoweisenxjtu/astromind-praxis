---
name: astromind-praxis
version: "0.2.2"
description: >
  星知·笃行 — 面向成年人的综合学习引擎。代码固化流程 + 关键环节 LLM 调用。
  诊断→教学→评估→复习四环闭环，知行合一，学以致用。
  通过 two-phase checkpoint 协议与 agent 协作：零 API key 下 agent 充当 LLM/搜索。
  v0.2.2：减法重构——LLM 调用点 8→5（diagnose_pack/teach_pack/review_pack 合并），
  Schema 17→9 表，checkpoint 往返 -32%。
  Do NOT use when: user asks for quick answers without structured learning,
  or when the topic is too simple for diagnosis→teaching→assessment flow.
allowed-tools:
  - Bash: run `python <skill_dir>/run.py <command>` (check exit codes 75/76/77)
  - Read: read req-NNN.json checkpoint files (in ~/.astromind-praxis/runs/<run_id>/)
  - Write: write rsp-NNN.json response files for checkpoints
metadata:
  version: 0.2.2
  stability: alpha
  owner: meta-learn team
  tags: [learning, teaching, sm2, diagnosis, spaced-repetition, praxis]
compatibility:
  requires: [python3, httpx, pyyaml, beautifulsoup4, requests]
  setup: run `python <skill_dir>/run.py doctor --json` first (installs/checks deps)
  database: ~/.astromind-praxis/astromind_praxis.db (v7 unified schema)
  shared_config: ~/.astromind-praxis/config.yaml
  runs: ~/.astromind-praxis/runs/ (checkpoint protocol, per-command Run dirs)
---

# 星知·笃行 (Astromind Praxis) v0.2.2

程序驱动的教学引擎。教学流程代码固化，关键环节（诊断/教学/出题/评估/复习出题）调用 LLM。
LLM 供给双模式：直连 API（config 或继承 OpenClaw）或 **two-phase checkpoint 协议**（agent 充当 LLM，零 API key）。

## v0.2.2 变更摘要（减法重构）

- **LLM 调用点 8→5**：`diagnose_pack`（知识图谱+诊断合并）、`teach_pack`（教学内容+出题合并）、`review_pack`（多节点批量出题）、`assessment` 注册化；删除单题评估路径
- **Schema v7（17→9 表）**：删除 8 张无生产写入表；interaction_log 吸收 teaching_interactions（review_session 标签）；knowledge_nodes 砍 9 个 NUSAP 质量字段
- **checkpoint 往返 -32%**：10 节点主题 34→23 次；5 节点复习 ~10→2 次
- 删除死代码 ~1,900 行（knowledge_quality / fake_detection / dao_weakness / dao_journal / dao_assessment / dao_interaction / dao_graph）
- 删除 `graph` 与 `migrate` 命令（v6→v7 迁移用独立脚本 `scripts/migrate_v6_to_v7.py`）

## 快速开始

```bash
SKILL_DIR="D:/workdata/shared/skills/astromind-praxis"

# 1. 自检（依赖+配置+DB，首次必跑）
python "$SKILL_DIR/run.py" doctor --json

# 2. 初始化（checkpoint 模式：不配 key 也可；配了 key 走直连）
python "$SKILL_DIR/run.py" init --check --json
python "$SKILL_DIR/run.py" init --llm-model "deepseek-v4-flash" --json   # 可选直连

# 3. 教学（agent 模式，全部命令带 --json --agent）
python "$SKILL_DIR/run.py" teach diagnose "量子计算" --json --agent
python "$SKILL_DIR/run.py" teach session 1 --json --agent
python "$SKILL_DIR/run.py" teach answer 1 --answers-file answers.json --json --agent
python "$SKILL_DIR/run.py" teach review --json --agent          # 到期节点复习
python "$SKILL_DIR/run.py" teach assess 1 --json --agent        # 综合评估
```

命令从任意 cwd 执行（run.py 自动定位技能目录）。

## 退出码契约（agent 编排核心）

| 退出码 | 含义 | stdout（--json 模式） |
|---|---|---|
| 0 | 成功完成 | 命令结果 JSON |
| 1 | 错误 | stderr: `{"error": "..."}` |
| 75 | NEEDS_LLM — 等 agent 用自身模型补答 | `{"need":"llm","run_id":"...","req_file":"...","step":"..."}` |
| 76 | NEEDS_SEARCH — 等 agent 搜索补答 | `{"need":"search","run_id":"...","req_file":"..."}` |
| 77 | AWAITING_ANSWERS — 题目已出，等用户答案 | `{"need":"answers","session_id":N,"questions":[...]}` |

**checkpoint 补答循环**（exit 75/76 时）：

```
1. Read req_file (req-NNN.json): 含完整 prompt + schema + instruction
2. 用自身能力生成响应（LLM：按 schema 生成 JSON；搜索：结果数组）
3. Write rsp-NNN.json（req 同目录）
4. python run.py resume <run_id> --rsp-file <rsp路径> --json --agent
5. 重复直到 exit 0 / 77
```

每条命令的 checkpoint 循环上限（v0.2.2 修订）：diagnose ≤2 次、session ≤1 次、answer ≤1 次、review ≤2 次、assess ≤1 次。超过上限未完成即报告异常。

## Agent 工作流（完整学习周期）

```
① doctor --json                   前置自检
② init --check --json             （checkpoint 模式跳过 LLM 配置）
③ teach diagnose <topic> --json --agent
      loop: exit 75/76 → Read req → 生成 → Write rsp → resume
      exit 0 → 诊断结果（session_id, level, gaps, misconceptions）
④ teach session <id> --json --agent
      loop: exit 75（教学包：内容+出题）→ 补答
      exit 77 → 把题目转达用户
⑤ 收集用户答案 → Write answers.json: {"answers": ["...", "..."]}
   teach answer <id> --answers-file answers.json --json --agent
      exit 75 → 补答评估 → exit 0 → 评估+SM-2+下一节点
      重复 ④⑤ 直到消息提示全部节点完成
⑥ teach assess <id> --json --agent   综合评估报告
⑦ 每日复习：teach review --json --agent
      exit 0 + due:0 → 无到期，转告用户
      exit 77 → 复习题转达用户 → teach answer <id> --review --answers-file ...
```

## 命令速查

| 命令 | 说明 |
|---|---|
| `run.py init [--check\|--reset\|--llm-base-url ...]` | 配置（交互/非交互） |
| `run.py doctor` | 依赖+配置+DB+run 自检 |
| `run.py resume [run_id] [--rsp-file <f>] [--rsp '<json>']` | 消费补答并继续（缺省取最新 pending run） |
| `run.py runs list \| --prune [--days N]` | run 管理，默认保留 14 天 |
| `run.py teach diagnose <topic> [--self-assessment N] [--description ...]` | 诊断：搜索→诊断包（KG+水平/缺口/迷思/路径）→建节点 |
| `run.py teach session <id>` | 教学：教学包（内容+3 道检验题）→（agent 模式 exit 77 / 人类交互答题） |
| `run.py teach answer <id> [--answers-file \| --answers] [--review]` | 批量评估答案→SM-2（教学或复习） |
| `run.py teach review [--track N] [--limit M]` | 到期节点复习出题（批量，exit 77） |
| `run.py teach assess <id>` | 综合评估报告 |
| `run.py teach status <id> \| next <id>` | 会话状态 / 下一节点 |
| `run.py node search \| content` | 知识节点查询/编辑 |
| `run.py track / review / report / schedule / misconception` | 维护命令 |

## 架构：Two-Phase Checkpoint

```
Agent                                    praxis 进程
  │ python run.py teach diagnose "X"        │
  │───────────────────────────────────────>│ 搜索→诊断包→需要LLM
  │                                         │ 写 req-001.json, exit 75
  │<── exit 75 + JSON ──────────────────────│
  │ Read req → 自身模型 → Write rsp         │
  │ python run.py resume <run_id>           │
  │───────────────────────────────────────>│ 读 rsp → 继续 → 下一 checkpoint / 完成
```

- **Run**：每次 CLI 命令 = `~/.astromind-praxis/runs/run-<ts>-<rand>/`（meta.json + req-NNN.json + rsp-NNN.json + cache.json）
- **幂等重放**：resume 重跑原命令，已答 checkpoint（prompt 指纹 sha256）命中缓存直接跳过；搜索/LLM 中间结果缓存保证重放输入稳定；DB 写入（节点/边/session/SM-2/复习记录）应用层幂等
- **pending 索引**：`runs/pending.json` 原子记录所有 pending run，`resume` 无参时取最新
- **直连模式**：config 配置 base_url/api_key/model 后 checkpoint 层旁路，exit 0 直接得结果

## LLM 调用点（v0.2.2，共 5 个）

| 调用点 | 用途 | checkpoint 上限 |
|---|---|---|
| `diagnose_pack` | 搜索→知识图谱+水平/缺口/迷思/路径（合并原 KG 评估与诊断） | diagnose ≤2 |
| `teach_pack` | 教学内容（直觉/动机/定义/边界/例题）+ 3 道检验题（合并原内容生成与出题） | session ≤1 |
| `evaluate_answers_batch` | 批量评估答案→SM-2（教学与复习共用） | answer ≤1 |
| `review_pack` | 多节点批量复习出题（替代逐节点循环） | review ≤2 |
| `assessment` | 综合评估报告（注册表化） | assess ≤1 |

## 配置 (`~/.astromind-praxis/config.yaml`)

```yaml
llm:
  base_url: ""    # 留空=checkpoint 协议（agent 充当 LLM）；或继承 OpenClaw
  api_key: ""
  model: ""
anysearch_api_key: ""   # 可选，提搜索额度
bing_key: ""            # 可选，提搜索额度
```

LLM 来源三态（`init --check` 显示）：`config`（显式直连）→ `agent`（继承 ~/.openclaw/openclaw.json）→ `checkpoint`（agent 协议，零 key）。

## 数据库（Schema v7，9 张表）

```
users / tracks / knowledge_nodes / node_dependencies / review_history /
misconceptions / workflow_context / interaction_log / knowledge_fts(FTS5)
```

v6→v7 迁移：`python scripts/migrate_v6_to_v7.py`（自动备份 .bak-v6；也可直接 `run.py doctor` 触发 init_db 内嵌迁移）。

---

## Changelog

### v0.2.2 (2026-08-28)

- **new**: LLM 调用点 8→5 — `diagnose_pack`（KG+诊断合并）、`teach_pack`（内容+出题合并）、`review_pack`（多节点批量出题，替代逐节点循环）、`assessment` 注册化；删除 `evaluate_answer` 单题路径与人类交互逐题评估
- **perf**: checkpoint 往返 -32%（10 节点主题 34→23 次）；复习 5 节点 ~10→2 次；上限修订 diagnose ≤2 / session ≤1 / review ≤2
- **schema**: v6→v7（17→9 表）— 删 8 张无生产写入表（learning_journal/assessment_log/weakness_patterns/knowledge_graph_edges/quality_audit_log/knowledge_sources/knowledge_coverage/teaching_interactions）；interaction_log 增 interaction_type（吸收 teaching_interactions）；knowledge_nodes 删 node_type+9 个 NUSAP 质量字段；tracks 删 workflow_context 列；misconceptions 删 interaction_id；node_dependencies 枚举收窄为 3 值
- **remove**: 死代码 ~1,900 行（knowledge_quality/fake_detection/dao_weakness/dao_journal/dao_assessment/dao_interaction/dao_graph/dao_user/migrate_from_json/schema_v5.sql）；`graph` 与 `migrate` 命令；submit_answer 人类交互路径
- **new**: `scripts/migrate_v6_to_v7.py` 一次性迁移脚本（备份+行数校验）；`tests/test_v7_migration.py`（迁移+全新初始化双断言）
- **fix**: dao_misconception 重复路径引用不存在的 last_encountered_at 列；`_create_node` INSERT 参数错位
- **tests**: 102→122 全绿（12 个适配新调用点/schema，新增 v7 迁移测试 + 调用点往返计数测试）

### v0.2.1 (2026-08-27)

- **new**: two-phase checkpoint 协议（engine/runs/）——LLM/搜索请求落盘 req-NNN.json + 退出码 75/76，agent 补答写 rsp-NNN.json + `resume` 续跑；幂等重放（prompt 指纹缓存 + 中间产物缓存 + 应用层幂等）
- **new**: `run.py` 根目录启动器（任意 cwd 可跑，根治相对导入崩溃）
- **fix**: CLI dispatch 修复——node/track/review/report/graph/schedule/misconception/migrate 全命令可达（原 8 组静默失效）
- **fix**: 删除 "(simulated)" 假答案——agent 模式题目经 exit 77 输出，`teach answer` 批量评估（evaluate_answers_batch）真实更新 SM-2
- **fix**: SM-2 quality 三值映射（correct+level≥4→5 / correct→4 / wrong→1-2）；next_review 落库
- **fix**: 节点完成时 pending→active（进入复习调度）；diagnose/assess 的 tracks.level 写错列 bug
- **new**: 复习闭环——`teach review`（review_questions 出检索题，历史题目去重 + 假懂信号驱动）+ `teach answer --review`（SM-2 + review_history + teaching_interactions）
- **new**: `--json` 全命令机器可读输出；`doctor` 自检；`runs list/prune`；非交互 `init`
- **tests**: 84→102 全绿

### v0.1.5 (2026-07-22)

- **split**: 解耦 author-coach 为独立技能（`shared/skills/author-coach/`）
- **remove**: 删除 author 相关 DAO/表/命令/提示词（Schema 回归纯 v6）

### v0.1.2 (2026-07-07)

- **merge**: 合并 meta-learning 16 张表 + astromind 的 workflow_context + interaction_log
- **new**: FTS5 全文检索 + 知识质量评估 + 假懂检测 10 信号
- **new**: CLI 17 个子命令
- **perf**: 提示词精简 + LLM Stdio 协议 + 搜索降级链

### v0.1.1 (2026-07-06)

- **fix**: Database.conn 在 `:memory:` 模式下 ensure_db_dir() 崩溃
- **fix**: schema 顺序问题（knowledge_edges 引用 node_dependencies 未创建）
- **fix**: 查询无结果时返回 None 而非抛异常
- **chore**: 兼容 Python 3.8+ 类型注解
