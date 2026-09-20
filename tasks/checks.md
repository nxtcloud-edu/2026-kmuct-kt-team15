# 체크포인트 검사 절차

`tasks/plan.md`의 체크포인트에서 돌리는 검사다. 9/19 리허설에서 메인 세션이 스크립트로 한 것을 절차로 적었다. 당일에는 이 문서를 보고 스크립트를 새로 짜서 돌린다.

공통:
- 서버는 DB 사본으로 띄운다. 팀 점검 전이면 모든 카드를 `check_ok = 1`로 둔 사본(리허설의 `data/kmu-demo.db`)을 복사해서 쓴다. 원본 `kmu.db`에 테스트 학생이 쌓이지 않게 한다.
- `DB_PATH=<사본> DEMO_TODAY=2026-03-16 uvicorn app.main:app --port <빈 포트>`
- 학생 범위 요청은 모두 `X-Student-Id` 헤더를 붙인다.

## Checkpoint 0

- `pytest -q` 통과
- `GET /` 200, `GET /api/config` → `{"today": "2026-03-16", "sources": 30, "suggested_questions": [...]}`
- `/`를 headless Chrome(폭 500px)으로 찍어 `docs/ui-screens/01-splash.png`와 비교한다. 이후 체크포인트에서 화면을 찍을 때도 같은 폭으로 찍어 같은 번호의 스크린샷과 비교한다. Chrome은 창 폭이 500px보다 좁으면 화면이 어긋나게 찍힌다.

## Checkpoint 1: 테스트 독립 검토 (API)

`pytest -q` 통과 뒤에 한다. 리허설에서는 이 검토 한 번에 실제 결함 2건과 SPEC과 반대로 된 테스트 2건이 나왔다.

1. 코드를 짜지 않은 에이전트에게 `SPEC.md`, `app/`, `tests/`만 주고 맡긴다. 레포 파일은 고치지 못하게 한다.
2. 할 일:
   - SPEC 10.1 표의 줄이 모두 테스트로 있는지 확인한다.
   - 테스트 기대값이 SPEC과 다른 곳을 찾는다.
   - 레포 사본에서 코드를 한 줄씩 망가뜨려(`>=` → `>`, 검증 호출 삭제, 필터 삭제 등) 테스트가 잡는지 본다.
3. 결과로 위험 순위 목록을 받는다. 실제 결함과 SPEC 불일치는 이 체크포인트에서 고친다. SPEC과 테스트 중 어느 쪽을 고칠지는 SPEC 쪽이 기본이다.

## Checkpoint 2: 시연 경로 (API 호출 순서)

| 순서 | 호출 | 기대 |
|---|---|---|
| 1 | `POST /api/students` | `{"id"}` (22자) |
| 2 | `PUT /api/me` 시드 값(재학, 5학기, 경영정보학부, 3.52, `langs` {"TOEIC": "850"}, 관심 3개, `history` {"외국인 유학생": false}) | 200, `eligible_count` N. 화면의 홈 "N개"는 첫 분야 필터가 걸린 수라서, 화면에서는 "전체 X개 중"의 X와 비교한다 |
| 3 | `GET /api/notices` | `eligible`이 true인 항목 수 = N. 정렬은 NEW, 그다음 마감순. 항목마다 `rows`가 있고 `chip`, `tip`이 빈 문자열이 아니다. 8.1 네 묶음의 수를 적는다(`fail` 있음, 입력하기 행 있음, 나머지) |
| 4 | `fail` 행이 없고 `field`가 있는 `missing` 행이 있는 카드 하나로 `GET /api/notices/{key}` / `fail` 카드 하나로 같은 요청 | `missing` 행에 `field`와 `ask`가 있다 / `alt`가 목록 항목이거나 null이다. `unresolved`뿐인 카드(입력하기 행 없음)는 여기서 쓰지 않는다 |
| 5 | 같은 key로 `GET /api/notices/{key}/raw` | 각 `highlights` 구간의 글자가 그 카드 조건의 `quote`와 같다 |
| 6 | `GET /api/ask` / 4번 카드의 되묻기 `field`로 `GET /api/ask?field=...` | 되묻기 카드. `unlock` ≥ 1 / 그 키의 카드 |
| 7 | 선택지 하나로 `PATCH /api/me` (history면 `{"history": {flag: 값}}`) | 200. 다시 `GET /api/notices`를 하면 그 키가 missing이던 `unlock`개 카드의 그 행이 pass나 fail이 된다(다른 missing 행이 남은 카드는 묶음이 그대로일 수 있다) |
| 8 | `POST /api/reveal-new` | `demo_new` 카드 1건, `is_new: true` |
| 9 | `POST /api/reveal-new` 다시 | `{"items": []}` |
| 10 | `GET /api/alerts` | 공개한 카드가 지원 가능하면 "새 기회를 찾았어요" |
| 11 | 두 번째 학생을 만들어 `GET /api/notices` | NEW가 없다 |
| 12 | 지원 가능 카드 `POST /api/plan/{key}` / 지원 불가 카드 | 204 / 409 |
| 13 | `GET /api/plan`의 첫 할 일로 `PUT /api/tasks/{id} {"done": true}` 뒤 `GET /api/plan` | 그 할 일이 `done: true` |
| 14 | 헤더 없이 `GET /api/notices` / `PATCH /api/me {"gpa": 9}` / `PUT /api/me`에 `lang_type` | 401 / 422 / 422 |
| 15 | 세 번째 학생을 유학생으로 만들어 `PUT /api/me` (`history` {"외국인 유학생": true}, `topik` 4, `gpa` null, `langs` {}) 뒤 `GET /api/notices` | 국적 조건(`외국인 유학생` must false) 카드는 `fail`, 누적(`cumulative`) `gpa` 조건이 있는 카드는 그 행이 `pending`, 직전 학기(`last`) `gpa` 행은 `missing`(field `gpa_last`) |

화면은 headless Chrome으로 같은 순서를 눌러 본다(새 브라우저 → 스플래시 → 온보딩 → 홈 N개와 네 묶음 → 칩 툴팁 → 상세 → 입력하기로 바로 답하기 → 원문 시트 강조 → 홈 되묻기 카드 → 새 공지 확인 → 내 계획 주·월 보기). 유학생 온보딩("혹시 유학생이신가요?")도 한 번 지난다. 사람이 한 번은 실제 브라우저로 본다.

## Checkpoint 3: 대화

1. 실제 키로 서버를 띄우고, 학생을 만들어 profile을 넣고, 지원 가능 카드 하나를 계획에 넣는다.
2. `POST /api/chat`으로 아래 질문을 보내고 NDJSON 줄을 모두 기록한다(질문마다 걸린 초도 적는다).
   - "학점 2.8이어도 자기설계 융합전공 신청할 수 있어?" → `step` 두 개(공지 검색, 조건 대조: overrides gpa 2.8), 답은 지원할 수 없다(학점 0.20 부족)이고 `answer`에 `kyungsang:1818`이 refs로 붙는다. 시드 학생 그대로(3.52)면 지원 가능이다. 시연 경로 5번이다.
   - "이번 주에 뭐부터 해?" → `get_plan` 단계와 답
   - "지금 받을 수 있는 장학금 있어?", "해외 연수나 교환학생 프로그램 있어?", "이번 달 마감 놓치면 안 되는 거 뭐야?" → 답 또는 "공지에서 찾을 수 없어요"
   - 추천 질문(`meta.suggested_questions`) 전부
3. 같은 질문을 두 번씩 보낸다. 리허설에서는 같은 질문이 한 번은 답하고 한 번은 실패했다. 실패가 나오면 모델 출력을 찍어 원인을 본다(같은 도구 반복, 0건일 때 found:false 등).
4. `LLM_API_KEY=""`로 서버를 다시 띄운다.
   - 목록·되묻기·계획은 200이다.
   - `/api/chat`은 `{"type": "error", "text": "잠시 후 다시 물어봐 주세요"}` 한 줄이다.
   - 301자 질문은 422다.
5. 테스트 독립 검토를 한 번 더 한다(대화·llm 모듈만). SPEC 10.1의 C, L 줄이 테스트로 있는지 본다.

## Checkpoint 4

- `pytest -q` 전부 통과
- 한 서버에서:
  - `/` 200
  - `/admin`은 비밀번호 없이 401, `ADMIN_PASSWORD`로 200
- 학점을 바꾸면(`PATCH /api/me {"gpa": ...}`) `eligible_count`가 바뀐다
- 계획 넣기·빼기와 할 일 체크가 다시 `GET` 해도 남는다
- 두 학생이 서로 독립이다
- 301자 질문은 422다
- 팀 점검(D5) 뒤에 `KMU_RELEASE=1 pytest tests/test_data.py`가 통과한다
