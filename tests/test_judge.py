"""T04, T05: judging, ask-back, assumed values and alerts (SPEC 6.2, 6.4, 8.1).

The tables below carry the examples of SPEC 10.1 J1-J20.
"""

import pytest

from app.judge import (
    KEY_RANGE,
    alerts,
    ask_back,
    judge_condition,
    judge_notice,
    with_overrides,
)

ROW_KEYS = {"type", "label", "need", "status", "have", "gap", "chip", "tip", "field", "ask"}


def cond(ctype, label="", need="", **params):
    """A SPEC 6.2 condition object."""
    return {
        "id": "c1",
        "type": ctype,
        "label": label,
        "need": need,
        "params": params,
        "source_id": 1,
        "quote": "인용",
    }


SEMESTERS = cond("semesters", "이수 학기", "4학기 이상", min=4)
GPA = cond("gpa", "평균 학점", "3.0 이상", min=3.0, scope="cumulative")
GPA_LAST = cond("gpa", "직전 학기 평점", "3.5 이상", min=3.5, scope="last")
LANG = cond("lang", "어학 성적", "TOEIC 800 이상", any_of={"TOEIC": 800, "IELTS": 6.0})
CREDITS = cond("credits", "직전 학기 이수 학점", "12학점 이상", min=12, scope="last")
TOPIK = cond("topik", "한국어능력", "3급 이상", min=3)
RECORD = cond("history", "징계 이력", "없음", flag="징계 이력", must=False)
UNRESOLVED = cond("unresolved", "지원 자격", "확인 중", reason="첨부 열람 불가")
FOREIGN = {"history": {"외국인 유학생": True}, "gpa": 3.9, "gpa_last": None}

# (test id, condition, profile, expected subset of the row)
CASES = [
    # --- semesters, grade, status (10.1 J1) ---
    (
        "J1 semesters equal to the threshold passes",
        SEMESTERS,
        {"semesters": 4},
        {"status": "pass", "have": "4학기", "gap": "", "chip": "4학기 이상",
         "tip": "내 이수 학기 4학기", "field": None, "ask": None},
    ),
    (
        "semesters below the threshold fails",
        SEMESTERS,
        {"semesters": 2},
        {"status": "fail", "have": "2학기", "gap": "이수 학기 2학기 부족",
         "tip": "내 이수 학기 2학기 · 이수 학기 2학기 부족"},
    ),
    (
        "semesters not entered is missing and is not asked back",
        SEMESTERS,
        {},
        {"status": "missing", "have": "", "gap": "이수 학기 정보 필요",
         "tip": "입력하지 않음", "field": None, "ask": None},
    ),
    (
        "grade comes from semesters",
        cond("grade", "학년", "2~4학년", min=2, max=4),
        {"semesters": 4},
        {"status": "pass", "have": "3학년", "tip": "내 학년 3학년"},
    ),
    (
        "grade below the range fails",
        cond("grade", "학년", "2~4학년", min=2, max=4),
        {"semesters": 0},
        {"status": "fail", "have": "1학년", "gap": "2~4학년 대상"},
    ),
    (
        "grade without semesters is missing without a field",
        cond("grade", "학년", "2~4학년", min=2, max=4),
        {},
        {"status": "missing", "gap": "학년 정보 필요", "field": None, "ask": None},
    ),
    (
        "status inside allowed passes",
        cond("status", "학적 상태", "재학생", allowed=["재학"]),
        {"status": "재학"},
        {"status": "pass", "have": "재학", "tip": "내 학적 상태 재학"},
    ),
    (
        "status outside allowed fails",
        cond("status", "학적 상태", "재학생", allowed=["재학"]),
        {"status": "휴학"},
        {"status": "fail", "have": "휴학", "gap": "재학생 대상"},
    ),
    (
        "status not entered is missing without a field",
        cond("status", "학적 상태", "재학생", allowed=["재학"]),
        {},
        {"status": "missing", "field": None, "ask": None},
    ),
    # --- gpa (10.1 J2, J5, J15, J18) ---
    (
        "J2 gpa equal to the threshold passes",
        GPA,
        {"gpa": 3.0},
        {"status": "pass", "have": "3.00", "chip": "학점 3.0 이상"},
    ),
    (
        "J15 gpa tooltip when it passes",
        GPA,
        {"gpa": 3.52},
        {"status": "pass", "chip": "학점 3.0 이상", "tip": "내 평균 학점 3.52"},
    ),
    (
        "J15 gpa tooltip when it fails",
        GPA,
        {"gpa": 2.80},
        {"status": "fail", "have": "2.80", "gap": "학점 0.20 부족",
         "tip": "내 평균 학점 2.80 · 학점 0.20 부족"},
    ),
    (
        "J15 gpa not entered is an onboarding field",
        GPA,
        {"gpa": None},
        {"status": "missing", "have": "", "gap": "평균 학점 정보 필요", "tip": "입력하지 않음",
         "field": "gpa", "ask": "평균 학점을 알려주시면 판단할 수 있어요"},
    ),
    (
        "J5 gpa_last range with an open top end",
        GPA_LAST,
        {"gpa_last": {"min": 3.8, "max": None}},
        {"status": "pass", "have": "3.8 이상"},
    ),
    (
        "J5 gpa_last range inside the threshold",
        GPA_LAST,
        {"gpa_last": {"min": 3.5, "max": 3.79}},
        {"status": "pass", "have": "3.5 ~ 3.79"},
    ),
    (
        "J5 gpa_last range below the threshold",
        GPA_LAST,
        {"gpa_last": {"min": 2.0, "max": 2.49}},
        {"status": "fail", "have": "2.0 ~ 2.49", "gap": "3.5 이상 대상"},
    ),
    (
        "J5 gpa_last single value keeps two decimals",
        GPA_LAST,
        {"gpa_last": 3.52},
        {"status": "pass", "have": "3.52"},
    ),
    (
        "J18 gpa_last range straddling the threshold is missing",
        GPA_LAST,
        {"gpa_last": {"min": 3.0, "max": 3.79}},
        {"status": "missing", "have": "3.0 ~ 3.79", "gap": "직전 학기 평점 정보 필요",
         "tip": "직전 학기 평점 정보 필요", "field": "gpa_last",
         "ask": "직전 학기 평점이 어느 구간인가요?"},
    ),
    (
        "J18 gpa_last range wholly below the threshold fails",
        GPA_LAST,
        {"gpa_last": {"min": None, "max": 3.49}},
        {"status": "fail", "have": "3.49 이하", "gap": "3.5 이상 대상"},
    ),
    # --- lang (10.1 J3, J4, J6, J12) ---
    (
        "J3 TOEIC equal to the threshold passes",
        cond("lang", "어학 성적", "TOEIC 800 이상", any_of={"TOEIC": 800}),
        {"langs": {"TOEIC": "800"}},
        {"status": "pass", "have": "TOEIC 800", "chip": "TOEIC 800 이상"},
    ),
    (
        "J3 IELTS band equal to the threshold passes",
        cond("lang", "어학 성적", "IELTS 6.0 이상", any_of={"IELTS": 6.0}),
        {"langs": {"IELTS": "6.0"}},
        {"status": "pass", "have": "IELTS 6.0", "chip": "IELTS 6.0 이상"},
    ),
    (
        "J4 OPIc compares by grade order",
        cond("lang", "어학 성적", "OPIc IM2 이상", any_of={"OPIc": "IM2"}),
        {"langs": {"OPIc": "IH"}},
        {"status": "pass", "have": "OPIc IH", "chip": "OPIc IM2 이상"},
    ),
    (
        "OPIc below the grade fails",
        cond("lang", "어학 성적", "OPIc IM2 이상", any_of={"OPIc": "IM2"}),
        {"langs": {"OPIc": "IL"}},
        {"status": "fail", "have": "OPIc IL", "gap": "OPIc IM2 필요"},
    ),
    (
        "J6 no lang score at all is the langs onboarding field",
        LANG,
        {"langs": {}},
        {"status": "missing", "have": "", "gap": "어학 정보 필요", "tip": "입력하지 않음",
         "field": "langs", "ask": "TOEIC이나 IELTS 성적 갖고 계신가요?"},
    ),
    (
        "J12 one of the tests meets the threshold",
        LANG,
        {"langs": {"TOEIC": "700", "IELTS": "6.5"}},
        {"status": "pass", "chip": "IELTS 6.0 이상", "have": "IELTS 6.5",
         "tip": "내 어학 성적 IELTS 6.5"},
    ),
    (
        "J12 every listed test falls short",
        LANG,
        {"langs": {"TOEIC": "700"}},
        {"status": "fail", "have": "TOEIC 700", "gap": "TOEIC 800 필요",
         "chip": "TOEIC 800 이상", "tip": "TOEIC 800 이상 / IELTS 6.0 이상"},
    ),
    (
        "J12 holds other tests only, so the standard cannot be checked",
        LANG,
        {"langs": {"OPIc": "IH"}},
        {"status": "missing", "have": "OPIc IH", "field": None, "ask": None,
         "gap": "TOEIC 등 어학 기준 확인 필요", "tip": "TOEIC 800 이상 / IELTS 6.0 이상"},
    ),
    # --- topik (10.1 J14) ---
    (
        "J14 topik 0 is asked again",
        TOPIK,
        {"topik": 0},
        {"status": "missing", "have": "", "gap": "한국어능력(TOPIK) 정보 필요",
         "field": "topik", "ask": "TOPIK 성적 갖고 계신가요?"},
    ),
    (
        "J14 topik at the threshold passes",
        TOPIK,
        {"topik": 3},
        {"status": "pass", "have": "TOPIK 3급", "tip": "내 한국어능력 TOPIK 3급"},
    ),
    (
        "J14 topik below the threshold fails",
        TOPIK,
        {"topik": 2},
        {"status": "fail", "have": "TOPIK 2급", "gap": "TOPIK 3급 이상 필요"},
    ),
    (
        "topik not entered is asked as an onboarding field",
        TOPIK,
        {},
        {"status": "missing", "field": "topik", "gap": "한국어능력(TOPIK) 정보 필요"},
    ),
    # --- credits, income, admission_year, major ---
    (
        "credits_last above the threshold passes",
        CREDITS,
        {"credits_last": 15},
        {"status": "pass", "have": "15학점", "tip": "내 직전 학기 이수 학점 15학점"},
    ),
    (
        "credits_last below the threshold fails",
        CREDITS,
        {"credits_last": 9},
        {"status": "fail", "have": "9학점", "gap": "12학점 이상 대상"},
    ),
    (
        "credits_last not entered is an ask-back field",
        CREDITS,
        {},
        {"status": "missing", "gap": "직전 학기 이수 학점 정보 필요", "field": "credits_last",
         "ask": "직전 학기에 몇 학점을 이수했나요?"},
    ),
    (
        "credits_last range straddling the threshold stays missing",
        CREDITS,
        {"credits_last": {"min": 10, "max": 14}},
        {"status": "missing", "have": "10 ~ 14학점", "field": "credits_last"},
    ),
    (
        "credits scope total reads credits_total",
        cond("credits", "총 이수 학점", "60학점 이상", min=60, scope="total"),
        {"credits_total": 70},
        {"status": "pass", "have": "70학점", "field": None},
    ),
    (
        "income bracket inside the ceiling passes",
        cond("income", "소득 분위", "8분위 이하", max=8),
        {"income_bracket": 5},
        {"status": "pass", "have": "5분위", "tip": "내 소득 분위 5분위"},
    ),
    (
        "income bracket above the ceiling fails",
        cond("income", "소득 분위", "8분위 이하", max=8),
        {"income_bracket": 9},
        {"status": "fail", "have": "9분위", "gap": "8분위 이하 대상"},
    ),
    (
        "income range with an open top end straddles the ceiling",
        cond("income", "소득 분위", "8분위 이하", max=8),
        {"income_bracket": {"min": 7, "max": None}},
        {"status": "missing", "have": "7분위 이상", "field": "income_bracket",
         "ask": "소득 분위가 어느 구간인가요?"},
    ),
    (
        "admission_year inside the range passes",
        cond("admission_year", "입학 연도", "2023~2026년", min=2023, max=2026),
        {"admission_year": 2024},
        {"status": "pass", "have": "2024년"},
    ),
    (
        "admission_year answer with an open end still lands inside the range",
        cond("admission_year", "입학 연도", "2023~2026년", min=2023, max=2026),
        {"admission_year": {"min": 2023, "max": None}},
        {"status": "pass", "have": "2023년 이상"},
    ),
    (
        "admission_year before the range fails",
        cond("admission_year", "입학 연도", "2023~2026년", min=2023, max=2026),
        {"admission_year": 2022},
        {"status": "fail", "have": "2022년", "gap": "2023~2026년 대상"},
    ),
    (
        "admission_year not entered is an ask-back field",
        cond("admission_year", "입학 연도", "2023~2026년", min=2023, max=2026),
        {},
        {"status": "missing", "field": "admission_year", "ask": "입학 연도가 언제인가요?"},
    ),
    (
        "major inside the list passes",
        cond("major", "학과", "소프트웨어학부·인공지능학부", majors=["소프트웨어학부", "인공지능학부"]),
        {"major": "소프트웨어학부"},
        {"status": "pass", "have": "소프트웨어학부", "tip": "내 학과 소프트웨어학부"},
    ),
    (
        "major outside the list fails",
        cond("major", "학과", "소프트웨어학부·인공지능학부", majors=["소프트웨어학부", "인공지능학부"]),
        {"major": "경영학부"},
        {"status": "fail", "gap": "소프트웨어학부·인공지능학부 대상"},
    ),
    (
        "major not entered is an onboarding field",
        cond("major", "학과", "소프트웨어학부·인공지능학부", majors=["소프트웨어학부"]),
        {},
        {"status": "missing", "field": "major", "ask": "학과 정보를 입력해 주시면 확인할 수 있어요"},
    ),
    # --- history (10.1 J17) ---
    (
        "J17 history flag on the wrong side fails",
        RECORD,
        {"history": {"징계 이력": True}},
        {"status": "fail", "chip": "징계 이력: 없음", "gap": "징계 이력: 없음",
         "tip": "징계 이력: 예 · 징계 이력: 없음"},
    ),
    (
        "J17 history flag not answered is asked back",
        RECORD,
        {"history": {}},
        {"status": "missing", "chip": "징계 이력: 없음", "gap": "징계 이력 정보 필요",
         "tip": "입력하지 않음", "field": "history:징계 이력",
         "ask": "'징계 이력'에 해당하나요?"},
    ),
    (
        "J17 history flag on the right side passes",
        RECORD,
        {"history": {"징계 이력": False}},
        {"status": "pass", "chip": "징계 이력: 없음", "have": "아니오",
         "tip": "징계 이력: 아니오"},
    ),
    (
        "history with must true reads the flag the other way",
        cond("history", "편입생", "해당", flag="편입생", must=True),
        {"history": {"편입생": True}},
        {"status": "pass", "have": "예", "tip": "편입생: 예"},
    ),
    (
        "the foreign-student flag is an onboarding field, not an ask-back one",
        cond("history", "국적", "대한민국 국적자", flag="외국인 유학생", must=False),
        {"history": {}},
        {"status": "missing", "field": "history:외국인 유학생",
         "ask": "신분 정보를 입력해 주시면 확인할 수 있어요"},
    ),
    # --- foreign students (10.1 J13) ---
    (
        "J13 cumulative gpa of a foreign student is still being checked",
        GPA,
        FOREIGN,
        {"status": "pending", "have": "", "field": None, "ask": None,
         "gap": "유학생 학점 기준은 별도 확인이 필요해요",
         "tip": "유학생 학점 기준은 별도 확인이 필요해요"},
    ),
    (
        "J13 a low cumulative threshold is pending too, not a pass",
        cond("gpa", "평균 학점", "2.0 이상", min=2.0, scope="cumulative"),
        FOREIGN,
        {"status": "pending", "gap": "유학생 학점 기준은 별도 확인이 필요해요"},
    ),
    (
        "J13 last-term gpa of a foreign student follows the normal rule",
        GPA_LAST,
        FOREIGN,
        {"status": "missing", "field": "gpa_last", "gap": "직전 학기 평점 정보 필요"},
    ),
    (
        "J13 a lang condition of a foreign student is still being checked",
        LANG,
        FOREIGN,
        {"status": "pending", "have": "", "field": None, "ask": None,
         "gap": "유학생 어학 기준은 별도 확인이 필요해요"},
    ),
    # --- none, unresolved ---
    (
        "a none condition always passes",
        cond("none", "지원 자격", "재학생 누구나"),
        {},
        {"status": "pass", "have": "", "gap": "", "chip": "재학생 누구나",
         "tip": "재학생 누구나", "field": None},
    ),
    (
        "an unresolved condition is pending and is never asked back",
        UNRESOLVED,
        {"gpa": 3.5},
        {"status": "pending", "have": "", "chip": "지원 자격 확인 중",
         "gap": "지원 자격 확인 중", "tip": "지원 자격 확인 중", "field": None, "ask": None},
    ),
]


@pytest.mark.parametrize(
    "condition, profile, expected",
    [pytest.param(c, p, e, id=name) for name, c, p, e in CASES],
)
def test_condition_row(condition, profile, expected):
    row = judge_condition(condition, profile)
    assert set(row) == ROW_KEYS
    assert row["type"] == condition["type"]
    assert row["label"] == condition["label"]
    assert row["need"] == condition["need"]
    for key, value in expected.items():
        assert row[key] == value, key


def group(result):
    """The screen's four buckets, read off `rows` (SPEC 8.1 "화면은 네 묶음이다")."""
    if result["eligible"]:
        return 1
    if any(row["status"] == "fail" for row in result["rows"]):
        return 2
    if any(row["ask"] for row in result["rows"]):
        return 3
    return 4


NOTICE_CASES = [
    (
        "J16 pass and a missing row with a field",
        [GPA, CREDITS],
        {"gpa": 3.52},
        False,
        "직전 학기 이수 학점 정보 필요",
        3,
    ),
    (
        "J16 pass and a pending row",
        [GPA, UNRESOLVED],
        {"gpa": 3.52},
        False,
        "지원 자격 확인 중",
        4,
    ),
    (
        "J16 a missing row with a field and a failing row",
        [CREDITS, SEMESTERS],
        {"semesters": 2},
        False,
        "직전 학기 이수 학점 정보 필요",
        2,
    ),
    (
        "J16 a pending row and a missing row with a field",
        [UNRESOLVED, CREDITS],
        {},
        False,
        "지원 자격 확인 중",
        3,
    ),
    (
        "every condition passes",
        [GPA, SEMESTERS],
        {"gpa": 3.52, "semesters": 6},
        True,
        None,
        1,
    ),
    (
        "a card without conditions is eligible",
        [],
        {},
        True,
        None,
        1,
    ),
]


@pytest.mark.parametrize(
    "conditions, profile, eligible, gap, bucket",
    [pytest.param(c, p, e, g, b, id=name) for name, c, p, e, g, b in NOTICE_CASES],
)
def test_notice(conditions, profile, eligible, gap, bucket):
    result = judge_notice({"conditions": conditions}, profile)
    assert set(result) == {"eligible", "gap", "rows"}
    assert result["eligible"] is eligible
    assert result["gap"] == gap
    assert len(result["rows"]) == len(conditions)
    assert group(result) == bucket


# --- T05: ask-back, assumed values, alerts (SPEC 8.1; examples 10.1 J7-J11, J19, J20) ---


def card(key, conditions):
    """A card the way the list hands it to the ask-back rule."""
    return {"key": key, "title": f"공지 {key}", "conditions": conditions}


def flag_cond(flag):
    return cond("history", flag, "해당", flag=flag, must=True)


def income_cond(ceiling):
    return cond("income", "소득 분위", f"{ceiling}분위 이하", max=ceiling)


YES_NO = [{"label": "예", "value": True}, {"label": "아니오", "value": False}]
ADMISSION = cond("admission_year", "입학 연도", "2023~2026년 입학", min=2023, max=2026)
CREDITS15 = cond("credits", "직전 학기 이수 학점", "15학점 이상", min=15, scope="last")
GPA_LAST38 = cond("gpa", "직전 학기 평점", "3.8 이상", min=3.8, scope="last")
GPA_LAST_CHOICES = [
    {"label": "3.5 이상", "value": {"min": 3.5, "max": None}},
    {"label": "3.5 미만", "value": {"min": None, "max": 3.49}},
]

# (test id, visible cards, profile, field, expected card)
ASK_CASES = [
    (
        "J7 history flags are counted in the order of the card",
        [card("n:1", [flag_cond("편입생"), flag_cond("징계 이력")])],
        {},
        None,
        {"field": "history:편입생", "question": "'편입생'에 해당하나요?", "unlock": 1,
         "choices": YES_NO},
    ),
    (
        "J7 the other order picks the other flag",
        [card("n:1", [flag_cond("징계 이력"), flag_cond("편입생")])],
        {},
        None,
        {"field": "history:징계 이력", "question": "'징계 이력'에 해당하나요?", "unlock": 1,
         "choices": YES_NO},
    ),
    (
        "J8 the key that unlocks the most notices wins over the table order",
        [
            card("n:1", [flag_cond("편입생")]),
            card("n:2", [flag_cond("편입생")]),
            card("n:3", [GPA_LAST]),
        ],
        {},
        None,
        {"field": "history:편입생", "question": "'편입생'에 해당하나요?", "unlock": 2,
         "choices": YES_NO},
    ),
    (
        "J9 a tie falls back to the SPEC 6.4 table order",
        [card("n:1", [income_cond(8)]), card("n:2", [GPA_LAST])],
        {},
        None,
        {"field": "gpa_last", "question": "직전 학기 평점이 어느 구간인가요?", "unlock": 1,
         "choices": GPA_LAST_CHOICES},
    ),
    (
        "J9 history flags rank behind every other ask-back key",
        [card("n:1", [flag_cond("편입생")]), card("n:2", [ADMISSION])],
        {},
        None,
        {"field": "admission_year", "question": "입학 연도가 언제인가요?", "unlock": 1,
         "choices": [
             {"label": "2023년 이상", "value": {"min": 2023, "max": None}},
             {"label": "2023년 미만", "value": {"min": None, "max": 2022}},
         ]},
    ),
    (
        "J10 a notice with a fail row is left out and the held range narrows the choices",
        [card("n:1", [CREDITS]), card("n:2", [CREDITS15])],
        {"credits_last": {"min": 10, "max": 14}},
        None,
        {"field": "credits_last", "question": "직전 학기에 몇 학점을 이수했나요?", "unlock": 1,
         "choices": [
             {"label": "12학점 이상", "value": {"min": 12, "max": 14}},
             {"label": "12학점 미만", "value": {"min": 10, "max": 11}},
         ]},
    ),
    (
        "J19 two income ceilings give a one-bracket middle choice",
        [card("n:1", [income_cond(5)]), card("n:2", [income_cond(6)])],
        {},
        None,
        {"field": "income_bracket", "question": "소득 분위가 어느 구간인가요?", "unlock": 2,
         "choices": [
             {"label": "7분위 이상", "value": {"min": 7, "max": None}},
             {"label": "6분위", "value": {"min": 6, "max": 6}},
             {"label": "6분위 미만", "value": {"min": None, "max": 5}},
         ]},
    ),
    (
        "J20 a boundary outside the key range is dropped",
        [card("n:1", [income_cond(10)]), card("n:2", [income_cond(5)])],
        {},
        None,
        {"field": "income_bracket", "question": "소득 분위가 어느 구간인가요?", "unlock": 2,
         "choices": [
             {"label": "6분위 이상", "value": {"min": 6, "max": None}},
             {"label": "6분위 미만", "value": {"min": None, "max": 5}},
         ]},
    ),
    (
        "J20 a key with no boundary left is not asked at all",
        [card("n:1", [income_cond(10)])],
        {},
        None,
        None,
    ),
    (
        "J20 that key is null when it is asked by name too",
        [card("n:1", [income_cond(10)])],
        {},
        "income_bracket",
        None,
    ),
    (
        "a fixed key also gathers notices that have a fail row",
        [card("n:1", [GPA_LAST, SEMESTERS])],
        {"semesters": 2},
        "gpa_last",
        {"field": "gpa_last", "question": "직전 학기 평점이 어느 구간인가요?", "unlock": 1,
         "choices": GPA_LAST_CHOICES},
    ),
    (
        "a notice with a fail row is never picked on its own",
        [card("n:1", [GPA_LAST, SEMESTERS])],
        {"semesters": 2},
        None,
        None,
    ),
    (
        "nothing is held back, so there is no question",
        [card("n:1", [SEMESTERS])],
        {"semesters": 6},
        None,
        None,
    ),
    (
        "a fixed key with no missing row anywhere is null",
        [card("n:1", [GPA_LAST])],
        {"gpa_last": 3.9},
        "gpa_last",
        None,
    ),
    (
        "onboarding keys are never counted",
        [card("n:1", [GPA, LANG])],
        {},
        None,
        None,
    ),
    (
        "two grade thresholds name the middle band by the next boundary",
        [card("n:1", [GPA_LAST]), card("n:2", [GPA_LAST38])],
        {},
        None,
        {"field": "gpa_last", "question": "직전 학기 평점이 어느 구간인가요?", "unlock": 2,
         "choices": [
             {"label": "3.8 이상", "value": {"min": 3.8, "max": None}},
             {"label": "3.5 ~ 3.8", "value": {"min": 3.5, "max": 3.79}},
             {"label": "3.5 미만", "value": {"min": None, "max": 3.49}},
         ]},
    ),
]


@pytest.mark.parametrize(
    "cards, profile, field, expected",
    [pytest.param(c, p, f, e, id=name) for name, c, p, f, e in ASK_CASES],
)
def test_ask_back(cards, profile, field, expected):
    assert ask_back(cards, profile, field) == expected


@pytest.mark.parametrize(
    "field", ["gpa", "langs", "major", "topik", "history:외국인 유학생", "없는키"]
)
def test_ask_back_rejects_a_key_without_a_question(field):
    with pytest.raises(ValueError):
        ask_back([card("n:1", [GPA_LAST])], {}, field)


def test_every_choice_stays_inside_the_profile_validation_range():
    """J20: every choice value has to survive PATCH /api/me (SPEC 7, 8.1 step 3)."""
    cards = [
        card("n:1", [GPA_LAST]),
        card("n:2", [CREDITS]),
        card("n:3", [income_cond(5)]),
        card("n:4", [ADMISSION]),
    ]
    profile, asked = {}, []
    while True:
        result = ask_back(cards, profile, None)
        if result is None:
            break
        key = result["field"]
        low, high = KEY_RANGE[key]
        for choice in result["choices"]:
            for end in (choice["value"]["min"], choice["value"]["max"]):
                if end is None:
                    continue
                assert low <= end <= high
                if key not in ("gpa", "gpa_last"):
                    assert isinstance(end, int)
        asked.append(key)
        profile = dict(profile)
        profile[key] = result["choices"][0]["value"]
    assert asked == ["gpa_last", "credits_last", "income_bracket", "admission_year"]


def test_answering_a_choice_settles_the_condition():
    """J20: answering "2023년 이상" makes that admission_year condition pass."""
    result = ask_back([card("n:1", [ADMISSION])], {}, None)
    top = result["choices"][0]["value"]
    assert judge_condition(ADMISSION, {"admission_year": top})["status"] == "pass"
    bottom = result["choices"][-1]["value"]
    assert judge_condition(ADMISSION, {"admission_year": bottom})["status"] == "fail"


def test_overrides_leave_the_given_profile_alone():
    """J11: assumed judging never touches the profile it was handed."""
    profile = {"gpa": 3.0, "history": {"편입생": True}, "langs": {"TOEIC": "850"}}
    merged = with_overrides(profile, {"gpa": 3.2, "history": {"징계 이력": False}})
    assert profile == {"gpa": 3.0, "history": {"편입생": True}, "langs": {"TOEIC": "850"}}
    assert merged["gpa"] == 3.2
    assert merged["history"] == {"편입생": True, "징계 이력": False}
    assert merged["langs"] == {"TOEIC": "850"}
    assert judge_condition(GPA, merged)["status"] == "pass"
    assert judge_condition(GPA, profile)["status"] == "pass"


def test_overrides_replace_langs_whole():
    profile = {"langs": {"TOEIC": "850", "IELTS": "7.0"}}
    merged = with_overrides(profile, {"langs": {"OPIc": "IM2"}})
    assert merged["langs"] == {"OPIc": "IM2"}
    assert profile["langs"] == {"TOEIC": "850", "IELTS": "7.0"}


TODAY = "2026-03-16"


def test_alerts_come_in_the_spec_order():
    items = [
        {"key": "n:1", "title": "OK프렌즈 서포터즈", "apply_end": "2026-03-25", "is_new": True,
         "planned": False, "conditions": [], "tasks": []},
        {"key": "n:2", "title": "성적우수 장학금", "apply_end": "2026-03-19", "is_new": False,
         "planned": True, "conditions": [], "tasks": []},
        {"key": "n:3", "title": "교내 근로", "apply_end": "2026-03-30", "is_new": False,
         "planned": True, "conditions": [],
         "tasks": [{"title": "성적증명서 발급", "due": TODAY, "done": False},
                   {"title": "신청서 제출", "due": "2026-03-30", "done": False}]},
    ]
    got = alerts(items, {}, TODAY)
    assert [a["kind"] for a in got] == ["new", "deadline", "today"]
    assert got[0] == {"kind": "new", "title": "새 기회를 찾았어요",
                      "body": "OK프렌즈 서포터즈 · 내 조건으로 지원할 수 있어요", "notice_key": "n:1"}
    assert got[1] == {"kind": "deadline", "title": "성적우수 장학금 마감이 3일 남았어요",
                      "body": "", "notice_key": "n:2"}
    assert got[2] == {"kind": "today", "title": "오늘 할 일", "body": "성적증명서 발급",
                      "notice_key": "n:3"}


def test_alerts_only_when_the_condition_holds():
    items = [
        {"key": "n:1", "title": "새 공지", "apply_end": "2026-03-25", "is_new": True,
         "planned": False, "conditions": [GPA], "tasks": []},            # not eligible
        {"key": "n:2", "title": "마감이 먼 공지", "apply_end": "2026-03-20", "is_new": False,
         "planned": True, "conditions": [], "tasks": []},                # today + 4
        {"key": "n:3", "title": "계획에 없는 공지", "apply_end": "2026-03-19", "is_new": False,
         "planned": False, "conditions": [], "tasks": []},               # not planned
        {"key": "n:4", "title": "다 끝낸 공지", "apply_end": "2026-03-30", "is_new": False,
         "planned": True, "conditions": [],
         "tasks": [{"title": "신청서 제출", "due": TODAY, "done": True}]},
    ]
    assert alerts(items, {"gpa": 2.0}, TODAY) == []
