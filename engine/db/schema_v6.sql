-- Astromind Praxis v0.1.2 Unified Schema (v6)
-- ?? meta-learning ?? 14 ?? + astromind ? workflow_context + interaction_log + FTS5

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- users
CREATE TABLE IF NOT EXISTS users (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    NOT NULL UNIQUE,
    display_name TEXT    NOT NULL DEFAULT '',
    config       TEXT    NOT NULL DEFAULT '{}' CHECK (json_valid(config)),
    created_at   TEXT    NOT NULL DEFAULT (date('now')),
    updated_at   TEXT    NOT NULL DEFAULT (date('now'))
);


-- tracks
CREATE TABLE IF NOT EXISTS tracks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name            TEXT    NOT NULL,
    target_type     TEXT    NOT NULL CHECK (target_type IN ('exam', 'applied', 'interest')),
    status          TEXT    NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'completed', 'archived')),
    priority        INTEGER NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
    current_state   TEXT    NOT NULL DEFAULT 'init' CHECK (current_state IN ('init', 'diagnosis', 'teaching', 'assessment', 'practice', 'completed')),
    workflow_context TEXT   NOT NULL DEFAULT '{}' CHECK (json_valid(workflow_context)),
    created_at      TEXT    NOT NULL DEFAULT (date('now')),
    updated_at      TEXT    NOT NULL DEFAULT (date('now'))
);

CREATE INDEX IF NOT EXISTS idx_tracks_user_status ON tracks(user_id, status);

CREATE INDEX IF NOT EXISTS idx_tracks_user_priority ON tracks(user_id, priority);


-- knowledge_nodes
CREATE TABLE IF NOT EXISTS knowledge_nodes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id      INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    parent_id     INTEGER REFERENCES knowledge_nodes(id) ON DELETE SET NULL,
    name          TEXT    NOT NULL,
    description   TEXT    NOT NULL DEFAULT '',
    importance    INTEGER NOT NULL DEFAULT 3 CHECK (importance BETWEEN 1 AND 5),
    current_level INTEGER NOT NULL DEFAULT 1 CHECK (current_level BETWEEN 1 AND 5),
    status        TEXT    NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'pending', 'mastered', 'archived')),
    ef            REAL    NOT NULL DEFAULT 2.5 CHECK (ef >= 1.3),
    interval      INTEGER NOT NULL DEFAULT 0 CHECK (interval >= 0),
    repetitions   INTEGER NOT NULL DEFAULT 0 CHECK (repetitions >= 0),
    next_review   TEXT,
    -- 知识内容
    content         TEXT    NOT NULL DEFAULT '',
    content_format  TEXT    NOT NULL DEFAULT 'markdown',
    source_url      TEXT    NOT NULL DEFAULT '',
    source_title    TEXT    NOT NULL DEFAULT '',
    tags            TEXT    NOT NULL DEFAULT '[]',
    cached_at       TEXT,
    -- ========== 知识质量评估字段 (v3) ==========
    -- 节点类型（模式层分类）
    node_type       TEXT    NOT NULL DEFAULT 'concept' CHECK (node_type IN (
                        'concept',      -- 概念/定义
                        'fact',         -- 事实性知识
                        'principle',    -- 原理/定律
                        'procedure',    -- 流程/方法
                        'framework',    -- 框架/模型
                        'case',         -- 案例/实例
                        'data_point',   -- 数据点/统计
                        'reference'     -- 引用/文献
                    )),
    -- 综合质量评分（0-100，由引擎自动计算）
    quality_score   INTEGER DEFAULT 0 CHECK (quality_score BETWEEN 0 AND 100),
    -- NUSAP Pedigree Matrix 三维度评分（0-4）
    theory_level    INTEGER DEFAULT 0 CHECK (theory_level BETWEEN 0 AND 4),  -- 理论支撑等级
    data_level      INTEGER DEFAULT 0 CHECK (data_level BETWEEN 0 AND 4),    -- 数据来源等级
    method_level    INTEGER DEFAULT 0 CHECK (method_level BETWEEN 0 AND 4),  -- 方法验证等级
    -- 来源可信度（0-4，数据层质量）
    source_reliability INTEGER DEFAULT 0 CHECK (source_reliability BETWEEN 0 AND 4),
    -- 时效性
    freshness_date  TEXT,   -- 知识时效截止日期（超过此日期需重新验证）
    -- 完整性标记
    completeness    INTEGER DEFAULT 0 CHECK (completeness BETWEEN 0 AND 4),  -- 完整性评分
    consistency     INTEGER DEFAULT 0 CHECK (consistency BETWEEN 0 AND 4),   -- 一致性评分
    created_at      TEXT    NOT NULL DEFAULT (date('now')),
    updated_at      TEXT    NOT NULL DEFAULT (date('now'))
);

CREATE INDEX IF NOT EXISTS idx_nodes_track_status ON knowledge_nodes(track_id, status);

CREATE INDEX IF NOT EXISTS idx_nodes_next_review ON knowledge_nodes(next_review);

CREATE INDEX IF NOT EXISTS idx_nodes_quality ON knowledge_nodes(quality_score);

CREATE INDEX IF NOT EXISTS idx_nodes_type ON knowledge_nodes(node_type);


-- review_history
CREATE TABLE IF NOT EXISTS review_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id         INTEGER NOT NULL REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
    quality         INTEGER NOT NULL CHECK (quality BETWEEN 0 AND 5),
    ef_after        REAL    NOT NULL CHECK (ef_after >= 1.3),
    interval_after  INTEGER NOT NULL CHECK (interval_after >= 0),
    reviewed_at     TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_reviews_node ON review_history(node_id);

CREATE INDEX IF NOT EXISTS idx_reviews_date ON review_history(reviewed_at);


-- assessment_log
CREATE TABLE IF NOT EXISTS assessment_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    track_id        INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    node_id         INTEGER REFERENCES knowledge_nodes(id) ON DELETE SET NULL,
    level_before    INTEGER NOT NULL CHECK (level_before BETWEEN 1 AND 5),
    level_after     INTEGER NOT NULL CHECK (level_after BETWEEN 1 AND 5),
    methods         TEXT    NOT NULL DEFAULT '[]' CHECK (json_valid(methods)),
    duration_minutes INTEGER DEFAULT 0,
    fake_signals    TEXT    NOT NULL DEFAULT '{}' CHECK (json_valid(fake_signals)),
    -- 知识质量评估结果 (v3)
    quality_before  INTEGER DEFAULT 0 CHECK (quality_before BETWEEN 0 AND 100),
    quality_after   INTEGER DEFAULT 0 CHECK (quality_after BETWEEN 0 AND 100),
    quality_notes   TEXT    NOT NULL DEFAULT '',
    notes           TEXT    NOT NULL DEFAULT '',
    created_at      TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_assessment_user_track ON assessment_log(user_id, track_id);

CREATE INDEX IF NOT EXISTS idx_assessment_date ON assessment_log(created_at);


-- learning_journal
CREATE TABLE IF NOT EXISTS learning_journal (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date            TEXT    NOT NULL,
    focus_minutes   INTEGER NOT NULL DEFAULT 0 CHECK (focus_minutes >= 0),
    diffuse_minutes INTEGER NOT NULL DEFAULT 0 CHECK (diffuse_minutes >= 0),
    topics          TEXT    NOT NULL DEFAULT '[]' CHECK (json_valid(topics)),
    methods         TEXT    NOT NULL DEFAULT '[]' CHECK (json_valid(methods)),
    track_minutes   TEXT    NOT NULL DEFAULT '{}' CHECK (json_valid(track_minutes)),
    highlights      TEXT    NOT NULL DEFAULT '',
    struggles       TEXT    NOT NULL DEFAULT '',
    tomorrow_plan   TEXT    NOT NULL DEFAULT '',
    UNIQUE(user_id, date)
);


-- node_dependencies
CREATE TABLE IF NOT EXISTS node_dependencies (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id       INTEGER NOT NULL REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
    depends_on_id INTEGER NOT NULL REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
    relation_type TEXT    NOT NULL DEFAULT 'prerequisite' CHECK (relation_type IN (
                        'prerequisite',     -- 前置知识
                        'related',          -- 相关概念
                        'reference',        -- 引用/参考
                        'is_a',             -- 父子关系（is-a）
                        'part_of',          -- 组成关系（part-of）
                        'contradicts',      -- 矛盾/冲突
                        'supports',         -- 支持/佐证
                        'applies_to'        -- 应用于
                    )),
    UNIQUE(node_id, depends_on_id)
);

CREATE INDEX IF NOT EXISTS idx_deps_node ON node_dependencies(node_id);

CREATE INDEX IF NOT EXISTS idx_deps_depends ON node_dependencies(depends_on_id);


-- quality_audit_log
CREATE TABLE IF NOT EXISTS quality_audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id         INTEGER NOT NULL REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
    audit_type      TEXT    NOT NULL CHECK (audit_type IN (
                        'initial',          -- 初始评估
                        'review_update',    -- 复习时更新
                        'source_verified',  -- 来源验证
                        'freshness_check',  -- 时效性检查
                        'cross_validation', -- 交叉验证
                        'expert_review'     -- 专家评审
                    )),
    -- NUSAP 评分
    theory_level    INTEGER NOT NULL CHECK (theory_level BETWEEN 0 AND 4),
    data_level      INTEGER NOT NULL CHECK (data_level BETWEEN 0 AND 4),
    method_level    INTEGER NOT NULL CHECK (method_level BETWEEN 0 AND 4),
    source_reliability INTEGER NOT NULL CHECK (source_reliability BETWEEN 0 AND 4),
    completeness    INTEGER NOT NULL CHECK (completeness BETWEEN 0 AND 4),
    consistency     INTEGER NOT NULL CHECK (consistency BETWEEN 0 AND 4),
    -- 综合质量分
    quality_score   INTEGER NOT NULL CHECK (quality_score BETWEEN 0 AND 100),
    -- 审计详情
    findings        TEXT    NOT NULL DEFAULT '[]' CHECK (json_valid(findings)),  -- 发现的问题列表
    recommendations TEXT    NOT NULL DEFAULT '[]' CHECK (json_valid(recommendations)),  -- 改进建议
    notes           TEXT    NOT NULL DEFAULT '',
    audited_by      TEXT    NOT NULL DEFAULT 'system',  -- 审计者（system/user/expert）
    created_at      TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_quality_audit_node ON quality_audit_log(node_id);

CREATE INDEX IF NOT EXISTS idx_quality_audit_type ON quality_audit_log(audit_type);

CREATE INDEX IF NOT EXISTS idx_quality_audit_date ON quality_audit_log(created_at);


-- knowledge_sources
CREATE TABLE IF NOT EXISTS knowledge_sources (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id         INTEGER NOT NULL REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
    source_type     TEXT    NOT NULL CHECK (source_type IN (
                        'academic_paper',   -- 学术论文
                        'textbook',         -- 教科书
                        'official_doc',     -- 官方文档
                        'industry_report',  -- 行业报告
                        'news_media',       -- 新闻媒体
                        'blog_forum',       -- 博客/论坛
                        'expert_opinion',   -- 专家意见
                        'personal_exp',     -- 个人经验
                        'other'             -- 其他
                    )),
    title           TEXT    NOT NULL DEFAULT '',
    url             TEXT    NOT NULL DEFAULT '',
    author          TEXT    NOT NULL DEFAULT '',
    publisher       TEXT    NOT NULL DEFAULT '',
    publish_date    TEXT,   -- 发布日期
    access_date     TEXT    NOT NULL DEFAULT (date('now')),  -- 访问日期
    reliability     INTEGER NOT NULL DEFAULT 2 CHECK (reliability BETWEEN 0 AND 4),
    citation_count  INTEGER DEFAULT 0,  -- 被引用次数
    notes           TEXT    NOT NULL DEFAULT '',
    UNIQUE(node_id, url)
);

CREATE INDEX IF NOT EXISTS idx_sources_node ON knowledge_sources(node_id);

CREATE INDEX IF NOT EXISTS idx_sources_type ON knowledge_sources(source_type);


-- knowledge_coverage
CREATE TABLE IF NOT EXISTS knowledge_coverage (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id        INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    domain          TEXT    NOT NULL,  -- 领域名称
    expected_nodes  INTEGER DEFAULT 0,  -- 该领域预期节点数
    actual_nodes    INTEGER DEFAULT 0,  -- 实际节点数
    coverage_pct    REAL    DEFAULT 0.0 CHECK (coverage_pct BETWEEN 0 AND 100),  -- 覆盖百分比
    depth_avg       REAL    DEFAULT 0.0 CHECK (depth_avg BETWEEN 1 AND 5),  -- 平均深度
    last_assessed   TEXT,   -- 最近评估日期
    notes           TEXT    NOT NULL DEFAULT '',
    UNIQUE(track_id, domain)
);

CREATE INDEX IF NOT EXISTS idx_coverage_track ON knowledge_coverage(track_id);


-- teaching_interactions
CREATE TABLE IF NOT EXISTS teaching_interactions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT    NOT NULL,
    user_id         INTEGER NOT NULL,
    track_id        INTEGER NOT NULL,
    node_id         INTEGER NOT NULL,
    interaction_type TEXT   NOT NULL CHECK (interaction_type IN (
                        'prerequisite_check',   -- 前置知识检测
                        'deep_teaching',        -- 深度教学
                        'instant_test',         -- 即时检验
                        'structural_test',      -- 结构检验
                        'feynman_explain',      -- 费曼讲解
                        'review_session'        -- 复习会话
                    )),
    method_used     TEXT,   -- 使用的方法：feynman / elaborative-interrogation / structural-test / dual-coding 等
    level_before   INTEGER DEFAULT 1 CHECK (level_before BETWEEN 1 AND 5),
    level_after    INTEGER DEFAULT 1 CHECK (level_after BETWEEN 1 AND 5),
    quality_score  INTEGER DEFAULT 0 CHECK (quality_score BETWEEN 0 AND 5),
    duration_seconds INTEGER DEFAULT 0,
    file_path      TEXT    NOT NULL DEFAULT '',
    created_at     TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_ti_user_node ON teaching_interactions(user_id, node_id);

CREATE INDEX IF NOT EXISTS idx_ti_session ON teaching_interactions(session_id);

CREATE INDEX IF NOT EXISTS idx_ti_type ON teaching_interactions(interaction_type);


-- misconceptions
CREATE TABLE IF NOT EXISTS misconceptions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL,
    node_id         INTEGER NOT NULL,
    interaction_id  INTEGER REFERENCES teaching_interactions(id) ON DELETE SET NULL,
    misconception   TEXT    NOT NULL,
    correction      TEXT    NOT NULL DEFAULT '',
    category        TEXT    CHECK (category IN (
                        'overgeneralization',   -- 过度泛化
                        'term_confusion',       -- 术语混淆
                        'surface_analogy',      -- 表面类比
                        'missing_boundary',     -- 边界缺失
                        'order_reversal',       -- 顺序颠倒
                        'other'                 -- 其他
                    )),
    is_resolved     INTEGER NOT NULL DEFAULT 0,
    encounter_count INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    resolved_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_mc_user_node ON misconceptions(user_id, node_id);

CREATE INDEX IF NOT EXISTS idx_mc_resolved ON misconceptions(user_id, is_resolved);


-- weakness_patterns
CREATE TABLE IF NOT EXISTS weakness_patterns (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL,
    pattern_type    TEXT    NOT NULL CHECK (pattern_type IN (
                        'overgeneralization',
                        'term_confusion',
                        'boundary_blur',
                        'method_confusion',
                        'overconfidence'
                    )),
    description     TEXT    NOT NULL,
    related_node_ids TEXT   NOT NULL DEFAULT '[]',
    frequency       INTEGER NOT NULL DEFAULT 1,
    severity        INTEGER NOT NULL DEFAULT 1 CHECK (severity BETWEEN 1 AND 5),
    last_observed_at TEXT   NOT NULL DEFAULT (datetime('now', 'localtime')),
    created_at      TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_wp_user ON weakness_patterns(user_id);


-- knowledge_graph_edges
CREATE TABLE IF NOT EXISTS knowledge_graph_edges (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL,
    source_node_id  INTEGER NOT NULL,
    target_node_id  INTEGER NOT NULL,
    relation_type   TEXT    NOT NULL CHECK (relation_type IN (
                        'drives',           -- 驱动
                        'conflicts_with',   -- 冲突
                        'resolves',         -- 解决
                        'extends',          -- 扩展
                        'is_prerequisite',  -- 前置
                        'is_example_of'     -- 示例
                    )),
    description     TEXT    NOT NULL DEFAULT '',
    confidence      INTEGER NOT NULL DEFAULT 1 CHECK (confidence BETWEEN 1 AND 3),
    created_at      TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE(user_id, source_node_id, target_node_id, relation_type)
);

CREATE INDEX IF NOT EXISTS idx_kge_user ON knowledge_graph_edges(user_id);

CREATE INDEX IF NOT EXISTS idx_kge_source ON knowledge_graph_edges(source_node_id);

CREATE INDEX IF NOT EXISTS idx_kge_target ON knowledge_graph_edges(target_node_id);


-- workflow_context
CREATE TABLE IF NOT EXISTS workflow_context (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    track_id        INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    topic           TEXT    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'diagnosed'
        CHECK (status IN ('diagnosed','teaching','teaching_complete',
                          'assessing','completed','abandoned')),
    level           INTEGER DEFAULT 1 CHECK (level BETWEEN 1 AND 5),
    diagnosis       TEXT    NOT NULL DEFAULT '{}',
    current_node    INTEGER REFERENCES knowledge_nodes(id) ON DELETE SET NULL,
    completed_nodes TEXT    NOT NULL DEFAULT '[]',
    state_data      TEXT    NOT NULL DEFAULT '{}',
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wfc_user ON workflow_context(user_id);
CREATE INDEX IF NOT EXISTS idx_wfc_track ON workflow_context(track_id);
CREATE INDEX IF NOT EXISTS idx_wfc_status ON workflow_context(status);

-- interaction_log
CREATE TABLE IF NOT EXISTS interaction_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    track_id            INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    node_id             INTEGER NOT NULL REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
    question            TEXT    NOT NULL,
    answer              TEXT    NOT NULL DEFAULT '',
    is_correct          INTEGER NOT NULL DEFAULT 0,
    understanding_level INTEGER DEFAULT 1 CHECK (understanding_level BETWEEN 1 AND 5),
    fake_signals        TEXT    NOT NULL DEFAULT '[]',
    quality             INTEGER DEFAULT 0 CHECK (quality BETWEEN 0 AND 5),
    created_at          TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_il_user_track ON interaction_log(user_id, track_id);
CREATE INDEX IF NOT EXISTS idx_il_node ON interaction_log(node_id);

-- knowledge_fts (FTS5)
CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
    name, content, tags, source_title,
    content='knowledge_nodes',
    content_rowid='id',
    tokenize='unicode61'
);
CREATE TRIGGER IF NOT EXISTS knowledge_fts_insert AFTER INSERT ON knowledge_nodes BEGIN
    INSERT INTO knowledge_fts(rowid, name, content, tags, source_title)
    VALUES (new.id, new.name, new.content, new.tags, new.source_title);
END;
CREATE TRIGGER IF NOT EXISTS knowledge_fts_delete AFTER DELETE ON knowledge_nodes BEGIN
    INSERT INTO knowledge_fts(knowledge_fts, rowid, name, content, tags, source_title)
    VALUES ('delete', old.id, old.name, old.content, old.tags, old.source_title);
END;
CREATE TRIGGER IF NOT EXISTS knowledge_fts_update AFTER UPDATE ON knowledge_nodes BEGIN
    INSERT INTO knowledge_fts(knowledge_fts, rowid, name, content, tags, source_title)
    VALUES ('delete', old.id, old.name, old.content, old.tags, old.source_title);
    INSERT INTO knowledge_fts(rowid, name, content, tags, source_title)
    VALUES (new.id, new.name, new.content, new.tags, new.source_title);
END;
