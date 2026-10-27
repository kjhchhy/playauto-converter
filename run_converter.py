import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT))

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")

import playauto.cli
import playauto.db_cli

DB_COMMANDS = {"db-import", "db-export"}


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in DB_COMMANDS:
        raise SystemExit(playauto.db_cli.main(sys.argv[1:]))
    raise SystemExit(playauto.cli.main())
