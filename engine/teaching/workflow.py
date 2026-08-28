"""教学编排器：固定流程驱动，关键环节调用 LLM.

流程:
  1. 诊断阶段: 搜索 -> 知识图谱 -> LLM 诊断 -> 建节点
  2. 教学阶段: LLM 概念教学 -> 渲染 -> LLM 出题 -> 收集回答 -> LLM 评估 -> SM-2
  3. 评估阶段: LLM 综合测试 -> 更新水平 -> 报告
"""

import json
import logging
from datetime import date, datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


def quality_from_eval(correct: bool, level: int) -> int:
    """SM-2 quality 三值映射（v0.2.1 §16.4）：
    correct 且 level>=4 → 5（正确且讲解流畅）
    correct → 4（正确但犹豫/不完整）
    wrong → 1-2（错误，按 level 压缩）
    """
    if correct and level >= 4:
        return 5
    if correct:
        return 4
    return max(1, min(int(level or 1), 2))


class TeachingOrchestrator:
    """教学编排器，唯一的核心流程控制器."""

    def __init__(self, db, llm, search, user_id: str, track_id: int,
                 run=None, run_store=None):
        self.db = db
        self.llm = llm
        self.search = search
        self.user_id = user_id
        self.track_id = track_id
        self.run = run              # v0.2.1: checkpoint run 上下文（可为 None=直连/无 run）
        self.run_store = run_store
        self._session_manager = None

    @property
    def session_manager(self):
        if self._session_manager is None:
            from .session import SessionManager
            self._session_manager = SessionManager(self.db)
        return self._session_manager

    # ── Diagnosis phase ──

    def run_diagnosis(self, topic: str, self_assessment: int = 3,
                      user_description: str = "") -> dict:
        """诊断阶段：搜索 -> LLM 诊断包（知识图谱 + 水平/缺口）-> 建节点.

        v0.2.2: assess_knowledge_graph 与 diagnosis 合并为单次 diagnose_pack 调用
        （原两次 checkpoint 往返 -> 一次）。
        """
        logger.info("Starting diagnosis for topic: %s", topic)

        # Step 1: Search for context
        search_results = self._search_context(topic)

        # Step 2: LLM 诊断包（KG 构建 + 水平/缺口/迷思/路径，单次调用）
        from ..llm.prompts import build_prompt
        sys_p, user_p, schema = build_prompt(
            "diagnose_pack",
            topic=topic,
            search_results=search_results,
            self_assessment=str(self_assessment),
            user_description=user_description or "未提供",
        )
        pack = self.llm.chat(sys_p, user_p, schema)

        kg = {
            "concepts": pack.get("concepts", []),
            "edges": pack.get("edges", []),
        }
        diagnosis = pack

        # Step 3: Determine prerequisite nodes
        concepts = pack.get("concepts", [])
        edges = pack.get("edges", [])

        # Step 4: Build knowledge nodes in DB
        node_map = {}
        for c in concepts:
            node_id = self._create_node(
                name=c["name"],
                level=c.get("level", "foundational"),
                complexity=c.get("complexity", 3),
                description=c.get("description", ""),
            )
            node_map[c["name"]] = node_id

        # Build prerequisite edges
        for edge in edges:
            src = node_map.get(edge["source"])
            tgt = node_map.get(edge["target"])
            if src and tgt:
                self._create_edge(src, tgt, edge.get("relation", "related"))

        # Step 6: Create session
        session_data = {
            "topic": topic,
            "level": diagnosis.get("level", 1),
            "gaps": diagnosis.get("gaps", []),
            "misconceptions": diagnosis.get("misconceptions", []),
            "recommended_path": diagnosis.get("recommended_path", []),
            "node_ids": list(node_map.values()),
            "node_map": node_map,
        }

        # v0.2.1 幂等：重放时 run 已记录 session_id 则复用，否则创建并登记
        if self.run and self.run.session_id:
            session_id = self.run.session_id
        else:
            session_id = self.session_manager.create_session(
                self.user_id, self.track_id, topic, session_data
            )
            if self.run and self.run_store:
                self.run.session_id = session_id
                self.run_store.save_run(self.run)

        # Set diagnosis level on session (tracks 表无 level 列；workflow_context 有)
        self.session_manager.update_session(session_id, level=diagnosis.get("level", 1))

        result = {
            "session_id": session_id,
            "diagnosis": session_data,
            "knowledge_graph": kg,
        }
        logger.info(
            "Diagnosis complete: session=%d, level=%d, %d concepts",
            session_id, diagnosis.get("level", 1), len(concepts),
        )
        return result

    # ── Teaching phase ──

    def run_teaching_session(self, session_id: int,
                             node_id: Optional[int] = None) -> dict:
        """教学会话：对指定节点执行完整教学流程."""
        session = self.session_manager.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        # Get next node if not specified
        if node_id is None:
            node_id = self.get_next_node(session)
            if node_id is None:
                return {"status": "completed", "message": "All nodes completed"}

        # Get node info
        node = self.db.fetch_one(
            "SELECT * FROM knowledge_nodes WHERE id = ?", [node_id]
        )
        if not node:
            raise ValueError(f"Node {node_id} not found")
        node = dict(node)

        self.session_manager.set_current_node(session_id, node_id)
        logger.info("Teaching session started: node=%s", node["name"])

        # Step 1: LLM 教学包（教学内容 + 检验题，单次调用；原两次 checkpoint 往返 -> 一次）
        topic = session.get("diagnosis", {}).get("topic", "") or ""
        content, questions = self._generate_teach_pack(
            concept=node["name"],
            topic=topic,
            level=node.get("level", "foundational"),
            prerequisites=self._get_prerequisites(node_id),
            misconceptions=self._get_node_misconceptions(session, node["name"]),
        )

        # Step 2: Render and return content for display
        from .render import render_concept_content
        rendered = render_concept_content(content, node["name"])

        result = {
            "node_id": node_id,
            "node_name": node["name"],
            "concept_content": content,
            "rendered": rendered,
            "questions": questions,
            "session_id": session_id,
        }
        return result

    def complete_node(self, session_id: int, node_id: int):
        """完成节点教学，更新状态（节点 pending → active，进入复习调度）."""
        from datetime import timezone as _tz
        self.db.execute(
            "UPDATE knowledge_nodes SET status = 'active', updated_at = ? WHERE id = ?",
            [datetime.now(timezone.utc).isoformat(), node_id],
        )
        self.session_manager.add_completed_node(session_id, node_id)
        self.session_manager.set_current_node(session_id, None)

        # Check if all nodes completed
        session = self.session_manager.get_session(session_id)
        if session:
            total = len(session.get("diagnosis", {}).get("node_ids", []))
            completed = len(session.get("completed_nodes", []))
            if completed >= total:
                self.session_manager.update_session(
                    session_id, status="teaching_complete"
                )
                logger.info("All nodes completed for session %d", session_id)
            else:
                logger.info(
                    "Node %d completed: %d/%d", node_id, completed, total
                )

    # ── Assessment phase ──

    def run_assessment(self, session_id: int) -> dict:
        """综合评估：分析整体掌握情况，生成报告."""
        session = self.session_manager.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        topic = session.get("topic", "")
        completed_nodes = session.get("completed_nodes", [])
        diagnosis = session.get("diagnosis", {})

        # Collect interaction history
        interactions = self._get_interactions(self.user_id, session.get("track_id", 0))

        # Build assessment prompt (v0.2.2: 注册表化，schema 固化)
        stats = self._compute_stats(interactions)
        from ..llm.prompts import build_prompt
        sys_p, user_p, schema = build_prompt(
            "assessment",
            topic=topic,
            node_count=str(len(diagnosis.get('node_ids', []))),
            completed_count=str(len(completed_nodes)),
            stats=json.dumps({
                "total": stats["total"],
                "correct": stats["correct"],
                "rate": f"{stats['rate']:.1%}",
                "avg_level": round(stats["avg_level"], 1),
                "fake_count": stats["fake_count"],
            }, ensure_ascii=False),
        )

        report = self.llm.chat(sys_p, user_p, schema)

        # Update session (workflow_context.level 已有；tracks 表无 level 列)
        self.session_manager.update_session(
            session_id,
            status="completed",
            level=report.get("overall_level", stats["avg_level"]),
        )

        logger.info(
            "Assessment complete: level=%d, report generated",
            report.get("overall_level", 1),
        )
        return report

    # ── Node navigation ──

    def get_next_node(self, session_or_id: Any) -> Optional[int]:
        """获取下一个未完成的学习节点."""
        if isinstance(session_or_id, int):
            session = self.session_manager.get_session(session_or_id)
        else:
            session = session_or_id

        if not session:
            return None

        diagnosis = session.get("diagnosis", {})
        all_nodes = diagnosis.get("node_ids", [])
        completed = session.get("completed_nodes", [])

        # Follow recommended path if available
        recommended = diagnosis.get("recommended_path", [])
        node_map = diagnosis.get("node_map", {})

        if recommended:
            for concept in recommended:
                nid = node_map.get(concept)
                if nid and nid not in completed:
                    return nid

        # Fallback: first uncompleted node
        for nid in all_nodes:
            if nid not in completed:
                return nid

        return None

    # ── Batch answers (v0.2.1 答题流) ──

    def run_answer_batch(self, session_id: int, node_id: int,
                         questions: list[dict], answers: list[str]) -> dict:
        """批量评估一次教学会话的全部答案（单次 LLM 调用）→ SM-2 → 落库.

        副作用幂等：resume 重放时通过 run 的 local step 标记跳过重复写入。
        """
        session = self.session_manager.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")
        node = self.db.fetch_one(
            "SELECT * FROM knowledge_nodes WHERE id = ?", [node_id]
        )
        if not node:
            raise ValueError(f"Node {node_id} not found")
        node = dict(node)

        if len(questions) != len(answers):
            raise ValueError(
                f"Answers count ({len(answers)}) != questions count ({len(questions)})"
            )

        # 幂等：重放时跳过副作用写入，返回缓存结果
        apply_cache_key = f"apply-answers:{session_id}:{node_id}"
        if self.run and self.run_store:
            cached = self.run_store.cache_get(self.run, apply_cache_key)
            if cached is not None:
                return cached

        # 单次 LLM 批量评估（checkpoint 协议：未答时抛 NeedsLLM → exit 75）
        from ..llm.prompts import build_prompt
        items = []
        for q, a in zip(questions, answers):
            items.append({
                "question": q.get("question", ""),
                "correct_answer": q.get("answer", ""),
                "learner_answer": a,
            })
        sys_p, user_p, schema = build_prompt(
            "evaluate_answers_batch",
            concept=node["name"],
            context=(node.get("content") or "")[:800] or "（教学内容）",
            items=json.dumps(items, ensure_ascii=False),
        )
        batch = self.llm.chat(sys_p, user_p, schema)

        results = batch.get("results", [])
        overall_feedback = batch.get("overall_feedback", "")

        # SM-2：各题 quality 均值
        qualities = []
        for i, (q, a) in enumerate(zip(questions, answers)):
            ev = results[i] if i < len(results) else {"correct": False, "level": 1}
            quality = quality_from_eval(ev.get("correct", False), ev.get("level", 1))
            qualities.append(quality)
            # interaction_log 逐题落库
            self._store_interaction(
                user_id=self.user_id,
                node_id=node_id,
                question=q.get("question", ""),
                answer=a,
                correct=ev.get("correct", False),
                level=ev.get("level", 1),
                fake_signals=ev.get("fake_signals", []),
            )
            # 迷思概念
            for signal in ev.get("fake_signals", []):
                if signal.get("type") == "misconception":
                    self._store_misconception(
                        node_id=node_id,
                        misconception=signal.get("detail", ""),
                        correction=ev.get("feedback", ""),
                    )

        avg_quality = round(sum(qualities) / len(qualities)) if qualities else 3
        sm2 = self._apply_sm2(node_id, avg_quality)

        # 节点完成
        self.complete_node(session_id, node_id)

        result = {
            "session_id": session_id,
            "node_id": node_id,
            "node_name": node["name"],
            "results": results,
            "overall_feedback": overall_feedback,
            "sm2": sm2,
        }

        # 副作用已应用 → 标记，重放跳过
        if self.run and self.run_store:
            self.run_store.cache_set(self.run, apply_cache_key, result)
            self.run_store.mark_step_done(self.run, apply_cache_key)

        return result

    # ── Review phase (v0.2.1 复习闭环) ──

    def get_due_nodes(self, limit: int = 5) -> list[dict]:
        """查询到期复习节点（next_review <= today）."""
        rows = self.db.fetch_all(
            "SELECT * FROM knowledge_nodes "
            "WHERE track_id = ? AND next_review IS NOT NULL "
            "AND next_review <= date('now') AND status IN ('active', 'mastered') "
            "ORDER BY next_review ASC LIMIT ?",
            [self.track_id, limit],
        )
        return [dict(r) for r in rows]

    def run_review_questions(self, nodes: list[dict]) -> list[dict]:
        """为到期节点批量出复习题（单次 LLM 调用，v0.2.2 review_pack）."""
        from ..llm.prompts import build_prompt

        payload = []
        for node in nodes:
            past_questions = self._get_node_past_questions(node["id"])
            fake_signals = self._get_node_fake_signals(node["id"])
            payload.append({
                "node_id": node["id"],
                "node_name": node["name"],
                "content": (node.get("content") or "")[:800] or "（教学内容）",
                "past_questions": past_questions[-8:],
                "fake_signals": fake_signals,
            })

        sys_p, user_p, schema = build_prompt(
            "review_pack",
            n=str(len(payload)),
            nodes_payload=json.dumps(payload, ensure_ascii=False),
        )
        result = self.llm.chat(sys_p, user_p, schema)

        # 按 nodes 顺序组装 items（schema: {"items": [{node_id, node_name, questions}]}）
        by_id = {}
        for item in result.get("items", []):
            by_id[item.get("node_id")] = item.get("questions", [])
        items = []
        for node in nodes:
            items.append({
                "node_id": node["id"],
                "node_name": node["name"],
                "questions": by_id.get(node["id"], []),
            })
        return items

    def run_review_answers(self, session_id: int, items: list[dict]) -> dict:
        """批量评估复习答案 → SM-2 → review_history + teaching_interactions.

        items: [{node_id, node_name, questions, answers}]
        副作用幂等：resume 重放时通过 run 缓存+local step 标记跳过重复写入。
        """
        apply_key = f"apply-review:{session_id}:{self.track_id}"
        if self.run and self.run_store:
            cached = self.run_store.cache_get(self.run, apply_key)
            if cached is not None:
                return cached

        results = []
        for item in items:
            node_id = item["node_id"]
            questions = item.get("questions", [])
            answers = item.get("answers", [])
            node = self.db.fetch_one(
                "SELECT * FROM knowledge_nodes WHERE id = ?", [node_id]
            )
            if not node or len(questions) != len(answers):
                continue
            node = dict(node)

            from ..llm.prompts import build_prompt
            items_payload = [{
                "question": q.get("question", ""),
                "correct_answer": q.get("answer", ""),
                "learner_answer": a,
            } for q, a in zip(questions, answers)]
            sys_p, user_p, schema = build_prompt(
                "evaluate_answers_batch",
                concept=node["name"],
                context="（复习检验）",
                items=json.dumps(items_payload, ensure_ascii=False),
            )
            batch = self.llm.chat(sys_p, user_p, schema)

            per_results = batch.get("results", [])
            qualities = []
            correct_count = 0
            for i, (q, a) in enumerate(zip(questions, answers)):
                ev = per_results[i] if i < len(per_results) else {"correct": False, "level": 1}
                quality = quality_from_eval(ev.get("correct", False), ev.get("level", 1))
                qualities.append(quality)
                if ev.get("correct"):
                    correct_count += 1
                self._store_interaction(
                    user_id=self.user_id,
                    node_id=node_id,
                    question=q.get("question", ""),
                    answer=a,
                    correct=ev.get("correct", False),
                    level=ev.get("level", 1),
                    fake_signals=ev.get("fake_signals", []),
                    interaction_type="review_session",
                )
            avg_quality = round(sum(qualities) / len(qualities)) if qualities else 3
            sm2 = self._apply_sm2(node_id, avg_quality)

            # review_history 落库（dao_review）
            self._store_review_history(node_id, avg_quality, sm2)

            results.append({
                "node_id": node_id,
                "node_name": node["name"],
                "correct_count": correct_count,
                "total": len(questions),
                "sm2": sm2,
                "results": per_results,
                "overall_feedback": batch.get("overall_feedback", ""),
            })

        result = {"items": results}
        if self.run and self.run_store:
            self.run_store.cache_set(self.run, apply_key, result)
            self.run_store.mark_step_done(self.run, apply_key)
        return result

    def _get_node_past_questions(self, node_id: int) -> list[str]:
        try:
            rows = self.db.fetch_all(
                "SELECT question FROM interaction_log "
                "WHERE user_id = ? AND node_id = ? ORDER BY id DESC LIMIT 20",
                [self.user_id, node_id],
            )
            return [r["question"] for r in rows]
        except Exception:
            return []

    def _get_node_fake_signals(self, node_id: int) -> list[str]:
        try:
            rows = self.db.fetch_all(
                "SELECT fake_signals FROM interaction_log "
                "WHERE user_id = ? AND node_id = ? AND fake_signals != '[]' "
                "ORDER BY id DESC LIMIT 10",
                [self.user_id, node_id],
            )
            signals = []
            for r in rows:
                try:
                    raw = json.loads(r["fake_signals"])
                    signals.extend(s.get("type", "") for s in raw if isinstance(s, dict))
                except (json.JSONDecodeError, TypeError):
                    continue
            return list(dict.fromkeys(signals))
        except Exception:
            return []

    def _store_review_history(self, node_id: int, quality: int, sm2: dict):
        try:
            self.db.execute(
                "INSERT INTO review_history (node_id, quality, ef_after, interval_after, reviewed_at) "
                "VALUES (?, ?, ?, ?, datetime('now', 'localtime'))",
                [node_id, quality, sm2.get("ef", 2.5), sm2.get("interval_days", 0)],
            )
        except Exception as e:
            logger.warning("Failed to store review history: %s", e)

    # ── Internal helpers ──

    def _search_context(self, topic: str) -> str:
        """搜索主题相关上下文."""
        try:
            results = self.search.search(topic, max_results=8)
            snippets = []
            for r in results[:8]:
                snippets.append(f"- {r.get('title', '')}: {r.get('content', '')[:200]}")
            return "\n".join(snippets) if snippets else "未找到相关搜索结果。"
        except Exception as e:
            logger.warning("Search failed during diagnosis: %s", e)
            return "搜索不可用。"

    def _generate_teach_pack(
        self, concept: str, level: str, prerequisites: list[str],
        misconceptions: list[dict], topic: str = "",
    ) -> tuple[dict, list[dict]]:
        """LLM 生成教学包（教学内容 + 检验题，单次调用；v0.2.2）."""
        from ..llm.prompts import build_prompt
        level_map = {"foundational": 1, "intermediate": 3, "advanced": 5}
        sys_p, user_p, schema = build_prompt(
            "teach_pack",
            concept=concept,
            topic=topic,
            level=level_map.get(level, 3),
            prerequisites=", ".join(prerequisites) if prerequisites else "无",
            misconceptions=json.dumps(
                [m.get("misconception", "") for m in misconceptions],
                ensure_ascii=False,
            ),
        )
        result = self.llm.chat(sys_p, user_p, schema)
        content = {k: result.get(k, "") for k in (
            "intuition", "motivation", "definition", "boundary", "connections", "examples",
        )}
        questions = result.get("questions", [])
        return content, questions

    def _get_prerequisites(self, node_id: int) -> list[str]:
        """获取前置概念列表 (从 node_dependencies)."""
        try:
            rows = self.db.fetch_all(
                "SELECT n.name FROM knowledge_nodes n "
                "JOIN node_dependencies d ON n.id = d.depends_on_id "
                "WHERE d.node_id = ? AND d.relation_type = 'prerequisite'",
                [node_id],
            )
            if rows:
                return [r["name"] for r in rows]
        except Exception as e:
            logger.warning("Failed to get prerequisites for node %d: %s", node_id, e)
        return []

    def _get_node_misconceptions(self, session: dict, concept: str) -> list[dict]:
        """获取节点相关的迷思概念."""
        diagnosis = session.get("diagnosis", {})
        all_mc = diagnosis.get("misconceptions", [])
        return [m for m in all_mc if m.get("concept") == concept]

    def _create_node(self, name: str, level: str, complexity: int,
                     description: str) -> int:
        """在 DB 中创建知识节点（v0.2.1 幂等：先查后插，重放不重复建）."""
        from datetime import timezone
        now = datetime.now(timezone.utc).isoformat()
        existing = self.db.fetch_one(
            "SELECT id FROM knowledge_nodes WHERE track_id = ? AND name = ?",
            [self.track_id, name],
        )
        if existing:
            return existing["id"]
        return self.db.execute(
            """INSERT INTO knowledge_nodes
               (track_id, name, importance, description, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'pending', ?, ?)""",
            [self.track_id, name, complexity, description, now, now],
        )

    def _create_edge(self, source_id: int, target_id: int,
                     relation: str):
        """创建知识边 (存入 node_dependencies, v0.2.2 枚举收窄为 prerequisite/related/part_of)."""
        mapped = relation if relation in ("prerequisite", "related", "part_of") else "related"
        try:
            self.db.execute(
                "INSERT OR IGNORE INTO node_dependencies "
                "(node_id, depends_on_id, relation_type) "
                "VALUES (?, ?, ?)",
                [target_id, source_id, mapped],
            )
        except Exception as e:
            logger.warning("Failed to create edge %d->%d (%s): %s",
                          source_id, target_id, mapped, e)

    def _apply_sm2(self, node_id: int, quality: int) -> dict:
        """应用 SM-2 算法更新节点复习参数."""
        from ..core.sm2 import SM2Calculator

        # Get current node data
        node = self.db.fetch_one(
            "SELECT * FROM knowledge_nodes WHERE id = ?", [node_id]
        )
        if not node:
            return {"error": "node not found"}
        node = dict(node)

        ef = node.get("ef", 2.5) or 2.5
        interval = node.get("interval", 0) or 0
        reps = node.get("repetitions", 0) or 0

        result = SM2Calculator.compute(
            quality=quality, ef=ef, interval_days=interval,
            repetitions=reps, today=date.today(),
        )

        self.db.execute(
            "UPDATE knowledge_nodes SET ef = ?, interval = ?, "
            "repetitions = ?, next_review = ?, updated_at = ? WHERE id = ?",
            [result["ef"], result["interval_days"], result["repetitions"],
             result["next_review"],
             datetime.now(timezone.utc).isoformat(), node_id],
        )

        return result

    def _store_interaction(self, user_id: str, node_id: int,
                           question: str, answer: str,
                           correct: bool, level: int,
                           fake_signals: list,
                           interaction_type: str = "deep_teaching"):
        """存储互动记录到 interaction_log 表（v0.2.2: 吸收 teaching_interactions 类型标签）."""
        from datetime import timezone
        now = datetime.now(timezone.utc).isoformat()
        signals_json = json.dumps(fake_signals, ensure_ascii=False)
        try:
            self.db.execute(
                """INSERT INTO interaction_log
                   (user_id, track_id, node_id, question, answer,
                    is_correct, understanding_level, fake_signals, interaction_type, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [user_id, self.track_id, node_id, question, answer,
                 int(correct), level, signals_json, interaction_type, now],
            )
        except Exception as e:
            logger.error("Failed to store interaction: %s", e)

    def _store_misconception(self, node_id: int, misconception: str,
                             correction: str):
        """存储迷思概念记录."""
        from datetime import timezone
        now = datetime.now(timezone.utc).isoformat()
        try:
            self.db.execute(
                """INSERT INTO misconceptions
                   (user_id, node_id, misconception, correction, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                [self.user_id, node_id, misconception, correction, now],
            )
        except Exception as e:
            logger.warning("Failed to store misconception for node %d: %s", node_id, e)

    def _get_interactions(self, user_id: str, track_id: int) -> list[dict]:
        """获取用户在当前路线的全部互动记录 (仅 interaction_log)."""
        try:
            rows = self.db.fetch_all(
                "SELECT * FROM interaction_log "
                "WHERE user_id = ? AND track_id = ? "
                "ORDER BY created_at ASC",
                [user_id, track_id],
            )
            if rows:
                return [dict(r) for r in rows]
        except Exception as e:
            logger.warning("Failed to get interactions for user %s: %s", user_id, e)
        return []

    def _compute_stats(self, interactions: list[dict]) -> dict:
        """计算学习互动统计."""
        total = len(interactions)
        if total == 0:
            return {"total": 0, "correct": 0, "rate": 0.0,
                    "avg_level": 0.0, "fake_count": 0}

        correct = sum(1 for i in interactions if i.get("is_correct"))
        levels = [i.get("understanding_level", 1) for i in interactions]
        fake_count = 0
        for i in interactions:
            raw = i.get("fake_signals")
            if raw:
                try:
                    signals = json.loads(raw)
                    if signals:
                        fake_count += 1
                except (json.JSONDecodeError, TypeError):
                    pass

        return {
            "total": total,
            "correct": correct,
            "rate": correct / total,
            "avg_level": sum(levels) / len(levels),
            "fake_count": fake_count,
        }
