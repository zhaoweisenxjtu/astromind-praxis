"""LLM 调用点的结构化提示词和输出 schema (v0.2.2).

v0.2.2 变更：8 个调用点收敛为 5 个——
  - diagnose_pack：合并 assess_knowledge_graph + diagnosis（诊断阶段 1 次往返）
  - teach_pack：合并 concept_content + test_questions（教学阶段 1 次往返）
  - evaluate_answers_batch：保留（批量答案评估）
  - review_pack：多节点批量复习出题（替代逐节点 review_questions）
  - assessment：注册化（原 workflow 手写 prompt）
删除：assess_knowledge_graph / diagnosis / concept_content / test_questions /
     evaluate_answer（单题，agent 模式已走批量）/ review_questions
"""


# ── 1. 诊断包: 知识图谱 + 水平/缺口/迷思/路径（合并 KG 评估与诊断）──

DIAGNOSE_PACK_SYSTEM = """你是学习诊断专家。基于搜索结果完成两件事：
1. 构建主题知识图谱（核心概念 + 概念间依赖关系）
2. 结合用户自评诊断当前水平、知识缺口、迷思概念，给出推荐学习路径"""

DIAGNOSE_PACK_USER = """主题：{topic}
搜索结果：
{search_results}

用户自评水平（1-5）：{self_assessment}
用户自述理解：{user_description}

要求：
1. 提取 5-15 个核心概念，标注层次（foundational/intermediate/advanced）与复杂度（1-5）
2. 标识概念间依赖关系（prerequisite / related / part_of）
3. 诊断用户的当前综合水平（1-5）、知识缺口（missing/weak/unstable）、可能的迷思概念
4. 给出推荐学习路径（概念学习顺序）

以 JSON 格式输出。"""

DIAGNOSE_PACK_SCHEMA = {
    "name": "diagnose_pack",
    "schema": {
        "type": "object",
        "properties": {
            "concepts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "level": {"type": "string", "enum": ["foundational", "intermediate", "advanced"]},
                        "complexity": {"type": "integer", "minimum": 1, "maximum": 5},
                        "description": {"type": "string"},
                    },
                    "required": ["name", "level", "complexity"],
                },
            },
            "edges": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "source": {"type": "string"},
                        "target": {"type": "string"},
                        "relation": {"type": "string", "enum": ["prerequisite", "related", "part_of"]},
                    },
                    "required": ["source", "target", "relation"],
                },
            },
            "level": {"type": "integer", "minimum": 1, "maximum": 5},
            "gaps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "concept": {"type": "string"},
                        "gap_type": {"type": "string", "enum": ["missing", "weak", "unstable"]},
                        "description": {"type": "string"},
                    },
                    "required": ["concept", "gap_type"],
                },
            },
            "misconceptions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "concept": {"type": "string"},
                        "misconception": {"type": "string"},
                        "correction": {"type": "string"},
                    },
                    "required": ["concept", "misconception"],
                },
            },
            "recommended_path": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": ["concepts", "edges", "level", "gaps", "misconceptions", "recommended_path"],
    },
}


# ── 2. 教学包: 教学内容 + 检验题（合并概念教学与出题）──

TEACH_PACK_SYSTEM = """你是教学专家。一次性完成两件事：
1. 按「直觉构建 → 动机激发 → 形式定义 → 边界澄清 → 示例」认知序列生成教学材料
2. 基于该材料出 3 道检验题（conceptual / applied / discrimination 各一），
   用于检测真实理解而非表面记忆（含变式题与边界案例）"""

TEACH_PACK_USER = """概念：{concept}
主题：{topic}
学习者水平：{level}/5
前置概念：{prerequisites}
相关迷思概念：{misconceptions}

输出两部分：
A. 教学材料：
   1. intuition — 直觉构建（日常类比或直观示例）
   2. motivation — 为什么重要？解决什么问题？
   3. definition — 精确定义（如适用）
   4. boundary — 适用边界、常见错误理解
   5. connections — 与前后概念的联系
   6. examples — 1-3 个例题（从易到难）
B. 检验题：3 道，覆盖 conceptual（为什么）/ applied（怎么做）/ discrimination（辨析）

以 JSON 格式输出。"""

TEACH_PACK_SCHEMA = {
    "name": "teach_pack",
    "schema": {
        "type": "object",
        "properties": {
            "intuition": {"type": "string"},
            "motivation": {"type": "string"},
            "definition": {"type": "string"},
            "boundary": {"type": "string"},
            "connections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "concept": {"type": "string"},
                        "relation": {"type": "string"},
                    },
                    "required": ["concept", "relation"],
                },
            },
            "examples": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "solution": {"type": "string"},
                        "difficulty": {"type": "integer", "minimum": 1, "maximum": 5},
                    },
                    "required": ["question", "solution"],
                },
            },
            "questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "options": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "answer": {"type": "string"},
                        "explanation": {"type": "string"},
                        "type": {
                            "type": "string",
                            "enum": ["conceptual", "applied", "discrimination"],
                        },
                        "difficulty": {"type": "integer", "minimum": 1, "maximum": 5},
                    },
                    "required": ["question", "answer", "explanation", "type"],
                },
            },
        },
        "required": ["intuition", "motivation", "definition", "boundary", "examples", "questions"],
    },
}


# ── 3. 批量评估: 一次评估全部答案（教学或复习）──

EVALUATE_BATCH_SYSTEM = """你是评估专家。批量判断学习者的回答是否正确，
并检测每道题的「假懂」信号（表面记忆、机械套用、混淆概念等）。"""

EVALUATE_BATCH_USER = """概念：{concept}
教学情境：{context}

题目与回答（每项含题目、正确答案、学习者回答）：
{items}

请逐题评估：
1. 是否正确（true/false）
2. 理解水平（1-5）
3. 假懂信号（如果有，type ∈ rote_memory/misconception/guessing/surface_understanding）
4. 该题反馈（针对性的纠正或鼓励）

最后给出整体反馈（指出共性薄弱点）。

以 JSON 格式输出。"""

EVALUATE_BATCH_SCHEMA = {
    "name": "evaluate_answers_batch",
    "schema": {
        "type": "object",
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "correct": {"type": "boolean"},
                        "level": {"type": "integer", "minimum": 1, "maximum": 5},
                        "fake_signals": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "type": {
                                        "type": "string",
                                        "enum": ["rote_memory", "misconception", "guessing", "surface_understanding"],
                                    },
                                    "detail": {"type": "string"},
                                },
                                "required": ["type", "detail"],
                            },
                        },
                        "feedback": {"type": "string"},
                    },
                    "required": ["question", "correct", "level", "feedback"],
                },
            },
            "overall_feedback": {"type": "string"},
        },
        "required": ["results", "overall_feedback"],
    },
}


# ── 4. 复习包: 多节点批量检索练习出题（v0.2.2）──

REVIEW_PACK_SYSTEM = """你是复习出题专家。为多个到期节点批量出检索练习题（retrieval practice）。
原则：复习≠重学——只出题不附讲解，最大化测试效应。"""

REVIEW_PACK_USER = """以下 {n} 个节点到期复习。为每个节点出 2 道检索练习题，
覆盖 recall（自由回忆）/ application（情境应用）/ discrimination（辨析）三类中的不同类型。

节点列表（JSON 数组，每项含 node_id / node_name / 教学内容摘要 / 历史作答 / 历史假懂信号）：
{nodes_payload}

规则：
1. 每个节点恰好 2 题
2. 避免历史原题重考（可出变式）
3. 若节点有历史假懂信号，至少 1 题针对曾暴露的信号
4. 只出题，不附讲解

以 JSON 格式输出（{{"items": [{{"node_id": N, "questions": [...]}}]}}）。"""

REVIEW_PACK_SCHEMA = {
    "name": "review_pack",
    "schema": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "node_id": {"type": "integer"},
                        "questions": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "question": {"type": "string"},
                                    "options": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "answer": {"type": "string"},
                                    "explanation": {"type": "string"},
                                    "type": {
                                        "type": "string",
                                        "enum": ["recall", "application", "discrimination"],
                                    },
                                    "difficulty": {"type": "integer", "minimum": 1, "maximum": 5},
                                },
                                "required": ["question", "answer", "explanation", "type"],
                            },
                        },
                    },
                    "required": ["node_id", "questions"],
                },
            },
        },
        "required": ["items"],
    },
}


# ── 5. 综合评估报告（v0.2.2 注册化，原 workflow 手写 prompt）──

ASSESSMENT_SYSTEM = """你是一个学习评估专家。基于学习者的完整互动记录，
进行综合评估并生成学习报告。"""

ASSESSMENT_USER = """主题：{topic}
目标概念数：{node_count}
已完成概念数：{completed_count}

互动统计（JSON）：
{stats}

请生成综合评估报告，包括：
1. 总体掌握水平（1-5）
2. 各概念掌握情况（mastered/learning/struggling）
3. 薄弱环节
4. 下一步学习建议
5. 复习计划建议（基于 SM-2）

以 JSON 格式输出。"""

ASSESSMENT_SCHEMA = {
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


# ── 提示词注册表 ──

PROMPT_REGISTRY = {
    "diagnose_pack": {
        "system": DIAGNOSE_PACK_SYSTEM,
        "user_template": DIAGNOSE_PACK_USER,
        "schema": DIAGNOSE_PACK_SCHEMA,
    },
    "teach_pack": {
        "system": TEACH_PACK_SYSTEM,
        "user_template": TEACH_PACK_USER,
        "schema": TEACH_PACK_SCHEMA,
    },
    "evaluate_answers_batch": {
        "system": EVALUATE_BATCH_SYSTEM,
        "user_template": EVALUATE_BATCH_USER,
        "schema": EVALUATE_BATCH_SCHEMA,
    },
    "review_pack": {
        "system": REVIEW_PACK_SYSTEM,
        "user_template": REVIEW_PACK_USER,
        "schema": REVIEW_PACK_SCHEMA,
    },
    "assessment": {
        "system": ASSESSMENT_SYSTEM,
        "user_template": ASSESSMENT_USER,
        "schema": ASSESSMENT_SCHEMA,
    },
}


def build_prompt(name: str, **kwargs) -> tuple[str, str, dict | None]:
    """Build system and user prompts for a named call point.

    Args:
        name: Prompt name in PROMPT_REGISTRY.
        **kwargs: Variables to fill into the user template.

    Returns:
        (system_prompt, user_prompt, schema_or_None)
    """
    entry = PROMPT_REGISTRY.get(name)
    if not entry:
        raise ValueError(f"Unknown prompt: {name}. Available: {list(PROMPT_REGISTRY.keys())}")

    system = entry["system"]
    user = entry["user_template"].format(**kwargs)
    schema = entry.get("schema")
    return system, user, schema
