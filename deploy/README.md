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
install -d -o playauto -g playauto -m 0750 /opt/playauto/data
```

`data/`는 서비스 시작 전에 위 명령으로 만들어 두어야 한다. 유닛은
`ProtectSystem=strict`로 파일시스템을 읽기 전용으로 만들고
`ReadWritePaths=/opt/playauto/data`만 쓰기를 허용하기 때문이다.

배포 후 소유권을 다시 확인한다.

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

`--with-deps`는 apt로 시스템 라이브러리를 설치하므로 root가 필요하고,
브라우저 다운로드는 `playauto` 사용자의 홈에 해야 한다. 두 단계로 나눈다.

```bash
# 1) Chromium 실행에 필요한 시스템 라이브러리 (root)
sudo /opt/playauto/.venv/bin/playwright install-deps chromium

# 2) Chromium 브라우저 바이너리 (playauto 사용자 홈)
sudo -u playauto env HOME=/opt/playauto \
  /opt/playauto/.venv/bin/playwright install chromium
```

브라우저는 `/opt/playauto/.cache/ms-playwright`에 설치된다. 유닛의
`HOME=/opt/playauto`와 worker의 `PLAYWRIGHT_BROWSERS_PATH`가 이 경로를
가리킨다. 런타임에는 이 디렉터리를 읽기 전용으로 사용하며, Chromium의 임시
파일은 `PrivateTmp`가 제공하는 전용 `/tmp`에 쓴다.

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

`SESSION_COOKIE_SECURE` 값은 접속 방식에 맞춰야 한다.

- **로컬/루프백 스모크(`:80`, 127.0.0.1 전용)**: 브라우저가 Secure 쿠키를
  평문 HTTP에서 저장하지 않으므로 임시로 `SESSION_COOKIE_SECURE=false`를
  쓴다. 스모크가 끝나면 즉시 되돌린다.
- **운영(도메인/HTTPS)**: `SESSION_COOKIE_SECURE=true`가 필수다.

평문 HTTP를 공인 인터넷에 노출한 상태에서 `SESSION_COOKIE_SECURE=true`를
권장하지 않는다. 로그인이 되지 않을 뿐 아니라, 우회를 위해 `false`로 두면
세션 쿠키가 암호화되지 않은 채 전송된다. 운영은 반드시 도메인/HTTPS를 쓴다.

## 7. systemd 등록

```bash
cp /opt/playauto/deploy/playauto-web.service /etc/systemd/system/
cp /opt/playauto/deploy/playauto-worker.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now playauto-web
systemctl enable --now playauto-worker
systemctl status playauto-web playauto-worker
```

유닛은 `NoNewPrivileges=true`, `PrivateTmp=true`, `ProtectSystem=strict`,
`ReadWritePaths=/opt/playauto/data`로 최소 권한을 적용한다. 따라서 코드,
가상환경, 브라우저 캐시는 읽기 전용이고, 런타임 쓰기는 `data/` 아래
(DB/WAL, reference, exports, uploads, browser-profile)로만 제한된다. 새 쓰기
경로가 필요하면 유닛의 `ReadWritePaths`를 갱신해야 한다.

## 8. Caddy 리버스 프록시

`deploy/Caddyfile`에는 두 가지 예시가 있다.

- `:80` 블록: **127.0.0.1에만 바인딩되는 로컬 스모크 테스트 전용** 평문
  HTTP. LAN/공인 인터넷에 노출되지 않는다.
- `{$PLAYAUTO_DOMAIN}` 블록(주석): Caddy가 직접 TLS를 종료하는 운영 예시.

이 저장소의 실제 배포는 **Synology NAS가 TLS를 종료하고, LXC의 Caddy는
HTTP만 처리**한다. Synology 역방향 프록시의 원본은 `HTTPS` /
`mall.ds307.duckdns.org` / `443`, 대상은 `HTTP` / `192.168.0.212` / `80`이다.
Caddy는 Synology IP만 허용해 LXC의 80 포트가 LAN에 직접 노출되지 않게 한다.

```caddyfile
:80 {
    log
    @synology remote_ip 192.168.0.202
    handle @synology {
        reverse_proxy 127.0.0.1:8000
    }
    handle {
        respond "Forbidden" 403
    }
}
```

```bash
caddy fmt --overwrite /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile
systemctl restart caddy
```

Synology에서 HSTS를 켜고, 필요하면 `Upgrade`/`Connection` 헤더를 전달한다.
Caddy의 `respond 403`를 unconditional로 먼저 두면 directive order 때문에
프록시가 막힐 수 있으므로 반드시 `handle` 블록으로 분기한다.

## 9. 접속과 로그인 확인

- 운영: `https://mall.ds307.duckdns.org/`
- LXC 내부: `http://127.0.0.1:8000/` (Caddy allowlist를 우회한 앱 직접 확인;
  `SESSION_COOKIE_SECURE=true`에서는 로그인 세션은 HTTPS에서만 유지)
- `https://mall.ds307.duckdns.org/`는 로그인 전 `302 /login?next=/`가 정상
- 관리자 비밀번호로 로그인되는지 확인
- 상품 등록, 크롤 job 생성, export 다운로드까지 한 번 점검
- HTTPS 로그인 응답의 `Set-Cookie`에 `Secure; HttpOnly; SameSite=Lax`가 있어야 한다.

## 10. 백업과 복구

SQLite는 WAL 모드이므로 서비스가 쓰는 중에 파일을 그대로 복사하면 깨질 수
있다. 아래처럼 `.backup`을 사용하거나, worker를 잠시 멈추고 복사한다.
`/var/backups/playauto`는 root 소유로 만들고 백업 파일도 root가 기록한다.

```bash
sudo install -d -o root -g root -m 0750 /var/backups/playauto
# 안전한 온라인 백업 (권장)
sudo sqlite3 /opt/playauto/data/playauto.db \
  ".backup '/var/backups/playauto/playauto-$(date +%F).db'"
# 기준 엑셀도 별도 경로에 함께 보관
sudo cp /opt/playauto/data/reference/current.xlsx /var/backups/playauto/
```

일 1회 cron/systemd timer로 위 백업을 실행한다. export 임시 파일은 백업하지
않는다(DB에서 다시 만들 수 있다).

기준 엑셀 업로드는 임시 파일 저장 후 `os.replace`로 원자적 교체를 하므로,
복사 도중 파일이 바뀌는 경쟁은 완전히 없앨 수는 없지만 교체 순간의 반쪽
파일이 남지는 않는다. 정합성이 중요하면 worker를 잠시 멈추고 백업한다.

복구는 서비스를 멈추고 백업 파일을 되돌린 뒤 다시 시작한다.

```bash
systemctl stop playauto-worker playauto-web
sudo cp /var/backups/playauto/playauto-YYYY-MM-DD.db \
  /opt/playauto/data/playauto.db
# WAL/SHM 잔여 파일이 있으면 함께 제거한다
sudo rm -f /opt/playauto/data/playauto.db-wal /opt/playauto/data/playauto.db-shm
sudo chown playauto:playauto /opt/playauto/data/playauto.db
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

## 13. Gmarket 차단 시

검색 job이 `failed`로 끝나고 `Gmarket이 자동 요청을 차단했습니다` 메시지가
보이면 Cloudflare 확인 페이지가 반환된 것이다. CAPTCHA를 우회하거나
프록시를 추가하지 말고, Gmarket에서 내려받은 크롤 xlsx를 `/imports`의
xlsx 업로드로 넣는다. 차단은 LXC의 공인 IP나 일시적인 요청 패턴에 따라
발생할 수 있으므로 잠시 후 검색을 다시 시도할 수 있다.
