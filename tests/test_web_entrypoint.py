import os
import socket
import subprocess
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]


class WebEntrypointTests(unittest.TestCase):
    def test_module_starts_server_on_port_env(self):
        with TemporaryDirectory() as tmp:
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]

            root = Path(tmp)
            env = os.environ.copy()
            env.update(
                {
                    "PYTHONPATH": os.pathsep.join(
                        [str(ROOT), str(ROOT / "vendor")]
                    ),
                    "SECRET_KEY": "entrypoint-secret",
                    "ADMIN_PASSWORD_HASH": "x",
                    "DATABASE": str(root / "playauto.db"),
                    "REFERENCE_PATH": str(root / "reference.xlsx"),
                    "EXPORT_ROOT": str(root / "exports"),
                    "UPLOAD_ROOT": str(root / "uploads"),
                    "BROWSER_PROFILE": str(root / "browser"),
                    "SESSION_COOKIE_SECURE": "false",
                    "PORT": str(port),
                }
            )
            proc = subprocess.Popen(
                [sys.executable, "-m", "playauto.web.app"],
                cwd=ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                deadline = time.monotonic() + 15
                connected = False
                while time.monotonic() < deadline:
                    if proc.poll() is not None:
                        break
                    try:
                        with socket.create_connection(
                            ("127.0.0.1", port), timeout=0.5
                        ):
                            connected = True
                            break
                    except OSError:
                        time.sleep(0.1)
                if not connected:
                    stdout, stderr = proc.communicate(timeout=5)
                    self.fail(
                        "web entrypoint did not listen; "
                        f"exit={proc.returncode}\n"
                        f"stdout={stdout}\nstderr={stderr}"
                    )
            finally:
                if proc.poll() is None:
                    proc.terminate()
                try:
                    proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.communicate()
