"""RunStore: two-phase checkpoint 持久化内核 (v0.2.1).

协议（设计文档 §3.1/§5.1.1）:
  CLI 命令一次执行 = 一个 Run (runs/run-<ts>-<rand>/)
  需要 LLM/搜索参与 → 写 req-NNN.json → 抛 NeedsLLM/NeedsSearch → CLI exit 75/76
  agent 补答 → Write rsp-NNN.json → resume → 消费缓存继续执行
  中间产物（如搜索结果）→ cache_get/cache_set 保证重放幂等

目录结构:
  ~/.astromind-praxis/runs/
    run-20260827-141523-a1b2/
      meta.json            Run 状态机
      req-001.json         LLM/搜索请求（agent 读取）
      rsp-001.json         agent 补答（agent 写入）
      cache.json           中间产物缓存（搜索等）
    pending.json           所有 pending run 索引（原子更新）
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import string
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# ── 异常契约 ──

EXIT_NEEDS_LLM = 75
EXIT_NEEDS_SEARCH = 76
EXIT_NEEDS_ANSWERS = 77


class NeedsLLM(Exception):
    """Checkpoint 请求 LLM 补答。CLI 层捕获后 sys.exit(75)。"""

    exit_code = EXIT_NEEDS_LLM

    def __init__(self, run_id: str, step: str, req_file: Path):
        self.run_id = run_id
        self.step = step
        self.req_file = req_file
        super().__init__(
            f"NEEDS_LLM: run={run_id} step={step} req={req_file}"
        )


class NeedsSearch(Exception):
    """Checkpoint 请求搜索补答。CLI 层捕获后 sys.exit(76)。"""

    exit_code = EXIT_NEEDS_SEARCH

    def __init__(self, run_id: str, step: str, req_file: Path):
        self.run_id = run_id
        self.step = step
        self.req_file = req_file
        super().__init__(
            f"NEEDS_SEARCH: run={run_id} step={step} req={req_file}"
        )


# ── 常量 ──

RUN_STATUSES = {
    "running",        # 执行中（或等待 agent 补答后 resume）
    "pending_llm",    # 已落 checkpoint，等 LLM 补答
    "pending_search", # 已落 checkpoint，等搜索补答
    "pending_answers",# 题目已出，等用户答题（阶段 4 启用）
    "done",
    "failed",
}

STEP_STATUSES = {"pending", "answered", "consumed", "done"}

DEFAULT_BASE_DIR = Path.home() / ".astromind-praxis" / "runs"
PENDING_INDEX = "pending.json"
CACHE_FILE = "cache.json"
DEFAULT_PRUNE_DAYS = 14

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utc_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


def _gen_run_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"run-{ts}-{rand}"


def prompt_key(system_prompt: str, user_prompt: str, schema: dict | None = None) -> str:
    """LLM 调用指纹：同一 run 内同样 prompt 稳定命中（幂等重放核心）。"""
    raw = json.dumps(
        {"s": system_prompt, "u": user_prompt, "sc": schema},
        ensure_ascii=False, sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


# ── 数据对象 ──

@dataclass
class Step:
    seq: int
    kind: str                    # llm | search
    key: str                     # prompt_key 或 query hash
    status: str = "pending"      # pending | answered | consumed | done
    req: str = ""                # req-NNN.json 文件名
    rsp: str = ""                # rsp-NNN.json 文件名

    def to_dict(self) -> dict:
        return {
            "seq": self.seq,
            "kind": self.kind,
            "key": self.key,
            "status": self.status,
            "req": self.req,
            "rsp": self.rsp,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Step":
        return cls(
            seq=int(d.get("seq", 0)),
            kind=str(d.get("kind", "llm")),
            key=str(d.get("key", "")),
            status=str(d.get("status", "pending")),
            req=str(d.get("req", "")),
            rsp=str(d.get("rsp", "")),
        )


@dataclass
class Run:
    id: str
    kind: str                    # teach_diagnose | teach_session | ...
    argv: dict                   # 原命令参数，resume 重放用
    track_id: int | None = None
    session_id: int | None = None
    status: str = "running"
    steps: list[Step] = field(default_factory=list)
    error: str = ""
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def step_by_key(self, key: str) -> Step | None:
        for s in self.steps:
            if s.key == key:
                return s
        return None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "argv": self.argv,
            "track_id": self.track_id,
            "session_id": self.session_id,
            "status": self.status,
            "steps": [s.to_dict() for s in self.steps],
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Run":
        return cls(
            id=str(d.get("id", "")),
            kind=str(d.get("kind", "")),
            argv=dict(d.get("argv", {}) or {}),
            track_id=d.get("track_id"),
            session_id=d.get("session_id"),
            status=str(d.get("status", "running")),
            steps=[Step.from_dict(s) for s in d.get("steps", [])],
            error=str(d.get("error", "")),
            created_at=str(d.get("created_at", "")),
            updated_at=str(d.get("updated_at", "")),
        )


# ── 原子写辅助 ──

def _atomic_write(path: Path, data: dict | list):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _read_json(path: Path) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


# ── RunStore ──

class RunStore:
    """run 生命周期 + checkpoint 读写 + pending 索引 + 中间产物缓存。"""

    def __init__(self, base_dir: str | Path | None = None):
        self.base_dir = Path(base_dir) if base_dir else DEFAULT_BASE_DIR
        self.base_dir.mkdir(parents=True, exist_ok=True)

    # ── 路径 ──

    def _run_dir(self, run_id: str) -> Path:
        return self.base_dir / run_id

    def _meta_path(self, run_id: str) -> Path:
        return self._run_dir(run_id) / "meta.json"

    def _pending_path(self) -> Path:
        return self.base_dir / PENDING_INDEX

    def _req_path(self, run_id: str, seq: int) -> Path:
        return self._run_dir(run_id) / f"req-{seq:03d}.json"

    def _rsp_path(self, run_id: str, seq: int) -> Path:
        return self._run_dir(run_id) / f"rsp-{seq:03d}.json"

    def _cache_path(self, run_id: str) -> Path:
        return self._run_dir(run_id) / CACHE_FILE

    # ── Run 生命周期 ──

    def create_run(
        self,
        kind: str,
        argv: dict,
        track_id: int | None = None,
        session_id: int | None = None,
    ) -> Run:
        run = Run(
            id=_gen_run_id(),
            kind=kind,
            argv=argv,
            track_id=track_id,
            session_id=session_id,
        )
        self._save_meta(run)
        logger.info("Run created: %s (%s)", run.id, kind)
        return run

    def get_run(self, run_id: str) -> Run | None:
        data = _read_json(self._meta_path(run_id))
        if not data:
            return None
        return Run.from_dict(data)

    def save_run(self, run: Run):
        run.updated_at = _now()
        self._save_meta(run)

    def _save_meta(self, run: Run):
        _atomic_write(self._meta_path(run.id), run.to_dict())

    def mark_done(self, run: Run):
        run.status = "done"
        self.save_run(run)
        self._rebuild_pending_index()
        logger.info("Run done: %s", run.id)

    def mark_failed(self, run: Run, error: str):
        run.status = "failed"
        run.error = error
        self.save_run(run)
        self._rebuild_pending_index()

    # ── Checkpoint 请求（写 req → 抛异常）──

    def create_request(
        self,
        run: Run,
        kind: str,
        key: str,
        payload: dict,
    ) -> Path:
        """写入 req-NNN.json，更新 run 状态，返回 req 文件路径。

        调用方（LLM/Search 客户端）随后抛 NeedsLLM/NeedsSearch，CLI 层 exit 75/76。
        """
        seq = len(run.steps) + 1
        req_path = self._req_path(run.id, seq)

        req = {
            "run_id": run.id,
            "step": f"step-{seq:03d}",
            "kind": kind,
            "key": key,
            "run_status_after": run.status,
            **payload,
            "instruction": (
                f"按 schema 生成 JSON，写入文件（使用 Write 工具）：\n{req_path}"
                if kind == "llm"
                else "用你的搜索能力获取结果，写入 JSON 数组文件：\n{req_path}"
            ),
            "created_at": _now(),
        }
        _atomic_write(req_path, req)

        step = Step(seq=seq, kind=kind, key=key, status="pending", req=req_path.name)
        run.steps.append(step)
        run.status = "pending_llm" if kind == "llm" else "pending_search"
        self.save_run(run)
        self._rebuild_pending_index()
        logger.info("Checkpoint created: %s step-%03d (%s)", run.id, seq, kind)
        return req_path

    # ── 应答消费（resume 重放命中）──

    def get_answer(self, run: Run, key: str) -> dict | None:
        """幂等消费：rsp 存在且 key 匹配 → 读回并标记 consumed；否则 None。"""
        step = run.step_by_key(key)
        if not step:
            return None
        rsp_path = self._rsp_path(run.id, step.seq)
        if not rsp_path.exists():
            return None
        data = _read_json(rsp_path)
        if data is None:
            return None
        if step.status != "consumed":
            step.status = "consumed"
            self.save_run(run)
            self._rebuild_pending_index()
        return data

    def submit_response(self, run_id: str, rsp_file: str | Path) -> dict:
        """resume 入口：读取 agent 补答文件，关联到第一个 pending step。

        Returns: 应答 dict。
        Raises: ValueError 当 run 不存在 / 无 pending step / rsp 文件不可读。
        """
        run = self.get_run(run_id)
        if not run:
            raise ValueError(f"Run not found: {run_id}")

        pending = [s for s in run.steps if s.status in ("pending", "answered")]
        if not pending:
            raise ValueError(f"Run {run_id} has no pending step to answer")

        step = pending[0]
        rsp_path = Path(rsp_file)
        if not rsp_path.exists():
            raise ValueError(f"Response file not found: {rsp_path}")

        data = _read_json(rsp_path)
        if data is None:
            raise ValueError(f"Response file is not valid JSON: {rsp_path}")

        # 落库：复制到 run 目录，与 req 相邻
        target = self._rsp_path(run.id, step.seq)
        _atomic_write(target, data)
        step.status = "answered"
        step.rsp = target.name
        run.status = "running"
        self.save_run(run)
        self._rebuild_pending_index()
        logger.info("Response consumed: %s step-%03d", run.id, step.seq)
        return data

    # ── 中间产物缓存（搜索等，保证重放幂等）──

    def cache_get(self, run: Run, cache_key: str) -> dict | None:
        data = _read_json(self._cache_path(run.id))
        if not data:
            return None
        return data.get("items", {}).get(cache_key)

    def cache_set(self, run: Run, cache_key: str, value):
        data = _read_json(self._cache_path(run.id)) or {"items": {}}
        data["items"][cache_key] = value
        data.setdefault("created_at", _now())
        data["updated_at"] = _now()
        _atomic_write(self._cache_path(run.id), data)

    # ── 本地副作用步骤（重放跳过标记）──

    def mark_step_done(self, run: Run, key: str):
        """标记本地副作用步骤已完成（重放时跳过重复执行，如 SM-2 落库）。"""
        if run.step_by_key(key):
            return
        seq = len(run.steps) + 1
        run.steps.append(Step(seq=seq, kind="local", key=key, status="done"))
        self.save_run(run)

    def is_step_done(self, run: Run, key: str) -> bool:
        step = run.step_by_key(key)
        return bool(step and step.status == "done")

    # ── pending 索引（§5.1.1：每次退出/消费时原子重建）──

    def pending_runs(self) -> list[Run]:
        data = _read_json(self._pending_path())
        if not data:
            return []
        runs = []
        for entry in data.get("pending", []):
            run = self.get_run(entry.get("run_id", ""))
            if run:
                runs.append(run)
        return runs

    def latest_pending(self) -> Run | None:
        runs = self.pending_runs()
        if not runs:
            return None
        return max(runs, key=lambda r: r.updated_at or "")

    def _rebuild_pending_index(self):
        entries = []
        for d in self.base_dir.iterdir():
            if not d.is_dir() or not d.name.startswith("run-"):
                continue
            run = self.get_run(d.name)
            if not run:
                continue
            if run.status in ("pending_llm", "pending_search", "pending_answers"):
                pending_step = next(
                    (s for s in run.steps if s.status in ("pending", "answered")),
                    None,
                )
                entries.append({
                    "run_id": run.id,
                    "kind": run.kind,
                    "status": run.status,
                    "pending_step": pending_step.req if pending_step else None,
                    "created_at": run.created_at,
                    "updated_at": run.updated_at,
                })
        entries.sort(key=lambda e: e["updated_at"] or "", reverse=True)
        _atomic_write(self._pending_path(), {
            "updated_at": _now(),
            "pending": entries,
        })

    # ── 维护 ──

    def list_runs(self, limit: int = 50) -> list[Run]:
        runs = []
        for d in self.base_dir.iterdir():
            if d.is_dir() and d.name.startswith("run-"):
                run = self.get_run(d.name)
                if run:
                    runs.append(run)
        runs.sort(key=lambda r: r.created_at or "", reverse=True)
        return runs[:limit]

    def prune(self, days: int = DEFAULT_PRUNE_DAYS) -> list[str]:
        """删除 done/failed 且超过 days 的 run 目录；pending 不删。"""
        cutoff = _utc_ts() - days * 86400
        removed = []
        for d in self.base_dir.iterdir():
            if not d.is_dir() or not d.name.startswith("run-"):
                continue
            run = self.get_run(d.name)
            if not run:
                continue
            if run.status not in ("done", "failed"):
                continue
            mtime = d.stat().st_mtime
            if mtime < cutoff:
                import shutil
                shutil.rmtree(d)
                removed.append(run.id)
        self._rebuild_pending_index()
        return removed
