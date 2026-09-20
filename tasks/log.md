# 실행 기록

자동 실행 모드에서 메인 세션이 채운다. 규칙은 `tasks/plan.md`의 "자동 실행 모드"에 있다.

## 요약

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
## 막힘

<!-- 작업 id, 무엇이 막혔나, 시도한 것, 사람이 정할 것 -->

## 사람 확인 대기

<!-- 작업 id 또는 체크포인트, 확인할 것 -->
- Checkpoint 0: 실제 브라우저로 `/`를 열어 스플래시와 탭바, 다크 모드를 눈으로 확인 (T03 수동 검증)
- T12 수동 검증: `.env`에 실제 키를 넣고 질문 하나 보내기 (자동 모드에서는 llm-x를 부르지 않는다)
- T09~T11 브라우저 클릭 검증: 화면을 스크린샷과 나란히 놓고 배치·문구 비교, 달력 미끄러짐, 새 공지 확인 진행 표시, 다크 모드
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
## spec 수정

<!-- 작업 id, 고친 절, 무엇을 왜 -->
- T12 / SPEC 8.4 `chat` 항목: 키와 `LLM_BASE_URL`을 호출할 때 읽는다, 줄 파싱을 따로 부를 수 있는 함수로 두고 `chat(messages, transport=None)`의 `transport`는 시험용이다.
- T04 / SPEC 8.1 "have 문구"와 `ask` 항목: 위 두 가지를 규칙으로 적었다.
- T05 / SPEC 8.1 "알림": 같은 종류 안 순서를 한 구절로 적었다.
- T13 / SPEC 8.4 도구 절: 도구 결과 모양, 검색 문서 구성, 작은 규칙들을 불릿 3개로 적었다.
- T10 / SPEC 8.3 "원문 시트": `path` 한 줄 위치와 빈 구역 처리를 적었다.
- T14 / SPEC 8.4 "NDJSON 이벤트": 미디어 타입, 라우터 자리와 import 순서, 헤더를 직접 읽는 이유를 적었다.
- T11 / `docs/ui-spec.md` 5.8: 고른 날 처음 값과 빈 계획의 버튼 숨김을 스크린샷 근거와 함께 적었다.
