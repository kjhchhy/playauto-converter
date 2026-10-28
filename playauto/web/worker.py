import logging
import os
import shutil
import time
from pathlib import Path

from playauto.db import connect, ensure_schema, import_crawl, load_crawl_rows

from .queries import claim_next_job, mark_stale_jobs, update_job

logger = logging.getLogger(__name__)

POLL_SECONDS = 2
CLEANUP_SECONDS = 60 * 60


def _search_crawl(job, crawler):
    try:
        from playauto.web import crawler as crawler_mod
    except ImportError as exc:
        raise RuntimeError("카드 정규화 모듈을 사용할 수 없습니다.") from exc

    normalize_cards = getattr(crawler_mod, "normalize_cards", None)
    if normalize_cards is None:
        raise RuntimeError("카드 정규화 모듈을 사용할 수 없습니다.")

    if crawler is None:
        crawler = getattr(crawler_mod, "fetch_search_cards", None)
        if crawler is None:
            raise RuntimeError(
                "검색 크롤러를 사용할 수 없습니다. 잠시 후 다시 시도해 주세요."
            )

    raw_cards = crawler(job["search_url"])
    crawl = normalize_cards(raw_cards)
    if not crawl.rows:
        raise ValueError("유효한 상품 카드가 없습니다.")
    return crawl


def process_job(conn, job, *, crawler=None) -> None:
    source = job["source"]
    xlsx_path = job["xlsx_path"]
    try:
        if source == "xlsx":
            if not xlsx_path:
                raise ValueError("엑셀 파일 경로가 없습니다.")
            crawl = load_crawl_rows(xlsx_path)
            crawl_path = xlsx_path
        elif source == "search":
            crawl = _search_crawl(job, crawler)
            crawl_path = job["search_url"] or ""
        else:
            raise ValueError(f"알 수 없는 작업 유형입니다: {source}")

        summary = import_crawl(
            conn,
            crawl,
            job["category_code"],
            job["margin"],
            crawl_path,
        )
        update_job(
            conn,
            job["id"],
            status="succeeded",
            row_count=summary.row_count,
            inserted_count=summary.inserted,
            updated_count=summary.updated,
            skipped_count=summary.skipped,
            import_batch_id=summary.batch_id,
        )
    except Exception as exc:  # noqa: BLE001 - job failures are recorded
        logger.exception("crawl job %s failed", job["id"])
        update_job(conn, job["id"], status="failed", error=str(exc))
    finally:
        if source == "xlsx" and xlsx_path:
            try:
                Path(xlsx_path).unlink(missing_ok=True)
            except OSError:
                logger.exception("failed to delete upload %s", xlsx_path)


def cleanup_exports(export_root, ttl_hours=24) -> int:
    root = Path(export_root)
    if not root.is_dir():
        return 0
    cutoff = time.time() - ttl_hours * 3600
    removed = 0
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        try:
            if entry.stat().st_mtime >= cutoff:
                continue
            shutil.rmtree(entry)
            removed += 1
        except OSError:
            logger.exception("failed to remove export directory %s", entry)
    return removed


def _cleanup_once(export_root, ttl_hours) -> None:
    try:
        cleanup_exports(export_root, ttl_hours)
    except Exception:  # noqa: BLE001 - cleanup must not stop the worker
        logger.exception("export cleanup failed")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    db_path = os.environ.get("DATABASE", "data/playauto.db")
    export_root = os.environ.get("EXPORT_ROOT", "data/exports")
    ttl_hours = int(os.environ.get("EXPORT_TTL_HOURS", "24"))

    conn = connect(db_path)
    ensure_schema(conn)
    try:
        mark_stale_jobs(conn)
        _cleanup_once(export_root, ttl_hours)
        last_cleanup = time.monotonic()

        while True:
            try:
                job = claim_next_job(conn)
                if job is None:
                    time.sleep(POLL_SECONDS)
                else:
                    process_job(conn, job)
            except Exception:  # noqa: BLE001 - worker keeps running
                logger.exception("worker loop error")
                time.sleep(POLL_SECONDS)

            now = time.monotonic()
            if now - last_cleanup >= CLEANUP_SECONDS:
                _cleanup_once(export_root, ttl_hours)
                last_cleanup = now
    finally:
        conn.close()


if __name__ == "__main__":
    main()
