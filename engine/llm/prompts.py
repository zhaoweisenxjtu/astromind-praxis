"""LLM 调用点的结构化提示词和输出 schema."""

# ── 1. 知识图谱评估: 搜索 + 提取概念图 ──

ASSESS_KNOWLEDGE_GRAPH_SYSTEM = """你是一个学习诊断专家。根据搜索结果，分析用户想要学习的主题，
提取出该主题的核心概念体系和概念之间的关系。"""

ASSESS_KNOWLEDGE_GRAPH_USER = """请分析以下搜索结果，为主题「{topic}」构建知识图谱。

搜索结果：
{search_results}

要求：
1. 提取 5-15 个核心概念
2. 标识概念间的依赖关系（prerequisite / related / part_of）
3. 估算每个概念的复杂度（1-5）
4. 区分 foundational / intermediate / advanced 三个层次

以 JSON 格式输出。"""

ASSESS_KNOWLEDGE_GRAPH_SCHEMA = {
    "name": "knowledge_graph",
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
        },
        "required": ["concepts", "edges"],
    },
}


# ── 2. 诊断: 水平及缺口 ──

DIAGNOSIS_SYSTEM = """你是一个学习诊断专家。通过分析用户的自评和概念理解，
评估用户的当前水平、知识缺口和可能存在的迷思概念。"""

DIAGNOSIS_USER = """主题：{topic}
目标概念：{concepts}

用户自评水平（1-5）：{self_assessment}
用户自述理解：{user_description}
概念理解测试结果：{test_results}

请诊断：
1. 用户的当前综合水平（1-5）
2. 知识缺口（哪些概念缺失或薄弱）
3. 可能的迷思概念
4. 推荐的学习路径（概念顺序）

以 JSON 格式输出。"""

DIAGNOSIS_SCHEMA = {
    "name": "diagnosis",
    "schema": {
        "type": "object",
        "properties": {
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
        "required": ["level", "gaps", "misconceptions", "recommended_path"],
    },
}


# ── 3. 概念教学: 生成教学材料 ──

CONCEPT_CONTENT_SYSTEM = """你是一个教学专家。为给定概念生成结构化的教学材料，
遵循「直觉构建 → 动机激发 → 形式定义 → 边界澄清 → 示例」的认知序列。"""

CONCEPT_CONTENT_USER = """请为概念「{concept}」生成教学材料。

主题：{topic}
学习者水平：{level}/5
前置概念：{prerequisites}
相关迷思概念：{misconceptions}

教学材料需要包含：
1. 直觉构建 — 用日常类比或直观示例建立直觉
2. 动机 — 为什么这个概念重要？解决什么问题？
3. 形式定义 — 精确定义（如果适用）
4. 边界条件 — 适用边界、常见错误理解
5. 关联概念 — 与前后概念的联系
6. 例题 — 1-3 个例题（从易到难）

以 JSON 格式输出。"""

CONCEPT_CONTENT_SCHEMA = {
    "name": "concept_content",
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
        },
        "required": ["intuition", "motivation", "definition", "boundary", "examples"],
    },
}


# ── 4. 检验题: 生成检验题目 ──

TEST_QUESTIONS_SYSTEM = """你是出题专家。根据概念教学材料生成检验题目，
用于检测学习者是否真正理解（而非表面记忆）。

请设计能暴露「假懂」的题目：
- 包含变式题（改变非本质特征）
- 包含边界案例
- 包含需要区分的易混淆概念"""

TEST_QUESTIONS_USER = """概念：{concept}
教学材料：{content}

请生成 {count} 道检验题，覆盖：
1. 至少 1 道概念理解题（为什么）
2. 至少 1 道应用题（怎么做）
3. 至少 1 道辨析题（区分易混淆概念）

题型：{question_types}

以 JSON 格式输出。"""

TEST_QUESTIONS_SCHEMA = {
    "name": "test_questions",
    "schema": {
        "type": "object",
        "properties": {
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
        "required": ["questions"],
    },
}


# ── 5. 回答评估: 判正确 + 假懂检测 ──

EVALUATE_ANSWER_SYSTEM = """你是评估专家。判断学习者的回答是否正确，
并检测是否存在「假懂」信号（表面记忆、机械套用、混淆概念等）。"""

EVALUATE_ANSWER_USER = """概念：{concept}
题目：{question}
正确答案：{correct_answer}
学习者回答：{learner_answer}

请评估：
1. 是否正确（true/false）
2. 理解水平（1-5）
3. 假懂信号（如果有）
4. 反馈（针对性的纠正或鼓励）

以 JSON 格式输出。"""

EVALUATE_ANSWER_SCHEMA = {
    "name": "evaluate_answer",
    "schema": {
        "type": "object",
        "properties": {
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
        "required": ["correct", "level", "feedback"],
    },
}


# ── 提示词注册表 ──

PROMPT_REGISTRY = {
    "assess_knowledge_graph": {
        "system": ASSESS_KNOWLEDGE_GRAPH_SYSTEM,
        "user_template": ASSESS_KNOWLEDGE_GRAPH_USER,
        "schema": ASSESS_KNOWLEDGE_GRAPH_SCHEMA,
    },
    "diagnosis": {
        "system": DIAGNOSIS_SYSTEM,
        "user_template": DIAGNOSIS_USER,
        "schema": DIAGNOSIS_SCHEMA,
    },
    "concept_content": {
        "system": CONCEPT_CONTENT_SYSTEM,
        "user_template": CONCEPT_CONTENT_USER,
        "schema": CONCEPT_CONTENT_SCHEMA,
    },
    "test_questions": {
        "system": TEST_QUESTIONS_SYSTEM,
        "user_template": TEST_QUESTIONS_USER,
        "schema": TEST_QUESTIONS_SCHEMA,
    },
    "evaluate_answer": {
        "system": EVALUATE_ANSWER_SYSTEM,
        "user_template": EVALUATE_ANSWER_USER,
        "schema": EVALUATE_ANSWER_SCHEMA,
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
