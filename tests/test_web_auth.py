import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlencode

from werkzeug.security import generate_password_hash

from playauto.web.app import create_app


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret",
                "ADMIN_PASSWORD_HASH": generate_password_hash("secret"),
                "DATABASE": str(Path(self.tmp.name) / "test.db"),
                "REFERENCE_PATH": str(Path(self.tmp.name) / "current.xlsx"),
                "EXPORT_ROOT": str(Path(self.tmp.name) / "exports"),
                "UPLOAD_ROOT": str(Path(self.tmp.name) / "uploads"),
                "BROWSER_PROFILE": str(Path(self.tmp.name) / "browser"),
                "EXPORT_TTL_HOURS": 24,
            }
        )
        self.client = self.app.test_client()

    def test_login_required_redirects(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_login_success(self):
        self.client.get("/login")
        with self.client.session_transaction() as session:
            token = session["_csrf_token"]
        response = self.client.post(
            "/login",
            data={"password": "secret", "csrf_token": token},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_login_failure(self):
        self.client.get("/login")
        with self.client.session_transaction() as session:
            token = session["_csrf_token"]
        response = self.client.post(
            "/login",
            data={"password": "wrong", "csrf_token": token},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("비밀번호", response.get_data(as_text=True))

    def test_post_without_csrf_rejected(self):
        response = self.client.post("/login", data={"password": "secret"})
        self.assertEqual(response.status_code, 400)

    def test_logout_clears_session(self):
        self.client.get("/login")
        with self.client.session_transaction() as session:
            token = session["_csrf_token"]
        self.client.post(
            "/login", data={"password": "secret", "csrf_token": token}
        )
        with self.client.session_transaction() as session:
            token = session["_csrf_token"]
        response = self.client.post(
            "/logout", data={"csrf_token": token}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get("/").status_code, 302)

    def test_login_failure_rate_limit(self):
        for _ in range(5):
            self.client.get("/login")
            with self.client.session_transaction() as session:
                token = session["_csrf_token"]
            response = self.client.post(
                "/login",
                data={"password": "wrong", "csrf_token": token},
            )
            self.assertEqual(response.status_code, 200)
        self.client.get("/login")
        with self.client.session_transaction() as session:
            token = session["_csrf_token"]
        response = self.client.post(
            "/login", data={"password": "wrong", "csrf_token": token}
        )
        self.assertEqual(response.status_code, 429)

    def test_login_next_rejects_unsafe_targets(self):
        unsafe_targets = [
            "/%09/evil.com",
            "//evil.com",
            "/\t/evil.com",
            "/\n/evil.com",
            "/\r/evil.com",
            "/\\evil.com",
            "https://evil.com",
        ]
        for target in unsafe_targets:
            self.client.get("/login")
            with self.client.session_transaction() as session:
                token = session["_csrf_token"]
            body = urlencode(
                {"password": "secret", "csrf_token": token, "next": target}
            )
            response = self.client.post(
                "/login",
                data=body,
                content_type="application/x-www-form-urlencoded",
            )
            self.assertEqual(response.status_code, 302, target)
            self.assertEqual(response.headers["Location"], "/", target)
