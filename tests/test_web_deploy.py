import unittest
from pathlib import Path


class DeploymentFilesTests(unittest.TestCase):
    def test_requirements_has_web_dependencies(self):
        text = Path("requirements-web.txt").read_text(encoding="utf-8")
        for name in ("Flask", "gunicorn", "playwright"):
            self.assertIn(name, text)

    def test_units_point_to_app_and_worker(self):
        web = Path("deploy/playauto-web.service").read_text(encoding="utf-8")
        worker = Path("deploy/playauto-worker.service").read_text(
            encoding="utf-8"
        )
        self.assertIn("playauto.web.app:create_app()", web)
        self.assertIn("playauto.web.worker", worker)

    def test_units_have_expected_runtime_identity(self):
        web = Path("deploy/playauto-web.service").read_text(encoding="utf-8")
        worker = Path("deploy/playauto-worker.service").read_text(
            encoding="utf-8"
        )
        for text in (web, worker):
            self.assertIn("User=playauto", text)
            self.assertIn("WorkingDirectory=/opt/playauto", text)
            self.assertIn("EnvironmentFile=/etc/playauto.env", text)
        self.assertIn("--bind 127.0.0.1:8000", web)
        self.assertIn("playauto-web.service", worker.split("[Service]")[0])

    def test_caddyfile_proxies_to_flask(self):
        text = Path("deploy/Caddyfile").read_text(encoding="utf-8")
        self.assertIn("reverse_proxy 127.0.0.1:8000", text)

    def test_lxc_readme_has_required_steps(self):
        text = Path("deploy/README.md").read_text(encoding="utf-8")
        self.assertIn("systemctl enable --now playauto-web", text)
        self.assertIn("sqlite3", text)


class DeploymentSecurityTests(unittest.TestCase):
    def test_caddyfile_smoke_listener_is_loopback_only(self):
        text = Path("deploy/Caddyfile").read_text(encoding="utf-8")
        self.assertIn("bind 127.0.0.1", text)

    def test_caddyfile_has_production_https_example(self):
        text = Path("deploy/Caddyfile").read_text(encoding="utf-8")
        self.assertIn("{$PLAYAUTO_DOMAIN}", text)
        self.assertIn("자동 HTTPS", text)

    def test_readme_requires_https_in_production(self):
        text = Path("deploy/README.md").read_text(encoding="utf-8")
        self.assertIn("도메인", text)
        self.assertIn("HTTPS", text)
        self.assertIn(":80", text)
        self.assertIn("로컬", text)

    def test_units_confine_writes_to_data_directory(self):
        for name in ("playauto-web.service", "playauto-worker.service"):
            text = Path("deploy", name).read_text(encoding="utf-8")
            self.assertIn("NoNewPrivileges=true", text)
            self.assertIn("PrivateTmp=true", text)
            self.assertIn("ProtectSystem=strict", text)
            self.assertIn("ReadWritePaths=/opt/playauto/data", text)
            self.assertIn("Environment=HOME=/opt/playauto", text)
            self.assertNotIn("ProtectHome=true", text)

    def test_readme_installs_browser_with_split_commands(self):
        text = Path("deploy/README.md").read_text(encoding="utf-8")
        self.assertIn(
            "sudo /opt/playauto/.venv/bin/playwright install-deps chromium",
            text,
        )
        self.assertIn(
            "sudo -u playauto env HOME=/opt/playauto",
            text,
        )
        self.assertIn(
            "playwright install chromium",
            text,
        )
        self.assertIn("/opt/playauto/.cache/ms-playwright", text)

    def test_readme_explains_secure_cookie_with_https(self):
        text = Path("deploy/README.md").read_text(encoding="utf-8")
        self.assertIn("SESSION_COOKIE_SECURE=true", text)
        self.assertIn("SESSION_COOKIE_SECURE=false", text)
        self.assertIn("평문 HTTP", text)


if __name__ == "__main__":
    unittest.main()
