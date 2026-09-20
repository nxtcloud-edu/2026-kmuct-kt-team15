# 실행 기록

자동 실행 모드에서 메인 세션이 채운다. 규칙은 `tasks/plan.md`의 "자동 실행 모드"에 있다.

## 요약

1회차 리허설을 9/20 09:30~11:01에 자동 실행 모드로 돌렸다. 벽시계 1시간 31분, 작업별 소요 시간의 합은 275분(T01~T19)이다. 레인 네 개를 git worktree로 병렬로 돌려 줄였다. 마지막 상태는 `pytest -q` 456 passed 3 skipped이다.

- **완료.** P1, T01~T19, D1~D4, D6. Checkpoint 0~4를 모두 통과했다. 시연 경로 1~15번을 API 호출 순서로 한 번(43개 검사), headless Chrome 클릭으로 한 번(36개 검사) 재현했고 모두 PASS다. 대화는 실제 llm-x 키로 6개 질문을 두 번씩 보내 12회 모두 답했다(6.6~17.9초, `error` 0회).
- **건너뜀.** D5 팀 점검. 팀 4명이 `data/check.html`로 카드를 대조해야 해서 Claude 몫(점검표)만 만들어 두었다. 그래서 정확도 수치가 아직 없고, `KMU_RELEASE=1 pytest tests/test_data.py`는 `data/kmu.db`에서 "148 cards still need the team check"로 3 failed다(점검 전이라 SPEC 10.1 D1대로 맞다). 모두 점검된 것으로 둔 사본 `data/kmu-demo.db`로는 10 passed다.
- **사람 확인 대기.** 6건. 실제 브라우저 눈 확인(Checkpoint 0, T09~T11), `/admin` 화면(HTTP Basic 프롬프트라 자동화하지 않았다), 실제 키로 질문 한 번 보내기(T12), `python -m app.interpret`와 `python -m app.collector --once --dry-run`(둘 다 SPEC 12절의 "먼저 물어볼 것"이라 돌리지 않았다), D5 팀 점검. 아래 "사람 확인 대기" 절에 그대로 있다.
- **막힘.** 1건. T17 서브에이전트가 레포에 없는 커밋을 보고했다. 레인 worktree를 fast-forward 하기 전에 그 에이전트가 정말 끝났는지 확인한다.
- **추측.** 16건. 대부분 `docs/ui-spec.md`와 SPEC 7, 8절이 정하지 않은 빈틈이다. 아래 "추측" 절에 작업별로 있다.
- **spec 수정.** 10건. SPEC 8.1, 8.3~8.7과 `docs/ui-spec.md` 5.8을 코드와 같이 고쳤다. 아래 "spec 수정" 절에 있다.
- **GitHub.** 이슈 #1~#19는 레인 worktree를 PR 없이 main에 직접 합쳐서 `Closes #N`이 걸리지 않았고, 그래서 작업이 끝난 뒤에도 열려 있다. 당일에는 PR로 합치거나 머지한 뒤 바로 닫는다.

## 진행

<!-- 한 줄씩 시간순: `HH:MM T04 완료 (23분)`, `HH:MM Checkpoint 1 통과: pytest 41 passed` -->
- 09:30 T01 완료 (5분). `pytest -q tests/test_db.py` 6 passed. 실제 `_all.json`으로 init·load 두 번: 939행, 테이블 10개, source_id 30종.
- 09:34 T02 완료 (4분). 실제 `data/kmu.db`(카드 148건)로 7 passed, KMU_RELEASE 3 skipped. 빈 DB·없는 DB는 10 skipped. quote 하나를 바꾸면 실패한다. `KMU_RELEASE=1`은 지금 "148 cards still need the team check"로 실패한다(10.1 D1대로, 팀 점검 전이라 맞다).
- 09:40 T03 완료 (12분). `pytest -q` 16 passed 3 skipped. `data/kmu-demo.db` 사본으로 서버를 띄워 `/` 200, `/api/config` = today 2026-03-16 · sources 30 · 추천 질문 6개.
- 09:41 Checkpoint 0 통과. headless Chrome(폭 500px)으로 `/`를 찍어 `docs/ui-screens/01-splash.png`와 대조: 글자 로고·문구·진행 막대 자리가 같다. 탭바는 화면 틀 사본(스크래치)으로 찍어 `06-home.png`의 탭바와 대조했다.
- 09:44 T12 완료 (D 레인). `pytest -q` 39 passed 3 skipped. main에 합침.
- 09:47 T04 완료 (B 레인, 12분). `pytest -q` 102 passed 3 skipped. main에 합침.
- 09:58 T05 완료 (B 레인). `pytest -q` 130 passed 3 skipped. main에 합침. B 레인은 T16까지 대기.
- 09:54 T06 완료 (A 레인, 6분). main에 합침.
- 09:55 T09 완료 (C 레인). main에 합침. `pytest -q` 205 passed 3 skipped.
- 10:04 T07 완료 (A 레인, 5분). `pytest -q` 234 passed 3 skipped. main에 합침.
- 10:05 T08 완료 (A 레인, 4분). A 레인 끝. `pytest -q` 251 passed 3 skipped.
- 10:08 T13 완료 (D 레인). main에 합침. `pytest -q` 286 passed 3 skipped.
- 10:07 Checkpoint 2의 API 부분 통과: `data/kmu-demo.db` 사본으로 시연 경로 1~15번 43개 검사 전부 PASS. 3/16 목록 59건(지원 가능 12 · 조건 안 맞음 11 · 입력하면 확인 17 · 확인 중 19). 원문 시트 강조 구간 81개가 모두 조건 `quote`와 글자 그대로 같다. 브라우저 클릭 확인은 남았다.
- 10:09 T10 완료 (C 레인, 22분). main에 합침. `pytest -q` 286 passed 3 skipped.
- 10:17 T14 완료 (D 레인). main에 합침. `pytest -q` 303 passed 3 skipped. 키를 비운 서버에서 `/api/notices` 200, 301자 422, `/api/chat`이 `error` 한 줄인 것을 확인했다.
- 10:22 T11 완료 (C 레인). main에 합침. `pytest -q` 303 passed 3 skipped.
- 10:26 Checkpoint 1 통과. `pytest -q` 303 passed 3 skipped. 테스트 독립 검토(코드를 짜지 않은 에이전트, 레포 사본): 10.1 J1~J20·A1~A13 누락 없음, 기대값 불일치 없음, **실제 결함 0건**. 돌연변이 80곳 중 62곳이 잡혔고 살아남은 9자리는 테스트 구멍으로 기록했다. API 쪽 3자리는 A 레인이, 판정 쪽 6자리는 B 레인이 T16 뒤에 막는다.
- 10:34 T16, T17, T18, T19와 Checkpoint 1 테스트 구멍 막기를 모두 합쳤다. `pytest -q` 456 passed 3 skipped.
- 10:40 Checkpoint 2 통과. headless Chrome을 DevTools 프로토콜(node 26의 WebSocket)로 몰아 시연 경로를 클릭으로 재현했다: 스플래시 → 온보딩(학과 콤보 검색 포함) → 홈(제목 "2개 있어요", "전체 12개 중", 네 묶음 12/13/5/9) → 칩 툴팁 열고 닫기 → 상세 → 입력하기로 바로 답하기 → 원문 시트 `<mark>` → 홈 되묻기 카드 답 → 토스트 → 계획 넣기 → 내 계획 주·월 → 새 공지 확인(NEW + 배너) → 대화 탭 → 내 정보(기준일 안내, 학점 저장) → 다크 모드. 36개 검사 전부 PASS. 스크린샷은 스크래치의 `shots2/`.
- 10:52 Checkpoint 3: 실제 llm-x 키로 `/api/chat`에 6개 질문을 두 번씩(12회) 보냈다. 12회 모두 답했고 `error` 0회, "공지에서 찾을 수 없어요" 0회, 6.6~17.9초. 시연 질문 "학점 2.8이어도 자기설계 융합전공 신청할 수 있어?"는 두 번 다 단계 두 개(공지 검색 → 조건 대조 "학점 0.20 부족")와 `refs` `kyungsang:1818`로 "지원할 수 없다"고 답했다(checks.md 기대값 그대로). 기록은 스크래치의 `cp3.json`.
- 10:55 Checkpoint 3 화면: headless Chrome으로 대화 탭에서 추천 질문을 눌러 11.1초 만에 "2단계로 확인했어요"와 답 말풍선, 참고 공지 행(칩 포함), "{src} 기준"까지 그려지는 것을 확인했다.
- 10:57 Checkpoint 3 키 없는 서버: `/api/notices` 200(59건), `/api/ask`·`/api/plan`·`/api/alerts`·`/` 200, `/api/chat`은 `{"type": "error", "text": "잠시 후 다시 물어봐 주세요"}` 한 줄, 301자 422, 300자 200, 공백뿐 422.
- 11:00 Checkpoint 4 자동 항목: `pytest -q` 456 passed 3 skipped. 한 프로세스 한 포트에서 `/` 200, `/admin` 비밀번호 없이 401·있으면 200, `/admin/api/reviews` 200. 학점 3.52→2.0으로 `eligible_count` 12→11. 계획 넣기·빼기와 할 일 체크가 다시 GET 해도 남는다. 두 학생이 서로 독립이다(계획, 새 공지 공개). 301자 질문 422. T01~T19 체크박스와 소요 시간이 모두 채워져 있다.
- 11:01 `KMU_RELEASE=1 pytest tests/test_data.py`: `data/kmu.db`에서는 "148 cards still need the team check"로 3 failed(10.1 D1대로, 팀 점검 전이라 맞다). 모두 점검된 사본 `data/kmu-demo.db`로는 10 passed다.
- 11:07 마무리. `pytest -q` 456 passed 3 skipped을 다시 확인하고 맨 위 요약을 썼다. GitHub 이슈 #1~#19는 아직 열려 있다(PR 없이 합쳐서 `Closes #N`이 걸리지 않았다). 닫는 것은 사람 확인 대기다.
## 막힘

<!-- 작업 id, 무엇이 막혔나, 시도한 것, 사람이 정할 것 -->
- T17 (D 레인): 서브에이전트가 "커밋 `b0a5ee6`" 이라고 보고했는데 그 커밋이 레포에 없었다(`git cat-file -t` → Not a valid object name, reflog에도 없음). `app/interpret.py` 660줄만 untracked로 남고 `tests/test_interpret.py`와 SPEC·todo 수정은 없었다. 보고를 받은 뒤 그 worktree에 `git merge --ff-only main`을 돌렸는데, 알고 보니 에이전트가 아직 돌고 있었다. **교훈: 레인 worktree를 fast-forward 하기 전에 그 에이전트가 정말 끝났는지 확인한다.** 같은 에이전트에게 실제 상태를 알려 주고 다시 맡겼다.
## 사람 확인 대기

<!-- 작업 id 또는 체크포인트, 확인할 것 -->
- Checkpoint 0: 실제 브라우저로 `/`를 열어 스플래시와 탭바, 다크 모드를 눈으로 확인 (T03 수동 검증)
- T12 수동 검증: `.env`에 실제 키를 넣고 질문 하나 보내기 (자동 모드에서는 llm-x를 부르지 않는다)
- T09~T11 브라우저 클릭 검증: 화면을 스크린샷과 나란히 놓고 배치·문구 비교, 달력 미끄러짐, 새 공지 확인 진행 표시, 다크 모드
- T16: `/admin` 화면을 브라우저로 열어 보기(HTTP Basic 프롬프트 때문에 자동화하지 않았다)
- T17, T18 수동 실행: `python -m app.interpret <key>`(llm-x 호출)와 `python -m app.collector --once --dry-run`(학교 사이트 수집). 둘 다 먼저 물어볼 항목이라 자동 모드에서 돌리지 않았다. 엔진 A 파서 규칙 두 가지는 그때 고칠 추정이다.
- D5 팀 점검: `data/check.html`로 카드를 대조하고 `data/check.csv`를 채운 뒤 `python data/prep/d5_check.py apply`. 그다음 `KMU_RELEASE=1 pytest tests/test_data.py`가 통과하고 정확도 수치(맞음/점검 건수)가 나온다.
## 추측

<!-- 작업 id, spec의 어느 절, 무엇을 어떻게 추측했나 -->
- T03 / SPEC 10, checks.md: Windows에서 pytest 기본 임시 폴더(`%TEMP%/pytest-of-*`)에 PermissionError가 나서 `pytest.ini`에 `--basetemp=.pytest_tmp`를 두고 `.gitignore`에 넣었다. 명세에 없던 파일이다.
- Checkpoint 0 / checks.md: 탭바는 클릭이 있어야 보이는데 headless Chrome CLI로는 클릭을 못 한다. `static/index.html` 사본의 첫 화면을 home으로 바꿔 찍었다. 레포 파일은 그대로다.
- T12 / SPEC 8.4: SSE 빈 줄과 `:` 주석은 건너뛴다, 모르는 이벤트 이름은 무시한다, 타임아웃 `httpx.Timeout(60.0, connect=10.0)`, 호출마다 `AsyncClient`를 새로 연다.
- T04 / SPEC 8.1: `lang`의 `have`에서 시험 여럿을 잇는 순서는 `LANG_TYPES` 순서로, `langs` 되묻기 문구는 시험이 셋 이상이면 앞의 둘만 쓴다. 6.2 표 밖의 모르는 type은 pending으로 둔다.
- T05 / SPEC 8.1: 같은 `kind` 안 알림 순서는 목록 순서로 정했다. `alerts()` 입력 모양은 7절 목록 항목과 상세 필드를 그대로 쓴다. 되묻기 선택지 라벨은 경계값 기준이고 값만 학생 구간으로 좁힌다.
- T06 / SPEC 7: `POST /api/students`는 200 + `{"id"}`, `created_at`은 로컬 ISO 초 단위. `grad_year` 범위는 7절 값을 `judge.KEY_RANGE`에 합쳤다. `langs` 값은 문자열만 받는다. `history`의 null은 "모름"으로 저장한다. `alt`의 "조건 없는 카드"에 조건 0건도 넣는다.
- T07 / SPEC 7: `POST /api/judge`의 `notice_keys`가 문자열 배열이 아니면 422. 원문 시트에서 `quote`가 그 구역 `text`에 없으면 그 인용만 건너뛴다. `?field=`가 빈 문자열이면 422. `raw_source`가 없는 카드는 `{"path": "", "sections": []}`. `/api/ask`가 없으면 200 + JSON `null`.
- T09 / `docs/ui-spec.md`: 목록을 받기 전 로딩 문구가 없어 목록 카드를 빈 채로 둔다. 상세에 할 일이 없으면 "준비할 것" 구역을 그리지 않는다. 칩 툴팁 열기는 `aria-expanded`와 `@media (hover:hover)` CSS로 한다.
- T08 / SPEC 7: `PUT /api/tasks/{id}`의 `done`이 bool이 아니면 422. `GET /api/plan` 마감 동률은 key 오름차순. `plan.added_at`은 `DEMO_TODAY` 날짜. `reveal-new`의 `items`는 이번에 보이게 된 카드만.
- T13 / SPEC 8.4: 도구 결과 카드 모양, 검색 문서 구성(제목 3배 + 부제 + 조건·요약 + 본문 앞 2,000자), 결과 JSON 1,200자 자르기, 모르는 category는 `check_eligibility`도 무시.
- T10 / `docs/ui-spec.md`: `path` 한 줄은 제목과 게시판 라벨 사이. `text`가 빈 구역은 글 상자를 그리지 않는다. 되묻기 질문은 18px/700. 홈 되묻기 카드 로드 실패는 카드만 숨긴다. `highlights`는 Python 문자 수라 이모지가 있으면 JS `slice`와 어긋난다(인용은 모두 한글).
- T14 / SPEC 8.4: 응답 미디어 타입 `application/x-ndjson`. 60초 제한은 다음 이벤트를 기다리는 동안에만 잰다. 인증 단계의 DB 실패는 평소 예외다. 분당 제한 창은 프로세스 메모리다.
- T11 / `docs/ui-spec.md` 5.8: 고른 날의 처음 값은 오늘. 빈 계획이면 "캘린더 앱에 모두 추가"를 감춘다. 막대 줄 배정은 전체 기간 기준 한 번. "+N"은 그 날 겹치는 공지 전부에서 3을 뺀 수. 진행 중에는 알약만 다시 그린다.
- Checkpoint 2 / checks.md: Claude in Chrome 확장이 연결돼 있지 않아 headless Chrome을 CDP로 직접 몰았다(`node` + 내장 WebSocket). 클릭은 `element.click()`으로 실제 이벤트를 쏜다.
- T18 / SPEC 8.7: `sites.json`의 `list_url` 30곳은 `_all.json`의 공지 URL에서 규칙대로 뽑은 추정이고 실제로 열어 보지 않았다. 첨부 이름 끝의 크기 표기는 떼고 확장자를 본다. 갱신 때 `posted_date`와 `source_name`은 건드리지 않는다.
- T17 / SPEC 8.6: HWP(구형 OLE)는 2등급에서 열람 불가. 모델의 `tasks`는 이름만 받고 `due`는 코드가 계산한다. 준비 기간 표는 임시값이다.
## spec 수정

<!-- 작업 id, 고친 절, 무엇을 왜 -->
- T12 / SPEC 8.4 `chat` 항목: 키와 `LLM_BASE_URL`을 호출할 때 읽는다, 줄 파싱을 따로 부를 수 있는 함수로 두고 `chat(messages, transport=None)`의 `transport`는 시험용이다.
- T04 / SPEC 8.1 "have 문구"와 `ask` 항목: 위 두 가지를 규칙으로 적었다.
- T05 / SPEC 8.1 "알림": 같은 종류 안 순서를 한 구절로 적었다.
- T13 / SPEC 8.4 도구 절: 도구 결과 모양, 검색 문서 구성, 작은 규칙들을 불릿 3개로 적었다.
- T10 / SPEC 8.3 "원문 시트": `path` 한 줄 위치와 빈 구역 처리를 적었다.
- T14 / SPEC 8.4 "NDJSON 이벤트": 미디어 타입, 라우터 자리와 import 순서, 헤더를 직접 읽는 이유를 적었다.
- T11 / `docs/ui-spec.md` 5.8: 고른 날 처음 값과 빈 계획의 버튼 숨김을 스크린샷 근거와 함께 적었다.
- T17 / SPEC 8.6: 모델이 내지 않는 것(`tasks`의 `due`, `title`, `dept`, `unresolved`)과 메시지 구성·판독본 없는 `read_image` 처리.
- T18 / SPEC 8.7: 첨부 이름 끝 괄호(크기 표기)는 떼고 확장자를 본다.
- T16 / SPEC 8.5: `hidden`·`resolved`는 true·false, 카드 없는 검토는 대기열에서 빼고, 카드도 원문도 없는 key의 원문은 404.
