"""CLI: python -m engine.knowledge <command> [args]

Commands:
    search <query> [--top-k N] [--scope category]
    sources
    rebuild
"""

import argparse
import json
import sys

from .retrieval import search, sources, rebuild


def main():
    parser = argparse.ArgumentParser(description="知识库检索 CLI")
    sub = parser.add_subparsers(dest="command")

    p_search = sub.add_parser("search", help="检索知识库")
    p_search.add_argument("query", help="搜索关键词")
    p_search.add_argument("--top-k", type=int, default=5, help="返回结果数")
    p_search.add_argument("--scope", help="限定分类 (core/methods/references/strategies/tracking/research)")

    p_sources = sub.add_parser("sources", help="列出知识源")
    p_rebuild = sub.add_parser("rebuild", help="重建索引")

    args = parser.parse_args()

    if args.command == "search":
        results = search(args.query, top_k=args.top_k, scope=args.scope)
        output = []
        for r in results:
            output.append({
                "score": r["score"],
                "source": r["source"],
                "category": r["category"],
                "section": r["section"],
                "content": r["content"][:200] + "..." if len(r["content"]) > 200 else r["content"],
            })
        print(json.dumps(output, ensure_ascii=False, indent=2))

    elif args.command == "sources":
        srcs = sources()
        print(json.dumps(srcs, ensure_ascii=False, indent=2))

    elif args.command == "rebuild":
        count = rebuild()
        print(json.dumps({"status": "ok", "chunks": count}, ensure_ascii=False, indent=2))

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
