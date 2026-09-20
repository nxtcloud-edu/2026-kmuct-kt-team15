# UniQ — 국민대 공지 에이전트

2026년 국민대학교 캠퍼스타운 키로톤 15팀 국민대경정.

흩어진 학교 공지 중에서 **내 조건으로 지금 지원할 수 있는 것만** 근거와 함께 보여주는 웹 서비스다.
화면에 보이는 서비스 이름은 UniQ다.

## 문제

국민대 공지는 게시판 30곳에 흩어져 있다(2026-02-01 ~ 04-30 기준 939건, 첨부 224개).
자격 조건은 공지마다 다르고 본문·이미지·첨부에 섞여 있다.

- 학년·학적 조건 44%, 소속 조건 33%, 배제·중복 조건 26%, 제출 서류 25%, 성적 조건 23%, 소득 조건 3%
- 55%는 이 조건 중 하나 이상이 있고, 22%는 세 개 이상이다.
- 본문도 첨부도 없는 공지가 254건(27%)이다. 내용이 이미지에만 있다.

학생은 공지를 찾고, 자격을 따지고, 마감을 챙기는 일을 혼자 한다.

## 하는 일

- 공지를 네 묶음으로 나눈다: **지원할 수 있는 공지 / 정보를 더 입력하면 판단할 수 있는 공지 / 아직 확인 중인 공지 / 조건이 안 맞는 공지**.
- 조건마다 칩 하나로 통과·비통과·정보 부족을 보여주고, 원문 시트에서 그 조건을 찾은 문장을 그대로 강조해 보여준다.
- 모자란 정보는 되묻는다. 홈에서는 가장 많은 공지를 한 번에 정리하는 질문 하나를, 상세에서는 그 공지에 필요한 질문을 묻는다.
- 유학생은 온보딩에서 신분을 고르면 유학생 기준으로 판정한다.
- 계획에 넣으면 준비할 일을 주·월 달력과 신청 기간 막대로 보여준다.
- 대화 탭의 질의 에이전트가 공지 카드와 판정 엔진을 조회해 답하고, 참고한 공지를 함께 보여준다.

**자격 판정에는 LLM을 쓰지 않는다.** 판정은 `app/judge.py`의 순수 함수이고, 같은 입력이면 늘 같은 결과가 나온다.

## 세 등급 — 무엇이 실시간이고 무엇이 미리 만든 데이터인가

| 등급 | 뜻 | 모듈 | 파일 |
|---|---|---|---|
| 1. 실시간 | 배포된 서버에서 실제로 동작한다 | `judge`, `student`, `web`, `chat` | `app/judge.py`, `app/main.py`, `static/index.html`, `app/chat.py`, `app/llm.py` |
| 2. 레포 전용 | 코드는 이 레포에 있고, **데모에서는 돌리지 않는다** | `admin`, `interpret`, `collector` | `app/admin.py`, `static/admin.html`, `app/interpret.py`, `app/collector.py` |
| 3. 사전 데이터 | 준비 단계에서 Claude Code로 미리 만들어 `kmu.db`로 가져간다 | `data` | `app/db.py`, `data/kmu.db` |

- **공지 수집과 해석은 실시간으로 돌지 않는다. 사전 처리다.** 공지 카드(조건, 요약, 원문 저장본, 할 일)는 준비 단계에서 만들어 `kmu.db`에 넣어 두고, 서버는 그 DB를 읽기만 한다.
- 2등급 코드(`interpret`, `collector`)는 3등급 데이터와 **같은 형식**을 쓴다. 이 에이전트가 만드는 형식 그대로 데이터를 미리 채운 것이다.
- LLM(llm-x)은 **대화 탭에서만** 부른다. 키를 비워 서버를 띄워도 목록·상세·판정·계획·되묻기는 모두 동작하고, 대화 탭만 "잠시 후 다시 물어봐 주세요" 안내를 띄운다.
- 날짜 계산의 "오늘"은 `DEMO_TODAY`(데모 기준일 2026-03-16)다. 실제 시각이 아니다.

## 데이터는 git에 없다

- **`kmu.db`(미리 만든 DB)와 크롤 데이터(`data/`)는 이 레포에 없다.** `.gitignore`가 막는다. 서버에는 git이 아니라 따로 올린다.
- `.env`도 커밋하지 않는다. 키 이름만 적은 `.env.example`이 대신 들어 있다.
- 실명과 학번은 받지 않는다. 학생 id는 서버가 발급하는 익명 id이고 브라우저의 localStorage에만 둔다.

## 실행

```bash
# 설치 (Windows는 .venv\Scripts\activate)
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# DB (data/는 레포에 없으므로 따로 받아 둔다)
python -m app.db init                                 # 빈 스키마를 DB_PATH에 만든다. 있는 테이블은 건드리지 않는다
python -m app.db load data/notices/_all.json          # notice 테이블 적재 (이미 있는 key는 건너뜀)

# 실행
uvicorn app.main:app --reload --port 8000             # 개발
uvicorn app.main:app --host 0.0.0.0 --port "$PORT"    # 배포

# 테스트
pytest -q
```

화면, `/api`, `/admin`을 한 프로세스가 한 포트로 서빙한다. 화면은 `/api/...`를 상대 경로로 부른다.

2등급 명령은 **데모에서 돌리지 않는다.**

```bash
python -m app.interpret <notice_key>                  # 공지 1건 해석 → card, raw_source, review
python -m app.collector --once --dry-run              # 목록 1회 수집, DB에 쓰지 않고 출력
python -m app.collector --schedule 3600               # 주기 수집
```

### 환경 변수 (`.env`)

| 키 | 예 | 용도 |
|---|---|---|
| `DB_PATH` | `data/kmu.db` | |
| `DEMO_TODAY` | `2026-03-16` | 모든 날짜 계산의 "오늘" |
| `LLM_BASE_URL`, `LLM_API_KEY` | | llm-x 게이트웨이. 서버에만 두고 브라우저로 내보내지 않는다 |
| `LLM_THINKING` | `0` | Qwen3 thinking 모드. 대화는 끈다 |
| `ADMIN_PASSWORD` | | `/admin` HTTP Basic 비밀번호 (2등급) |

## 구조

```
app/
  main.py        FastAPI 앱: 정적 파일, /api 라우트, chat·admin 라우터 연결
  db.py          스키마, 연결, init/load CLI
  judge.py       판정 엔진. 순수 함수만, DB와 LLM을 모른다
  chat.py        질의 에이전트 라우터 (/api/chat NDJSON 스트림)
  llm.py         llm-x 클라이언트
  admin.py       /admin 검토 대기열 (2등급)
  interpret.py   공지 해석 에이전트 (2등급)
  collector.py   수집기, 스케줄러, 공지 연결 (2등급)
static/
  index.html     학생 화면 한 파일
  admin.html     운영자 화면 (2등급)
tests/           pytest
docs/
  ui-spec.md     화면 명세, ui-screens/ 스크린샷 28장, assets/ 로고
SPEC.md          무엇을 만드는지. 스키마, API 계약, 모듈별 요구사항, 경계
tasks/todo.md    작업 목록
data/            git에 없다 (kmu.db, 크롤 데이터)
```

만드는 방법은 `SPEC.md`에, 작업 단위와 결과는 `tasks/todo.md`에 있다.
