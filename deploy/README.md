# Playauto 웹 관리자 LXC 배포 절차

Ubuntu 24.04 LXC 컨테이너에 Flask 웹(`playauto-web`)과 크롤 worker
(`playauto-worker`)를 systemd로 상시 구동하고, Caddy를 앞단에 두는 절차다.

## 1. LXC 생성

- Ubuntu 24.04, unprivileged 컨테이너
- 권장 사양: 4 vCPU / 8GB RAM / 40GB 디스크 (Chromium 크롤링 고려)
- 최소 사양: 2 vCPU / 4GB RAM

## 2. 패키지 설치

```bash
apt update
apt install -y python3.12-venv sqlite3 caddy
```

## 3. 사용자와 코드 배치

`playauto` 사용자를 만들고 코드를 `/opt/playauto`에 둔다. 서비스는 이 사용자로
실행되므로 `.venv`와 `data/`는 반드시 `playauto` 소유여야 한다.

```bash
adduser --system --group --home /opt/playauto playauto
mkdir -p /opt/playauto
# git clone 또는 rsync로 코드를 /opt/playauto에 배치
chown -R playauto:playauto /opt/playauto
```

배포 후 `.venv`와 `data/` 소유권을 다시 확인한다.

```bash
chown -R playauto:playauto /opt/playauto/.venv /opt/playauto/data
```

## 4. Python 가상환경과 의존성

```bash
cd /opt/playauto
sudo -u playauto python3.12 -m venv .venv
sudo -u playauto .venv/bin/pip install --upgrade pip
sudo -u playauto .venv/bin/pip install -r requirements-web.txt
```

`openpyxl` 등 기존 라이브러리는 `vendor/`를 그대로 사용하므로
`PYTHONPATH`에 `/opt/playauto:/opt/playauto/vendor`를 넣는다(systemd 유닛에
설정되어 있음).

## 5. Chromium 설치

```bash
cd /opt/playauto
sudo -u playauto .venv/bin/playwright install --with-deps chromium
```

`--with-deps`는 Chromium 실행에 필요한 시스템 라이브러리를 함께 설치한다.
브라우저 캐시는 `playauto` 사용자의 홈(`/opt/playauto/.cache`)에 생성되므로
systemd 유닛은 `/home`을 숨기지 않는다.

## 6. 환경변수 파일

`/etc/playauto.env`에 비밀값을 둔다. 이 파일은 저장소에 커밋하지 않는다.
권한은 `playauto`만 읽을 수 있게 제한한다.

```bash
cat >/etc/playauto.env <<'EOF'
SECRET_KEY=<무작위_긴_문자열>
ADMIN_PASSWORD_HASH=<Werkzeug_해시>
SESSION_COOKIE_SECURE=true
EOF
chown root:playauto /etc/playauto.env
chmod 640 /etc/playauto.env
```

- `SECRET_KEY`: `python -c "import secrets; print(secrets.token_urlsafe(48))"`
- `ADMIN_PASSWORD_HASH`: `python -c "from werkzeug.security import generate_password_hash as g; print(g('비밀번호'))"`
- `SESSION_COOKIE_SECURE=true`는 **HTTPS로 서비스할 때만** 사용한다.
  평문 HTTP로 접속하면 브라우저가 Secure 쿠키를 저장하지 않아 로그인이
  되지 않는다. 로컬 평문 스모크에서는 잠시 `false`로 두고, 운영 HTTPS로
  전환한 뒤 반드시 `true`로 되돌린다.

## 7. systemd 등록

```bash
cp /opt/playauto/deploy/playauto-web.service /etc/systemd/system/
cp /opt/playauto/deploy/playauto-worker.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now playauto-web
systemctl enable --now playauto-worker
systemctl status playauto-web playauto-worker
```

유닛은 `NoNewPrivileges=true`, `PrivateTmp=true`, `ProtectSystem=full`,
`ReadWritePaths=/opt/playauto/data`로 최소 권한을 적용한다. 따라서 DB,
export, 업로드, browser-profile 같은 쓰기는 `data/` 아래에서만 가능하다.
새 쓰기 경로가 필요하면 유닛의 `ReadWritePaths`를 갱신한다.

## 8. Caddy 리버스 프록시

`deploy/Caddyfile`에는 두 가지 예시가 있다.

- `:80` 블록: **로컬/LAN 스모크 테스트 전용** 평문 HTTP. 공인 인터넷에
  노출하지 않는다.
- `example.com` 블록(주석): 운영용. 도메인을 연결하면 Caddy가 자동 HTTPS
  인증서를 발급한다.

운영에서는 도메인/HTTPS 구성이 필수다. 스펙은 암호화되지 않은 공개 노출을
금지한다. 도메인이 없으면 LAN 또는 Tailscale 인터페이스에만 바인딩한다.

```bash
# 예: /etc/caddy/Caddyfile 에 deploy/Caddyfile 내용을 반영
caddy validate --config /etc/caddy/Caddyfile
systemctl reload caddy
```

## 9. 접속과 로그인 확인

- `https://<도메인>/` (운영) 또는 `http://<LXC-IP>/` (로컬 스모크)
- 관리자 비밀번호로 로그인되는지 확인
- 상품 등록, 크롤 job 생성, export 다운로드까지 한 번 점검

## 10. 백업과 복구

SQLite는 WAL 모드이므로 서비스가 쓰는 중에 파일을 그대로 복사하면 깨질 수
있다. 아래처럼 `.backup`을 사용하거나, worker를 잠시 멈추고 복사한다.

```bash
mkdir -p /var/backups/playauto
# 안전한 온라인 백업 (권장)
sqlite3 /opt/playauto/data/playauto.db \
  ".backup '/var/backups/playauto/playauto-$(date +%F).db'"
# 기준 엑셀도 별도 경로에 함께 보관
cp /opt/playauto/data/reference/current.xlsx /var/backups/playauto/
```

일 1회 cron/systemd timer로 위 백업을 실행한다. export 임시 파일은 백업하지
않는다(DB에서 다시 만들 수 있다).

복구는 서비스를 멈추고 백업 파일을 되돌린 뒤 다시 시작한다.

```bash
systemctl stop playauto-worker playauto-web
cp /var/backups/playauto/playauto-YYYY-MM-DD.db \
  /opt/playauto/data/playauto.db
# WAL/SHM 잔여 파일이 있으면 함께 제거한다
rm -f /opt/playauto/data/playauto.db-wal /opt/playauto/data/playauto.db-shm
chown playauto:playauto /opt/playauto/data/playauto.db
systemctl start playauto-web playauto-worker
```

## 11. export 정리

worker가 시작할 때와 1시간마다 `data/exports/`에서 24시간 지난 디렉터리를
삭제한다. 보관 기간은 `/settings`의 `EXPORT_TTL_HOURS` 설정을 따른다.
별도 cron은 필요 없다.

## 12. 로그와 장애 확인

두 서비스 모두 journald로 기록된다.

```bash
journalctl -u playauto-web -u playauto-worker -n 200 --no-pager
journalctl -u playauto-worker -f
```

- 웹 접근/오류: `journalctl -u playauto-web`
- 크롤/정리 작업: `journalctl -u playauto-worker`
- Caddy: `journalctl -u caddy`

journald 기본 보관 정책을 쓰며, 디스크 사용량은
`journalctl --disk-usage`로 확인한다. 보관 기간이 필요하면
`/etc/systemd/journald.conf`의 `MaxRetentionSec`/`SystemMaxUse`를 조정하고
`systemctl restart systemd-journald`로 적용한다.
