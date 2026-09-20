# 실행 기록

자동 실행 모드에서 메인 세션이 채운다. 규칙은 `tasks/plan.md`의 "자동 실행 모드"에 있다.

## 요약

## 진행

<!-- 한 줄씩 시간순: `HH:MM T04 완료 (23분)`, `HH:MM Checkpoint 1 통과: pytest 41 passed` -->
- 09:30 T01 완료 (5분). `pytest -q tests/test_db.py` 6 passed. 실제 `_all.json`으로 init·load 두 번: 939행, 테이블 10개, source_id 30종.
- 09:34 T02 완료 (4분). 실제 `data/kmu.db`(카드 148건)로 7 passed, KMU_RELEASE 3 skipped. 빈 DB·없는 DB는 10 skipped. quote 하나를 바꾸면 실패한다. `KMU_RELEASE=1`은 지금 "148 cards still need the team check"로 실패한다(10.1 D1대로, 팀 점검 전이라 맞다).
- 09:40 T03 완료 (12분). `pytest -q` 16 passed 3 skipped. `data/kmu-demo.db` 사본으로 서버를 띄워 `/` 200, `/api/config` = today 2026-03-16 · sources 30 · 추천 질문 6개.
- 09:41 Checkpoint 0 통과. headless Chrome(폭 500px)으로 `/`를 찍어 `docs/ui-screens/01-splash.png`와 대조: 글자 로고·문구·진행 막대 자리가 같다. 탭바는 화면 틀 사본(스크래치)으로 찍어 `06-home.png`의 탭바와 대조했다.

## 막힘

<!-- 작업 id, 무엇이 막혔나, 시도한 것, 사람이 정할 것 -->

## 사람 확인 대기

<!-- 작업 id 또는 체크포인트, 확인할 것 -->
- Checkpoint 0: 실제 브라우저로 `/`를 열어 스플래시와 탭바, 다크 모드를 눈으로 확인 (T03 수동 검증)

## 추측

<!-- 작업 id, spec의 어느 절, 무엇을 어떻게 추측했나 -->
- T03 / SPEC 10, checks.md: Windows에서 pytest 기본 임시 폴더(`%TEMP%/pytest-of-*`)에 PermissionError가 나서 `pytest.ini`에 `--basetemp=.pytest_tmp`를 두고 `.gitignore`에 넣었다. 명세에 없던 파일이다.
- Checkpoint 0 / checks.md: 탭바는 클릭이 있어야 보이는데 headless Chrome CLI로는 클릭을 못 한다. `static/index.html` 사본의 첫 화면을 home으로 바꿔 찍었다. 레포 파일은 그대로다.

## spec 수정

<!-- 작업 id, 고친 절, 무엇을 왜 -->
