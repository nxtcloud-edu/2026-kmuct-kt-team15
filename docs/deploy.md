# 배포: EC2 1대 + S3, GitHub Actions

`main`에 push하면 `.github/workflows/deploy.yml`이 pytest → tarball → EC2로 scp → `scripts/deploy.sh` → smoke test를 돈다.
한 프로세스(uvicorn)가 한 포트로 화면·`/api`·`/admin`을 서빙하고(SPEC 4절), 비밀 파일(`.env`, `kmu.db`)은 git이 아니라 S3에 둔다. RDS는 쓰지 않는다(맨 아래).

```
GitHub Actions ──scp/ssh(22)──▶ EC2 us-east-1 (AL2023, t3.small, 35.172.129.104)
                                   systemd uniq.service → uvicorn app.main:app --port 8000 --workers 1
                                   /opt/uniq/.env, /opt/uniq/data/kmu.db   ◀── S3 (인스턴스 롤로 읽음)
                                   cron 10분 → scripts/backup.sh → S3 backup/
브라우저 ──HTTP:8000──▶ http://35.172.129.104:8000/
S3 kmuct-ht-15-uniq (비공개, 버저닝): secrets/.env, db/kmu.db, release/uniq-<sha>.tar.gz, backup/
```

## 만들어 둔 것 (2026-09-20, 계정 730335373015, 사용자 kmuct-ht-15)

| 리소스 | 값 |
|---|---|
| EC2 | `i-00b7c5c11ac280ad5`, t3.small, AMI `ami-0190258a3c1abc699` (nxtcloud-ami-v1.0.2, Amazon Linux 2023, `ec2-user`, Python 3.12), 퍼블릭 IP `35.172.129.104`, 인스턴스 프로파일 `SafeInstanceProfile-kmuct-ht-15` |
| 보안 그룹 | `sg-0ee4abe5a3cdd28df` (`kmuct-ht-15-uniq`): 인바운드 8000, 22 ← 0.0.0.0/0 |
| 키페어 | `kmuct-ht-15-uniq` (AWS 생성본은 CloudShell `~/kmuct-ht-15-uniq.pem`). CI용 ed25519 공개키를 인스턴스 `authorized_keys`에 추가함 |
| S3 | `kmuct-ht-15-uniq`, us-east-1, 퍼블릭 차단, 버저닝 |
| GitHub Secrets | `EC2_HOST`=35.172.129.104, `EC2_SSH_KEY`=CI용 개인키. **AWS 키는 넣지 않는다** (인스턴스 롤이 S3를 담당) |

## 이 계정의 제약 (확인한 것)

| 제약 | 결과 |
|---|---|
| `RestrictRegionVirginia` | **us-east-1만** 허용. 서울 불가 |
| `DenyUnapprovedAMI` | Name 태그 `nxtcloud-ami-v*`인 AMI만. Ubuntu 공식 AMI 불가 → AL2023 |
| `RequireOwnInstanceProfile` | `SafeInstanceProfile-<사용자명>`을 붙여야 `RunInstances` 허용 |
| 인스턴스 타입 | t3.micro, t3.small 허용. t3.medium 거부 |
| `ec2:AllocateAddress` 거부 | **Elastic IP 없음.** 인스턴스를 stop하면 IP가 바뀐다 → **stop 금지, 재부팅만.** 바뀌면 `EC2_HOST` 시크릿과 발표 자료 URL을 갱신 |
| 보안 그룹 80 포트 거부 | 22, 8000은 허용 → 서비스 포트 **8000** |
| `ec2:ImportKeyPair` 거부 | 키페어는 AWS가 만든 것만. CI 키는 `authorized_keys`에 직접 추가 |
| `ssm:GetParameter`, IAM 쓰기, IAM 정책 읽기 거부 | 롤 권한은 인스턴스에서 직접 확인함: 팀 버킷 읽기·쓰기·삭제 가능 |
| AMI에 code-server(9080) 포함 | 보안 그룹에서 열지 않는다 |
| 학교망 아웃바운드 22 차단 | 교내에서는 EC2에 SSH 불가. CloudShell(콘솔 하단)에서 `ssh -i ~/kmuct-ht-15-uniq.pem ec2-user@35.172.129.104` |

## 당일 순서

1. **DB 올리기** (노트북, 1회): `aws s3 cp data/kmu.db s3://kmuct-ht-15-uniq/db/kmu.db`. 시연용 사본이면 그 파일을 `db/kmu.db` 이름으로. 서버에 이미 DB가 있으면 배포는 덮어쓰지 않는다 → 새 DB로 갈아끼우려면 CloudShell → ssh → `sudo FORCE_DB=1 S3_BUCKET=kmuct-ht-15-uniq bash /opt/uniq/scripts/deploy.sh`
2. **`.env` 올리기** (llm-x 키가 생기면): `aws s3 cp .env s3://kmuct-ht-15-uniq/secrets/.env` 후 배포 한 번(Actions → Deploy → Run workflow). `.env`는 배포마다 S3에서 새로 받는다. `DB_PATH`는 스크립트가 절대경로로 고친다
3. **코드**: `main`에 push. Actions 탭에서 초록불 확인 → `http://35.172.129.104:8000/`
4. **롤백**: 이전 커밋을 `main`에 push하거나, CloudShell → ssh → `aws s3 cp s3://kmuct-ht-15-uniq/release/uniq-<sha>.tar.gz /tmp/u.tar.gz && sudo CODE_TAR=/tmp/u.tar.gz S3_BUCKET=kmuct-ht-15-uniq bash /opt/uniq/scripts/deploy.sh`

## 서버에서 보는 법 (CloudShell → ssh)

```bash
sudo systemctl status uniq         # 상태
journalctl -u uniq -f              # 로그
curl -s localhost:8000/api/config  # 헬스체크
crontab -l                         # 백업 cron (deploy.sh가 넣는다)
```

## 사고 대응

| 증상 | 조치 |
|---|---|
| Actions 배포 실패 (ssh timeout) | 인스턴스 IP 변경 여부 확인 → `EC2_HOST` 갱신. 보안 그룹 22 확인 |
| 인스턴스가 죽음 | 콘솔에서 **재부팅**(stop 아님). 서비스는 enable돼 있어 자동으로 뜬다 |
| DB 유실·오염 | ssh → `aws s3 cp s3://kmuct-ht-15-uniq/backup/latest.db /opt/uniq/data/kmu.db && sudo systemctl restart uniq` |
| 대화 탭만 안 됨 | llm-x 문제. 목록·상세·판정·계획은 LLM 없이 돈다. `.env` 값 확인 후 S3에 다시 올리고 재배포 |
| 8000이 안 열림 | `sudo ss -ltnp | grep 8000`, `journalctl -u uniq -n 50` |

## 쓰지 않는 것과 이유

- **RDS**: EC2 1대·카드 148건·심사위원 수십 명에 SQLite 파일 하나면 충분하다. 옮기면 SQL 48곳 수정, psycopg 추가(SPEC 3절 밖), `kmu.db`를 그대로 가져가는 전략이 깨진다. 옮길 지점은 `app/db.py`의 `connect()` 하나다.
- **nginx / Docker / HTTPS**: 도메인이 없고 80·443도 못 연다. spec이 HTTP를 전제로 설계됐다(`crypto.randomUUID()` 안 씀).
- **S3 정적 호스팅으로 화면 분리**: SPEC 4절 "한 프로세스 한 포트, `/api` 상대 경로"에 어긋난다.
- **uvicorn 워커 2개 이상**: SQLite에 쓰기가 있으므로 1개.
- **CI에 AWS 액세스 키**: 인스턴스 롤이 S3를 읽고 쓰므로 필요 없다. 시크릿은 SSH 키와 IP 둘뿐이다.
