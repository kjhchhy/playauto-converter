import argparse
import json
from datetime import date as date_type
from pathlib import Path

from .db import connect, ensure_schema, import_crawl, load_crawl_rows
from .db_export import export_from_db


def build_parser():
    parser = argparse.ArgumentParser(description="플레이오토 DB 가져오기/내보내기")
    subparsers = parser.add_subparsers(dest="command", required=True)

    import_parser = subparsers.add_parser("db-import", help="크롤 xlsx를 DB로 가져오기")
    import_parser.add_argument(
        "--db", type=Path, default=Path("data/playauto.db"), help="SQLite DB 경로"
    )
    import_parser.add_argument("--crawl", type=Path, required=True, help="크롤 xlsx 경로")
    import_parser.add_argument(
        "--category-code", required=True, help="상품분류 코드 (예: 기타재화[35])"
    )
    import_parser.add_argument("--margin", type=float, default=0.15, help="기본 마진율")

    export_parser = subparsers.add_parser("db-export", help="DB에서 설정/최종 엑셀 생성")
    export_parser.add_argument(
        "--db", type=Path, default=Path("data/playauto.db"), help="SQLite DB 경로"
    )
    export_parser.add_argument("--reference", type=Path, required=True, help="참조 xlsx 경로")
    export_parser.add_argument(
        "--output-dir", type=Path, default=Path("."), help="출력 디렉터리 (기본: 현재 디렉터리)"
    )
    export_parser.add_argument(
        "--option", default="기타재화[35]", help="상품분류 옵션 (예: 기타재화[35])"
    )
    export_parser.add_argument("--commission-gmarket", type=float, default=12.0)
    export_parser.add_argument("--commission-smartstore", type=float, default=6.0)
    export_parser.add_argument("--commission-coupang", type=float, default=10.0)
    export_parser.add_argument(
        "--date",
        type=date_type.fromisoformat,
        default=None,
        help="파일명 날짜 (YYYY-MM-DD, 기본: 오늘)",
    )
    export_parser.add_argument(
        "--coupang-single",
        action="store_true",
        help="쿠팡 단일 파일만 생성",
    )

    return parser


def _print_json(payload):
    printable = {
        key: str(value) if isinstance(value, Path) else value
        for key, value in payload.items()
    }
    print(json.dumps(printable, ensure_ascii=True))


def _run_import(args):
    conn = connect(args.db)
    try:
        ensure_schema(conn)
        crawl = load_crawl_rows(args.crawl)
        summary = import_crawl(
            conn,
            crawl,
            args.category_code,
            args.margin,
            str(args.crawl),
        )
    finally:
        conn.close()

    _print_json({
        "db": args.db,
        "batch_id": summary.batch_id,
        "inserted": summary.inserted,
        "updated": summary.updated,
        "skipped": summary.skipped,
    })


def _run_export(args):
    commission = {
        "지마켓": args.commission_gmarket,
        "스마트스토어": args.commission_smartstore,
        "쿠팡": args.commission_coupang,
    }
    result = export_from_db(
        args.db,
        args.reference,
        args.output_dir,
        args.option,
        coupang_single=args.coupang_single,
        commission=commission,
        run_date=args.date,
    )
    _print_json(result)


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "db-import":
        _run_import(args)
    elif args.command == "db-export":
        _run_export(args)
    return 0
