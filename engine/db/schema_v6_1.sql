-- Astromind Praxis v6.1 Schema Extension
-- 新增 author-knowledge 系统使用的 4 表 + 1 FTS5
-- 前置条件: schema_v6.sql 已执行
-- 特点: 只追加，不修改已有表

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ================================================================
-- L0: 原始文章全文
-- ================================================================
CREATE TABLE IF NOT EXISTS articles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    author_name     TEXT    NOT NULL,
    title           TEXT    NOT NULL,
    url             TEXT    NOT NULL,
    url_hash        TEXT    NOT NULL UNIQUE,
    published_at    TEXT,
    ingested_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    content_text    TEXT    NOT NULL,
    word_count      INTEGER DEFAULT 0,
    source_type     TEXT    DEFAULT 'wechat'  -- wechat | zhihu | manual
);

CREATE INDEX IF NOT EXISTS idx_articles_author ON articles(author_name);
CREATE INDEX IF NOT EXISTS idx_articles_pubdate ON articles(published_at);

-- ================================================================
-- L1: 原子知识点 (6 类型 Schema)
-- ================================================================
CREATE TABLE IF NOT EXISTS knowledge_atoms (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id      INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    author_name     TEXT    NOT NULL,
    type            TEXT    NOT NULL CHECK (type IN ('fact','method','value','assumption','counter','style')),
    content         TEXT    NOT NULL,
    topic           TEXT    NOT NULL,
    evidence        TEXT,            -- 原文引用片段
    embedding_ref   TEXT,            -- vec_index 向量 ID
    merged_to       INTEGER,         -- FK → mental_models.id (归并后回填)
    -- 时间追踪
    valid_from      TEXT,            -- 观点开始生效时间 (LLM 从文本推断)
    valid_until     TEXT,            -- 被修正/推翻时间 (新文章归并时覆盖)
    last_confirmed_at TEXT,          -- 最近被新文章确认的时间
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    published_at    TEXT             -- t_obs: 文章发布日期
);

CREATE INDEX IF NOT EXISTS idx_atoms_author ON knowledge_atoms(author_name);
CREATE INDEX IF NOT EXISTS idx_atoms_type ON knowledge_atoms(type);
CREATE INDEX IF NOT EXISTS idx_atoms_topic ON knowledge_atoms(topic);
CREATE INDEX IF NOT EXISTS idx_atoms_merged ON knowledge_atoms(merged_to);
CREATE INDEX IF NOT EXISTS idx_atoms_article ON knowledge_atoms(article_id);

-- FTS5 全文搜索 (knowledge_atoms)
CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_atoms_fts USING fts5(
    content, topic, author_name,
    content='knowledge_atoms', content_rowid='id',
    tokenize='unicode61'
);

CREATE TRIGGER IF NOT EXISTS atoms_fts_insert AFTER INSERT ON knowledge_atoms BEGIN
    INSERT INTO knowledge_atoms_fts(rowid, content, topic, author_name)
    VALUES (new.id, new.content, new.topic, new.author_name);
END;

CREATE TRIGGER IF NOT EXISTS atoms_fts_delete AFTER DELETE ON knowledge_atoms BEGIN
    INSERT INTO knowledge_atoms_fts(knowledge_atoms_fts, rowid, content, topic, author_name)
    VALUES ('delete', old.id, old.content, old.topic, old.author_name);
END;

CREATE TRIGGER IF NOT EXISTS atoms_fts_update AFTER UPDATE ON knowledge_atoms BEGIN
    INSERT INTO knowledge_atoms_fts(knowledge_atoms_fts, rowid, content, topic, author_name)
    VALUES ('delete', old.id, old.content, old.topic, old.author_name);
    INSERT INTO knowledge_atoms_fts(rowid, content, topic, author_name)
    VALUES (new.id, new.content, new.topic, new.author_name);
END;

-- ================================================================
-- L2: 心智模型
-- ================================================================
CREATE TABLE IF NOT EXISTS mental_models (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    author_name     TEXT    NOT NULL,
    topic           TEXT    NOT NULL,       -- 归并后的统一 topic
    title           TEXT    NOT NULL,       -- 心智模型标题
    content_md      TEXT    NOT NULL,       -- Markdown 全文
    md_path         TEXT    NOT NULL,       -- authors/<名>/models/<topic>.md
    evidence_count  INTEGER DEFAULT 0,      -- 支撑原子知识点数
    article_count   INTEGER DEFAULT 0,      -- 跨文章数
    first_seen_at   TEXT,                   -- 首次出现日期
    last_updated_at TEXT,                   -- 最近更新日期
    triple_check    TEXT    NOT NULL DEFAULT '{}',  -- 三重验证结果 JSON
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_models_author ON mental_models(author_name);
CREATE INDEX IF NOT EXISTS idx_models_topic ON mental_models(topic);

-- ================================================================
-- 作者索引
-- ================================================================
CREATE TABLE IF NOT EXISTS author_profiles (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    author_name         TEXT    NOT NULL UNIQUE,
    knowledge_base_path TEXT    NOT NULL,    -- authors/<名>/ 目录
    article_count       INTEGER DEFAULT 0,  -- 已摄入文章数
    atom_count          INTEGER DEFAULT 0,  -- L1 原子知识点数
    l2_model_count      INTEGER DEFAULT 0,  -- L2 心智模型数
    l3_available        INTEGER DEFAULT 0,  -- 0/1 persona.md 是否已生成
    l4_available        INTEGER DEFAULT 0,  -- 0/1 writing-mirror.md 是否已生成
    persona_md          TEXT    DEFAULT '', -- L3 persona content (for astromind cross-read)
    mirror_md           TEXT    DEFAULT '', -- L4 mirror content (for astromind cross-read)
    last_article_at     TEXT,               -- 最近一篇文章的发布日期
    last_distilled_at   TEXT,               -- 最近一次蒸馏时间
    created_at          TEXT    NOT NULL DEFAULT (datetime('now'))
);
