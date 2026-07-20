"""知识质量评估引擎

基于知识图谱质量评估框架（工程界）和 NUSAP Pedigree Matrix，
对知识节点进行多维度质量评估。

评估维度：
1. 模式层质量 — 节点类型分类、关系类型规范化、本体设计合理性
2. 数据层质量 — 准确性、完整性、一致性、时效性、来源可信度
3. NUSAP Pedigree — 理论支撑、数据来源、方法验证
4. 应用层质量 — 检索召回率、覆盖度、知识深度
"""

import json
import math
from datetime import date, datetime, timedelta
from typing import Any

from ..db.database import get_connection


# ============================================================
# NUSAP Pedigree Matrix 评分标准
# ============================================================

THEORY_LEVELS = {
    4: "成熟理论/公认定律",
    3: "领域内广泛接受的框架或模型",
    2: "有学术论文支撑但未成共识",
    1: "基于经验推断或类比",
    0: "纯猜测",
}

DATA_LEVELS = {
    4: "官方统计/一手实测/权威数据库",
    3: "行业白皮书/头部机构报告",
    2: "媒体报道/企业公开信息",
    1: "二手转述/论坛/自媒体",
    0: "无来源/无法追溯",
}

METHOD_LEVELS = {
    4: "独立第三方验证/复现",
    3: "有同行评审",
    2: "内部验证/自洽",
    1: "未验证但有逻辑支撑",
    0: "未验证",
}

SOURCE_RELIABILITY = {
    4: "一手权威来源（官方统计、学术期刊、专利）",
    3: "高可信来源（行业白皮书、头部机构报告）",
    2: "中等可信来源（媒体报道、企业公开信息）",
    1: "低可信来源（论坛、自媒体、二手转述）",
    0: "不可追溯来源",
}

COMPLETENESS_LEVELS = {
    4: "完整覆盖（定义、原理、示例、边界条件、反例）",
    3: "较完整（定义、原理、示例）",
    2: "基本完整（定义+简要说明）",
    1: "不完整（仅有名称或一句话描述）",
    0: "空节点",
}

CONSISTENCY_LEVELS = {
    4: "与所有已知知识一致，无任何矛盾",
    3: "与主流知识一致，有少量未验证细节",
    2: "基本一致，存在可解释的局部矛盾",
    1: "存在明显矛盾或冲突",
    0: "自相矛盾",
}

NODE_TYPE_LABELS = {
    "concept": "概念/定义",
    "fact": "事实性知识",
    "principle": "原理/定律",
    "procedure": "流程/方法",
    "framework": "框架/模型",
    "case": "案例/实例",
    "data_point": "数据点/统计",
    "reference": "引用/文献",
}


class KnowledgeQualityAssessor:
    """知识质量评估器"""

    def __init__(self, db_conn=None):
        self._conn = db_conn

    def _get_conn(self):
        if self._conn:
            return self._conn
        return get_connection()

    # ============================================================
    # 单节点质量评估
    # ============================================================

    def assess_node(self, node_id: int) -> dict:
        """对单个知识节点进行完整质量评估。

        Returns:
            {node_id, nusap: {theory, data, method}, quality: {completeness, consistency, source_reliability},
             overall_score, findings, recommendations}
        """
        conn = self._get_conn()
        try:
            node = conn.execute(
                "SELECT * FROM knowledge_nodes WHERE id = ?", (node_id,)
            ).fetchone()
            if not node:
                return {"error": "node not found"}

            node = dict(node)
            findings = []
            recommendations = []

            # --- NUSAP Pedigree 评估 ---
            theory = node.get("theory_level", 0)
            data = node.get("data_level", 0)
            method = node.get("method_level", 0)

            # 自动推断缺失的评分
            if theory == 0 and node.get("source_url"):
                theory = self._infer_theory_level(node)
            if data == 0 and node.get("source_url"):
                data = self._infer_data_level(node)
            if method == 0:
                method = self._infer_method_level(node)

            # --- 数据层质量评估 ---
            completeness = node.get("completeness", 0)
            if completeness == 0:
                completeness = self._assess_completeness(node)

            consistency = node.get("consistency", 0)
            if consistency == 0:
                consistency = self._assess_consistency(node)

            source_reliability = node.get("source_reliability", 0)
            if source_reliability == 0 and node.get("source_url"):
                source_reliability = self._infer_source_reliability(node)

            # --- 时效性检查 ---
            freshness = self._check_freshness(node)

            # --- 综合质量分 (0-100) ---
            overall_score = self._calculate_overall_score(
                theory, data, method, completeness, consistency, source_reliability, freshness
            )

            # --- 发现问题和改进建议 ---
            if theory < 2:
                findings.append("理论支撑不足，建议补充权威文献或理论依据")
                recommendations.append("查找该领域的经典教材或综述论文作为理论支撑")
            if data < 2:
                findings.append("数据来源可信度低，建议引用一手或权威数据")
                recommendations.append("优先使用官方统计、学术论文或行业白皮书数据")
            if method < 2:
                findings.append("方法验证不足，建议进行交叉验证")
                recommendations.append("通过多源对比或独立验证确认结论可靠性")
            if completeness < 3:
                findings.append("知识内容不完整，缺少关键要素")
                recommendations.append("补充定义、原理、示例、边界条件和反例")
            if consistency < 3:
                findings.append("存在一致性风险，建议检查与其他知识的矛盾")
                recommendations.append("检查该节点与相关节点的逻辑一致性")
            if freshness["status"] == "stale":
                findings.append(f"知识已过期（超过{freshness['days_overdue']}天），建议更新")
                recommendations.append("查找最新资料更新该知识点")
            if source_reliability < 2:
                findings.append("来源可靠性低，建议核实原始出处")
                recommendations.append("追溯原始来源并评估其权威性")

            return {
                "node_id": node_id,
                "node_name": node["name"],
                "node_type": node.get("node_type", "concept"),
                "nusap": {
                    "theory": {"score": theory, "label": THEORY_LEVELS.get(theory, "未评估")},
                    "data": {"score": data, "label": DATA_LEVELS.get(data, "未评估")},
                    "method": {"score": method, "label": METHOD_LEVELS.get(method, "未评估")},
                },
                "quality": {
                    "completeness": {"score": completeness, "label": COMPLETENESS_LEVELS.get(completeness, "未评估")},
                    "consistency": {"score": consistency, "label": CONSISTENCY_LEVELS.get(consistency, "未评估")},
                    "source_reliability": {"score": source_reliability, "label": SOURCE_RELIABILITY.get(source_reliability, "未评估")},
                    "freshness": freshness,
                },
                "overall_score": overall_score,
                "findings": findings,
                "recommendations": recommendations,
            }
        finally:
            if not self._conn:
                conn.close()

    def _infer_theory_level(self, node: dict) -> int:
        """根据来源URL和内容推断理论支撑等级。"""
        url = node.get("source_url", "")
        content = node.get("content", "")

        # 学术论文/教科书
        if any(kw in url for kw in [".edu", "scholar", "arxiv", "doi.org", "pubmed", "ieee"]):
            return 3
        # 行业报告/白皮书
        if any(kw in url for kw in ["report", "whitepaper", "research"]):
            return 2
        # 一般网站
        if url:
            return 1
        return 0

    def _infer_data_level(self, node: dict) -> int:
        """根据来源URL推断数据来源等级。"""
        url = node.get("source_url", "")
        if any(kw in url for kw in [".gov", ".edu", "stats", "data.gov", "who.int", "worldbank"]):
            return 4
        if any(kw in url for kw in [".org", "reports", "gartner", "forrester", "mckinsey"]):
            return 3
        if any(kw in url for kw in [".com", "news", "blog", "medium"]):
            return 2
        if url:
            return 1
        return 0

    def _infer_method_level(self, node: dict) -> int:
        """根据节点类型和内容推断方法验证等级。"""
        content = node.get("content", "")
        # 有引用标记
        if any(kw in content for kw in ["[1]", "[2]", "(202", "(201", "et al.", "等人"]):
            return 3
        # 有逻辑推导
        if any(kw in content for kw in ["因此", "所以", "证明", "推导", "验证"]):
            return 2
        # 有解释
        if len(content) > 200:
            return 1
        return 0

    def _infer_source_reliability(self, node: dict) -> int:
        """根据来源URL推断来源可信度。"""
        url = node.get("source_url", "")
        if any(kw in url for kw in [".gov", ".edu", "who.int", "worldbank", "un.org"]):
            return 4
        if any(kw in url for kw in [".org", "scholar", "arxiv", "doi.org", "pubmed"]):
            return 3
        if any(kw in url for kw in [".com", "news", "medium"]):
            return 2
        if any(kw in url for kw in ["blog", "forum", "zhihu", "bbs"]):
            return 1
        if url:
            return 1
        return 0

    def _assess_completeness(self, node: dict) -> int:
        """评估知识节点的完整性。"""
        content = node.get("content", "")
        description = node.get("description", "")
        combined = (content + " " + description).lower()

        score = 0
        # 有定义
        if any(kw in combined for kw in ["定义", "是", "指", "means", "defined"]):
            score += 1
        # 有原理/解释
        if any(kw in combined for kw in ["原理", "原因", "因为", "所以", "why", "because"]):
            score += 1
        # 有示例
        if any(kw in combined for kw in ["例如", "比如", "示例", "example", "e.g."]):
            score += 1
        # 有边界条件
        if any(kw in combined for kw in ["适用", "不适用", "条件", "限制", "limitation", "boundary"]):
            score += 1
        # 有反例/对比
        if any(kw in combined for kw in ["区别", "对比", "不同于", "相反", "difference", "vs"]):
            score += 1

        return min(score, 4)

    def _assess_consistency(self, node: dict) -> int:
        """评估知识节点的一致性（初步基于内容分析）。"""
        content = node.get("content", "")
        # 检查是否有自相矛盾的表述
        contradiction_patterns = [
            ("但是", "然而", "不过"),
            ("实际上", "事实上"),
            ("换句话说", "也就是说"),
        ]
        has_contradiction = False
        for patterns in contradiction_patterns:
            found = sum(1 for p in patterns if p in content)
            if found >= 2:
                has_contradiction = True
                break

        if has_contradiction:
            return 2  # 有矛盾但可能是有意对比
        if len(content) > 500:
            return 3  # 内容较丰富，默认较高
        if len(content) > 100:
            return 2
        return 1

    def _check_freshness(self, node: dict) -> dict:
        """检查知识时效性。"""
        freshness_date = node.get("freshness_date")
        if not freshness_date:
            # 如果没有设置时效日期，根据节点类型推断
            node_type = node.get("node_type", "concept")
            created_at = node.get("created_at", date.today().isoformat())
            try:
                created = date.fromisoformat(created_at)
            except (ValueError, TypeError):
                created = date.today()

            # 不同类型知识的默认有效期
            validity_days = {
                "concept": 365 * 5,      # 概念：5年
                "fact": 365 * 2,          # 事实：2年
                "principle": 365 * 10,    # 原理：10年
                "procedure": 365 * 3,     # 流程：3年
                "framework": 365 * 5,     # 框架：5年
                "case": 365 * 1,          # 案例：1年
                "data_point": 365 * 1,    # 数据点：1年
                "reference": 365 * 10,    # 引用：10年
            }
            expiry = created + timedelta(days=validity_days.get(node_type, 365 * 2))
        else:
            try:
                expiry = date.fromisoformat(freshness_date)
            except (ValueError, TypeError):
                expiry = date.today()

        today = date.today()
        days_remaining = (expiry - today).days

        if days_remaining < 0:
            return {
                "status": "stale",
                "days_overdue": abs(days_remaining),
                "expiry_date": expiry.isoformat(),
            }
        elif days_remaining < 30:
            return {
                "status": "expiring_soon",
                "days_remaining": days_remaining,
                "expiry_date": expiry.isoformat(),
            }
        else:
            return {
                "status": "fresh",
                "days_remaining": days_remaining,
                "expiry_date": expiry.isoformat(),
            }

    def _calculate_overall_score(self, theory, data, method,
                                  completeness, consistency,
                                  source_reliability, freshness) -> int:
        """计算综合质量分 (0-100)。"""
        # NUSAP 维度权重 40%
        nusap_score = (theory + data + method) / 12 * 40

        # 数据层质量权重 35%
        quality_score = (completeness + consistency + source_reliability) / 12 * 35

        # 时效性权重 25%
        if freshness["status"] == "fresh":
            freshness_score = 25
        elif freshness["status"] == "expiring_soon":
            freshness_score = 15
        else:
            freshness_score = 5

        total = nusap_score + quality_score + freshness_score
        return min(100, max(0, round(total)))

    # ============================================================
    # 批量评估
    # ============================================================

    def assess_track(self, track_id: int) -> dict:
        """评估整个学习路线的知识质量。"""
        conn = self._get_conn()
        try:
            nodes = conn.execute(
                "SELECT * FROM knowledge_nodes WHERE track_id = ? AND status = 'active'",
                (track_id,),
            ).fetchall()

            if not nodes:
                return {"error": "no active nodes in track"}

            results = []
            total_score = 0
            for node in nodes:
                assessment = self.assess_node(node["id"])
                if "error" not in assessment:
                    results.append(assessment)
                    total_score += assessment["overall_score"]

            avg_score = round(total_score / len(results), 1) if results else 0

            # 质量分布
            distribution = {"excellent": 0, "good": 0, "fair": 0, "poor": 0}
            for r in results:
                s = r["overall_score"]
                if s >= 80:
                    distribution["excellent"] += 1
                elif s >= 60:
                    distribution["good"] += 1
                elif s >= 40:
                    distribution["fair"] += 1
                else:
                    distribution["poor"] += 1

            # 节点类型分布
            type_dist = {}
            for r in results:
                nt = r.get("node_type", "concept")
                type_dist[nt] = type_dist.get(nt, 0) + 1

            # 常见问题汇总
            all_findings = []
            for r in results:
                all_findings.extend(r.get("findings", []))
            top_findings = {}
            for f in all_findings:
                top_findings[f] = top_findings.get(f, 0) + 1
            top_findings = sorted(top_findings.items(), key=lambda x: -x[1])[:5]

            return {
                "track_id": track_id,
                "total_nodes": len(results),
                "average_quality_score": avg_score,
                "quality_distribution": distribution,
                "node_type_distribution": type_dist,
                "top_findings": [{"finding": f, "count": c} for f, c in top_findings],
                "nodes": results,
            }
        finally:
            if not self._conn:
                conn.close()

    def assess_all(self, user_id: int) -> dict:
        """评估用户所有知识库的质量。"""
        conn = self._get_conn()
        try:
            tracks = conn.execute(
                "SELECT id, name FROM tracks WHERE user_id = ? AND status = 'active'",
                (user_id,),
            ).fetchall()

            track_results = []
            total_nodes = 0
            total_score = 0

            for track in tracks:
                result = self.assess_track(track["id"])
                if "error" not in result:
                    track_results.append({
                        "track_id": track["id"],
                        "track_name": track["name"],
                        "total_nodes": result["total_nodes"],
                        "average_quality_score": result["average_quality_score"],
                        "quality_distribution": result["quality_distribution"],
                        "top_findings": result["top_findings"],
                    })
                    total_nodes += result["total_nodes"]
                    total_score += result["average_quality_score"] * result["total_nodes"]

            overall_avg = round(total_score / total_nodes, 1) if total_nodes > 0 else 0

            return {
                "user_id": user_id,
                "total_tracks": len(track_results),
                "total_nodes": total_nodes,
                "overall_quality_score": overall_avg,
                "tracks": track_results,
            }
        finally:
            if not self._conn:
                conn.close()

    # ============================================================
    # 知识质量更新
    # ============================================================

    def update_node_quality(self, node_id: int, audit_type: str = "review_update",
                            theory_level: int = None, data_level: int = None,
                            method_level: int = None, source_reliability: int = None,
                            completeness: int = None, consistency: int = None,
                            notes: str = "") -> dict:
        """更新节点质量评分并记录审计日志。"""
        conn = self._get_conn()
        try:
            node = conn.execute(
                "SELECT * FROM knowledge_nodes WHERE id = ?", (node_id,)
            ).fetchone()
            if not node:
                return {"error": "node not found"}

            node = dict(node)

            # 使用现有值或传入值
            t = theory_level if theory_level is not None else node.get("theory_level", 0)
            d = data_level if data_level is not None else node.get("data_level", 0)
            m = method_level if method_level is not None else node.get("method_level", 0)
            sr = source_reliability if source_reliability is not None else node.get("source_reliability", 0)
            comp = completeness if completeness is not None else node.get("completeness", 0)
            cons = consistency if consistency is not None else node.get("consistency", 0)

            # 计算综合分
            freshness = self._check_freshness(node)
            overall = self._calculate_overall_score(t, d, m, comp, cons, sr, freshness)

            # 更新节点
            conn.execute(
                """UPDATE knowledge_nodes SET
                    theory_level = ?, data_level = ?, method_level = ?,
                    source_reliability = ?, completeness = ?, consistency = ?,
                    quality_score = ?, updated_at = date('now')
                WHERE id = ?""",
                (t, d, m, sr, comp, cons, overall, node_id),
            )

            # 记录审计日志
            conn.execute(
                """INSERT INTO quality_audit_log
                    (node_id, audit_type, theory_level, data_level, method_level,
                     source_reliability, completeness, consistency,
                     quality_score, findings, recommendations, notes, audited_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    node_id, audit_type,
                    t, d, m, sr, comp, cons, overall,
                    "[]", "[]", notes, "system",
                ),
            )

            conn.commit()

            return {
                "node_id": node_id,
                "quality_score": overall,
                "nusap": {"theory": t, "data": d, "method": m},
                "quality": {"completeness": comp, "consistency": cons, "source_reliability": sr},
                "audit_type": audit_type,
            }
        finally:
            if not self._conn:
                conn.close()

    # ============================================================
    # 覆盖度评估
    # ============================================================

    def assess_coverage(self, track_id: int) -> dict:
        """评估知识库的领域覆盖度。"""
        conn = self._get_conn()
        try:
            # 获取已定义的覆盖度目标
            coverage_rows = conn.execute(
                "SELECT * FROM knowledge_coverage WHERE track_id = ?",
                (track_id,),
            ).fetchall()

            # 获取实际节点分布
            nodes = conn.execute(
                "SELECT node_type, COUNT(*) as cnt FROM knowledge_nodes "
                "WHERE track_id = ? AND status = 'active' GROUP BY node_type",
                (track_id,),
            ).fetchall()

            node_type_counts = {r["node_type"]: r["cnt"] for r in nodes}

            # 节点类型健康度评估
            type_health = {}
            for nt, label in NODE_TYPE_LABELS.items():
                count = node_type_counts.get(nt, 0)
                if nt in ("concept", "principle", "fact"):
                    recommended = "高优先级"
                elif nt in ("procedure", "framework"):
                    recommended = "中优先级"
                else:
                    recommended = "补充型"
                type_health[nt] = {
                    "label": label,
                    "count": count,
                    "priority": recommended,
                }

            # 深度分布
            depth_dist = {}
            for r in conn.execute(
                "SELECT current_level, COUNT(*) as cnt FROM knowledge_nodes "
                "WHERE track_id = ? AND status = 'active' GROUP BY current_level",
                (track_id,),
            ).fetchall():
                depth_dist[str(r["current_level"])] = r["cnt"]

            return {
                "track_id": track_id,
                "node_type_distribution": type_health,
                "depth_distribution": depth_dist,
                "coverage_targets": [dict(r) for r in coverage_rows],
            }
        finally:
            if not self._conn:
                conn.close()

    # ============================================================
    # 质量报告
    # ============================================================

    def generate_quality_report(self, user_id: int) -> str:
        """生成知识质量评估报告（人类可读）。"""
        overall = self.assess_all(user_id)
        if "error" in overall:
            return f"评估失败：{overall['error']}"

        lines = []
        lines.append("=" * 50)
        lines.append("📊 知识库质量评估报告")
        lines.append("=" * 50)
        lines.append(f"总路线数：{overall['total_tracks']}")
        lines.append(f"总节点数：{overall['total_nodes']}")
        lines.append(f"综合质量分：{overall['overall_quality_score']}/100")
        lines.append("")

        for track in overall["tracks"]:
            lines.append(f"── {track['track_name']} ──")
            lines.append(f"  节点数：{track['total_nodes']}")
            lines.append(f"  平均质量分：{track['average_quality_score']}/100")
            dist = track["quality_distribution"]
            lines.append(f"  质量分布：优秀{dist['excellent']} 良好{dist['good']} 一般{dist['fair']} 差{dist['poor']}")
            if track["top_findings"]:
                lines.append("  主要问题：")
                for f in track["top_findings"]:
                    lines.append(f"    · {f['finding']}（出现{f['count']}次）")
            lines.append("")

        lines.append("=" * 50)
        lines.append("NUSAP Pedigree Matrix 评分标准")
        lines.append("-" * 50)
        lines.append("理论支撑：0=纯猜测 1=经验推断 2=有论文支撑 3=广泛接受 4=成熟理论")
        lines.append("数据来源：0=无来源 1=二手转述 2=媒体报道 3=行业报告 4=官方统计")
        lines.append("方法验证：0=未验证 1=有逻辑支撑 2=内部验证 3=同行评审 4=独立验证")
        lines.append("=" * 50)

        return "\n".join(lines)


# ============================================================
# CLI 接口
# ============================================================

def cli_assess(args: list[str]) -> str:
    """CLI: assess <node_id> | assess-track <track_id> | assess-all <user_id> | report <user_id>"""
    if not args:
        return "用法：assess <node_id> | assess-track <track_id> | assess-all <user_id> | report <user_id>"

    assessor = KnowledgeQualityAssessor()
    cmd = args[0]

    if cmd == "assess" and len(args) >= 2:
        result = assessor.assess_node(int(args[1]))
        if "error" in result:
            return f"错误：{result['error']}"
        return json.dumps(result, ensure_ascii=False, indent=2)

    elif cmd == "assess-track" and len(args) >= 2:
        result = assessor.assess_track(int(args[1]))
        if "error" in result:
            return f"错误：{result['error']}"
        return json.dumps(result, ensure_ascii=False, indent=2)

    elif cmd == "assess-all" and len(args) >= 2:
        result = assessor.assess_all(int(args[1]))
        if "error" in result:
            return f"错误：{result['error']}"
        return json.dumps(result, ensure_ascii=False, indent=2)

    elif cmd == "report" and len(args) >= 2:
        return assessor.generate_quality_report(int(args[1]))

    return "未知命令"
