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


class TeachingOrchestrator:
    """教学编排器，唯一的核心流程控制器."""

    def __init__(self, db, llm, search, user_id: str, track_id: int):
        self.db = db
        self.llm = llm
        self.search = search
        self.user_id = user_id
        self.track_id = track_id
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
        """诊断阶段：搜索 -> 知识图谱 -> LLM 诊断 -> 建节点."""
        logger.info("Starting diagnosis for topic: %s", topic)

        # Step 1: Search for context
        search_results = self._search_context(topic)

        # Step 2: LLM knowledge graph assessment
        kg = self._assess_knowledge_graph(topic, search_results)

        # Step 3: Determine prerequisite nodes
        concepts = kg.get("concepts", [])
        edges = kg.get("edges", [])

        # Step 4: LLM diagnosis
        from ..llm.prompts import build_prompt
        sys_p, user_p, schema = build_prompt(
            "diagnosis",
            topic=topic,
            concepts=json.dumps([c["name"] for c in concepts], ensure_ascii=False),
            self_assessment=str(self_assessment),
            user_description=user_description or "未提供",
            test_results="待测试",
        )
        diagnosis = self.llm.chat(sys_p, user_p, schema)

        # Step 5: Build knowledge nodes in DB
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

        session_id = self.session_manager.create_session(
            self.user_id, self.track_id, topic, session_data
        )

        # Set diagnosis level on track
        self.db.execute(
            "UPDATE tracks SET level = ? WHERE id = ?",
            [diagnosis.get("level", 1), self.track_id],
        )

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

        # Step 1: LLM generate concept content
        content = self._generate_concept_content(
            concept=node["name"],
            level=node.get("level", "foundational"),
            prerequisites=self._get_prerequisites(node_id),
            misconceptions=self._get_node_misconceptions(session, node["name"]),
        )

        # Step 2: Render and return content for display
        from .render import render_concept_content
        rendered = render_concept_content(content, node["name"])

        # Step 3: LLM generate test questions
        questions = self._generate_test_questions(
            concept=node["name"],
            content=json.dumps(content, ensure_ascii=False),
        )

        result = {
            "node_id": node_id,
            "node_name": node["name"],
            "concept_content": content,
            "rendered": rendered,
            "questions": questions,
            "session_id": session_id,
        }
        return result

    def submit_answer(self, session_id: int, node_id: int,
                      question: dict, answer: str) -> dict:
        """提交单题答案并评估."""
        session = self.session_manager.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        node = self.db.fetch_one(
            "SELECT * FROM knowledge_nodes WHERE id = ?", [node_id]
        )
        if not node:
            raise ValueError(f"Node {node_id} not found")
        node = dict(node)

        # LLM evaluate
        from ..llm.prompts import build_prompt
        sys_p, user_p, schema = build_prompt(
            "evaluate_answer",
            concept=node["name"],
            question=question["question"],
            correct_answer=question["answer"],
            learner_answer=answer,
        )
        evaluation = self.llm.chat(sys_p, user_p, schema)

        # SM-2 calculation
        quality = 5 if evaluation.get("correct") else (
            evaluation.get("level", 3)
        )
        sm2 = self._apply_sm2(node_id, quality)

        # Store interaction
        self._store_interaction(
            user_id=self.user_id,
            node_id=node_id,
            question=question["question"],
            answer=answer,
            correct=evaluation.get("correct", False),
            level=evaluation.get("level", 1),
            fake_signals=evaluation.get("fake_signals", []),
        )

        # Store misconception if detected
        for signal in evaluation.get("fake_signals", []):
            if signal.get("type") == "misconception":
                self._store_misconception(
                    node_id=node_id,
                    misconception=signal.get("detail", ""),
                    correction=evaluation.get("feedback", ""),
                )

        result = {
            "correct": evaluation.get("correct", False),
            "level": evaluation.get("level", 1),
            "feedback": evaluation.get("feedback", ""),
            "fake_signals": evaluation.get("fake_signals", []),
            "sm2": sm2,
        }
        return result

    def complete_node(self, session_id: int, node_id: int):
        """完成节点教学，更新状态."""
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

        # Build assessment prompt
        stats = self._compute_stats(interactions)
        system_prompt = (
            "你是一个学习评估专家。基于学习者的完整互动记录，"
            "进行综合评估并生成学习报告。"
        )
        user_prompt = (
            f"主题：{topic}\n"
            f"目标概念数：{len(diagnosis.get('node_ids', []))}\n"
            f"已完成概念数：{len(completed_nodes)}\n\n"
            f"互动统计：\n"
            f"- 总答题数：{stats['total']}\n"
            f"- 正确数：{stats['correct']}\n"
            f"- 正确率：{stats['rate']:.1%}\n"
            f"- 平均理解水平：{stats['avg_level']:.1f}/5\n"
            f"- 假懂信号数：{stats['fake_count']}\n\n"
            f"请生成综合评估报告，包括：\n"
            f"1. 总体掌握水平（1-5）\n"
            f"2. 各概念掌握情况\n"
            f"3. 薄弱环节\n"
            f"4. 下一步学习建议\n"
            f"5. 复习计划建议（基于 SM-2）\n\n"
            f"以 JSON 格式输出。"
        )
        schema = {
            "name": "assessment_report",
            "schema": {
                "type": "object",
                "properties": {
                    "overall_level": {"type": "integer", "minimum": 1, "maximum": 5},
                    "concept_mastery": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "concept": {"type": "string"},
                                "level": {"type": "integer", "minimum": 1, "maximum": 5},
                                "status": {
                                    "type": "string",
                                    "enum": ["mastered", "learning", "struggling"],
                                },
                            },
                            "required": ["concept", "level", "status"],
                        },
                    },
                    "weaknesses": {"type": "array", "items": {"type": "string"}},
                    "recommendations": {"type": "array", "items": {"type": "string"}},
                    "review_plan": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "concept": {"type": "string"},
                                "next_review": {"type": "string"},
                                "interval_days": {"type": "integer"},
                            },
                            "required": ["concept", "next_review"],
                        },
                    },
                },
                "required": ["overall_level", "concept_mastery", "recommendations"],
            },
        }

        report = self.llm.chat(system_prompt, user_prompt, schema)

        # Update session
        self.session_manager.update_session(
            session_id,
            status="completed",
            level=report.get("overall_level", stats["avg_level"]),
        )

        # Update track level
        self.db.execute(
            "UPDATE tracks SET level = ?, updated_at = ? WHERE id = ?",
            [report.get("overall_level", 1),
             datetime.now(timezone.utc).isoformat(),
             self.track_id],
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

    # ── Author coaching ──

    def train_by_author(self, author_name: str, scenario: str = None) -> dict:
        """作者思维教练模式: 基于 L2+L3 教用户用作者的思维框架分析问题.

        1. 读取 L2 模型列表 + L3 persona
        2. 按依赖关系排序生成学习路径
        3. 三步教学: 示范(作者怎么想) → 练习(你试试) → 反馈(对比差异)
        4. 复用 SM-2 / FakeDetector / NUSAP
        """

        # Load L3 persona from DB
        persona_text = ""
        try:
            row = self.db.fetch_one(
                "SELECT persona_md FROM author_profiles WHERE author_name = ?",
                (author_name,),
            )
            if row and row.get("persona_md"):
                persona_text = row["persona_md"]
        except Exception as e:
            logger.warning("Failed to load persona for %s: %s", author_name, e)

        # Load L2 models from DB
        try:
            models = self.db.fetch_all(
                "SELECT * FROM mental_models WHERE author_name = ? ORDER BY evidence_count DESC",
                (author_name,),
            )
            models = [dict(m) for m in models] if models else []
        except Exception as e:
            logger.warning("Failed to load mental models for %s: %s", author_name, e)
            models = []

        if not models:
            return {"error": f"作者 {author_name} 没有 L2 心智模型"}

        # Build learning path: sort by foundational → applied
        path = self._build_learning_path(models, persona_text)

        # If scenario provided, generate demo
        demo = None
        if scenario:
            demo = self._generate_author_demo(author_name, models, persona_text, scenario)

        result = {
            "author_name": author_name,
            "model_count": len(models),
            "learning_path": path,
            "demo": demo,
            "scenario": scenario,
        }
        return result

    def _build_learning_path(self, models: list[dict], persona_text: str) -> list[dict]:
        """Build a recommended learning path from mental models.

        Uses LLM to sort models by dependency: foundational concepts first.
        """
        if len(models) <= 1:
            return [{"title": m["title"], "topic": m["topic"], "order": 1,
                     "reason": "唯一模型"} for m in models]

        model_list = "\n".join(
            f"- {m['title']} (topic: {m['topic']}, evidence: {m.get('evidence_count', '?')})"
            for m in models
        )

        try:
            from ..llm.prompts import build_prompt
            sys_p, user_p, schema = build_prompt(
                "author_learning_path",
                models_text=model_list,
            )
            result = self.llm.chat(sys_p, user_p, schema, temperature=0.3)
            return result.get("path", [])
        except Exception as e:
            logger.warning("Failed to build learning path: %s", e)
            return [{"title": m["title"], "topic": m["topic"], "order": i + 1,
                     "reason": "fallback 排序"} for i, m in enumerate(models)]

    def _generate_author_demo(self, author_name: str, models: list[dict],
                              persona_text: str, scenario: str) -> dict:
        """Generate a demonstration: how the author would analyze the given scenario."""
        models_text = "\n".join(
            f"- {m['title']}: {m.get('content_md', '')[:300]}"
            for m in models[:5]
        )

        try:
            from ..llm.prompts import build_prompt
            sys_p, user_p, schema = build_prompt(
                "author_demo",
                author_name=author_name,
                persona_text=persona_text[:2000],
                models_text=models_text[:2000],
                scenario=scenario,
            )
            result = self.llm.chat(sys_p, user_p, schema, temperature=0.5, max_tokens=4096)
            return result
        except Exception as e:
            logger.warning("Failed to generate author demo: %s", e)
            return {"error": str(e)}

    def apply_mental_model(self, model_id: int, problem: str) -> dict:
        """应用模式: 用作者的一个心智模型分析实际问题.

        1. 加载 mental_models 记录
        2. 生成作者式思维链示范
        3. 生成练习题让学习者尝试
        """
        try:
            row = self.db.fetch_one(
                "SELECT * FROM mental_models WHERE id = ?", (model_id,)
            )
        except Exception as e:
            return {"error": f"查询模型失败: {e}"}

        if not row:
            return {"error": f"模型 {model_id} 不存在"}

        model = dict(row)
        author_name = model.get("author_name", "")

        # Load persona for calibration from DB
        persona_text = ""
        try:
            p_row = self.db.fetch_one(
                "SELECT persona_md FROM author_profiles WHERE author_name = ?",
                (author_name,),
            )
            if p_row and p_row.get("persona_md"):
                persona_text = p_row["persona_md"][:1000]
        except Exception:
            pass

        prompt = f"""你是 {author_name}。基于以下心智模型分析问题:

心智模型: {model['title']}
内容:
{model.get('content_md', '')[:2000]}

作者认知校准:
{persona_text}

问题:
{problem}

请以作者视角:
1. 用该心智模型拆解问题
2. 给出分步分析
3. 得出结论

以 JSON 输出:
{{"analysis_steps": [{{"step": 1, "thinking": "..."}}],
 "conclusion": "...",
 "confidence": "high|medium|low",
 "boundary_notes": "该模型的适用边界说明"}}"""

        schema = {
            "name": "model_application",
            "schema": {
                "type": "object",
                "properties": {
                    "analysis_steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "step": {"type": "integer"},
                                "thinking": {"type": "string"},
                            },
                        },
                    },
                    "conclusion": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                    "boundary_notes": {"type": "string"},
                },
                "required": ["analysis_steps", "conclusion"],
            },
        }

        try:
            sys_p = "你是一个心智模型应用教练。严格基于给定的模型进行推理。"
            result = self.llm.chat(sys_p, prompt, schema, temperature=0.5, max_tokens=4096)

            # Generate practice question
            practice = self._generate_practice_question(model, problem)

            return {
                "model": {"id": model["id"], "title": model["title"], "topic": model["topic"]},
                "demo": result,
                "practice_question": practice,
            }
        except Exception as e:
            logger.warning("apply_mental_model failed: %s", e)
            return {"error": str(e)}

    def _generate_practice_question(self, model: dict, context: str) -> dict:
        """Generate a practice question based on the model."""
        prompt = f"""基于以下心智模型生成一个变式练习题，测试学习者是否真正理解了模型的适用方法（而非记住表面结论）:

模型: {model['title']}
模型内容: {model.get('content_md', '')[:1000]}
原问题: {context}

要求:
1. 新场景与原问题类似但不相同
2. 需要学习者自己运用模型的判断逻辑
3. 不直接考察记忆

输出 JSON:
{{"scenario": "新场景描述", "question": "问题", "expected_approach": "期望的分析路径", "success_criteria": "答对的判定标准"}}"""

        schema = {
            "name": "practice",
            "schema": {
                "type": "object",
                "properties": {
                    "scenario": {"type": "string"},
                    "question": {"type": "string"},
                    "expected_approach": {"type": "string"},
                    "success_criteria": {"type": "string"},
                },
                "required": ["scenario", "question"],
            },
        }

        try:
            return self.llm.chat(
                "你是教学练习设计专家。", prompt, schema, temperature=0.7,
            )
        except Exception:
            return {"scenario": "（练习生成失败）"}

    def write_as_author(self, author_name: str, topic: str,
                        validate: bool = True) -> dict:
        """写作镜像模式: 加载 L4 writing-mirror 作为 system prompt 生成仿写文章."""

        # Load mirror from DB
        mirror_content = None
        try:
            row = self.db.fetch_one(
                "SELECT mirror_md FROM author_profiles WHERE author_name = ?",
                (author_name,),
            )
            if row and row.get("mirror_md"):
                mirror_content = row["mirror_md"]
        except Exception:
            pass

        if not mirror_content:
            return {"error": f"作者 {author_name} 的写作镜像未生成，请先完成 L4 提炼"}

        # Use mirror as system prompt
        write_prompt = f"""请以「{author_name}」的风格，写一篇关于「{topic}」的文章。

遵循写作镜像中的全部指令: 认知先行 → 表达包装 → 结构组织 → 诚实检查。

直接输出文章，不需要 JSON 包装或额外说明。"""

        try:
            article = self.llm.chat(
                mirror_content, write_prompt,
                temperature=0.7, max_tokens=4096,
            )
        except Exception as e:
            logger.warning("write_as_author failed: %s", e)
            return {"error": f"生成失败: {e}"}

        # When schema is None, chat() may return {"response": text}
        article_text = article.get("response", "") if isinstance(article, dict) else str(article)
        if not article_text:
            article_text = json.dumps(article, ensure_ascii=False)

        result = {"article": article_text, "author_name": author_name, "topic": topic}

        # Quality validation
        if validate:
            quality_report = self._validate_writing(
                author_name, article_text, mirror_content,
            )
            result["quality_report"] = quality_report

        return result

    def _validate_writing(self, author_name: str, article: str,
                          mirror_content: str) -> dict:
        """Validate generated article against author's persona and expression DNA."""
        # Load persona from DB
        persona_text = ""
        try:
            p_row = self.db.fetch_one(
                "SELECT persona_md FROM author_profiles WHERE author_name = ?",
                (author_name,),
            )
            if p_row and p_row.get("persona_md"):
                persona_text = p_row["persona_md"]
        except Exception:
            pass

        # Extract expression DNA section from persona
        expr_section = ""
        if "## 表达DNA" in persona_text:
            expr_section = persona_text.split("## 表达DNA", 1)[1][:2000]

        # Extract mental models summary
        models_summary = ""
        try:
            models = self.db.fetch_all(
                "SELECT title, content_md FROM mental_models WHERE author_name = ? LIMIT 5",
                (author_name,),
            )
            if models:
                models_summary = "\n".join(
                    f"- {m['title']}: {m['content_md'][:200]}"
                    for m in models
                )
        except Exception:
            pass

        validate_prompt = f"""目标作者: {author_name}
目标作者表达DNA: {expr_section[:1500]}
目标作者认知体系: {models_summary[:1000]}

待评估仿写文章:
{article[:3000]}

评估维度:
1. 表达DNA辨识度 (1-5): 句式、词汇、语气是否像作者
2. 认知一致性 (1-5): 分析逻辑是否符合作者的心智模型
3. 诚实边界 (1-5): 不确定处是否诚实，是否越界

输出 JSON:
{{"expression_score": <1-5>, "expression_notes": "...",
 "cognition_score": <1-5>, "cognition_notes": "...",
 "honesty_score": <1-5>, "honesty_notes": "...",
 "verdict": "pass|pass_with_warnings|fail",
 "improvement_suggestions": ["..."]}}"""

        validate_schema = {
            "name": "quality_report",
            "schema": {
                "type": "object",
                "properties": {
                    "expression_score": {"type": "integer", "minimum": 1, "maximum": 5},
                    "expression_notes": {"type": "string"},
                    "cognition_score": {"type": "integer", "minimum": 1, "maximum": 5},
                    "cognition_notes": {"type": "string"},
                    "honesty_score": {"type": "integer", "minimum": 1, "maximum": 5},
                    "honesty_notes": {"type": "string"},
                    "verdict": {"type": "string", "enum": ["pass", "pass_with_warnings", "fail"]},
                    "improvement_suggestions": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["expression_score", "cognition_score", "honesty_score", "verdict"],
            },
        }

        try:
            sys_p = "你是写作质量评估器。只评估模仿准确性，不评判内容好坏。"
            result = self.llm.chat(sys_p, validate_prompt, validate_schema, temperature=0.3)
            return result
        except Exception as e:
            logger.warning("Quality validation failed: %s", e)
            return {"error": str(e), "verdict": "fail"}

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

    def _assess_knowledge_graph(self, topic: str, search_results: str) -> dict:
        """LLM 评估知识图谱."""
        from ..llm.prompts import build_prompt
        sys_p, user_p, schema = build_prompt(
            "assess_knowledge_graph",
            topic=topic,
            search_results=search_results,
        )
        return self.llm.chat(sys_p, user_p, schema)

    def _generate_concept_content(
        self, concept: str, level: str, prerequisites: list[str],
        misconceptions: list[dict],
    ) -> dict:
        """LLM 生成概念教学材料."""
        from ..llm.prompts import build_prompt
        level_map = {"foundational": 1, "intermediate": 3, "advanced": 5}
        sys_p, user_p, schema = build_prompt(
            "concept_content",
            concept=concept,
            topic="",
            level=level_map.get(level, 3),
            prerequisites=", ".join(prerequisites) if prerequisites else "无",
            misconceptions=json.dumps(
                [m.get("misconception", "") for m in misconceptions],
                ensure_ascii=False,
            ),
        )
        return self.llm.chat(sys_p, user_p, schema)

    def _generate_test_questions(self, concept: str, content: str) -> list[dict]:
        """LLM 生成检验题."""
        from ..llm.prompts import build_prompt
        sys_p, user_p, schema = build_prompt(
            "test_questions",
            concept=concept,
            content=content,
            count="3",
            question_types="conceptual, applied, discrimination",
        )
        result = self.llm.chat(sys_p, user_p, schema)
        return result.get("questions", [])

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
        """在 DB 中创建知识节点."""
        from datetime import timezone
        now = datetime.now(timezone.utc).isoformat()
        # level → node_type, complexity → importance
        node_type_map = {
            "foundational": "concept",
            "intermediate": "principle",
            "advanced": "framework",
        }
        return self.db.execute(
            """INSERT INTO knowledge_nodes
               (track_id, name, node_type, importance, description, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)""",
            [self.track_id, name, node_type_map.get(level, "concept"),
             complexity, description, now, now],
        )

    def _create_edge(self, source_id: int, target_id: int,
                     relation: str):
        """创建知识边 (存入 node_dependencies)."""
        relation_map = {
            "prerequisite": "prerequisite",
            "related": "related",
            "part_of": "part_of",
            "extends": "supports",
        }
        mapped = relation_map.get(relation, "related")
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
            "repetitions = ?, updated_at = ? WHERE id = ?",
            [result["ef"], result["interval"], result["repetitions"],
             datetime.now(timezone.utc).isoformat(), node_id],
        )

        return result

    def _store_interaction(self, user_id: str, node_id: int,
                           question: str, answer: str,
                           correct: bool, level: int,
                           fake_signals: list):
        """存储互动记录到 interaction_log 表."""
        from datetime import timezone
        now = datetime.now(timezone.utc).isoformat()
        signals_json = json.dumps(fake_signals, ensure_ascii=False)
        try:
            self.db.execute(
                """INSERT INTO interaction_log
                   (user_id, track_id, node_id, question, answer,
                    is_correct, understanding_level, fake_signals, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [user_id, self.track_id, node_id, question, answer,
                 int(correct), level, signals_json, now],
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
