# Spec: 국민대 공지 에이전트

2026-09-19 · 입력: `docs/decisions.md`, 상민의 UI 시안(원본 `UI (2).html`, 9/19 밤 최종. 당일에는 HTML을 가져갈 수 없어 `docs/ui-spec.md`로 글로 옮겼다), 아키텍처 그림 4장(`firebim/kirothon` 레포의 `docs/diagrams/`), 같은 레포의 `core/llm.py`.
오늘 리허설과 9/20 당일 모두 이 문서로 만든다. "초안"이라고 적힌 곳은 아직 확정되지 않았다.
9/19 밤에 UI 시안이 `UI (1)`에서 `UI (2)`로 바뀌었다. 바뀐 점과 그에 따라 고친 곳은 13절에 있다.

## 1. 목표

**문제.** 국민대 공지는 30개 게시판에 흩어져 있다(2026-02-01 ~ 04-30, 939건, 첨부 224개). 자격 조건은 공지마다 다르고 본문, 이미지, 첨부에 섞여 있다.
- 학년·학적 조건 44%, 소속 조건 33%, 배제·중복 조건 26%, 제출 서류 25%, 성적 조건 23%, 소득 조건 3%
- 55%는 위 조건 중 하나 이상이 있다. 22%는 세 개 이상이다.
- 본문도 첨부도 없는 공지가 254건(27%)이다. 내용이 이미지에만 있다.

학생은 공지를 찾고, 자격을 따지고, 마감을 챙기는 일을 혼자 한다.

**사용자.** 국민대 학부생(내국인과 외국인 유학생). 데모에서는 심사위원과 참여자가 로그인 없이 브라우저로 직접 쓴다.

**만드는 것.** 학생 정보를 넣으면 지금 모집 중인 공지 중 지원할 수 있는 것을 조건별 근거와 함께 보여주는 웹 서비스다. 화면에 보이는 서비스 이름은 UniQ다(UI 시안).
- 공지를 네 묶음으로 나눈다: 지원할 수 있는 공지, 정보를 더 입력하면 판단할 수 있는 공지, 아직 확인 중인 공지, 조건이 안 맞는 공지.
- 모자란 정보는 되묻는다. 홈에서는 가장 많은 공지를 정리하는 질문 하나를, 상세에서는 그 공지에 필요한 질문을 묻는다.
- 유학생은 온보딩에서 신분을 고르면 유학생 기준으로 판정한다.
- 계획에 넣으면 준비할 일을 날짜별로 보여준다.
- 대화 탭의 질의 에이전트가 공지 카드와 판정 엔진을 조회해 답한다.

**발표.** 총 7분이고 그중 시연은 2분 안팎이다. 심사는 문제 정의(숫자 근거)와 에이전트 설계를 가장 크게 본다. 동작 완성도는 가산점이다.

### 세 등급

| 등급 | 뜻 | 모듈 |
|---|---|---|
| 1. 실시간 | 배포 URL에서 실제로 동작한다. 당일 먼저 만든다 | `judge`, `student`, `web`, `chat` |
| 2. 레포 전용 | 코드는 제출 레포에 있고, 데모에서는 돌리지 않는다. 당일 마지막에 만든다 | `admin`, `interpret`, `collector` |
| 3. 사전 데이터 | 준비 단계에서 Claude Code로 만들어 `kmu.db`로 가져간다 | `data` |

- LLM(llm-x)은 대화 탭에서만 부른다. 공지 해석 결과는 3등급 데이터로 미리 만든다.
- 2등급 코드는 3등급 데이터와 같은 형식을 쓴다. 발표에서는 "이 에이전트가 만드는 형식 그대로 데이터를 미리 채웠다"고 말한다.
- LLM이 멈춰도 목록, 상세, 판정, 계획은 동작한다. 멈추는 것은 대화 탭뿐이다.

## 2. 모듈 구성

| 모듈 id | 등급 | 책임 | 파일 | 의존 |
|---|---|---|---|---|
| `data` | 3 | DB 스키마, 적재, 사전 데이터 | `app/db.py`, `data/kmu.db` | — |
| `judge` | 1 | 판정 4상태, 부족분, 칩 문구, 되묻기, 가정 판정, 알림. LLM 0회 | `app/judge.py` | data |
| `student` | 1 | 익명 학생, 학생 정보, 목록·상세 API, 대안 추천, 계획·할 일, 새 공지 공개 | `app/main.py` | data, judge |
| `web` | 1 | UI 시안 이식, 되묻기 카드와 상세에서 바로 답하기, 원문 시트 | `static/index.html` | student (API 계약) |
| `chat` | 1 | 질의 에이전트, llm-x 클라이언트, 사용량 제한 | `app/chat.py`, `app/llm.py` | judge, student |
| `admin` | 2 | 검토 대기열 보정, 숨김, 재판정 | `app/admin.py`, `static/admin.html` | judge |
| `interpret` | 2 | 공지 해석 에이전트 | `app/interpret.py` | data, chat의 `llm.py` |
| `collector` | 2 | 수집기, 스케줄러, 공지 연결 | `app/collector.py`, `app/sites.json` | data, interpret |

**만드는 순서:** `data` 스키마 → `judge` 와 `web` 병렬 → `student` → `chat` → `admin`, `interpret`, `collector` 병렬.

- `web`은 7절 API 계약을 보고 시작한다. 처음에는 시안의 가짜 데이터를 그대로 둔 채 화면을 옮기고, API가 생기면 연결한다.
- `data`의 내용(카드, 원문 저장본)은 오늘 앱 개발과 따로 병렬로 만든다. 당일에는 만든 DB를 가져오므로 스키마만 코드로 다시 쓴다.

**설계만 두는 것(코드 없음):** 수집 설정 생성 에이전트, 성적 화면 읽기.

## 3. 기술 스택

- Python 3.12 (EC2 Ubuntu 24.04 기본 버전)
- FastAPI, uvicorn, httpx, python-dotenv
- DB는 stdlib `sqlite3`를 쓴다. ORM 없이 SQL을 직접 쓰고, WAL 모드로 연다.
- 테스트는 pytest다.
- 2등급 전용 의존성은 pypdf(첨부 PDF 변환) 하나다.
- 화면은 빌드 도구 없는 HTML 파일 하나(vanilla JS)다. `docs/ui-spec.md`(UI 명세)와 스크린샷 `docs/ui-screens/`, 로고 `docs/assets/`를 보고 만든다.
- `requirements.txt`에는 처음 설치할 때 받은 버전을 `==`로 고정한다.

## 4. 명령

```bash
# 설치 (Windows는 .venv\Scripts\activate)
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# DB
python -m app.db init                                 # 빈 스키마를 DB_PATH에 만든다. 있는 테이블은 건드리지 않는다
python -m app.db load data/notices/_all.json          # notice 테이블 적재 (이미 있는 key는 건너뜀)

# 실행
uvicorn app.main:app --reload --port 8000             # 개발
uvicorn app.main:app --host 0.0.0.0 --port "$PORT"    # EC2. systemd나 tmux로 띄워 둔다

# 테스트
pytest -q

# 2등급 (데모에서는 돌리지 않는다)
python -m app.interpret <notice_key>                  # 공지 1건 해석 → card, raw_source, review
python -m app.collector --once --dry-run              # 목록 1회 수집, DB에 쓰지 않고 출력
python -m app.collector --schedule 3600               # 주기 수집
```

**환경 변수** (`.env`, 커밋하지 않는다. 키 이름만 적은 `.env.example`은 커밋한다)

| 키 | 예 | 용도 |
|---|---|---|
| `DB_PATH` | `data/kmu.db` | |
| `DEMO_TODAY` | `2026-03-16` | 모든 날짜 계산의 "오늘". 3/16은 월요일 |
| `LLM_BASE_URL`, `LLM_API_KEY` | | llm-x 게이트웨이. 서버에만 둔다 |
| `LLM_THINKING` | `0` | Qwen3 thinking 모드. 대화는 끈다 |
| `ADMIN_PASSWORD` | | `/admin` HTTP Basic 비밀번호 (2등급) |

**배포 요구사항.** 배포 방식은 지호가 정한다. spec이 요구하는 것은 다음뿐이다.
- 한 프로세스가 한 포트로 화면, `/api`, `/admin`을 모두 서빙한다.
- 화면은 `/api/...`를 상대 경로로 부른다.
- `kmu.db`와 `.env`는 git이 아니라 S3(비공개)나 scp로 서버에 올린다.
- HTTPS 없이 열 수 있으므로 브라우저의 `crypto.randomUUID()`를 쓰지 않는다. 이 함수는 보안 연결에서만 동작한다. 학생 id는 서버가 발급한다.

## 5. 프로젝트 구조

```
app/
  main.py        FastAPI 앱: 정적 파일, /api 라우트, chat·admin 라우터 연결
  db.py          스키마, 연결, init/load CLI
  judge.py       판정 엔진. 순수 함수만, DB와 LLM을 모른다
  chat.py        질의 에이전트 라우터
  llm.py         llm-x 클라이언트
  admin.py       /admin 라우터 (2등급)
  interpret.py   공지 해석 에이전트 (2등급)
  collector.py   수집기, 스케줄러, 공지 연결 (2등급)
  sites.json     수집 대상 30곳 (2등급)
static/
  index.html     학생 화면 (UI 시안 이식)
  admin.html     운영자 화면 (2등급)
tests/
data/            gitignore. _all.json, image_text.json, kmu.db
docs/decisions.md
docs/ui-spec.md       UI 시안을 글로 옮긴 화면 명세. static/index.html은 이것으로 만든다
docs/ui-screens/      시안 화면 스크린샷 28장 (ui-spec.md가 번호로 가리킨다)
docs/assets/          로고 PNG 2개
docs/ui-mockup.html   상민의 시안 HTML 원본. 레포에만 있고 당일에는 없다. 만들 때 읽지 않는다
SPEC.md
tasks/               plan.md, todo.md
```

## 6. 데이터 (`data`)

당일 코드가 오늘 만든 `kmu.db`를 그대로 읽어야 한다. 그래서 아래 스키마는 글자 그대로 지킨다. 바꾸려면 먼저 물어본다.

`python -m app.db init`은 아래 SQL의 `CREATE TABLE`을 `CREATE TABLE IF NOT EXISTS`로 바꿔 실행한다(컬럼은 글자 그대로다). 있는 DB 파일이나 테이블을 지우거나 다시 만들지 않는다. 미리 만든 `kmu.db`가 `DB_PATH`에 있을 수 있기 때문이다.

### 6.1 스키마

```sql
PRAGMA journal_mode = WAL;

CREATE TABLE notice (             -- 수집한 공지 원본. _all.json 한 항목 = 한 행
  key          TEXT PRIMARY KEY,  -- "{source_id}:{notice_id}"
  source_id    TEXT NOT NULL,
  source_name  TEXT NOT NULL,
  url          TEXT NOT NULL,
  title        TEXT NOT NULL,
  posted_date  TEXT NOT NULL,     -- YYYY-MM-DD
  department   TEXT,
  body_text    TEXT NOT NULL DEFAULT '',
  attachments  TEXT NOT NULL DEFAULT '[]',  -- JSON [{"name", "url"}]
  body_hash    TEXT NOT NULL,     -- sha1(title + "\n" + body_text). 수정 감지용
  crawled_at   TEXT NOT NULL
);

CREATE TABLE card (               -- 공지 해석 결과. 기회성 공지만 카드가 있다
  notice_key     TEXT PRIMARY KEY REFERENCES notice(key),
  title          TEXT NOT NULL,
  sub            TEXT NOT NULL DEFAULT '',  -- 목록 부제. 예: "2학기 · 주 10시간 내외"
  dept           TEXT NOT NULL,             -- 표시용 부서명
  category       TEXT NOT NULL,             -- 6.3의 9종 중 하나
  apply_start    TEXT,                      -- YYYY-MM-DD
  apply_end      TEXT,                      -- YYYY-MM-DD. NULL이면 목록에 안 나온다
  conditions     TEXT NOT NULL DEFAULT '[]',-- JSON. 6.2 조건 스키마
  fields         TEXT NOT NULL DEFAULT '[]',-- JSON [["제출 서류", "..."], ...] 공지 요약
  trace          TEXT NOT NULL DEFAULT '[]',-- JSON [{"tool", "arg", "result"}] 해석 과정
  linked_to      TEXT REFERENCES card(notice_key),  -- 같은 프로그램의 대표 카드. 대표면 NULL
  check_ok       INTEGER,                   -- 팀 점검: 1 맞음, 0 틀림, NULL 미점검
  hidden         INTEGER NOT NULL DEFAULT 0,
  demo_new       INTEGER NOT NULL DEFAULT 0,-- 1이면 "새 공지 확인"을 누른 학생에게만 보인다
  interpreted_by TEXT NOT NULL              -- 'claude-prep' | 'agent'
);

CREATE TABLE raw_source (         -- 원문 저장본. 해석 때 읽은 것을 그대로 저장. 인용 대조의 기준
  id          INTEGER PRIMARY KEY,
  notice_key  TEXT NOT NULL REFERENCES notice(key),
  ord         INTEGER NOT NULL,   -- 해석 때 연 순서
  kind        TEXT NOT NULL,      -- body | attachment | image | link
  label       TEXT NOT NULL,      -- "본문", 파일명, "이미지 2", 링크 제목
  url         TEXT NOT NULL,      -- 출처 링크
  text        TEXT NOT NULL,
  confidence  TEXT                -- image만: high | low
);

CREATE TABLE task_template (      -- 준비할 일 틀. 공지당 하나, 날짜는 미리 계산
  id          INTEGER PRIMARY KEY,
  notice_key  TEXT NOT NULL REFERENCES card(notice_key),
  ord         INTEGER NOT NULL,
  title       TEXT NOT NULL,
  due         TEXT NOT NULL       -- YYYY-MM-DD = 마감 - 서류별 준비 기간
);

CREATE TABLE review (             -- 검토 대기열
  id           INTEGER PRIMARY KEY,
  notice_key   TEXT NOT NULL REFERENCES notice(key),
  condition_id TEXT,              -- 확인 중 조건의 id. 카드 전체 문제면 NULL
  reason       TEXT NOT NULL,     -- 못 찾음 | 열람 불가 | 판독 저신뢰
  note         TEXT NOT NULL DEFAULT '',
  resolved     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE student (
  id           TEXT PRIMARY KEY,  -- 서버 발급 secrets.token_urlsafe(16)
  profile      TEXT NOT NULL DEFAULT '{}',  -- JSON. 6.4 학생 정보 키
  revealed_new INTEGER NOT NULL DEFAULT 0,
  is_seed      INTEGER NOT NULL DEFAULT 0,  -- 미리 넣은 학생 (admin 재판정 장면용)
  created_at   TEXT NOT NULL
);

CREATE TABLE plan (
  student_id  TEXT NOT NULL REFERENCES student(id),
  notice_key  TEXT NOT NULL REFERENCES card(notice_key),
  added_at    TEXT NOT NULL,
  PRIMARY KEY (student_id, notice_key)
);

CREATE TABLE task_done (
  student_id  TEXT NOT NULL REFERENCES student(id),
  task_id     INTEGER NOT NULL REFERENCES task_template(id),
  PRIMARY KEY (student_id, task_id)
);

CREATE TABLE chat_miss (          -- 대화에서 답하지 못한 질문. 검토 대기열과 따로 쌓는다
  id          INTEGER PRIMARY KEY,
  student_id  TEXT,
  question    TEXT NOT NULL,
  created_at  TEXT NOT NULL
);

CREATE TABLE meta (
  key   TEXT PRIMARY KEY,         -- suggested_questions: JSON 문자열 배열 6개
  value TEXT NOT NULL
);
```

### 6.2 조건 스키마

`card.conditions`는 조건 객체의 배열이다. 해석이 쓰고 판정 엔진이 읽는다.

```json
{
  "id": "c1",
  "type": "gpa",
  "label": "평균 학점",
  "need": "3.0 이상",
  "params": {"min": 3.0, "scope": "cumulative"},
  "source_id": 812,
  "quote": "전체 평점평균 3.0/4.5 이상인 자"
}
```

- `label`, `need`: 화면에 그대로 나가는 한국어 문구다.
- `source_id`: `raw_source.id`다.
- `quote`: 그 행의 `text`에 글자 그대로 들어 있어야 한다(인용 대조 규칙). 공백 차이도 허용하지 않는다.

| type | params | 비교할 학생 정보 키 |
|---|---|---|
| `semesters` | `{"min": 4}` | `semesters` ≥ min |
| `grade` | `{"min": 2, "max": 4}` | 학년 = min(4, semesters // 2 + 1). min ≤ 학년 ≤ max |
| `status` | `{"allowed": ["재학"]}` | `status` ∈ allowed |
| `gpa` | `{"min": 3.0, "scope": "cumulative" \| "last"}` | cumulative는 `gpa`, last는 `gpa_last`. 값 ≥ min |
| `credits` | `{"min": 12, "scope": "last" \| "total"}` | `credits_last` 또는 `credits_total` ≥ min |
| `lang` | `{"any_of": {"TOEIC": 800, "IELTS": 6.0, "OPIc": "IM2"}}` | `langs`에 any_of의 시험이 있고, 그중 하나라도 점수가 기준 이상 |
| `topik` | `{"min": 3}` | `topik` ≥ min |
| `major` | `{"majors": ["소프트웨어학부", "인공지능학부"]}` | `major` ∈ majors |
| `income` | `{"max": 8}` | `income_bracket` ≤ max |
| `admission_year` | `{"min": 2023, "max": 2026}` | min ≤ `admission_year` ≤ max. 없는 쪽은 null |
| `history` | `{"flag": "교내장학 수혜", "must": false}` | `history[flag]` == must |
| `none` | `{}` | 항상 통과. "재학생 누구나" 같은 인용이 있을 때만 쓴다 |
| `unresolved` | `{"reason": "못 찾음"}` | 항상 확인 중. 같은 공지에 `review` 행이 있어야 한다 |

- **`major` 목록:** "SW 관련 학과" 같은 조건은 해석 때 UI의 학과 목록(`DEPTS`)을 보고 학과 이름 목록으로 바꿔 저장한다(decisions 5번).
- **`history` flag:** 데이터 준비 때 고정 목록으로 맞춘다. 판정은 flag를 문자열로만 비교한다.
  - 기본 목록(9/19 준비): 교내장학 수혜, 교외장학 수혜, 국가근로 참여, 교환학생 파견 경험, 현장실습 참여 경험, 징계 이력, 편입생, 외국인 유학생, 다자녀 가구, 국가보훈 대상, 장애 학생, 다문화·한부모 가정, `지역 연고(<지역명>)`.
  - 목록에 없는 예/아니오 사정은 같은 말투로 새로 만들었다(예: 외식업주 가정, 학자금대출 이용). 전체 목록은 `kmu.db`의 카드에서 뽑을 수 있다.
  - `income.max`의 0은 기초생활수급자·차상위, 1~10은 한국장학재단 학자금 지원 구간이다(중위소득 130% = 6구간).
- **OPIc 비교:** 등급 순서 `NL < NM < NH < IL < IM1 < IM2 < IM3 < IH < AL`으로 비교한다.
- **`lang` 시험:** any_of 키는 TOEIC, TOEFL iBT, IELTS, TOEIC Speaking, OPIc 중에서 쓴다(UI 시안 `LANG_TYPES`). TOPIK은 `lang`이 아니라 `topik` type으로 쓴다. 유학생 판정에서 둘을 다르게 다루기 때문이다(8.1).
- **유학생 조건:** 따로 type을 두지 않고 `history` flag `외국인 유학생`으로 쓴다. "대한민국 국적자", "외국인 유학생 불가"는 `must: false`, "외국인 유학생 대상"은 `must: true`다. 학생의 이 값은 온보딩의 신분 선택이 채운다(6.4).
- 9/19 `kmu.db`에는 `lang`, `topik` 조건이 없고, `외국인 유학생` flag 조건이 8건(모두 `must: false`) 있다. `topik` type은 UI (2)를 따라 더했고, 기존 카드는 그대로 유효하다.

### 6.3 분야

`card.category`는 다음 9종 중 하나다: 장학, 인턴·현장실습, 국제교류, 교내활동, 학사·전공, 한국어·문화, 창업, 공모전·경진대회, 자격증·어학.
- 홈 필터는 앞의 6종이다. 한국어·문화는 유학생에게만 보인다(UI 명세 7절 `CATS`).
- 관심 분야 선택지는 내국인이 한국어·문화를 뺀 8종, 유학생이 국제교류를 뺀 8종이다(UI 명세 7절).
- 9/19 `kmu.db`에는 한국어·문화 카드가 없다.

### 6.4 학생 정보 (`student.profile`)

| 키 | 값 | 받는 곳 |
|---|---|---|
| `status` | 재학 \| 휴학 \| 졸업예정 | 온보딩 |
| `grad_year`, `grad_term` | 2026~2029, "2월" \| "8월" | 온보딩 (졸업예정일 때) |
| `semesters` | 정수 0~8 (마친 학기) | 온보딩 |
| `major` | 학과명. 화면은 UI 시안 `DEPTS` 목록에서만 고르게 한다 | 온보딩 |
| `gpa` | 0~4.5 (누적 평점). 비워 둘 수 있다(null) | 온보딩 (내국인) |
| `langs` | `{"TOEIC": "850", "IELTS": "7.0"}`. 시험은 6.2의 5종, 여러 개. 없으면 `{}` | 온보딩 (내국인) |
| `topik` | 정수 0~6. 0은 "아직 없어요" | 온보딩 (유학생) |
| `interests` | 6.3의 9종 중 여러 개. 홈에 처음 들어갈 때 분야 필터로만 쓴다 | 온보딩 |
| `gpa_last` | 직전 학기 평점 | 되묻기, 대화 |
| `credits_last`, `credits_total` | 직전 학기 이수 학점, 총 이수 학점 | 되묻기, 대화 |
| `income_bracket` | 0~10 | 되묻기, 대화 |
| `admission_year` | 2000~2026 | 되묻기, 대화 (학번 대신 받는다) |
| `history` | `{"교내장학 수혜": false}`. `외국인 유학생`은 온보딩의 신분이 채운다(내국인 false, 유학생 true) | 온보딩 (신분), 되묻기, 대화 |

- **숫자 키 값의 형식:** 숫자, 구간 `{"min": a, "max": b}`(양 끝 포함, 한쪽은 null 가능), null(모름) 중 하나다. 구간은 되묻기 답에서만 생긴다. `gpa`, `gpa_last` 말고는 정수만 받고(구간 끝도), `semesters`, `topik`은 구간도 받지 않는다.
- **구간의 null 끝:** 판정에서는 그 키의 범위 끝(7절 학생 정보 검증)으로 본다. "7분위 이상" {7, null}은 7~10분위, "2023년 이상"은 2023~2026년이다. 그래야 `admission_year` {2023, 2026} 같은 조건이 "2023년 이상" 답으로 `pass`로 정해진다. `have` 문구는 저장된 구간 그대로 쓴다("7분위 이상").
- **신분별로 받는 것:** 내국인 온보딩은 `gpa`, `langs`를, 유학생 온보딩은 `topik`을 받는다(UI 명세 5.3). 받지 않은 키는 null이나 `{}`로 두고, 신분을 바꿔도 지우지 않는다.
- **받지 않는 것:** 실명과 학번은 받지 않는다.

### 6.5 사전 데이터 만들기 (오늘, Claude Code)

1. `python -m app.db init`, `load`로 939건을 적재한다.
2. **대상 고르기:** 게시일이 `DEMO_TODAY` 이전인 444건 중 기회성 공지만 고른다. 강연 안내, 시설 공지 같은 것은 뺀다. 해석할 건수는 초안이며 미결 질문 1번이다.
3. **해석:** 공지마다 해석 에이전트와 같은 순서로 읽고 표를 채운다.
   - 순서: 본문 → 첨부(PDF, HWP, HWPX, DOCX를 텍스트로 변환) → 본문 이미지 → 허용 도메인 링크.
   - 읽은 것은 `raw_source`에, 결과는 `card`, `task_template`, `review`에 쓴다. `card.interpreted_by = 'claude-prep'`이다.
   - 해석 과정을 `trace`에 남긴다.
4. **이미지:** 공지 페이지를 다시 받아 `<img>`를 모은다. 20건 안쪽만 Claude가 읽어 `raw_source(kind='image')`로 넣는다. 이 20건에는 "새 공지 확인" 데모용 1건과 시연 장면에 쓸 공지를 넣는다.
   - 판독이 불확실하면 `confidence='low'`로 둔다.
   - 읽지 않은 이미지 공지는 조건을 `unresolved`로 두고 `review`에 "열람 불가"로 넣는다.
5. **할 일 날짜:** `due = apply_end - 서류별 준비 기간`이다. 준비 기간 표는 팀이 쓰고, 없으면 1일로 둔다. 실제 신청·제출 할 일은 준비 기간 0일(마감일)이다. `apply_end`가 없으면 할 일도 없다.
6. **공지 연결:** 같은 프로그램을 묶는다. 대표 카드는 정보가 가장 많은 것으로 하고, 나머지는 `linked_to`를 채운다.
7. **점검:** 4명이 나눠서 상세 화면과 원문 시트를 대조하고 `data/check.csv`(`key,ok,note`)에 적는다. Claude가 이를 `check_ok`에 반영한다.
   - 틀린 카드는 고친 뒤 `check_ok = 1`로 바꾸거나 `hidden = 1`로 숨긴다.
   - 점검 결과(예: 30건 중 27건)는 발표의 정확도 수치로 쓴다.
8. **나머지:** 시드 학생 5명, `demo_new` 카드 1건, `meta.suggested_questions` 6개를 넣고 `DEMO_TODAY`를 확정한다.
9. **UI (2) 보정 (9/19 밤, `tasks/todo.md` D6):** 6.4 키가 바뀌었으므로 시드 학생의 `lang_type`, `lang_score`를 `langs`로 바꾸고 `history["외국인 유학생"]`을 넣는다. 유학생 시드 학생 1명을 더한다.

**완료 조건:** `pytest tests/test_data.py`가 통과한다(10절).

## 7. API 계약 (`student`, `chat`)

- 학생 범위의 요청은 헤더 `X-Student-Id`를 보낸다. 없거나 모르는 id면 401이다. 화면은 401을 받으면 새 학생을 만들고 온보딩부터 시작한다.
- 모든 날짜는 `YYYY-MM-DD`이고, "오늘"은 `DEMO_TODAY`다.

| 메서드 | 경로 | 요청 | 응답 |
|---|---|---|---|
| GET | `/api/config` | | `{"today", "sources": 30, "suggested_questions": [...]}` |
| POST | `/api/students` | | `{"id"}` |
| GET | `/api/me` | | `{"profile", "eligible_count"}` |
| PUT | `/api/me` | profile 전체 | 같음. 422: 검증 실패 |
| PATCH | `/api/me` | 일부 키. `history`는 키 단위로 합친다 | 같음 |
| GET | `/api/notices` | | `{"items": [목록 항목]}` |
| GET | `/api/notices/{key}` | | 상세. 404: 목록에 없는 카드 |
| GET | `/api/notices/{key}/raw` | | 원문 시트 |
| POST | `/api/judge` | `{"notice_keys": [...], "overrides": {...}}` | `[판정]`. 저장하지 않는다 |
| GET | `/api/ask` | `?field=` 선택 | 되묻기 카드 또는 `null`. 422: 질문 틀이 없는 `field` |
| GET | `/api/plan` | | `{"items": [상세]}` 마감순 |
| POST | `/api/plan/{key}` | | 204. 409: 지원 불가 |
| DELETE | `/api/plan/{key}` | | 204 |
| PUT | `/api/tasks/{id}` | `{"done": true}` | 204 |
| GET | `/api/alerts` | | `[{"kind", "title", "body", "notice_key"}]`. `kind`는 8.1 알림 순서대로 `new` \| `deadline` \| `today` |
| POST | `/api/reveal-new` | | `{"items": [목록 항목]}`. 이미 공개했으면 빈 배열 |
| POST | `/api/chat` | `{"message"}` 300자 이하 | NDJSON 스트림 (8.4) |

**목록에 보이는 카드.** 다음을 모두 만족하는 카드다.
- `check_ok = 1`, `hidden = 0`, `linked_to IS NULL`
- `apply_end >= 오늘`, `apply_start`가 NULL이거나 `<= 오늘`
- 공지 게시일 `<= 오늘`
- `demo_new = 0`이거나 학생의 `revealed_new = 1`

정렬은 NEW(공개된 `demo_new`) 먼저, 그다음 `apply_end` 오름차순, 마감이 같으면 `key` 오름차순이다.

**목록 항목**
```json
{"key": "hq_cat7:11684", "title": "성적우수 장학금", "sub": "다음 학기 등록금 일부 감면",
 "dept": "학생지원팀", "category": "장학", "apply_start": "2026-03-09", "apply_end": "2026-03-20",
 "is_new": false, "planned": false, "eligible": true, "gap": null,
 "rows": [{"type": "gpa", "label": "평균 학점", "need": "3.0 이상", "status": "pass", "have": "3.52", "gap": "",
           "chip": "학점 3.0 이상", "tip": "내 평균 학점 3.52", "field": null, "ask": null}]}
```
- `rows`는 카드의 조건 순서 그대로, 조건마다 한 행이다. 화면의 칩과 상세의 판정이 모두 이것을 쓴다. 문구 규칙은 8.1.
- UI (1)의 `chips`(문자열 배열)는 없앴다. 화면이 모든 조건을 칩으로 그리기 때문이다.

**상세** = 목록 항목에 아래를 더한 것
```json
{"url": "https://...", "posted_date": "2026-03-05", "fields": [["제출 서류", "신청서"]],
 "tasks": [{"id": 12, "title": "성적증명서 발급", "due": "2026-03-18", "done": false}],
 "alt": null}
```
- `posted_date`는 `notice.posted_date`다. 원문 시트 머리의 "{dept} 게시판 · {게시일} 게시"에 쓴다. 시안은 신청 시작일을 게시일 자리에 썼지만 실제 카드의 절반쯤은 `apply_start`가 null이다.
- `alt`는 "대신 이건 지원할 수 있어요"에 보일 목록 항목 하나이거나 null이다(8.2). `GET /api/notices/{key}`에서만 채우고, `/api/plan`의 상세에서는 null이다.

**원문 시트**
```json
{"path": "본문 → 붙임1.pdf → 이미지 1",
 "sections": [{"kind": "attachment", "label": "붙임1.pdf", "url": "https://...",
               "text": "...", "highlights": [[120, 152]]}]}
```
`highlights`는 이 카드 조건들의 `quote`가 `text`에서 시작하는 위치와 끝 위치다.
- `[start, end)`이고 끝은 들어가지 않는다. 곧 `text[start:end] == quote`다. 위치는 Python 문자 위치다.
- 조건의 `source_id`가 그 구역의 `raw_source.id`인 인용만 그 구역에 표시한다.
- `text`에서 처음 나오는 곳 하나만 쓴다. `quote`가 빈 조건(`unresolved`)은 건너뛴다.
- 구간은 위치 순서이고, 같은 구간은 한 번만 쓴다. 목록에 없는 카드의 원문 시트는 404다.

**되묻기 카드**
```json
{"field": "gpa_last", "question": "직전 학기 평점이 어느 구간인가요?", "unlock": 4,
 "choices": [{"label": "3.8 이상", "value": {"min": 3.8, "max": null}},
             {"label": "3.5 ~ 3.8", "value": {"min": 3.5, "max": 3.79}},
             {"label": "3.5 미만", "value": {"min": null, "max": 3.49}}]}
```
- 답은 `PATCH /api/me {"gpa_last": {...}}`로 저장한다.
- `history` 항목은 `field`가 `"history:교내장학 수혜"`이고 선택지는 `[{"label": "예", "value": true}, {"label": "아니오", "value": false}]`다. `unlock`은 숫자 키와 같다. 답은 `PATCH /api/me {"history": {"교내장학 수혜": true}}`로 보낸다(`"history:..."`를 키로 보내면 422).
- "모르겠어요"는 화면에서 이번 방문 동안 카드만 숨긴다.
- `?field=`를 주면 그 키 하나로 만든 카드다. 상세의 행에 있는 `field` 값을 그대로 보낸다(`history:{flag}` 포함). 질문 틀(8.1)이 있는 키만 받고, 온보딩 키(`gpa`, `langs`, `major`, `topik`)나 모르는 값은 422다. 그 키가 `missing`인 보이는 공지가 없으면 null이다.

**가정 판정 (`POST /api/judge`).** 응답은 8.1 공지 판정 `{"eligible", "gap", "rows"}`의 배열이고 `notice_keys` 순서다. `overrides`는 빼도 되고(저장된 학생 정보로 판정), PATCH와 같은 검증으로 어기면 422다. `notice_keys`에 목록에 없는 key가 하나라도 있으면 404다.

**계획과 할 일.** `POST /api/plan/{key}`는 목록에 없는 카드면 404이고, 이미 넣은 카드를 다시 넣어도 204다. `DELETE`는 계획에 없어도 204다. `GET /api/plan`은 계획에 넣은 카드 중 지금 목록에 보이는 것만 준다. `PUT /api/tasks/{id}`는 `{"done": false}`면 체크를 푼다. 계획에 넣지 않은 공지의 할 일도 체크할 수 있고(상세의 준비할 것), 모르는 id는 404다. 알림의 `today`는 공지 key, 할 일 순서다.

**학생 정보 검증 (PUT, PATCH).** 어기면 422를 돌려준다.
- `semesters`: 정수 0~8
- `gpa`, `gpa_last`: 0~4.5
- `langs`: 객체. 키는 6.2의 5종, 값은 점수 문자열이다. TOEIC 10~990, TOEFL iBT 0~120, TOEIC Speaking 0~200, IELTS 0~9, OPIc은 등급 목록 안. 빈 문자열도 422다. PATCH에서는 `history`와 달리 통째로 바꾼다.
- `topik`: 정수 0~6
- `major`: 1~50자
- `interests`: 9종 안
- `income_bracket` 0~10, `admission_year` 2000~2026, `grad_year` 2026~2029, `credits_last` 0~30, `credits_total` 0~250. 모든 숫자 키에 위 끝이 있다(9/20 Checkpoint 1: 끝이 없던 학점에 10**400을 넣으면 500이 났다). 실제 카드의 학점 기준은 12, 15라 되묻기 답이 이 범위 안이다
- `history`: 합친 결과가 키 100개 이하, 값은 true·false·null. flag 이름은 카드에 없는 것이어도 받는다(50자 이하)
- 숫자 키는 모두 null(모름)을 받는다. 숫자가 아닌 키(`status`, `grad_term`, `major`, `interests`, `langs`, `history`)는 null도 422다.
- 숫자 키의 구간 값: min ≤ max, 키는 `min`, `max` 둘 다 있고 그 밖의 키는 없다, 양 끝은 그 키의 범위 안이거나 null
- 6.4 표에 없는 키(UI (1)의 `lang_type`, `lang_score` 포함), 6.4 목록 밖의 `status`·`grad_term` 값, 타입이 틀린 값(숫자 자리에 문자열, bool, NaN)은 422다. `semesters`, `topik`은 구간 없이 정수만 받는다.
- `gpa`, `gpa_last` 말고 숫자 키는 모두 정수만 받는다. 구간의 양 끝도 정수다. `2024.5`, `5.0`은 422다("2024.5년"처럼 보이지 않게).

## 8. 모듈별 요구사항

### 8.1 `judge` (1등급)

`app/judge.py`는 순수 함수다. 입력은 카드 dict와 학생 정보 dict이고, DB와 LLM을 모른다.

**조건 하나의 판정.** 결과는 7절 `rows`의 한 행이다: `{"type", "label", "need", "status", "have", "gap", "chip", "tip", "field", "ask"}`. `type`, `label`, `need`는 조건 객체 그대로다. `status`는 다음 넷 중 하나다.

| status | 뜻 | 화면 (UI 시안) |
|---|---|---|
| `pass` | 해당 | 분류별 색 칩 |
| `fail` | 비해당 | 점선 칩, 흐린 글자 |
| `missing` | 정보 부족. 학생 정보 값이 null이거나 구간이 기준에 걸침 | 점선 칩. `field`가 있으면 "입력하기" 행 |
| `pending` | 확인 중. `unresolved` 조건, 유학생 기준 확인 필요 | 점선 칩. 되묻기 대상 아님 |

UI 시안의 `missing`(입력 안 함)과 `unknown`(기준 확인 필요)은 화면 모양이 같다. 여기서 입력 안 함은 `field`가 있는 `missing`이고, 기준 확인 필요는 `pending`이거나 `field`가 null인 `missing`이다. 화면은 `field`와 `ask`가 있을 때만 입력하기 행을 둔다.

- **`lang` 판정:**
  - `langs`가 `{}`이면 `missing`, `field` "langs"다. 부족분은 "어학 정보 필요"다.
  - 가진 시험 중 any_of에 있는 것이 없으면 `missing`, `field` null이다(입력하기 행도 되묻기도 없다). 부족분은 "{any_of 첫 시험} 등 어학 기준 확인 필요"다.
  - any_of에 있는 시험 중 하나라도 기준 이상이면 `pass`, 모두 미달이면 `fail`이다. 부족분은 "{any_of 첫 시험} {기준} 필요"다.
  - 되묻기로는 묻지 않는다.
- **`topik` 판정:** `topik`이 null이거나 0이면 `missing`, `field` "topik"이다("아직 없어요"도 되묻는다. UI 시안). 이때 `have`는 빈 문자열이다. 부족분은 "한국어능력(TOPIK) 정보 필요", `fail`이면 "TOPIK {min}급 이상 필요"다.
- **유학생 판정.** `history["외국인 유학생"]`이 true인 학생은 온보딩에서 누적 학점과 어학을 받지 않는다. 그래서(시안의 유학생 규칙), 학생 정보에 값이 남아 있어도 상관없이:
  - `gpa` 조건 중 `scope`가 `cumulative`인 것은 기준과 상관없이 `pending`, 부족분 "유학생 학점 기준은 별도 확인이 필요해요"다. 시안은 기준 3.0 미만이면 통과로 보지만(시안 주석 "가정: 검증 필요"), 근거 없이 "지원할 수 있어요"가 나오므로 따르지 않는다(14절 10번). `scope`가 `last`인 것은 `gpa_last`로 보통 판정한다(되묻기로 누구나 답할 수 있다).
  - `lang` 조건은 `pending`, 부족분 "유학생 어학 기준은 별도 확인이 필요해요"다.
- **부족분 문구(`gap`)는 UI 시안 문구를 따른다:**
  - `semesters`: "이수 학기 {n}학기 부족"
  - `gpa`: "학점 {차이:.2f} 부족"
  - `grade`, `major`: "{need} 대상"
  - `history`: "{label}: {need}" (`need`가 "없음", "수혜하지 않음"처럼 그것만으로는 뜻이 없는 경우가 많다)
  - `missing`: "{label} 정보 필요". 시안의 "학점 정보 필요"와 같은 꼴이고 `label`을 쓰므로 "평균 학점 정보 필요"가 된다.
  - `pending`: "{label} 확인 중"
  - `lang`, `topik`, 유학생: 위 항목
  - 나머지 `fail`: "{need} 대상"
  - 학생 값이 구간일 때: 구간이 기준에 걸치면 `missing`이므로 "{label} 정보 필요", 구간 전체가 기준 밖이면 `fail`이고 차이를 셀 수 없으므로 type과 상관없이 "{need} 대상"이다.
- **`have` 문구:** `semesters` "5학기", `grade` "3학년", `gpa` 소수 둘째 자리 "3.52", `credits` "15학점", `income` "5분위", `admission_year` "2024년", `history` "예" | "아니오", `topik` "TOPIK 4급", `status`·`major`는 값 그대로다. `lang`은 `pass`면 통과한 시험 하나(여럿이면 any_of 순서로 첫 번째, "TOEIC 850"), 아니면 가진 시험 전부(any_of 밖 시험 포함)를 "{시험} {점수}"로 ", "로 잇는다(UI 시안 `LANG_TYPES` 순서). 구간은 평점이면 "3.5 ~ 3.79", "3.8 이상", "3.49 이하"(숫자 모양은 아래 "평점 숫자"), 정수 키면 되묻기 선택지와 같은 꼴("12 ~ 14학점", "6분위", "7분위 이상", "5분위 이하", "2024년 이상")로 쓴다. 값이 없거나 `none`, `unresolved`면 빈 문자열이다. 유학생 규칙으로 `pending`이 된 행도 빈 문자열이다.
- **평점 숫자:** 구간 끝과 되묻기 선택지의 평점은 소수 둘째 자리가 0이면 한 자리로, 아니면 둘째 자리까지 쓴다(3.80 → "3.8", 2.00 → "2.0", "3.79"). 학생 값 하나를 쓰는 `have`와 부족분 차이는 늘 둘째 자리다("3.52", "0.20").
- **칩 문구(`chip`):** `need`다. 다음만 다르다(UI 시안의 칩처럼 그것만 읽어도 뜻이 통하게):
  - `gpa`: "학점 {need}" ("학점 3.0 이상")
  - `lang`: `pass`면 "{통과한 시험} {기준} 이상", 아니면 "{any_of 첫 시험} {기준} 이상"
  - `history`: "{label}: {need}" ("징계 이력: 없음")
  - `unresolved`: "{label} {need}" ("지원 자격 확인 중")
  - IELTS 기준은 칩과 툴팁 모두 소수 한 자리로 쓴다("IELTS 6.0 이상").
- **툴팁 문구(`tip`):**
  - `pass`: `have`가 있으면 "내 {label} {have}", 없으면 `need`다. `history`는 "{flag}: {have}"다.
  - `fail`: "{pass일 때 문구} · {gap}"이다.
  - `missing`: `have`가 없으면 "입력하지 않음", 있으면 `gap`이다.
  - `pending`: `gap`이다.
  - `lang`은 `fail`과 "기준 확인 필요"(`field` null인 `missing`)일 때 any_of 전체를 "TOEIC 800 이상 / IELTS 6.0 이상"처럼 잇는다(UI 시안).
- **`field`:** `missing`의 원인이 된 학생 정보 키다. 두 가지뿐이다.
  - 되묻기 키: `gpa_last`, `credits_last`, `credits_total`, `income_bracket`, `admission_year`, `history:{flag}` (`history:외국인 유학생`은 빼고)
  - 온보딩 키: `gpa`, `langs`, `major`, `topik`, `history:외국인 유학생`
  - 그 밖에는 null이다: `missing`이 아닌 행, "기준 확인 필요"인 `lang`, 빈 profile에서 `semesters`·`status`·`grade`가 비어 생긴 `missing`(온보딩이 받으므로 따로 묻지 않는다).
- **`ask`:** `field`가 있을 때만 문구, 없으면 null이다. 되묻기 키는 아래 질문 틀이다. 온보딩 키는 UI 시안 문구다:
  - `gpa`: "평균 학점을 알려주시면 판단할 수 있어요"
  - `langs`: "{any_of 첫 시험}이나 {둘째 시험} 성적 갖고 계신가요?" (시험이 하나면 "{시험} 성적 갖고 계신가요?", 셋 이상이면 앞의 둘만 쓴다)
  - `major`: "학과 정보를 입력해 주시면 확인할 수 있어요"
  - `topik`: "TOPIK 성적 갖고 계신가요?"
  - `history:외국인 유학생`: "신분 정보를 입력해 주시면 확인할 수 있어요" (시안에는 없다. 온보딩이 늘 채우므로 옛 profile에서만 나온다)
- 시안에 없는 type(`status`, `credits`, `income`, `admission_year`, `history`, `none`, `unresolved`)의 칩과 툴팁도 위 규칙으로 만든다.

**공지 판정.** 결과는 `{"eligible", "gap", "rows"}`이고, `rows`는 7절 목록 항목의 `rows` 모양이다.
- `eligible` = 모든 조건이 `pass`다.
- `gap` = 첫 번째 `pass`가 아닌 조건의 부족분 문구다.
- 조건이 없는 카드는 `eligible`이다.
- **화면은 네 묶음이다.** 묶음은 API 필드가 아니고, 화면이 `rows`를 보고 아래 순서로 정한다.
  1. `eligible`이면 "지원할 수 있는 공지"(시안).
  2. `fail` 행이 하나라도 있으면 "조건이 안 맞는 공지"(시안).
  3. 그 밖에 `ask`가 있는 행(입력하기 행)이 하나라도 있으면 "정보를 더 입력하면 판단할 수 있어요"(시안).
  4. 나머지, 곧 비통과 행이 모두 입력하기 행 없는 행(`pending`, 기준 확인 필요)이면 "아직 확인 중인 공지"(시안에 없음, 8.3 UI 변경). 입력해도 풀리지 않는 공지다(3/16 사본 59건 중 19건이 `unresolved`뿐이다).
- 상세의 판정도 같은 기준이다: 1 "지원할 수 있어요"(✓), 2 "지금은 지원할 수 없어요"(✗), 3 "정보를 더 입력하면 확인할 수 있어요"(?), 4 ? 아이콘에 첫 비통과 행의 `gap`("지원 자격 확인 중").

**되묻기.**
1. 보이는 카드 중 `fail`이 하나도 없고 `missing`이 있는 공지를 모은다.
2. `missing`의 원인이 된 학생 정보 키(행의 `field`)별로 공지 수를 센다. 가장 많은 키 하나를 고른다. 동률이면 6.4 표 순서를 따른다.
   - 되묻기 키(위 `field` 목록)만 센다. 온보딩 키는 묻지 않는다. 화면의 "입력하기"가 내 정보로 보낸다.
   - 동률이면 6.4 표 순서이고, 같은 줄의 `credits_last`가 `credits_total`보다 먼저다. `history` flag들은 맨 뒤이고, flag끼리 동률이면 먼저 나온 것이다. "먼저"는 목록 순서(NEW, 마감순)로 카드를 보고, 카드 안에서는 조건 순서다.
3. 선택지 경계값은 그 공지들 조건의 기준값을 정렬해서 만든다. 구간 끝은 평점이면 0.01, 정수 키면 1씩 뺀다.
   - 경계값: `min`은 그대로, `income`의 `max`와 `admission_year`의 `max`는 +1이다(이하 조건이라서).
   - 경계값은 그 키의 범위(7절 학생 정보 검증) 아래 끝보다 크고 위 끝 이하인 것만 쓴다. 나머지는 버린다. 예: `admission_year` max 2026 → 2027, `income` max 10 → 11, `gpa_last` min 0은 버린다. 그래서 모든 선택지 값이 `PATCH /api/me`를 통과한다. 버린 경계값 쪽의 한계는 어떤 답도 만족한다(6.4 "구간의 null 끝").
   - 경계값이 하나도 남지 않는 키는 묻지 않는다. 어떤 답을 골라도 갈리지 않기 때문이다. 2단계에서 그 키를 빼고 고르며, `?field=`로 그 키를 주면 null이다.
   - 선택지는 높은 구간부터다. 문구: "{c} 이상", 가운데 "{lo} ~ {hi}"(평점은 다음 경계값, 정수 키는 구간 끝), "{c} 미만". 단위는 학점, 분위, 년을 붙인다. 예: "12 ~ 14학점". 정수 키에서 lo와 hi가 같으면 "{lo}분위"처럼 하나만 쓴다. 평점 숫자 모양은 위 "평점 숫자"다.
   - 학생 값이 이미 구간이면 선택지 구간을 그 안으로 좁힌다. 앞 답에서 안 것을 넓히지 않기 위해서다.
4. `unlock`은 모은 공지 중 고른 키가 `missing`인 공지의 수다. 어느 선택지를 골라도 이 공지들의 그 조건은 `pass`나 `fail`로 정해진다.

**키를 정한 되묻기(`?field=`).** 상세에서 그 공지의 행에 바로 답할 때 쓴다. 1단계에서 `fail`이 있는 공지도 빼지 않고, 그 키가 `missing`인 보이는 공지를 모두 모은다. 2단계는 건너뛰고, 3·4단계는 같다. 그 공지 자체에 `fail`이 있어도 그 행에 답할 수 있어야 하기 때문이다. 되묻기 키가 아닌 값(온보딩 키, `history:외국인 유학생` 포함)은 오류다(API는 422).

`unlock`개 공지가 바뀐다는 말은 그 공지들의 그 행이 `pass`나 `fail`로 정해진다는 뜻이다. 다른 `missing` 행이 남은 공지는 묶음이 그대로일 수 있다.

**질문 문구는 키별 고정 틀이다.**
- `gpa_last`: "직전 학기 평점이 어느 구간인가요?"
- `credits_last`: "직전 학기에 몇 학점을 이수했나요?"
- `credits_total`: "지금까지 이수한 학점은 어느 구간인가요?"
- `income_bracket`: "소득 분위가 어느 구간인가요?"
- `admission_year`: "입학 연도가 언제인가요?"
- `history`: "'{flag}'에 해당하나요?"

**가정 판정.** 학생 정보에 `overrides`를 덮어쓴 복사본으로 판정한다. `history`는 PATCH처럼 키 단위로 합친다. 저장하지 않는다(decisions 20번).

**알림.** 세 종류이고 하나도 없으면 빈 배열이다. 아래 순서로 쌓는다. 같은 종류 안에서는 목록 순서이고, `today`만 공지 key, 할 일 순서다(7절). 문구는 `title` / `body`다.
1. `new`: 공개된 `demo_new` 카드가 `eligible`이면 "새 기회를 찾았어요" / "{title} · 내 조건으로 지원할 수 있어요"
2. `deadline`: 계획에 넣은 카드의 `apply_end`가 정확히 오늘 + 3일이면 "{title} 마감이 3일 남았어요" / ""
3. `today`: 계획에 넣은 카드에 오늘이 기한인 미완료 할 일이 있으면 "오늘 할 일" / "{할 일 제목}"

### 8.2 `student` (1등급)

`app/main.py`에 7절 API를 구현한다.
- 판정은 요청마다 `judge`를 부른다. 카드는 수백 건이라 캐시하지 않는다.
- `POST /api/plan/{key}`는 서버에서도 판정해서, 지원 불가면 409를 돌려준다.
- `eligible_count`는 목록 기준 `eligible` 카드 수다.
- **상세의 `alt`:** 그 카드의 `rows`에 `fail`이 있을 때만 고른다. 후보는 목록에 보이는 다른 카드 중 `eligible`인 것이다. 같은 분야 중 `apply_end`가 가장 이른 것, 없으면 조건이 없거나 `none`뿐인 카드 중 `apply_end`가 가장 이른 것, 그것도 없으면 null이다(시안의 대안 고르기). 마감이 같으면 `key` 오름차순으로 앞의 것이다.
- `/`는 `static/index.html`을 서빙한다.

### 8.3 `web` (1등급)

`docs/ui-spec.md`(UI 명세, 이하 "시안")와 스크린샷 `docs/ui-screens/`로 `static/index.html`을 만든다. 명세의 화면, 문구, 동작을 그대로 따르고, 데이터는 가짜 없이 처음부터 API에서 받는다. 시안 HTML(`docs/ui-mockup.html`)은 당일에 없으므로 읽지 않는다.
- 로고는 `docs/assets/`의 PNG 두 개를 base64 data URI로 `index.html` 안에 넣는다. 화면은 파일 하나로 둔다.
- 순서: T03이 명세 1~4절(틀, 토큰, 공통 부품, 화면 흐름)과 스플래시, 탭바를 만든다. 화면은 T09(온보딩, 홈, 상세, 내 정보), T10(원문 시트, 되묻기), T11(내 계획, 새 공지, 알림), T15(대화)가 만든다.

**가짜 데이터를 API로 바꾼다.**
- `TODAY`는 `/api/config.today`로 바꾼다.
- 홈 목록과 묶음은 `/api/notices`에서 받는다. 묶음은 8.1 "공지 판정"의 네 묶음이다.
- 조건 칩(명세 3절)은 목록 항목의 `rows`로 그린다.
  - 칩 문구는 `chip`, 툴팁은 `tip`, 모양은 `status`(`pass`는 색 칩, 나머지는 점선 칩)로 정한다.
  - 명세의 "정보 부족" 모양(점선 테두리, sub 글자)은 `fail`이 아닌 비통과 행(`missing`, `pending`) 모두에 쓴다. 명세가 "정보 부족만 있는 공지"라고 하는 것은 8.1의 3번 묶음(입력하기 행이 있는 것)이고, 4번 묶음은 따로 모은다.
  - 색은 `type`으로 정한다: `semesters`·`grade`·`credits`·`admission_year` → sem, `gpa` → gpa, `lang`·`topik` → lang, `major` → major, 나머지 → any.
  - 목록 행에는 시안처럼 `pass`를 앞으로 모아 4개까지 보인다. 상세에는 모두 보인다.
  - `history` flag가 `외국인 유학생`인 행은 내국인에게 `pass`면 칩을 그리지 않는다(시안의 국적 칩 숨김). 자격요건 요약에는 남긴다. 행에는 flag가 없으므로 `tip`이 "외국인 유학생: 아니오"인 `pass` 행으로 알아본다(8.1 툴팁 규칙: `history` `pass`는 "{flag}: {have}", 이 flag가 "아니오"로 통과하는 학생은 내국인뿐이다).
  - 칩 툴팁의 열고 닫기는 카드 key와 행 순서(index)로 구분한다. 행에는 id가 없다.
- 상세는 `/api/notices/{key}`에서 받는다.
  - "자격요건"은 `rows`의 `chip`을 " · "로 잇는다(`need`만 이으면 "3.0 이상", "없음"처럼 뜻이 빠진다). `rows`가 없으면 "재학생 누구나"다.
  - "신청 기간"은 시안처럼 "{시작 M/D} ~ {마감}"이고, `apply_start`가 null이면 "~ {마감}"이다.
  - "대신 이건 지원할 수 있어요"는 `alt`다.
  - `ask`가 있는 행마다 시안의 입력하기 행을 둔다. "입력하기"는 `field`가 온보딩 키면 내 정보로 가고, 되묻기 키면 아래 "상세에서 바로 답하기"를 연다.
  - 원문 보기 옆 링크는 카드의 `url`이다. 문구는 시안 그대로 "국민대 공지사항 게시판에서 보기"다. 원문 시트 머리의 게시일은 `posted_date`다.
- 계획, 할 일 체크(홈, 상세, 내 계획), 달력 막대는 `/api/plan`, `/api/tasks`를 쓴다.
  - 할 일은 `tasks[].id`로 구분한다. 공지 key와 순서를 ":"로 이어 쓰지 않는다(실제 key에 ":"가 있다. 9/19 리허설에서 깨졌다).
  - 막대는 `apply_start` ~ `apply_end`다. `apply_start`가 null이면 시안처럼 마감 3일 전부터 흐리게 그린다.
- 명세의 신분은 `history["외국인 유학생"]`, 어학 성적은 `langs`, TOPIK은 `topik`("아직 없어요"는 0)이다.
- 첫 홈 분야 필터(관심 분야 ∩ 필터 6종)는 시안처럼 온보딩을 마치고 홈에 들어올 때 한 번만 건다. 스플래시에서 바로 홈으로 오는 재방문은 필터 없이 시작한다.
- 대화의 두 번째 인사 말풍선 개수는 `/api/me`의 `eligible_count`다.
- 새 공지 공개, 되묻기 답, 내 정보 저장, 대화의 "바꾸기" 뒤에는 `/api/notices`와 `/api/ask`를 다시 받아 개수, 묶음, 홈 되묻기 카드를 새로 그린다.

**실제 데이터로 그릴 때 (9/19 리허설에서 깨졌던 것).**
- DB에서 온 글자(제목, 요약, 원문, 칩, 대화의 질문·답·단계)는 템플릿 문자열에 넣기 전에 HTML 이스케이프한다. 실제 제목에 `<Freshman Admissions>`가 있다.
- `YYYY-MM-DD` 문자열은 `new Date(s + 'T00:00')`로 로컬 자정 날짜로 만든다. `new Date('YYYY-MM-DD')`는 UTC라서 D-day, 날짜 비교, 달력 칸이 하루 어긋난다.
- PUT 전에 입력값을 7절 타입으로 바꾼다: `semesters`·`grad_year`·`topik`은 정수("3급" → 3), `gpa`는 실수이고 비었으면 null, 점수가 빈 어학 시험은 `langs`에서 뺀다. 내 정보에서 값이 7절 검증에 걸리면 그 저장은 보내지 않고 토스트도 띄우지 않는다(입력 중인 값이다).
- 졸업예정일 때만 `grad_year`, `grad_term`을 보낸다. 학과 입력은 `maxlength=50`이다.

**학생 id.** 첫 방문에 `POST /api/students`로 받아 localStorage `kmu_student_id`에 저장한다. localStorage 접근은 try/catch로 감싼다.
- 스플래시가 끝나면(2.4초 또는 탭) 저장된 id로 `GET /api/me`를 부른다. 성공하고 `profile`이 비어 있지 않으면 홈으로 가고, 비어 있으면 온보딩(ob1)부터다.

**온보딩과 내 정보.**
- 온보딩 "내 기회 찾기"를 누르면 `PUT /api/me`를 보낸다. 내국인 경로(ob1 → ob2)는 `history["외국인 유학생"]`을 false로, 유학생 경로(ob-i1 → ob-i2)는 true로 보낸다. 내 정보의 "신분" 칩도 같은 값을 바꾼다.
- 내 정보 화면은 입력이 바뀔 때 400ms 뒤 `PUT /api/me`를 보내고, 응답의 `eligible_count`로 개수 문구를 바꾼다.
- PUT은 profile 전체를 바꾸므로, 화면 입력에 없는 키(되묻기·대화로 받은 `gpa_last`, `history`, 다른 신분 화면의 `gpa`·`langs`·`topik` 등)는 마지막으로 받은 `profile`에서 그대로 실어 보낸다. 그러지 않으면 내 정보 저장이 되묻기 답을 지운다.

**UI 변경.** 시안에 없거나 시안과 다르게 하는 것이다. 이 목록 밖의 화면은 바꾸지 않는다(12절).
- **되묻기 카드 (홈):** "오늘 할 일" 카드와 분야 칩 사이에 둔다. `GET /api/ask` 결과이고, 명세 3절의 카드와 선택 칩 모양을 재사용한다.
  - 라벨 "확인이 필요한 공지 {unlock}개", 질문, 선택지 칩, "모르겠어요"를 둔다.
  - 답하면 `PATCH /api/me` 뒤 목록을 다시 받고 "공지 N개가 정리됐어요" 토스트를 띄운다(N = `unlock`).
  - "모르겠어요"는 이번 방문 동안(새로고침 전까지) 그 질문만 숨긴다.
- **상세에서 바로 답하기:** 입력하기 행의 `field`가 되묻기 키면, "입력하기"가 `GET /api/ask?field={field}`의 선택지 칩을 그 행 아래에 펼친다. 답하면 `PATCH /api/me` 뒤 상세와 목록을 다시 받고 같은 토스트를 띄운다.
- **상세 아래 버튼:** 시안의 "정보 입력하고 확인하기"는 늘 내 정보로 가지만, 여기서는 첫 입력하기 행과 같은 일을 한다(되묻기 키면 그 행의 선택지를 펼친다).
- **묶음 박스 (홈):** 시안은 목록 카드 하나 안에 지원 가능 행을 두고 나머지 묶음을 접기 버튼으로 숨긴다. 여기서는 8.1의 네 묶음이 각자 카드가 된다(명세 3절의 카드 모양, 카드 사이 12px). 접기 버튼은 없애고 늘 펴 둔다. 다 펴면 목록이 길어지는 것은 박스 안 세로 스크롤로 막는다.
  - 순서는 시안 그대로다: 지원 가능 → "정보를 더 입력하면 판단할 수 있어요 {n}건" → "아직 확인 중인 공지 {n}개" → "조건이 안 맞는 공지 {n}개".
  - 머리글은 명세 3절의 라벨(14px muted)이고 문구는 위와 같다. 지원 가능 박스만 머리글이 없다. 머리의 큰 제목이 이미 그 수를 말한다.
  - 빈 묶음은 카드를 그리지 않는다(시안의 "비어 있으면 버튼도 없다"와 같다). 분야 필터는 네 묶음에 모두 걸린다.
  - 박스 안 목록은 `max-height` 400px에 넘치면 스크롤한다. 행 높이는 제목과 조건 칩이 줄바꿈해서 일정하지 않으므로 "네 줄"을 재지 않는다. 400px가 대략 네 행이고, 잘린 행이 보이는 것이 "더 있다"는 표시가 된다.
  - 지원 가능이 0개일 때의 두 안내(시안의 "선택한 분야에 맞는 공지가 없어요", "조건에 맞는 공지가 없어요")는 지원 가능 박스 자리에 카드 하나로 그린다.
- **확인 중인 공지 묶음:** 8.1의 4번 묶음도 위의 박스 하나를 받고, 문구는 "아직 확인 중인 공지 {n}개"다. 행의 부제와 상세 판정 문구는 첫 비통과 행의 `gap`이고, 상세 아래 버튼은 그 `gap`을 쓴 비활성 버튼(시안의 지원 불가 버튼 모양)이다.
- **"전체" 분야 칩:** 시안은 보이는 필터 6종을 모두 고르지만, 여기서는 필터를 모두 끈다. 그래야 필터가 없는 창업, 공모전·경진대회, 자격증·어학 공지도 보인다. "전체" 칩은 고른 분야가 없을 때 눌린 모양이다. 첫 홈 필터는 관심 분야 중 필터 6종에 드는 것이고, 하나도 없으면 필터를 걸지 않는다.
- **홈 알약 문구:** 시안의 "공지 새로고침 · 오늘 06:00 확인"은 매일 자동 수집하는 것처럼 읽힌다(12절). 처음에는 "공지 새로고침 · {M}월 {D}일 기준"(`/api/config.today`)으로 쓴다. 새 공지 확인 뒤의 "방금 확인"은 시안 그대로다.
- **원문 시트:** 제목 아래 `path` 한 줄을 둔다(시안의 "{부서} 게시판 · {게시일} 게시" 라벨 위). 출처별 구역마다 "출처 열기" 링크를 달고, `highlights` 구간을 `<mark>`로 강조하고, 열 때 첫 강조로 스크롤한다. `text`가 빈 구역은 구역 머리(label과 링크)만 두고 원문 글 상자를 그리지 않는다(이미지만 있는 공지의 본문 행이 그렇다. 빈 상자는 고장처럼 보인다). 시안의 게시판 링크와 닫기 버튼은 그대로 둔다.
- **새 공지 확인:**
  - 진행 표시를 "n/12"에서 "n/30"으로 바꾼다. 한 칸 72ms로, 시안의 총 시간(약 2.2초)을 지킨다.
  - 진행이 끝나면 `POST /api/reveal-new`를 부른다. 결과가 없으면 "새로 올라온 공지가 없어요" 토스트를 띄운다.
  - 결과가 있으면 그 항목의 묶음(8.1)으로 배너를 띄운다: 1번 "새 기회를 찾았어요" / "{title} · 내 조건으로 지원할 수 있어요", 2번 "새 공지가 올라왔어요" / "{title} · 지금 조건으로는 지원할 수 없어요", 3번 "새 공지가 올라왔어요" / "{title} · 정보를 더 입력하면 확인할 수 있어요"(여기까지 시안), 4번 "새 공지가 올라왔어요" / "{title} · {첫 비통과 행의 gap}".
- **선택 박스 (온보딩, 내 정보):** 명세 5.9의 select 다섯 곳(졸업 예정 연도, 졸업 예정 시기, 마친 학기, IELTS 밴드, OPIc 등급)을 명세 3절의 학과 콤보로 바꾼다. `<select>`는 휴대폰의 스크롤 피커를 열어서, 바로 옆 학과 칸과 모양도 동작도 다르다.
  - 상자와 목록 판은 학과와 같다. 학과만 글자를 칠 수 있고 단과대로 묶어 거른다. 나머지는 `readonly`라 키보드가 올라오지 않는다.
  - 상자의 `value`는 select가 쓰던 값 글자 그대로다(마친 학기는 `"3"`, 졸업 예정 시기는 `"2월"`). 저장 경로(`syncInputs` → 7절 타입 변환)는 바뀌지 않는다.
  - 한 번에 한 판만 열린다. 초점이 들어오면 열고, 나가고 0.15초 뒤에 닫는다(줄을 누를 시간).
- **기준일 안내:** 내 정보의 "처음부터 보기" 위에 "데모 기준일은 3월 16일(월)이에요" 한 줄을 둔다. 날짜는 `/api/config.today`로 만든다. UI (2)에서 시안의 안내 문단이 빠져서 한 줄로 더한다.
- **추천 질문:** `/api/config.suggested_questions`로 바꾼다. 시안의 유학생용 추천 질문 거르기는 하지 않는다. 추천 질문은 신분과 상관없이 답할 수 있는 것으로 고른다.
- **대화 화면:** 8.4 끝의 세 가지(단계는 완료 모양, 0단계 답은 머리글 숨김, 끊긴 스트림은 오류 말풍선)도 이 목록의 변경이다.
- **시안에 없는 문구 (9/19 리허설에서 정함):** API 오류 토스트는 422면 "입력한 값을 확인해 주세요", 그 밖이면 "잠시 후 다시 시도해 주세요"다. 대화의 "바꾸기"(8.4 `confirm_update`) 뒤 토스트는 "내 정보를 바꿨어요"다.

**기존 동작 연결.**
- "마감 알림 받아보기"는 `/api/alerts`에서 `kind`가 `new`가 아닌 첫 항목을 배너로 띄운다. 없으면 "받을 알림이 없어요" 토스트를 띄운다. `body`가 빈 문자열이면 배너의 본문 줄을 뺀다.
- "캘린더 앱에 모두 추가"는 시안처럼 토스트만 띄운다(decisions 17번). 문구도 시안 그대로 "캘린더 앱에 추가했어요 (시안)"이다. 실제로 추가하지 않으므로 "(시안)"을 빼지 않는다.
- 새 공지 확인은 홈의 "공지 새로고침" 알약 버튼으로만 한다. UI (2)에서 내 정보의 "새 공지 확인하기" 버튼이 빠졌다.

### 8.4 `chat` (1등급)

**llm-x 게이트웨이 (`app/llm.py`).** 파일럿에서 잰 특성이다.
- **요청:** `POST {LLM_BASE_URL}/chat`, 헤더 `Authorization: Bearer {LLM_API_KEY}`.
  - 본문: `{"messages": [...], "stream": true, "web_search": false, "thinking_enabled": false}`.
  - OpenAI 호환이 아니고, 도구 호출 기능도 없다.
- **응답:** SSE이고 한 줄이 `data: {json}`이며 `data: [DONE]`으로 끝난다. `[DONE]` 없이 끝나면 끊긴 스트림이므로 게이트웨이 오류다(끊긴 답을 깨진 JSON으로 다시 부르지 않는다).
  - `{"type": "token", "text"}`
  - `{"type": "error"}`
  - `{"event": "tokens_input", "input", "max_input"}`
  - `{"event": "tokens_output", "output", "tps"}` (tps는 없을 때가 있다)
- **스트리밍 필수:** 항상 스트리밍으로 부른다. Cloudflare가 비스트리밍 요청을 약 100초에 끊는다.
- **숨은 system prompt:** 게이트웨이가 모든 호출 앞에 약 3.2k 토큰짜리 system prompt를 붙인다.
- **긴 텍스트는 system 메시지에:** 긴 텍스트를 user 메시지에 넣으면 게이트웨이의 의도 분류기가 약 13k 토큰을 끼워 넣는다. 도구 결과는 전부 system 메시지에 넣고, user 메시지에는 학생 질문만 넣는다.
- **32k 초과는 조용히 잘림:** 입력이 `max_input`(32,768)을 넘어도 에러 없이 조용히 잘린다. `input >= max_input`이면 예외를 던진다.
- **기억 없음:** 게이트웨이는 호출 사이를 기억하지 않는다. 질문 하나를 독립적으로 처리한다(다중 턴은 미결 질문 7번).
- **함수:** `async def chat(messages)`가 `{text, input_tokens, output_tokens, tps, seconds}`를 돌려준다(`tps`는 없으면 `None`). `/api/chat`의 60초 제한이 취소하면 연결도 닫힌다. 실패는 `RuntimeError`(키나 `LLM_BASE_URL` 없음, `error` 이벤트, `max_input` 도달, 읽을 수 없는 줄, `[DONE]` 없음)나 `httpx.HTTPError`다. `thinking_enabled`는 `LLM_THINKING=1`일 때만 켠다. CLI(2등급)는 `asyncio.run`으로 부른다. 키와 `LLM_BASE_URL`은 import할 때가 아니라 호출할 때 읽는다(키가 비어도 서버는 뜬다). 줄 파싱은 `chat`과 따로 부를 수 있는 함수(`parse_lines`)로 두어 네트워크 없이 시험한다. `chat(messages, transport=None)`의 `transport`는 시험용이고(`httpx.MockTransport`), 실제 호출은 `None`이다.

**에이전트 루프.** 질문 하나에 LLM을 최대 5회 부른다. 모델은 매번 JSON 객체 하나만 출력한다.
- 도구 호출: `{"tool": "search_notices", "args": {"query": "교환학생", "category": null}}`
- 답: `{"answer": "...", "refs": ["hq_cat4:11700"], "found": true}`
- 정보 수정 제안: `{"answer": "학점을 3.8로 바꿀까요?", "confirm_update": {"gpa": 3.8}, "refs": [], "found": true}`
- JSON이 깨지면 한 번 다시 부른다. 이것도 5회 예산에 센다.
  - 앞뒤 글자와 코드 펜스는 무시하고 첫 번째로 읽히는 `{...}`를 쓴다(JSON으로 읽히지 않는 `{`는 건너뛴다). `tool`, `answer`, `found`가 하나도 없어도 깨진 것이다. 연달아 두 번 깨지면 답이 없는 것으로 친다.
- **메시지 순서:** `[system 지시문, user 질문, system 이번 질문의 도구 호출과 결과 + "다음 JSON을 내라"]`. 도구 결과를 첫 system 메시지 끝에 붙이면 모델이 결과를 보고도 `found: false`를 냈다(실제 키로 확인).
  - 마지막 system 메시지는 "오늘은 {DEMO_TODAY}이다"로 시작하고, 끝에 Qwen3의 `/no_think`를 붙인다. 게이트웨이의 숨은 system prompt에 실제 날짜가 있어서 모델이 오늘을 헷갈리고 영어로 긴 추론을 냈다(9/20 실제 키로 확인). 도구를 아직 부르지 않았으면 결과 자리에 "아직 도구를 부르지 않았다. 먼저 도구를 불러라"를 넣는다.
- **날짜는 모델이 비교하지 않는다:** 도구 결과의 카드마다 `days_left`(오늘부터 `apply_end`까지 날 수)를 넣는다. 날짜만 주면 모델이 모집 중인 공지를 "마감이 지났다"고 답했다(9/20). 지시문의 예시에는 실제 값을 쓰지 않는다. `confirm_update` 예시("학점을 3.8로 바꿀까요?")를 그대로 답으로 낸 적이 있다.
- **`found: false` 되돌리기:** 모델이 도구를 하나도 부르기 전에 `found: false`를 내면 답으로 치지 않고 "먼저 도구를 불러라"를 넣어 다시 부른다. 도구 결과에 공지가 있는데 `found: false`를 내면 한 번만 "결과에 공지 N건이 있다, 이 결과로 답하라"를 넣어 다시 부른다. 둘 다 예산에 센다. 9/20 실제 키로 돌렸을 때 12번 중 9번이 도구를 하나도 부르지 않고 끝났다(첫 호출에서 system 지시문의 `found: false` 예시를 그대로 냈다).
- 없는 도구나 잘못된 인자(검증에 걸린 `overrides` 포함)는 오류 문구를 도구 결과 자리에 넣고 다시 부른다. 예산에 세고 `step`은 보내지 않는다.

- **같은 호출 반복:** 모델이 이미 결과가 있는 도구·인자를 다시 부르면 실행하지 않고, "이미 결과가 있다, 다음은 방금 검색한 key로 check_eligibility(검색 전이면 빈 검색) 또는 답"을 system 메시지에 넣는다. 예산에는 센다.
- **마지막 호출:** 5번째 호출의 system 메시지에는 "이번이 마지막 답이다, 도구를 부르지 말라"를 넣는다. 그래도 도구를 부르면 실행하지 않고 답이 없는 것으로 친다.

**도구.** 결과는 짧게 잘라 system 메시지에 붙인다.

| 도구 | 하는 일 | 화면 단계 이름 |
|---|---|---|
| `search_notices(query, category?)` | 점검된 카드 전체에서 제목 3배 가중 + 부제·요약·원문의 글자 bigram BM25로 상위 5건. 지난 공지도 `open` 표시와 함께 돌려준다 | 공지 검색 |
| `get_profile()` | 학생 정보 | 내 정보 불러오기 |
| `check_eligibility(notice_keys?, overrides?, category?)` | `judge` 호출. 가정 질문은 overrides로. `notice_keys`가 없으면 열린 공지 전체(`category`를 주면 그 분야만)를 판정해 지원 가능한 것만 마감순으로 20건까지 준다 | 조건 대조 |
| `get_plan()` | 계획한 카드와 남은 할 일 | 내 계획 불러오기 |

- **조회 범위:** `check_ok = 1`, `hidden = 0`, `linked_to IS NULL`, 게시일 ≤ 오늘인 카드. `demo_new`는 공개한 학생만 본다. 도구 넷 모두 이 범위만 본다(`get_plan`도 계획에 넣은 뒤 숨기거나 연결된 카드는 빼고, 그 카드의 할 일도 세지 않는다). `open`은 목록의 신청 기간 조건을 만족하는지다. `search_notices`는 모르는 category를 무시하고, query가 비면 열린 공지를 마감순으로 5건 준다. `check_eligibility`의 `overrides`는 `PATCH /api/me`와 같은 검증을 거친다. `notice_keys`는 1~10개이거나 null이고, 범위 밖 key는 결과의 `not_found`에 적는다. 모두 범위 밖이면 잘못된 인자다. null이면 결과는 `{"summary": "모집 중인 공지 N건 중 M건에 지금 지원할 수 있다", "checked", "eligible", "results": [{"key", "title", "apply_end", "days_left", "category"}]}`이고 단계 설명은 "N건 중 M건 지원 가능"이다. "지금 지원할 수 있는 것", "받을 수 있는 장학금", "이번 달 마감"처럼 공지를 정하지 않은 질문은 검색 5건으로는 답할 수 없어서 더했다(시드 학생은 마감이 가까운 5건이 모두 지원 불가이고, 지원 가능한 첫 카드가 9번째다).
- **도구 결과 모양.** 카드 한 건은 `{"key", "title", "category", "apply_end", "days_left", "open"}`이다. `search_notices`는 `{"items": [카드]}`, `get_profile`은 `{"profile"}`, `get_plan`은 `{"items": [카드 + "tasks": [{"title", "due", "done"}]], "remaining_tasks"}`다. `notice_keys`를 준 `check_eligibility`는 `notice_keys`가 null일 때와 같은 껍데기(`summary`, `checked`, `eligible`, `results`)에 카드마다 `eligible`, `gap`, `conditions`(`label`, `need`, `status`, `have`)를 더하고 `not_found`를 붙인다. 결과 JSON은 1,200자에서 자른다.
- **검색 문서:** 제목(3배) + 부제 + 조건의 `label`·`need`와 `fields`(요약) + 공지 본문 앞 2,000자(원문)의 글자 bigram이다. 색인은 두지 않고 질문마다 점수를 낸다.
- 모르는 category는 `check_eligibility`도 무시한다. 인자가 없는 도구의 `step.arg`는 빈 문자열이다. refs가 0건인 답(정보 수정 제안, 찾지 못함)의 `src`도 "공지 통합 검색"이다.
- **정보 수정:** 도구로 두지 않는다. `confirm_update`가 오면 화면에 "바꾸기" 버튼을 띄우고, 학생이 누르면 `PATCH /api/me`를 보낸 뒤 목록을 다시 받는다(decisions 21번).
- **첨부:** 대화에서 첨부를 읽지 않는다. 카드와 원문 저장본만 조회한다.

**근거 검증 (규칙).**
- `refs`에서 이번 질문의 도구 결과에 나온 key만 남긴다.
- 자격은 `check_eligibility` 결과로만 말하라고 system 메시지에 적는다.
- `found: false`거나 5회 안에 답이 없으면 "공지에서 찾을 수 없어요"라고 답하고 `chat_miss`에 넣는다(위 "`found: false` 되돌리기"로 다시 부른 경우는 빼고).
- 지원 가능한 공지가 없으면 없다고 답한다. 이것은 `found: true`다(system 지시문에 적는다).

**NDJSON 이벤트.** `/api/chat` 응답은 한 줄에 이벤트 하나다.
```
{"type": "step", "title": "공지 검색", "tool": "search_notices", "arg": "query=\"교환학생\"", "detail": "카드 3건", "ms": 820}
{"type": "answer", "text": "...", "refs": [목록 항목], "src": "국제교류팀 공지 · 3월 2일", "confirm_update": null}
{"type": "error", "text": "잠시 후 다시 물어봐 주세요"}
```
- `step`은 도구 호출이 끝날 때마다 보낸다. 실제로 호출한 도구만 보낸다.
  - `arg`는 null이 아닌 인자를 `이름=JSON값`으로 ", "로 잇는다. `ms`는 그 단계의 LLM 호출부터 도구 실행 끝까지다.
  - `detail`: 공지 검색 "카드 N건", 내 정보 "5학기 이수 · 평균 3.52"(`gpa`가 없으면 "5학기 이수"), 조건 대조 "N건 중 M건 지원 가능"(1건이면 "지원 가능" 또는 부족분), 내 계획 "계획 N개 · 남은 할 일 M개".
- `answer.refs`는 걸러낸 key 중 목록에 보이는 카드만 목록 항목으로 준다(지난 공지는 상세가 404라서 뺀다). `src`는 refs가 1건이면 "{dept} 공지 · {M}월 {D}일"(게시일), 아니면 "공지 통합 검색"이다.
- 화면은 시안의 단계 표시, 글자 타이핑 효과, 로고 아바타를 그대로 쓴다. 참고 공지 행은 목록 행과 같은 모양(칩 포함)이다.
  - `step`은 도구가 끝난 뒤에만 오므로 모두 완료 모양으로 그린다. 진행 중 표시는 "생각하는 중" 머리글이다.
  - 단계가 0개인 답(정보 수정 제안, 오류)은 "N단계로 확인했어요" 머리글을 숨긴다.
  - 스트림이 끊기거나 4xx/5xx면 `error` 이벤트와 같은 문구의 말풍선을 띄운다.
- 응답 미디어 타입은 `application/x-ndjson`이다. 라우터는 `app/chat.py`에 두고 `app/main.py` 맨 끝 두 줄이 연결한다. `app/chat.py`는 맨 끝 줄에서 `app.main`을 import한다(그래서 어느 모듈을 먼저 import해도 라우터가 다 만들어진 뒤에 연결된다). 이 순서 때문에 `/api/chat`은 `Depends(current_student)` 대신 헤더를 직접 읽어 `current_student`를 부른다.

**외부 사용자 대비.**
- LLM 동시 실행은 전체 3개다(`asyncio.Semaphore`). 질문이 아니라 llm-x 호출 하나마다 잡는다.
- 학생당 분당 질문은 5개다(메모리 dict, 최근 60초 기준). 6번째는 LLM을 부르지 않고 `error` 이벤트 하나로 끝난다(HTTP 200). 거절한 질문은 세지 않는다.
- 질문 하나 전체 제한 시간은 60초다. 넘거나 게이트웨이 오류가 나면 `error` 이벤트를 보낸다. 그 전까지 보낸 `step`은 그대로 둔다. 오류 문구는 모두 "잠시 후 다시 물어봐 주세요"다.
- 게이트웨이가 읽을 수 없는 줄(JSON이 아니거나 필드가 빠지거나 타입이 틀린 SSE 줄)을 보내거나 `[DONE]` 없이 끊겨도 게이트웨이 오류로 본다. DB 연결 실패도 `error` 이벤트로 끝낸다. 그 밖의 예상 못 한 예외도 스트림을 끊지 않고 로그를 남긴 뒤 `error` 이벤트로 끝낸다. 모델이 문자열이 아닌 `tool`을 내면 잘못된 도구 호출로 되돌려 준다.
- 입력은 300자로 제한한다. 화면은 `maxlength=300`, 서버는 422를 돌려준다. 문자열이 아니거나 공백뿐이어도 422다.

### 8.5 `admin` (2등급)

- `/admin` 전체를 HTTP Basic(`ADMIN_PASSWORD`)으로 막는다. 사용자 이름은 보지 않는다. `ADMIN_PASSWORD`가 비어 있으면 아무도 들어가지 못한다.
- 화면은 `static/admin.html` 한 장이다: 미해결 `review` 목록, 원문 시트, 조건 편집(type, label, need, params, 인용), `apply_end` 입력, 숨김 스위치.
  - 고친 조건도 6.2를 지킨다. params는 6.2 표와 맞아야 하고, 인용은 같은 공지의 `raw_source` 한 행에 글자 그대로 있어야 한다. 원문 시트에서 문장을 드래그하면 인용과 출처가 채워진다. 어기면 422다.
  - 그래서 원문 저장본에 글이 없는 공지(읽지 않은 이미지뿐인 "열람 불가")는 조건을 고칠 수 없고, 숨기거나 마감만 고친다.
  - `apply_end`는 `YYYY-MM-DD`나 null이고, 그 카드의 할 일 `due`보다 이를 수 없다(422). 할 일이 있는 카드는 null로 둘 수 없다(6.5: 마감이 없으면 할 일도 없다).
  - 고친 조건은 바꾸는 `unresolved` 조건의 `id`를 이어받는다(요청의 `id`는 무시). 고친 조건의 type은 `unresolved`일 수 없고, `label`, `need`, `quote`는 비울 수 없다.
- 저장하면 해당 `unresolved` 조건(카드 전체 검토면 첫 번째 `unresolved` 조건)을 바꾼다. 그 검토가 덮는 `unresolved` 조건이 남지 않으면 `review.resolved = 1`로 둔다. 숨김이나 마감만 바꾸면 검토는 대기열에 남는다. 그 검토가 덮는 `unresolved` 조건이 이미 없는데 `condition`을 보내면 422다.
- 정보를 넣은 모든 학생(`profile`이 `{}`가 아닌 학생)을 그 카드에 대해 저장 전후로 판정하고 "학생 N명 재판정 · M명 지원 가능해짐"을 보여준다. N은 판정한 학생 수, M은 `eligible`이 거짓에서 참으로 바뀐 학생 수다. 목록 노출 조건(숨김, 마감)은 따지지 않는다.
- 운영자 API는 7절 계약 밖이고 `/admin` 아래라 같은 비밀번호로 막힌다. `hidden`과 `resolved`는 true·false로 주고받는다. 카드가 없는 검토는 대기열 목록에 넣지 않는다(고칠 것이 없다). 카드도 원문도 없는 key의 원문은 404다.

| 메서드 | 경로 | 요청 | 응답 |
|---|---|---|---|
| GET | `/admin` | | `static/admin.html` |
| GET | `/admin/api/reviews` | | 미해결 검토 id순. `[{review 열, "title", "apply_end", "hidden", "conditions", "url"}]` |
| GET | `/admin/api/notices/{key}/raw` | | 목록에 없는 카드도 된다. `[{"id", "kind", "label", "url", "text", "highlights"}]` |
| PUT | `/admin/api/reviews/{id}` | `{"condition"?, "apply_end"?, "hidden"?}`. 빠진 키는 그대로 둔다. 다른 키는 422 | `{"resolved", "rejudged": N, "newly_eligible": M}`. 404: 없거나 이미 해결된 검토, 카드가 없는 검토. 422 |

### 8.6 `interpret` (2등급)

그림 `kmu-interpret-loop`를 코드로 옮긴다. 실행하면 llm-x를 부르고, 데모에서는 실행하지 않는다.

- **채울 필드:** category, sub, apply_start, apply_end, conditions, fields, 준비할 일
- **도구:**
  - `read_attachment(name)`: PDF는 pypdf로, DOCX·HWPX는 stdlib zipfile의 XML로 변환한다. 나머지 형식은 열람 불가다. 형식은 파일 이름이 아니라 내용으로 가린다(`%PDF`, zip 안의 `word/document.xml` 또는 `Contents/section*.xml`). 받지 못했거나 글자가 없어도 열람 불가다.
  - `read_image(n)`: 준비된 `raw_source(kind='image')`를 조회한다. 없으면 열람 불가다.
  - `follow_link(url)`: `*.kookmin.ac.kr`만 허용한다(리다이렉트 뒤 주소도 본다). HTML은 stdlib `html.parser`로 텍스트를 뽑는다. 링크는 열지 못해도 모델에게 알리기만 하고 열람 불가 조건을 만들지 않는다.
  - `finish`
- **루프:**
  1. LLM이 다음 도구를 고른다.
  2. 코드가 실행해 결과를 `raw_source`에 쓴다.
  3. LLM이 값과 인용을 뽑는다.
  4. 인용 대조 규칙에 걸린 값은 버린다.
  5. 빈 필드가 남고 예산(8콜)이 남았으면 1로 돌아간다.
  - LLM 호출 한 번이 1과 3을 함께 한다. 지금까지 읽은 원문 전부로 카드를 다시 채우고 다음 도구를 고른다. 8콜은 LLM 호출 수이고 깨진 JSON도 센다.
  - 인용 대조나 6.2 표에 걸린 조건은 이유를 붙여 다시 묻는다. 모델이 `finish`를 골라도 버린 값이 있으면 빈 필드로 보고 다시 묻는다.
  - 원문과 결과는 루프가 끝날 때 한 트랜잭션으로 쓴다. 중간에 실패하면 아무것도 쓰지 않는다.
  - 모델 출력: `{"card": {category, sub, apply_start, apply_end, conditions, fields, tasks}, "next": {"tool", "arg"}}` 또는 `{"skip": 이유}`. 조건의 `source`는 읽은 원문 번호(1부터)이고, 쓸 때 `raw_source.id`로 바꾼다. 원문은 system 메시지에 하나당 6천 자, 모두 1만 8천 자까지 싣고, user 메시지에는 key와 제목만 넣는다.
  - 조건 검사: 인용 대조, 6.2 표의 params, `major`의 학과 이름이 화면의 `DEPTS`(`static/index.html`) 안인지. 카드 검사: category 9종, 날짜 형식, `apply_start` ≤ `apply_end`.
  - `finish`를 골랐는데 조건이 비었으면(버린 값은 없고) 더 묻지 않고 못 찾음으로 끝낸다.
- **종료:**
  - 조건을 모두 채웠거나, 인용이 있는 조건 없음(`none`)이면 카드를 쓴다(`interpreted_by = 'agent'`, `check_ok = NULL`).
  - 못 찾음, 열람 불가, `confidence = 'low'`는 `unresolved` 조건과 `review` 행이 된다.
  - 예산이 끝날 때까지 인용 대조에 걸린 조건은 빼지 않고 `unresolved`(못 찾음)로 남긴다. 조건이 조용히 빠지면 지원 가능으로 잘못 보이기 때문이다.
  - `unresolved`로 바뀐 조건은 모델의 label·need를 그대로 쓰고(없으면 "지원 자격"·"확인 중"), 인용 대조에 걸린 것은 quote를 비운다. 판독 저신뢰 이미지를 인용한 조건은 quote와 원문을 남긴다. 열람 불가 파일은 공지당 조건 하나로 묶고 `review.note`에 파일 이름을 적는다. 남은 조건이 없으면 "지원 자격 확인 중"(못 찾음) 하나를 둔다. `review`는 `unresolved` 조건마다 한 행이다.
  - 예산이 끝나도 category를 정하지 못했으면 아무것도 쓰지 않고 실패로 돌려준다(CLI는 종료 코드 1, 수집기는 로그).
  - 기회성 공지가 아니면 모델이 `{"skip": 이유}`를 내고 아무것도 쓰지 않는다. 수집기가 새 공지마다 부르기 때문이다.
  - 다시 돌리면 그 공지의 카드, 할 일, 검토, `raw_source`를 바꾼다. 준비된 이미지 판독본은 남긴다. CLI는 `claude-prep` 카드를 `--force` 없이 덮어쓰지 않는다. 카드의 `linked_to`, `hidden`, `demo_new`는 그대로 두고, 지운 할 일의 `task_done`도 지운다.
- **할 일 날짜:** 6.5의 5번과 같은 규칙이다. 준비 기간 표는 코드 안의 dict다(할 일 이름에 처음 나오는 낱말로 고른다. 신청·제출·접수·지원은 0일, 표에 없으면 1일). 팀 표가 나오기 전까지는 임시 값이다(14절 4번).
- **모델이 내지 않는 것:** `tasks`는 할 일 이름만 내고 `due`는 코드가 위 표로 계산한다. 카드의 `title`과 `dept`는 공지에서 가져온다. `unresolved`는 코드만 붙이므로 모델이 낸 `unresolved` 조건은 버린다.
- **메시지:** system(지시문 + 지금까지 읽은 원문 + 되돌린 이유)과 user(key와 제목) 둘이다. 준비된 판독본이 없는 `read_image`는 열람 불가로 세고 `review.note`에 "이미지 N"으로 적는다.

### 8.7 `collector` (2등급)

그림의 수집기, 스케줄러, 공지 연결을 옮긴다. 앱은 이것을 띄우지 않는다.

- **`sites.json`:** 30곳을 `{"source_id", "name", "engine", "list_url"}`로 적는다. 크롤 데이터(`_all.json`)의 공지 URL에서 뽑았고, 엔진 A의 `list_url`(`.../notice/{n}/index.do`)은 추정이다. 다른 엔진의 `list_url`도 공지 URL에서 글 번호(경로 끝이나 `mode`·`articleNo`·`do`·`bwrite_id` 쿼리)를 뗀 추정이다.
  - 파서는 엔진 A(본교 `www.kookmin.ac.kr/user/kmuNews/notice/{n}` 게시판 8개, 454건)만 구현한다.
    - 목록: 이 게시판의 `{n}/{id}/view.do` 링크마다 한 행이다(상대 주소는 목록 주소로 푼다). 제목은 링크 안의 가장 긴 글, 게시일은 날짜만 있는 칸이다(`2026.04.30`, `-`·`/` 구분, 끝 점 허용). 게시일은 그 링크부터 다음 행 링크 전까지에서 처음 나오는 날짜다. 같은 글의 링크가 여럿이면 한 행으로 합치고 가장 긴 제목을 쓴다. 제목이나 게시일이 없는 행은 로그를 남기고 건너뛴다.
    - 상세: class가 `view_cont` 류(`view_cont`, `view-cont`, `viewcont`가 들어간 것)인 첫 틀 안의 글이 본문, 글이 파일 이름(pdf, hwp, hwpx, doc, docx, xls, xlsx, ppt, pptx, zip, 그림, txt)인 링크가 첨부다. 이름 끝의 괄호(`붙임1.hwp (200KB)`)는 떼고 확장자를 본다. 첨부 링크는 페이지 어디에 있어도 센다. `department`는 채우지 않는다(NULL).
    - 두 규칙 모두 실제 페이지로 확인하지 않은 추정이다. 처음 `--once --dry-run`을 돌려 보고 고친다.
  - 다른 엔진은 로그를 남기고 건너뛴다.
- **`collect_once()`:** 엔진 A 게시판마다 목록 첫 페이지를 받는다. `body_hash`에는 본문이 필요하므로 목록의 공지마다 상세를 받는다. 새 key이거나 `body_hash`가 바뀐 공지만 `notice`에 넣거나 갱신한다(갱신은 제목, 본문, 첨부, `body_hash`, `crawled_at`). `{"new": [key], "changed": [key]}`를 돌려준다.
- **`--once`:** `--schedule`의 한 회(수집, 새 key의 해석과 연결)를 돈다. `--once --dry-run`은 목록만 받아 출력한다. 상세를 받지 않고 DB에 쓰지 않는다. 게시판 하나나 공지 하나를 받지 못하면 로그를 남기고 나머지를 계속한다.
- **`--schedule N`:** N초마다 `collect_once()`를 돈다. 새 key가 있으면 해석하고 연결한다.
  - 바뀐 공지는 `notice`만 갱신하고 카드는 그대로 둔다. 다시 해석하려면 `python -m app.interpret <key>`를 돌린다.
  - 공지 하나의 해석이나 연결이 실패하면 로그만 남긴다. 다음 회에는 새 key가 아니므로 다시 하지 않는다.
- **공지 연결:**
  - 후보는 규칙으로 뽑는다: 정규화한 제목이 같거나 제목 bigram Jaccard ≥ 0.6이고, 게시일 차이가 30일 이내. 제목은 `notice.title`이다.
    - 정규화: `[]`, `()`, `<>`, `【】` 묶음, 공백과 기호, "학년도"를 지우고 소문자로 바꾼다. "2026학년도 1학기"와 "2026-1학기"가 같아진다.
    - 미리 만든 카드 148건에 돌리면 같은 묶음 45쌍을 모두 후보로 내고, 다른 프로그램 13쌍도 후보로 낸다(LLM이 거른다).
    - 비슷한 순서로 5개까지 LLM에 준다.
  - LLM 1회로 같은 프로그램인지 확정하고 `linked_to`를 채운다. 모델은 `{"same": 후보 key 또는 null}`을 낸다. 깨진 JSON이나 후보 밖 key면 연결하지 않는다. 후보가 없으면 LLM을 부르지 않는다. 후보 목록은 system 메시지에, 새 공지의 key와 제목만 user 메시지에 넣는다.
  - 후보는 카드가 있는 공지 전체(대표든 아니든)에서 뽑는다. 고른 후보의 묶음(그 대표와 대표에 연결된 카드 전부)에 새 카드를 더해 대표를 다시 고른다.
  - 대표 카드는 숨기지 않은 카드, 점검한 카드(`check_ok = 1`), 조건 수, 본문 길이 순으로 고른다. 6.5의 6번 규칙에 앞의 두 가지를 더했다(학생 목록에 보이던 카드가 점검 전 카드로 바뀌지 않게). 묶음 전체의 `linked_to`를 새 대표로 다시 쓴다.

## 9. 코드 스타일

```python
def at_least(value, need: float) -> str:
    """value >= need? value is a number, an ask-back range {"min", "max"}, or None."""
    if value is None:
        return "missing"
    if isinstance(value, dict):
        if value["min"] is not None and value["min"] >= need:
            return "pass"
        if value["max"] is not None and value["max"] < need:
            return "fail"
        return "missing"  # the range straddles the threshold
    return "pass" if value >= need else "fail"
```

- 식별자, 주석, 커밋 메시지는 영어로 쓴다. 학생에게 보이는 문구는 한국어이고, UI 시안의 말투를 따른다.
- 함수와 dict를 쓴다. 클래스는 상태가 있을 때만 쓴다. 한 번만 쓰는 추상화는 만들지 않는다.
- SQL은 `?` 파라미터로만 값을 넣는다. 문자열을 이어 붙이지 않는다.
- 라우트는 sync `def`로 쓴다(sqlite3는 블로킹). `/api/chat`만 async 스트리밍이다.
- API 응답은 7절 JSON 모양 그대로 둔다. 필드를 더하거나 빼려면 7절을 먼저 고친다.
- 일부러 한계를 둔 곳에는 `# ponytail: <한계>, <나중에 바꿀 방법>` 주석을 단다.
- 화면 코드는 시안의 스타일(템플릿 문자열, `state` 객체 하나, `render()`)을 유지한다.

## 10. 테스트

- **`tests/test_judge.py`:**
  - 조건 type별로 pass, fail, missing을 확인한다. 구간 값과 `pending`도 확인한다.
  - 행의 `chip`, `tip`, `field`, `ask`와 유학생 판정을 확인한다.
  - 공지 판정, 되묻기 키 선택(`field`를 준 경우 포함), 경계값, `unlock`을 확인한다.
  - 가정 판정이 저장하지 않는지, 알림 세 종류가 맞는지 확인한다.
  - 표 형태(parametrize)로 쓴다.
- **`tests/test_api.py`:** FastAPI `TestClient`와 임시 DB를 쓰고, 테스트 안에서 10.1 A줄에 필요한 카드를 직접 넣는다(대안 A9에는 4개 이상).
  - 흐름: 학생 생성 → 정보 저장 → 목록 → 상세(`alt`) → 되묻기 답(`?field=` 포함) → 목록 변화 → 계획 넣기(409 포함) → 할 일 체크 → 새 공지 공개.
  - 401과 422 경우도 확인한다.
- **`tests/test_chat.py`:** LLM 함수를 가짜로 바꿔 끼운다. 네트워크는 쓰지 않는다.
  - JSON 파싱과 재시도, 5회 예산, refs 걸러내기, `found: false` → `chat_miss`를 확인한다.
  - 301자 입력 → 422를 확인한다.
- **`tests/test_data.py`:** `DB_PATH` 파일이 없거나 카드가 0건이면 skip한다. 있으면 다음을 확인한다.
  - 모든 `quote`가 해당 `raw_source.text`의 부분 문자열이다. 그 `raw_source`는 같은 공지의 행이다. `unresolved`는 `quote`가 비어 있을 수 있다.
  - type과 params가 6.2 표와 맞는다(params 키가 정확히 같고 값의 형식이 맞다). category가 9종 안이다.
  - `unresolved` 조건마다 미해결 `review` 행이 있다. `condition_id`가 그 조건 id이거나 NULL(카드 전체)이다.
  - `linked_to`가 대표 카드(`linked_to IS NULL`인 카드)를 가리킨다.
  - 할 일 `due`가 `apply_end`와 같거나 이전이다. `apply_end`가 NULL인 카드에는 할 일이 없다.
  - `demo_new` 카드가 정확히 1건이다.
  - **시연 준비 검사(`KMU_RELEASE=1`일 때만 돈다):** 숨기지 않은 카드는 모두 `check_ok`가 NULL이 아니고, `DEMO_TODAY`에 목록에 보이는 카드가 1건 이상이고, `demo_new` 카드가 점검됐고 마감 전이다. 팀 점검(6.5의 7번) 전에는 실패하는 것이 맞으므로 평소 `pytest -q`에서는 건너뛴다. 시연 전에 `KMU_RELEASE=1 pytest tests/test_data.py`로 돌린다.
- **테스트 환경:** `app/db.py`, `app/llm.py`가 import할 때 `.env`를 읽으므로, `tests/conftest.py`가 import할 때와 모든 테스트에서 `LLM_API_KEY`, `LLM_BASE_URL`을 비운다(`test_llm.py`가 비었는지 확인한다). LLM을 가짜로 바꾸지 않은 테스트가 실제 게이트웨이를 부르지 않게 하기 위해서다.
- **2등급:** 순수 함수 테스트 하나씩만 둔다. 인용 대조, 첨부 형식 판별, 연결 후보 규칙이다.
- 커버리지 목표는 두지 않는다. 시연 경로(11절)는 브라우저로 직접 확인한다.

### 10.1 반드시 맞아야 하는 예시

9/19 리허설에서 코드와 테스트가 함께 틀렸던 곳, 테스트가 없어서 못 잡았던 곳이다. 앞의 절에 규칙으로 적혀 있어도 구현이 어긋났던 것이 많다. 해당 모듈을 만들 때 이 표의 줄을 그대로 테스트로 옮긴다. 조건 객체는 6.2 모양이고, 오늘은 `DEMO_TODAY = 2026-03-16`이다.

**`judge` (8.1)**

| # | 입력 | 정답 | 리허설에서 |
|---|---|---|---|
| J1 | `semesters` 조건 min 4, 학생 4 | `pass` (기준과 같으면 통과) | 테스트 없음 |
| J2 | `gpa` 조건 min 3.0, 학생 3.0 | `pass`, have "3.00" | 테스트 없음 |
| J3 | `lang` any_of {"TOEIC": 800}, 학생 TOEIC "800" / IELTS 기준 6.0, 학생 "6.0" | 둘 다 `pass` | 테스트 없음 |
| J4 | `lang` any_of {"OPIc": "IM2"}, 학생 OPIc "IH" | `pass` (등급 순서, 알파벳 순서 아님) | 테스트 있음 |
| J5 | `gpa` scope last, 학생 `gpa_last` {"min": 3.8, "max": null} / {"min": 3.5, "max": 3.79} / {"min": 2.0, "max": 2.49} | have "3.8 이상" / "3.5 ~ 3.79" / "2.0 ~ 2.49" (8.1 "평점 숫자"). 한 값은 "3.52" | 코드가 "3.80 이상" |
| J6 | `lang` any_of {"TOEIC": 800, "IELTS": 6.0}, 학생 `langs` {} | `missing`, have "", field "langs", ask "TOEIC이나 IELTS 성적 갖고 계신가요?" (UI (1) 때는 "TOEIC -"이 틀렸었다) | 코드가 "TOEIC -" |
| J7 | 보류 카드 하나에 history flag가 A, B 순서 / B, A 순서 | 되묻기 field "history:A" / "history:B" (카드 안 순서, set 금지). 선택지는 `[{"label": "예", "value": true}, {"label": "아니오", "value": false}]` | 코드가 set을 써서 실행마다 바뀜 |
| J8 | 같은 history flag가 missing인 카드 2개, `gpa_last`가 missing인 카드 1개 | field "history:{flag}", unlock 2 (개수가 먼저, 표 순서는 동률일 때만) | 테스트 없음 |
| J9 | `income_bracket`과 `gpa_last`가 각각 1건씩 동률 / history와 `admission_year` 동률 | `gpa_last` / `admission_year` (6.4 표 순서, history는 맨 뒤) | 테스트 있음 |
| J10 | 학생 `credits_last` {"min": 10, "max": 14}, 보류 카드 기준 12와 15 | unlock 1(15짜리는 fail), 선택지 "12학점 이상" {12, 14}, "12학점 미만" {10, 11}. 앞 답의 구간을 넘지 않는다 | 테스트 없음 |
| J11 | 가정 판정 뒤 입력 학생 dict | 바뀌지 않는다 | 테스트 있음 |
| J12 | `lang` any_of {"TOEIC": 800, "IELTS": 6.0}, 학생 {"TOEIC": "700", "IELTS": "6.5"} / {"TOEIC": "700"} / {"OPIc": "IH"} | `pass`, chip "IELTS 6.0 이상", have "IELTS 6.5", tip "내 어학 성적 IELTS 6.5"(label이 "어학 성적"일 때) / `fail`, gap "TOEIC 800 필요", tip "TOEIC 800 이상 / IELTS 6.0 이상" / `missing`, field null, gap "TOEIC 등 어학 기준 확인 필요", tip은 fail과 같다 | UI (2)로 새로 생김 |
| J13 | 유학생(`history` {"외국인 유학생": true}), `gpa` 3.9(남은 값), `gpa_last` null. `gpa` cumulative min 3.0 / cumulative min 2.0 / last min 3.5 / `lang` 조건 | `pending`, gap "유학생 학점 기준은 별도 확인이 필요해요", field null, have "" / 같다(기준 3.0 미만도 `pending`. 시안은 `pass`) / `missing`, field "gpa_last"(유학생 규칙 밖) / `pending`, gap "유학생 어학 기준은 별도 확인이 필요해요", field null | UI (2)로 새로 생김 |
| J14 | `topik` min 3, 학생 `topik` 0 / 3 / 2 | `missing`, field "topik" / `pass`, have "TOPIK 3급" / `fail`, gap "TOPIK 3급 이상 필요" | UI (2)로 새로 생김 |
| J15 | `gpa` min 3.0, need "3.0 이상", label "평균 학점". 학생 3.52 / 2.80 / null | chip "학점 3.0 이상". tip "내 평균 학점 3.52" / "내 평균 학점 2.80 · 학점 0.20 부족" / "입력하지 않음"(gap "평균 학점 정보 필요", field "gpa", ask "평균 학점을 알려주시면 판단할 수 있어요") | UI (2)로 새로 생김 |
| J16 | 공지 판정: 조건 [pass, missing(field 있음)] / [pass, pending] / [missing(field 있음), fail] / [pending, missing(field 있음)] | 넷 다 `eligible` false, `gap`은 첫 비통과 행의 것. 8.1 묶음은 3번 / 4번 / 2번 / 3번 | UI (2)로 새로 생김 |
| J17 | `history` label "징계 이력", need "없음", flag "징계 이력", must false. 학생 history {"징계 이력": true} / {} / {"징계 이력": false} | 셋 다 chip "징계 이력: 없음". `fail`, gap "징계 이력: 없음", tip "징계 이력: 예 · 징계 이력: 없음" / `missing`, field "history:징계 이력", ask "'징계 이력'에 해당하나요?", gap "징계 이력 정보 필요", tip "입력하지 않음" / `pass`, tip "징계 이력: 아니오" | 문구 규칙이 "없음 대상"을 냈을 것 |
| J18 | `gpa` scope last, min 3.5, label "직전 학기 평점", need "3.5 이상". 학생 `gpa_last` {"min": 3.0, "max": 3.79} / {"min": null, "max": 3.49} | `missing`, field "gpa_last", gap "직전 학기 평점 정보 필요", tip도 같다 / `fail`, gap "3.5 이상 대상" | 규칙이 두 갈래로 읽혔음 |
| J19 | 되묻기: 보류 카드 둘, `income` max 5 / max 6, 학생 `income_bracket` null | 선택지 "7분위 이상" {7, null}, "6분위" {6, 6}, "6분위 미만" {null, 5}, unlock 2 ("6 ~ 6분위"가 아니다) | 테스트 없음 |
| J20 | 되묻기: 보류 카드 `admission_year` {min 2023, max 2026} / `income` max 10과 max 5 / `income` max 10 하나 | 선택지 "2023년 이상" {2023, null}, "2023년 미만" {null, 2022}, "2023년 이상"으로 답하면 그 조건은 `pass` / "6분위 이상" {6, null}, "6분위 미만" {null, 5}, unlock 2 / null. 모든 선택지 값이 `PATCH /api/me` 검증을 통과한다 | 체크포인트 1 검토: "2027년 이상", "11분위 이상"이 나와 PATCH가 422 |

**`student` API (7, 8.2)**

| # | 입력 | 정답 | 리허설에서 |
|---|---|---|---|
| A1 | 카드 `apply_end` = 오늘 / `apply_start` = 오늘 / 공지 게시일 = 오늘 | 셋 다 목록에 있다. `apply_end` = 어제는 없다 | 테스트 없음 |
| A2 | `PATCH /api/me {"history": {"교내장학 수혜": true}}` 두 번째로 다른 flag | 두 flag가 모두 남는다. 키 `"history:교내장학 수혜"`로 보내면 422 | 테스트 있음 |
| A3 | `gpa_last`가 있는 학생에게 `gpa_last` 없는 profile로 `PUT` | `gpa_last`가 사라진다(PUT은 전체 교체) | 테스트 없음 |
| A4 | 본문 `{"gpa": NaN}` | 422 | 테스트 없음 |
| A5 | 빈 profile 학생이 `POST /api/plan/{key}` (조건 있는 카드) | 409 ("확인 필요"도 지원 불가) | 테스트 없음 |
| A6 | 마감 3/30 카드와 3/19 카드를 계획에 넣고 `GET /api/plan` | 3/19가 먼저 | 테스트 없음 |
| A7 | 숨긴 카드에만 `gpa_last` 조건 | `/api/ask`가 그 카드를 세지 않는다 | 테스트 없음 |
| A8 | `POST /api/reveal-new` 두 번 | 두 번째는 `{"items": []}`, 다른 학생 목록에는 NEW가 없다 | 테스트 있음 |
| A9 | `fail` 카드의 상세. 같은 분야의 지원 가능 카드 마감 3/20, 3/18 / 같은 분야가 없고 조건 없는 지원 가능 카드가 있음 / 지원 가능 카드의 상세 | `alt`는 3/18 카드 / 조건 없는 카드 / null | UI (2)로 새로 생김 |
| A10 | `GET /api/ask?field=gpa_last` (그 키가 missing인 카드가 `fail`도 있음) / `?field=gpa` / `?field=history:외국인 유학생` / `?field=없는키` | 카드(그 카드를 센 `unlock`) / 422 / 422 / 422 | UI (2)로 새로 생김 |
| A13 | 알림 셋이 모두 있는 학생의 `GET /api/alerts` / 공지 상세 | `kind`가 `new`, `deadline`, `today` 순서 / `posted_date`가 `notice.posted_date` | UI (2)로 새로 생김 |
| A11 | `PUT /api/me`에 `lang_type` / `langs` {"TOEIC": "999"} / `langs` {"TOEIC": ""} / `topik` 7 | 넷 다 422 | UI (2)로 새로 생김 |
| A12 | `langs` {"TOEIC": "850", "IELTS": "7.0"}인 학생에게 `PATCH {"langs": {"OPIc": "IM2"}}` | `langs`는 {"OPIc": "IM2"}만 남는다(통째로 바꿈, `history`와 다름) | UI (2)로 새로 생김 |

**`chat`, `llm` (8.4)**

| # | 입력 | 정답 | 리허설에서 |
|---|---|---|---|
| C1 | `search_notices(query="")` | 모집 중(`open`) 카드만, 마감 오름차순, 마감 당일 카드 포함 | 코드가 지난 공지도 줌 |
| C2 | `check_eligibility` overrides `{"gpa": 9}` / `{"semesters": 4.5}` / 모르는 키 | PATCH와 같은 검증으로 거절하고, 모델에게 오류로 되돌려 준다(step 없음) | 검증을 지워도 테스트가 통과했음 |
| C3 | 모델 답의 refs에 도구 결과에 없던 key와 마감된 key | 둘 다 빠진다 | 마감 key 제거는 테스트 없음 |
| C4 | 모델이 같은 도구·인자를 다시 부름 | 실행하지 않고 "이미 결과가 있다, 다음은 …"을 넣는다. 예산에는 센다 | 실제 모델이 예산을 다 쓰고 실패 |
| C5 | 5번째 LLM 호출 | system 메시지에 "이번이 마지막 답" 안내가 있다 | 같음 |
| C6 | 모델이 `"tool": ["search_notices"]` | 잘못된 도구로 되돌려 주고 계속한다 | 코드가 TypeError로 스트림을 끊음 |
| C7 | 게이트웨이 줄 `data: {not json` / `input`이 빠진 `tokens_input` | `RuntimeError` → `/api/chat`은 `error` 이벤트 한 줄 | 스트림이 오류 없이 끊김 |
| C8 | 질문 4개 동시, 각 LLM 호출이 느림 | 동시에 도는 llm-x 호출은 최대 3개, 4번째는 기다렸다가 답한다 | 테스트 있음 |
| C9 | 같은 학생 6번째 질문 → 61초 뒤 다시 | 6번째는 `error`, 61초 뒤는 받는다 | 창 만료는 테스트 없음 |
| L1 | `llm.chat`의 HTTP 요청 | `POST {LLM_BASE_URL}/chat`, `Authorization: Bearer {key}`, 본문 `{"messages", "stream": true, "web_search": false, "thinking_enabled": false}`(`LLM_THINKING=1`일 때만 true) | 요청 형식 테스트가 없었음 |

**데이터와 테스트 환경 (6.5, 10)**

| # | 입력 | 정답 |
|---|---|---|
| D1 | 팀 점검 전의 `kmu.db`로 `KMU_RELEASE=1 pytest tests/test_data.py` | 실패("… cards still need the team check") |
| D2 | `.env`에 실제 키가 있는 PC에서 `pytest -q` | 어떤 테스트도 실제 llm-x를 부르지 않는다(`conftest.py`가 키를 지운다) |

## 11. 성공 기준

**시연 경로 (초안, 약 2분).** 각 단계가 새 브라우저에서 그대로 된다.
1. 온보딩: 스플래시 뒤 시드 값으로 두 화면을 통과한다.
2. 홈: "지원할 수 있는 기회가 N개 있어요"와 조건 칩(색, 툴팁)이 보인다. 첫 진입은 관심 분야로 필터가 걸리므로 N은 걸린 분야 안의 수이고, "전체 X개 중"의 X가 `eligible_count`와 같다. 아래에 "정보를 더 입력하면 판단할 수 있어요 M건", "아직 확인 중인 공지 P개", "조건이 안 맞는 공지 K개"가 있다.
3. 상세: 판정(✓/?/✗)과 조건 칩, 입력하기 행이 보인다. 원문 시트에서 인용 문장이 강조되고 출처 링크가 열린다.
4. 되묻기: 홈 카드에 답하면 보류된 공지 `unlock`개의 그 조건이 한꺼번에 정해진다. 상세의 "입력하기"로 그 공지의 행에 바로 답해도 된다.
5. 대화: "학점 3.2여도 ○○ 돼?"에 단계 표시와 함께 답하고, 참고 공지 행이 붙는다.
6. 새 공지 확인: 진행 표시 뒤 NEW 공지와 알림 배너가 뜬다.
7. (선택) 유학생: "혹시 유학생이신가요?"로 들어가면 국적 조건 공지가 "조건이 안 맞는 공지"로 간다.

**그 밖의 기준**
- 두 브라우저는 서로 다른 학생이다. 한쪽의 새 공지 공개와 계획이 다른 쪽에 보이지 않는다.
- 내 정보에서 학점을 바꾸면 개수 문구가 바뀐다.
- 계획 넣기·빼기와 할 일 체크가 새로고침 뒤에도 남는다. 지원 불가 공지는 버튼이 비활성이고, 서버도 409를 돌려준다.
- llm-x 키를 비워 서버를 띄워도 대화 탭 말고는 모두 동작한다. 대화 탭은 "잠시 후 다시" 안내를 띄운다.
- 301자 질문은 거부된다. 동시에 4번째 질문이 오면 기다리거나 시간 초과 안내를 받는다.
- `uvicorn` 한 프로세스, 한 포트로 `/`, `/api`, `/admin`이 모두 열린다.
- `pytest -q`가 통과한다.
- 점검 결과로 정확도 수치(맞음/점검 건수)를 낼 수 있다.

## 12. 경계

**항상**
- 자격 판정은 `judge.py`로만 한다. 판정에서 LLM을 부르지 않는다.
- API 입력(학생 정보, 대화 질문)은 7절 규칙으로 검증한다.
- 커밋 전에 `pytest -q`를 돌린다.
- 화면 문구와 동작은 UI 명세(`docs/ui-spec.md`)를 따른다. 바꾸는 것은 8.3의 목록뿐이다.
- 문제가 생기면 코드와 함께 spec이나 task 문구도 고친다. 당일 가져가는 것은 이 문서다.

**먼저 물어볼 것**
- 6.1 스키마나 6.2 조건 스키마를 바꾸는 것. 이미 만든 `kmu.db`가 깨진다.
- 3절 목록 밖의 의존성을 추가하는 것.
- 8.3 목록 밖의 UI를 바꾸는 것.
- 대화 탭 말고 다른 곳에서 llm-x를 부르는 것.
- 학교 사이트를 실제로 수집하는 것.

**하지 않는 것**
- `.env`를 커밋하지 않는다. 제출용 레포(당일 주최측 레포)에는 `data/`, `kmu.db`도 커밋하지 않는다. 팀이 쓰는 비공개 리허설 레포에는 `data/`를 올린다(첨부 원본과 설치한 라이브러리는 빼고, `.gitignore`).
- llm-x 키를 화면에 내보내거나 브라우저에서 llm-x를 부르지 않는다.
- 실명과 학번을 받지 않는다.
- README나 발표에서 수집과 해석이 실시간으로 돈다고 말하지 않는다. 사전 처리라고 밝힌다.
- 긴 텍스트를 llm-x user 메시지에 넣지 않는다.
- 미리 짠 코드를 행사장에 가져가지 않는다. 가져가는 것은 문서와 DB다.

## 13. decisions.md와 달라진 점

- **수집기, 스케줄러, 공지 해석 에이전트, 공지 연결:** "구현"에서 "2등급(레포 전용)"으로 바뀌었다. 해석 결과와 연결은 3등급 데이터로 미리 만든다.
- **12번 `/admin`:** 2등급으로 바뀌었다. 점검에서 틀린 공지는 DB에서 바로 고치거나 숨긴다.
- **13번 새 공지 확인:** 실시간 해석을 하지 않는다. 미리 만든 카드 1건을 버튼을 누른 학생에게만 공개한다. 그래서 외부 사용자 대비 2번 초기화 명령은 없앤다.
- **16번 할 일 날짜:** 런타임 규칙이 아니라 사전 데이터다. 학생별로는 완료 여부만 저장한다.
- **이미지 판독:** OCR 대신 Claude가 미리 읽은 판독본을 쓴다. 20건 안쪽이고, 나머지는 검토 대기열로 간다.
- **학사안내 조회 도구:** 뺐다.

**UI (2)로 바뀐 것 (9/19 밤).** 상민의 최종 시안을 따른다. 백엔드 코드는 고치지 않고 문서만 고쳤고, 재실행 때 이 문서로 다시 만든다.

| 바뀐 것 | decisions | 고친 곳 |
|---|---|---|
| 서비스 이름 UniQ, 스플래시, 로고 | — | 1, 8.3 |
| 목록이 세 묶음: 지원 가능 / 정보를 더 입력하면 / 조건이 안 맞는. 상세 판정도 셋 | 2번의 "두 갈래"를 바꿈 | 8.1, 14절 8번 해결 |
| 모든 조건을 칩으로(분류별 색, 툴팁). 상세의 조건 행 대신 칩과 입력하기 행 | 11번 | 7 (`chips` → `rows`), 8.1 |
| 어학 성적을 여러 개 받음. IELTS가 시안에 들어옴 | 6번의 "학생당 1개"를 바꿈 | 6.2, 6.4, 7, 8.1 |
| 학점을 비워 둘 수 있음 → "입력하지 않음", 입력하기 행 | — | 6.4, 8.1 |
| 관심 분야를 첫 홈 분야 필터로 씀, "전체" 칩 | 4번의 "저장만"을 바꿈 | 6.4, 14절 11번 |
| 유학생 흐름: 신분, TOPIK, 한국어·문화 분야(9종, 필터 6종), 유학생 학점·어학 기준 | 3번의 "필터 5종, 관심 분야 8종", 8번(유학생 온보딩 추가)을 바꿈 | 6.2 (`topik`), 6.3, 6.4, 8.1 |
| 휴학생은 "재학생" 조건 미충족 | — | 바꿀 것 없음. 데이터의 `status` 조건이 이미 이렇다 |
| 상세: 대안 추천, 자격요건 요약, 준비할 것 체크 | — | 7 (`alt`), 8.2, 8.3 |
| 내 계획: 주·월 보기, 신청 기간 막대 | 15번 | 8.3 (API는 그대로) |
| 새 공지 배너가 판정에 따라 세 가지 | 18번 | 8.3 |
| 되묻기 카드가 시안에 없음 → 유지하고 상세에서 바로 답하기를 더함(9/19 사용자 결정) | 9번 | 7 (`?field=`), 8.1, 8.3 |
| 원문 시트, n/30, 기준일 안내, 추천 질문은 여전히 시안에 없음 → 8.3 UI 변경으로 유지 | 10, 13번 | 8.3 |
| 시안 HTML을 당일 가져갈 수 없어 화면을 `docs/ui-spec.md`(명세), `docs/ui-screens/`(스크린샷), `docs/assets/`(로고)로 옮김. 화면은 가짜 데이터 단계 없이 API에 바로 연결 | — | 3, 5, 8.3, `docs/ui-spec.md` |
| 문서 검토에서 더한 것: 실제 데이터로 그릴 때의 규칙(이스케이프, 날짜, 할 일 id, 입력값 변환), 상세 `posted_date`, 알림 `kind`, `history`·`unresolved` 칩 문구, 평점 숫자 모양 | — | 7, 8.1, 8.3, 10.1 J17~J19, A13 |
| 9/19 밤 정한 것(14절 10~15번): 유학생 누적 학점은 늘 확인 필요, "아직 확인 중인 공지" 묶음(네 묶음), "전체" 칩은 필터 해제, 홈 알약 문구, 칩 문구 일반화 확정, 유학생 데이터는 더하지 않음 | 2, 4번 | 8.1, 8.3, 14 |

## 14. 미결 질문

1. ~~해석할 공지 수~~ 9/19 결정: 444건 중 기회성 공지이면서 제목에 적힌 마감이 3/16 이후이거나 없는 149건을 해석했다(카드 148건). 규칙은 `tasks/todo.md` D1 결과.
2. ~~`DEMO_TODAY` 최종값~~ 9/19 결정: 2026-03-16. 공지 연결 뒤 모집 중인 카드가 가장 많은 날이다(60건, 3/17은 59건).
3. 시연 경로 확정 (11절 초안). 5번 대화 질문에 쓸 실제 공지도 정한다. 9/19 밤 D6에서 추천 질문을 "학점 2.8이어도 자기설계 융합전공 신청할 수 있어?"로 바꿨다(`kyungsang:1818`, 누적 학점 3.0 이상. 시드 학생은 3.52라 가능, 가정 2.8이면 불가). 이전 질문의 일주학술문화재단 장학금은 2학년 대상이라 결과가 뒤집히지 않았다.
4. 서류별 준비 기간 표, 10종 정도 (팀).
5. 학과 목록 공식 편제 대조 (팀). 출처가 나무위키다.
6. 추천 질문 6개 (팀, 실제 데이터를 보고 고른다). 9/19 초안이 `meta.suggested_questions`에 있다.
7. 대화를 다중 턴으로 할지. 초안은 질문 하나씩 독립 처리다.
8. ~~"확인 필요" 공지가 "조건이 안 맞는 공지"에 섞임~~ 9/19 UI (2)에서 "정보를 더 입력하면 판단할 수 있어요" 묶음으로 풀렸다.
9. EC2 포트, 보안 그룹, HTTPS 여부 (지호).
10. ~~유학생의 학점 조건~~ 9/19 결정: 시안은 기준 3.0 미만이면 유학생도 충족한다고 보지만, 근거 없이 "지원할 수 있어요"가 나오므로 누적 학점 조건은 기준과 상관없이 "별도 확인"(`pending`)으로 둔다(8.1).
11. ~~"전체" 분야 칩~~ 9/19 결정: "전체"는 필터를 모두 끈다(9종이 다 보인다). 첫 필터는 관심 분야 중 필터 6종에 드는 것이고, 없으면 걸지 않는다(8.3 UI 변경).
12. ~~유학생 데이터~~ 9/19 결정: 더하지 않는다. D1에서 뺀 "외국인·대학원생 대상" 7건(대학원 과정, 입학 안내 포함)에는 학부 유학생 기회가 거의 없다. 유학생 시연은 국적 조건 8건(3/16 목록에 5건)으로 보인다. 유학생에게 가정 질문 "학점 3.2여도 …"는 누적 학점 조건이면 늘 "별도 확인"이다.
13. ~~칩·툴팁 문구~~ 9/19 결정: 8.1의 일반화 규칙으로 간다. 시안과 조금 다르다: 시안 "나의 이수 학기 5학기", "내 학점 2.80 · 0.20 부족", "학과 정보 필요", "내국인 재학생 대상"은 여기서 "내 이수 학기 5학기", "내 평균 학점 2.80 · 학점 0.20 부족", "전공 정보 필요", "국적: 대한민국 국적자"(8.1 `history` 칩 규칙)가 된다.
14. ~~확인 중 공지~~ 9/19 결정: 입력해도 풀리지 않는 공지(3/16 사본 기준 19건)는 "아직 확인 중인 공지" 묶음으로 따로 접어 둔다(8.1 4번 묶음, 8.3 UI 변경). 목록에서 숨기지는 않는다.
15. ~~홈 알약 문구~~ 9/19 결정: "공지 새로고침 · {M}월 {D}일 기준"으로 바꾼다. 발표에서는 수집과 해석이 사전 처리라고 밝힌다(12절).
