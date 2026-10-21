"""주제어로 KOSIS 통합검색 + 메타 조회를 돌려 카탈로그 후보(catalog.draft.json)를 만든다.

사용: uv run python scripts/build_catalog.py "초등학생 수" "사교육비" [--per-topic 5]
KOSIS_API_KEY가 필요하다 (환경변수 또는 작업 폴더 .env). 결과는 사람이 확인한 뒤
src/ne_kosis_mcp/data/catalog.json으로 옮긴다 (설명, 키워드, 주의사항을 채운다).
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from ne_kosis_mcp.client import ApiError, KosisClient
from ne_kosis_mcp.config import load_dotenv_if_present, resolve_api_key

DRAFT = Path("catalog.draft.json")


async def build(topics: list[str], per_topic: int) -> list[dict]:
    client = KosisClient(resolve_api_key(os.environ))
    drafts: list[dict] = []
    try:
        for topic in topics:
            hits = await client.search(topic, count=per_topic)
            for hit in hits:
                org, tbl = hit.get("ORG_ID"), hit.get("TBL_ID")
                entry = {
                    "id": f"{org}-{tbl}",
                    "orgId": org,
                    "tblId": tbl,
                    "title": hit.get("TBL_NM"),
                    "topic": hit.get("MT_ATITLE"),
                    "description": "",
                    "period": f"{hit.get('STRT_PRD_DE')}~{hit.get('END_PRD_DE')}",
                    "keywords": [topic],
                    "notes": [],
                    "verified": None,
                    "_searchSummary": hit.get("CONTENTS"),
                }
                try:
                    entry["_items"] = await client.table_meta(org, tbl, "ITM")
                    entry["_classifications"] = await client.table_meta(org, tbl, "OBJ")
                except ApiError as e:
                    entry["_metaError"] = str(e)
                drafts.append(entry)
    finally:
        await client.aclose()
    return drafts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("topics", nargs="+")
    parser.add_argument("--per-topic", type=int, default=5)
    args = parser.parse_args()
    load_dotenv_if_present()
    drafts = asyncio.run(build(args.topics, args.per_topic))
    DRAFT.write_text(json.dumps(drafts, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(drafts)}개 후보를 {DRAFT}에 썼습니다. 값을 확인하고 catalog.json으로 옮기세요.", file=sys.stderr)


if __name__ == "__main__":
    main()
