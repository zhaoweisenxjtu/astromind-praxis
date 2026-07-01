-- Astromind Praxis v0.1 Schema Extension (v5)
-- 星知·笃行 — 独立 DB 完整 schema（不与 meta-learn 共用）

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ============================================================
-- 15. Workflow Context (教学会话状态) [v5 新增]
--      断点续传：每个教学会话的完整上下文
-- ============================================================
CREATE TABLE IF NOT EXISTS workflow_context (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT    NOT NULL,
    track_id        INTEGER NOT NULL,
    topic           TEXT    NOT NULL,
    status          TEXT    NOT NULL DEFAULT 'diagnosed' CHECK (status IN (
                        'diagnosed',            -- 已诊断
                        'teaching',             -- 教学中
                        'teaching_complete',    -- 教学完成
                        'assessing',            -- 评估中
                        'completed',            -- 已完成
                        'abandoned'             -- 已放弃
                    )),
    level           INTEGER DEFAULT 1 CHECK (level BETWEEN 1 AND 5),
    diagnosis       TEXT    NOT NULL DEFAULT '{}',  -- JSON: 诊断结果
    current_node    INTEGER,                        -- 当前教学节点 ID
    completed_nodes TEXT    NOT NULL DEFAULT '[]',   -- JSON: 已完成节点 ID 列表
    state_data      TEXT    NOT NULL DEFAULT '{}',   -- JSON: 扩展状态数据
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wfc_user ON workflow_context(user_id);
CREATE INDEX IF NOT EXISTS idx_wfc_track ON workflow_context(track_id);
CREATE INDEX IF NOT EXISTS idx_wfc_status ON workflow_context(status);

-- ============================================================
-- 16. Interaction Log (互动记录) [v5 新增]
--      与 teaching_interactions 互补，专注问答评估
-- ============================================================
CREATE TABLE IF NOT EXISTS interaction_log (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           TEXT    NOT NULL,
    track_id          INTEGER NOT NULL,
    node_id           INTEGER NOT NULL,
    question          TEXT    NOT NULL,
    answer            TEXT    NOT NULL DEFAULT '',
    is_correct        INTEGER NOT NULL DEFAULT 0,
    understanding_level INTEGER DEFAULT 1 CHECK (understanding_level BETWEEN 1 AND 5),
    fake_signals      TEXT    NOT NULL DEFAULT '[]',
    quality           INTEGER DEFAULT 0 CHECK (quality BETWEEN 0 AND 5),
    created_at        TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_il_user_track ON interaction_log(user_id, track_id);
CREATE INDEX IF NOT EXISTS idx_il_node ON interaction_log(node_id);

-- ============================================================
-- 17. Knowledge Edges (知识边) [v5 新增]
--      与 node_dependencies / knowledge_graph_edges 互补
-- ============================================================
CREATE TABLE IF NOT EXISTS knowledge_edges (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id        INTEGER NOT NULL,
    source_node_id  INTEGER NOT NULL,
    target_node_id  INTEGER NOT NULL,
    relation_type   TEXT    NOT NULL DEFAULT 'related' CHECK (relation_type IN (
                        'prerequisite',
                        'related',
                        'part_of',
                        'extends',
                        'example_of'
                    )),
    created_at      TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE(track_id, source_node_id, target_node_id)
);
CREATE INDEX IF NOT EXISTS KE_source ON knowledge_edges(source_node_id);
CREATE INDEX IF NOT EXISTS KE_target ON knowledge_edges(target_node_id);
