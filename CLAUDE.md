# 국민대 공지 에이전트

## 먼저 읽을 것
- `SPEC.md`: 무엇을 만드는지. 스키마(6.1), 조건 스키마(6.2), API 계약(7), 모듈별 요구사항(8), 경계(12).
- `tasks/todo.md`: 작업 목록. "T04 해"라고 하면 그 작업 항목을 찾아 "읽을 곳"에 적힌 SPEC 절을 읽고 시작한다.
- 화면 작업이면 `docs/ui-spec.md`(UI 명세)와 `docs/ui-screens/`의 스크린샷을 읽는다. 명세에 없는데 만들 것은 SPEC 8.3 "UI 변경"에 있다. `docs/ui-mockup.html`은 당일에 없는 원본이라 읽지 않는다.

## 작업 규칙
- **작업 하나만 한다.** 끝나면 `tasks/todo.md`의 그 작업 체크박스와 "소요 시간"을 채운다.
- 완료 조건과 검증을 모두 확인한 뒤 끝낸다. 수동 검증을 못 했으면 못 했다고 적는다.
- 테스트는 SPEC 10.1 예시 표에서 그 작업에 해당하는 줄을 먼저 옮기고, 기대값은 코드가 아니라 SPEC에서 가져온다.
- spec이 모자라거나 틀렸으면 코드와 함께 `SPEC.md`도 고친다.
- 커밋 메시지, 식별자, 주석은 영어다. 학생에게 보이는 문구는 한국어이고 UI 시안 말투를 따른다.

## 명령 (SPEC 4절)
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m app.db init                               # 빈 스키마를 DB_PATH에 만든다 (있는 테이블은 건드리지 않음)
python -m app.db load data/notices/_all.json        # notice 적재 (있는 key는 건너뜀)
uvicorn app.main:app --reload --port 8000
pytest -q
```
환경 변수는 `.env`에 둔다. 키 목록은 `.env.example`과 SPEC 4절에 있다.

## 코드 스타일 (SPEC 9절)
- 함수와 dict. 클래스는 상태가 있을 때만. 한 번 쓰는 추상화는 만들지 않는다.
- SQL은 `?` 파라미터로만 값을 넣는다.
- 라우트는 sync `def`. `/api/chat`만 async 스트리밍.
- API 응답은 SPEC 7절 모양 그대로. 바꾸려면 7절을 먼저 고친다.
- 일부러 한계를 둔 곳에는 `# ponytail: <한계>, <나중에 바꿀 방법>` 주석.

## 경계 (SPEC 12절 요약)
**항상**
- 자격 판정은 `app/judge.py`로만. 판정에서 LLM을 부르지 않는다.
- API 입력은 SPEC 7절 규칙으로 검증한다.
- 커밋 전에 `pytest -q`.
- 화면 문구와 동작은 UI 명세를 따른다. 바꾸는 것은 SPEC 8.3 목록뿐이다.

**먼저 물어볼 것**
- 6.1 스키마, 6.2 조건 스키마 변경 (이미 만든 `kmu.db`가 깨진다)
- SPEC 3절 밖의 의존성 추가
- 8.3 목록 밖의 UI 변경
- 대화 탭 말고 다른 곳에서 llm-x 호출
- 학교 사이트 실제 수집

**하지 않는 것**
- `.env` 커밋. 제출용 레포(당일 주최측 레포)에 `data/`, `kmu.db` 커밋 (비공개 리허설 레포에는 `data/`를 올린다. `.gitignore` 참고)
- llm-x 키를 화면에 내보내거나 브라우저에서 llm-x 호출
- 실명, 학번 받기
- 수집과 해석이 실시간으로 돈다고 쓰기 (사전 처리다)
- 긴 텍스트를 llm-x user 메시지에 넣기
