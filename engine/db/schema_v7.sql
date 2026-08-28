-- Astromind Praxis v0.2.2 Unified Schema (v7)
-- v6 -> v7: 17 表收敛为 9（8 基表 + FTS），删除全部无生产写入路径的表
-- 删除: learning_journal / assessment_log / weakness_patterns / knowledge_graph_edges /
--       quality_audit_log / knowledge_sources / knowledge_coverage / teaching_interactions
-- 变更: knowledge_nodes 删 9 个 NUSAP 质量字段; tracks 删 workflow_context JSON 列;
--       interaction_log 增 interaction_type（吸收 teaching_interactions 类型标签）;
--       misconceptions 删 interaction_id（FK 目标表删除）

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

-- tracks（v7: 删 workflow_context JSON 列，会话状态由 workflow_context 表承载）
CREATE TABLE IF NOT EXISTS tracks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name            TEXT    NOT NULL,
    target_type     TEXT    NOT NULL CHECK (target_type IN ('exam', 'applied', 'interest')),
    status          TEXT    NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'completed', 'archived')),
    priority        INTEGER NOT NULL DEFAULT 3 CHECK (priority BETWEEN 1 AND 5),
    current_state   TEXT    NOT NULL DEFAULT 'init' CHECK (current_state IN ('init', 'diagnosis', 'teaching', 'assessment', 'practice', 'completed')),
    created_at      TEXT    NOT NULL DEFAULT (date('now')),
    updated_at      TEXT    NOT NULL DEFAULT (date('now'))
);

CREATE INDEX IF NOT EXISTS idx_tracks_user_status ON tracks(user_id, status);
CREATE INDEX IF NOT EXISTS idx_tracks_user_priority ON tracks(user_id, priority);

-- knowledge_nodes（v7: 删 node_type/NUSAP 质量字段，保留内容与来源元数据）
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
    created_at      TEXT    NOT NULL DEFAULT (date('now')),
    updated_at      TEXT    NOT NULL DEFAULT (date('now'))
);

CREATE INDEX IF NOT EXISTS idx_nodes_track_status ON knowledge_nodes(track_id, status);
CREATE INDEX IF NOT EXISTS idx_nodes_next_review ON knowledge_nodes(next_review);
CREATE INDEX IF NOT EXISTS idx_nodes_type ON knowledge_nodes(status);

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

-- node_dependencies（知识图谱边的实际存储）
CREATE TABLE IF NOT EXISTS node_dependencies (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id       INTEGER NOT NULL REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
    depends_on_id INTEGER NOT NULL REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
    relation_type TEXT    NOT NULL DEFAULT 'prerequisite' CHECK (relation_type IN (
                        'prerequisite',     -- 前置知识
                        'related',          -- 相关概念
                        'part_of'           -- 组成关系
                    )),
    UNIQUE(node_id, depends_on_id)
);

CREATE INDEX IF NOT EXISTS idx_deps_node ON node_dependencies(node_id);
CREATE INDEX IF NOT EXISTS idx_deps_depends ON node_dependencies(depends_on_id);

-- misconceptions（v7: 删 interaction_id）
CREATE TABLE IF NOT EXISTS misconceptions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL,
    node_id         INTEGER NOT NULL,
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

-- workflow_context（会话状态机）
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

-- interaction_log（v7: 增 interaction_type，吸收 teaching_interactions 类型标签）
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
    interaction_type    TEXT    NOT NULL DEFAULT 'deep_teaching' CHECK (interaction_type IN (
                        'prerequisite_check',   -- 前置知识检测
                        'deep_teaching',        -- 深度教学
                        'instant_test',         -- 即时检验
                        'structural_test',      -- 结构检验
                        'feynman_explain',      -- 费曼讲解
                        'review_session'        -- 复习会话
                    )),
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
