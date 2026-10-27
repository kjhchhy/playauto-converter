import argparse
import json
from datetime import date as date_type
from pathlib import Path

from .xlsx import convert_phase1


def build_parser():
    parser = argparse.ArgumentParser(
        description="플레이오토 Phase1 설정/최종 엑셀 생성"
    )
    parser.add_argument("input", type=Path, help="setting/template 시트가 있는 xlsx")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("."),
        help="출력 디렉터리 (기본: 현재 디렉터리)",
    )
    parser.add_argument(
        "--option",
        default="기타재화[35]",
        help="상품분류 옵션 (예: 기타재화[35])",
    )
    parser.add_argument(
        "--coupang-single",
        action="store_true",
        help="쿠팡 단일 파일만 생성",
    )
    parser.add_argument("--commission-gmarket", type=float, default=12.0)
    parser.add_argument("--commission-smartstore", type=float, default=6.0)
    parser.add_argument("--commission-coupang", type=float, default=10.0)
    parser.add_argument(
        "--no-setting-copy",
        action="store_true",
        help="설정 워크북 복사본을 만들지 않음",
    )
    parser.add_argument(
        "--date",
        type=date_type.fromisoformat,
        default=None,
        help="파일명 날짜 (YYYY-MM-DD, 기본: 오늘)",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if not args.input.exists():
        raise SystemExit(f"입력 파일 없음: {args.input}")
    commission = {
        "지마켓": args.commission_gmarket,
        "스마트스토어": args.commission_smartstore,
        "쿠팡": args.commission_coupang,
    }
    result = convert_phase1(
        input_path=args.input,
        output_dir=args.output_dir,
        selected_option=args.option,
        coupang_single=args.coupang_single,
        commission=commission,
        run_date=args.date,
        copy_setting=not args.no_setting_copy,
    )
    printable = {
        key: str(value) if value is not None else None
        for key, value in result.items()
    }
    print(json.dumps(printable, ensure_ascii=True))
    return 0
