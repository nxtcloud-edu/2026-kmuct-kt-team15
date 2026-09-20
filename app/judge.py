"""Eligibility judging (SPEC 6.2, 6.4, 8.1).

Pure functions: the input is a card dict and a student profile dict. This module
knows nothing about the DB or the LLM (SPEC 12).
"""

from datetime import date, timedelta

LANG_TYPES = ["TOEIC", "TOEFL iBT", "IELTS", "TOEIC Speaking", "OPIc"]
OPIC_GRADES = ["NL", "NM", "NH", "IL", "IM1", "IM2", "IM3", "IH", "AL"]
FOREIGN_FLAG = "외국인 유학생"

# SPEC 7 "학생 정보 검증": the range of every numeric profile key. A null range end
# means this limit when judging (SPEC 6.4 "구간의 null 끝").
KEY_RANGE = {
    "semesters": (0, 8),
    "gpa": (0, 4.5),
    "gpa_last": (0, 4.5),
    "topik": (0, 6),
    "credits_last": (0, 30),
    "credits_total": (0, 250),
    "income_bracket": (0, 10),
    "admission_year": (2000, 2026),
}

# The ask-back keys in SPEC 6.4 table order, which breaks ties in step 2 of the
# ask-back rule. `history:{flag}` keys rank after all of these.
ASK_ORDER = ["gpa_last", "credits_last", "credits_total", "income_bracket", "admission_year"]

# SPEC 8.1 "질문 문구는 키별 고정 틀이다". `history:{flag}` has its own template.
QUESTIONS = {
    "gpa_last": "직전 학기 평점이 어느 구간인가요?",
    "credits_last": "직전 학기에 몇 학점을 이수했나요?",
    "credits_total": "지금까지 이수한 학점은 어느 구간인가요?",
    "income_bracket": "소득 분위가 어느 구간인가요?",
    "admission_year": "입학 연도가 언제인가요?",
}

# Unit suffix of a numeric key, used by `have` ranges and by the ask-back choices.
UNITS = {
    "gpa": "",
    "gpa_last": "",
    "credits_last": "학점",
    "credits_total": "학점",
    "income_bracket": "분위",
    "admission_year": "년",
}


def at_least(value, need) -> str:
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


def at_most(value, need) -> str:
    """value <= need? Same value shapes as at_least (SPEC 6.2 `income`)."""
    if value is None:
        return "missing"
    if isinstance(value, dict):
        if value["max"] is not None and value["max"] <= need:
            return "pass"
        if value["min"] is not None and value["min"] > need:
            return "fail"
        return "missing"
    return "pass" if value <= need else "fail"


def between(value, low, high) -> str:
    """low <= value <= high, where a None end is open (SPEC 6.2 `grade`, `admission_year`)."""
    if value is None:
        return "missing"
    if isinstance(value, dict):
        inside_low = low is None or (value["min"] is not None and value["min"] >= low)
        inside_high = high is None or (value["max"] is not None and value["max"] <= high)
        if inside_low and inside_high:
            return "pass"
        if high is not None and value["min"] is not None and value["min"] > high:
            return "fail"
        if low is not None and value["max"] is not None and value["max"] < low:
            return "fail"
        return "missing"
    if low is not None and value < low:
        return "fail"
    if high is not None and value > high:
        return "fail"
    return "pass"


def gpa_text(value) -> str:
    """A grade-point range end (SPEC 8.1 "평점 숫자"): 3.80 -> "3.8", 3.79 -> "3.79"."""
    text = f"{float(value):.2f}"
    return text[:-1] if text.endswith("0") else text


def resolve_range(value, key):
    """A range's null end means that key's own limit (SPEC 6.4)."""
    if not isinstance(value, dict):
        return value
    low, high = KEY_RANGE[key]
    return {
        "min": low if value.get("min") is None else value["min"],
        "max": high if value.get("max") is None else value["max"],
    }


def range_text(value, unit, is_gpa=False) -> str:
    """The stored range as `have` shows it (SPEC 8.1): "7분위 이상", "12 ~ 14학점"."""
    low, high = value.get("min"), value.get("max")
    fmt = gpa_text if is_gpa else (lambda v: str(int(v)))
    if low is not None and high is not None:
        if low == high:
            return f"{fmt(low)}{unit}"
        return f"{fmt(low)} ~ {fmt(high)}{unit}"
    if low is not None:
        return f"{fmt(low)}{unit} 이상"
    if high is not None:
        return f"{fmt(high)}{unit} 이하"
    return ""


def value_text(value, unit, is_gpa=False) -> str:
    """The `have` text of one numeric profile value (SPEC 8.1 "have 문구")."""
    if value is None:
        return ""
    if isinstance(value, dict):
        return range_text(value, unit, is_gpa)
    if is_gpa:
        return f"{float(value):.2f}"
    return f"{value}{unit}"


def score_text(test, score) -> str:
    """A lang threshold as chips and tooltips show it. IELTS keeps one decimal (SPEC 8.1)."""
    if isinstance(score, str):
        return score
    if test == "IELTS":
        return f"{float(score):.1f}"
    number = float(score)
    return str(int(number)) if number.is_integer() else str(number)


def lang_ok(test, have, need) -> bool:
    """Does one held score meet the threshold? OPIc compares by grade order (SPEC 6.2)."""
    if test == "OPIc":
        have, need = str(have).upper(), str(need).upper()
        if have not in OPIC_GRADES or need not in OPIC_GRADES:
            return False
        return OPIC_GRADES.index(have) >= OPIC_GRADES.index(need)
    try:
        return float(have) >= float(need)
    except (TypeError, ValueError):
        return False


def ask_text(field, params) -> str:
    """The "입력하기" wording of a row (SPEC 8.1 `ask`)."""
    if field == "gpa":
        return "평균 학점을 알려주시면 판단할 수 있어요"
    if field == "major":
        return "학과 정보를 입력해 주시면 확인할 수 있어요"
    if field == "topik":
        return "TOPIK 성적 갖고 계신가요?"
    if field == "langs":
        # ponytail: the wording names at most two tests, the rest of any_of is dropped.
        # A third test would need a new template in SPEC 8.1.
        tests = list((params.get("any_of") or {}))
        if len(tests) == 1:
            return f"{tests[0]} 성적 갖고 계신가요?"
        return f"{tests[0]}이나 {tests[1]} 성적 갖고 계신가요?"
    if field.startswith("history:"):
        flag = field.split(":", 1)[1]
        if flag == FOREIGN_FLAG:
            return "신분 정보를 입력해 주시면 확인할 수 있어요"
        return f"'{flag}'에 해당하나요?"
    return QUESTIONS[field]


def _tip(label, need, status, have, gap, flag=None) -> str:
    """Tooltip wording shared by every type (SPEC 8.1 "툴팁 문구")."""
    if status in ("pass", "fail"):
        if flag is not None:
            base = f"{flag}: {have}"
        else:
            base = f"내 {label} {have}" if have else need
        return base if status == "pass" else f"{base} · {gap}"
    if status == "missing":
        return gap if have else "입력하지 않음"
    return gap  # pending


def judge_condition(cond, profile):
    """One condition -> one row of SPEC 7 `rows` (SPEC 8.1 "조건 하나의 판정")."""
    ctype = cond.get("type")
    label = cond.get("label") or ""
    need = cond.get("need") or ""
    params = cond.get("params") or {}
    history = profile.get("history") or {}
    foreign = history.get(FOREIGN_FLAG) is True

    chip = need
    field = None
    flag = None
    tip = None
    gap = None
    fail_gap = f"{need} 대상"  # SPEC 8.1 default for `fail`
    miss_gap = f"{label} 정보 필요"  # SPEC 8.1 default for `missing`

    if ctype == "none":
        status, have = "pass", ""
    elif ctype == "unresolved":
        status, have = "pending", ""
        chip = f"{label} {need}".strip()
    elif ctype == "semesters":
        value = profile.get("semesters")
        status = at_least(resolve_range(value, "semesters"), params["min"])
        have = value_text(value, "학기")
        if status == "fail" and not isinstance(value, dict):
            fail_gap = f"이수 학기 {params['min'] - value}학기 부족"
    elif ctype == "grade":
        semesters = profile.get("semesters")
        year = None if semesters is None else min(4, semesters // 2 + 1)
        status = between(year, params.get("min"), params.get("max"))
        have = f"{year}학년" if year is not None else ""
    elif ctype == "status":
        value = profile.get("status")
        status = "missing" if value is None else ("pass" if value in params["allowed"] else "fail")
        have = value or ""
    elif ctype == "gpa":
        key = "gpa_last" if params.get("scope") == "last" else "gpa"
        value = profile.get(key)
        chip = f"학점 {need}"
        if foreign and key == "gpa":
            # SPEC 8.1 "유학생 판정": onboarding never asks a foreign student for the GPA.
            status, have = "pending", ""
            gap = "유학생 학점 기준은 별도 확인이 필요해요"
        else:
            status = at_least(resolve_range(value, key), params["min"])
            have = value_text(value, "", is_gpa=True)
            if status == "missing":
                field = key
            if status == "fail" and not isinstance(value, dict):
                fail_gap = f"학점 {params['min'] - value:.2f} 부족"
    elif ctype == "credits":
        key = "credits_total" if params.get("scope") == "total" else "credits_last"
        value = profile.get(key)
        status = at_least(resolve_range(value, key), params["min"])
        have = value_text(value, "학점")
        if status == "missing":
            field = key
    elif ctype == "income":
        value = profile.get("income_bracket")
        status = at_most(resolve_range(value, "income_bracket"), params["max"])
        have = value_text(value, "분위")
        if status == "missing":
            field = "income_bracket"
    elif ctype == "admission_year":
        value = profile.get("admission_year")
        status = between(
            resolve_range(value, "admission_year"), params.get("min"), params.get("max")
        )
        have = value_text(value, "년")
        if status == "missing":
            field = "admission_year"
    elif ctype == "major":
        value = profile.get("major")
        status = "missing" if value is None else ("pass" if value in params["majors"] else "fail")
        have = value or ""
        if status == "missing":
            field = "major"
    elif ctype == "topik":
        value = profile.get("topik")
        miss_gap = "한국어능력(TOPIK) 정보 필요"
        if value is None or value == 0:
            # "아직 없어요"(0) is asked again, like a missing value (SPEC 8.1).
            status, have, field = "missing", "", "topik"
        else:
            status = at_least(value, params["min"])
            have = f"TOPIK {value}급"
            if status == "fail":
                fail_gap = f"TOPIK {params['min']}급 이상 필요"
    elif ctype == "lang":
        any_of = params.get("any_of") or {}
        tests = list(any_of)
        langs = profile.get("langs") or {}
        mine = [t for t in LANG_TYPES if t in langs] + [t for t in langs if t not in LANG_TYPES]
        mine_text = ", ".join(f"{t} {langs[t]}" for t in mine)
        need_text = " / ".join(f"{t} {score_text(t, s)} 이상" for t, s in any_of.items())
        if tests:
            chip = f"{tests[0]} {score_text(tests[0], any_of[tests[0]])} 이상"
        if foreign:
            # SPEC 8.1 "유학생 판정": onboarding never asks a foreign student for a lang score.
            status, have = "pending", ""
            gap = "유학생 어학 기준은 별도 확인이 필요해요"
        elif not langs:
            status, have, field = "missing", "", "langs"
            miss_gap = "어학 정보 필요"
        elif not any(t in langs for t in tests):
            # Holds other tests only: the standard cannot be checked, and we do not ask back.
            status, have = "missing", mine_text
            miss_gap = f"{tests[0]} 등 어학 기준 확인 필요"
            tip = need_text
        else:
            passed = [t for t in tests if t in langs and lang_ok(t, langs[t], any_of[t])]
            if passed:
                status = "pass"
                have = f"{passed[0]} {langs[passed[0]]}"
                chip = f"{passed[0]} {score_text(passed[0], any_of[passed[0]])} 이상"
            else:
                status, have = "fail", mine_text
                fail_gap = f"{tests[0]} {score_text(tests[0], any_of[tests[0]])} 필요"
                tip = need_text
    elif ctype == "history":
        flag = params.get("flag") or label
        value = history.get(flag)
        must = bool(params.get("must"))
        status = "missing" if value is None else ("pass" if bool(value) == must else "fail")
        have = "" if value is None else ("예" if value else "아니오")
        chip = f"{label}: {need}"
        fail_gap = f"{label}: {need}"
        if status == "missing":
            field = f"history:{flag}"
    else:
        # An unknown type is treated like `unresolved`: shown as still being checked.
        status, have = "pending", ""

    if gap is None:
        gap = {
            "pass": "",
            "fail": fail_gap,
            "missing": miss_gap,
            "pending": f"{label} 확인 중",
        }[status]
    if status != "missing":
        field = None
    if tip is None:
        tip = _tip(label, need, status, have, gap, flag if ctype == "history" else None)
    return {
        "type": ctype,
        "label": label,
        "need": need,
        "status": status,
        "have": have,
        "gap": gap,
        "chip": chip,
        "tip": tip,
        "field": field,
        "ask": ask_text(field, params) if field else None,
    }


def judge_notice(card, profile):
    """One card -> {"eligible", "gap", "rows"} (SPEC 8.1 "공지 판정")."""
    rows = [judge_condition(cond, profile) for cond in (card.get("conditions") or [])]
    gap = next((row["gap"] for row in rows if row["status"] != "pass"), None)
    return {
        "eligible": all(row["status"] == "pass" for row in rows),
        "gap": gap,
        "rows": rows,
    }


def is_ask_field(field) -> bool:
    """Is this one of the ask-back keys? Onboarding keys are answered in 내 정보 (SPEC 8.1)."""
    if not field:
        return False
    if field.startswith("history:"):
        return field.split(":", 1)[1] != FOREIGN_FLAG
    return field in ASK_ORDER


def _boundaries(key, cond):
    """Choice boundaries one condition contributes (SPEC 8.1 step 3)."""
    params = cond.get("params") or {}
    out = []
    if key == "income_bracket":
        if params.get("max") is not None:
            out.append(params["max"] + 1)  # "이하" 조건이라서 +1
    else:
        if params.get("min") is not None:
            out.append(params["min"])
        if key == "admission_year" and params.get("max") is not None:
            out.append(params["max"] + 1)
    low, high = KEY_RANGE[key]
    return [c for c in out if low < c <= high]  # SPEC 8.1: the rest cannot split any answer


def _choices(key, boundaries, held):
    """Ask-back choices, highest band first (SPEC 7 되묻기 카드, 8.1 step 3)."""
    is_gpa = key in ("gpa", "gpa_last")
    step = 0.01 if is_gpa else 1
    unit = UNITS[key]
    fmt = gpa_text if is_gpa else (lambda v: str(int(v)))
    low_end = held.get("min") if isinstance(held, dict) else None
    high_end = held.get("max") if isinstance(held, dict) else None

    def value(low, high):
        # SPEC 8.1: an answer already held as a range narrows the choices, never widens them.
        if low is None or (low_end is not None and low_end > low):
            low = low_end
        if high is None or (high_end is not None and high_end < high):
            high = high_end
        return {"min": low, "max": high}

    out = []
    for index in range(len(boundaries) - 1, -1, -1):
        start = boundaries[index]
        if index == len(boundaries) - 1:
            out.append({"label": f"{fmt(start)}{unit} 이상", "value": value(start, None)})
            continue
        after = boundaries[index + 1]
        end = round(after - step, 2) if is_gpa else after - 1
        if is_gpa:
            label = f"{fmt(start)} ~ {fmt(after)}"  # 평점은 다음 경계값
        elif start == end:
            label = f"{fmt(start)}{unit}"
        else:
            label = f"{fmt(start)} ~ {fmt(end)}{unit}"
        out.append({"label": label, "value": value(start, end)})
    first = boundaries[0]
    end = round(first - step, 2) if is_gpa else first - 1
    out.append({"label": f"{fmt(first)}{unit} 미만", "value": value(None, end)})
    return out


def _question(field) -> str:
    if field.startswith("history:"):
        return f"'{field.split(':', 1)[1]}'에 해당하나요?"
    return QUESTIONS[field]


def _rank_fields(pool):
    """Ask-back keys of the held notices, best first (SPEC 8.1 step 2)."""
    counts, first_seen = {}, {}
    for card_index, (_, result) in enumerate(pool):
        seen = set()
        for row_index, row in enumerate(result["rows"]):
            field = row["field"]
            if row["status"] != "missing" or not is_ask_field(field):
                continue
            first_seen.setdefault(field, (card_index, row_index))
            if field not in seen:
                seen.add(field)
                counts[field] = counts.get(field, 0) + 1

    def order(field):
        table = ASK_ORDER.index(field) if field in ASK_ORDER else len(ASK_ORDER)
        return (-counts[field], table, first_seen[field])

    return sorted(counts, key=order)


def ask_back(cards, profile, field=None):
    """The ask-back card of SPEC 7, or None (SPEC 8.1 "되묻기").

    `cards` are the cards visible to this student, in list order (NEW, then deadline).
    `field` asks with one fixed key instead, and then notices with a `fail` row count
    too. A key with no question template raises ValueError (the API answers 422).
    """
    judged = [(card, judge_notice(card, profile)) for card in cards]
    if field is not None:
        if not is_ask_field(field):
            raise ValueError(f"not an ask-back field: {field}")
        pool, candidates = judged, [field]
    else:
        pool = [
            (card, result)
            for card, result in judged
            if not any(row["status"] == "fail" for row in result["rows"])
            and any(row["status"] == "missing" for row in result["rows"])
        ]
        candidates = _rank_fields(pool)

    for key in candidates:
        held = [
            (card, result)
            for card, result in pool
            if any(row["field"] == key and row["status"] == "missing" for row in result["rows"])
        ]
        if not held:
            continue
        if key.startswith("history:"):
            choices = [{"label": "예", "value": True}, {"label": "아니오", "value": False}]
        else:
            boundaries = sorted(
                {
                    boundary
                    for card, result in held
                    for cond, row in zip(card.get("conditions") or [], result["rows"])
                    if row["field"] == key and row["status"] == "missing"
                    for boundary in _boundaries(key, cond)
                }
            )
            if not boundaries:
                continue  # SPEC 8.1: no boundary left, so no answer would split anything
            choices = _choices(key, boundaries, profile.get(key))
        return {
            "field": key,
            "question": _question(key),
            "unlock": len(held),
            "choices": choices,
        }
    return None


def with_overrides(profile, overrides):
    """A copy of the profile with assumed values (SPEC 8.1 "가정 판정"). Never stored."""
    merged = dict(profile)
    for key, value in (overrides or {}).items():
        if key == "history":
            history = dict(profile.get("history") or {})
            history.update(value or {})
            merged["history"] = history
        else:
            merged[key] = value
    return merged


def alerts(items, profile, today):
    """The three alert kinds, in SPEC 8.1 order. `items` are the visible cards.

    Each item carries `key`, `title`, `apply_end`, `is_new`, `planned`, `conditions`
    and `tasks` ({"title", "due", "done"}), the way SPEC 7 shapes them.
    """
    out = []
    for item in items:
        if item.get("is_new") and judge_notice(item, profile)["eligible"]:
            out.append({
                "kind": "new",
                "title": "새 기회를 찾았어요",
                "body": f"{item['title']} · 내 조건으로 지원할 수 있어요",
                "notice_key": item["key"],
            })
    in_three_days = (date.fromisoformat(today) + timedelta(days=3)).isoformat()
    for item in items:
        if item.get("planned") and item.get("apply_end") == in_three_days:
            out.append({
                "kind": "deadline",
                "title": f"{item['title']} 마감이 3일 남았어요",
                "body": "",
                "notice_key": item["key"],
            })
    planned = sorted((i for i in items if i.get("planned")), key=lambda i: i["key"])
    for item in planned:  # SPEC 7: notice key first, then the order of the tasks
        for task in item.get("tasks") or []:
            if task.get("due") == today and not task.get("done"):
                out.append({
                    "kind": "today",
                    "title": "오늘 할 일",
                    "body": task["title"],
                    "notice_key": item["key"],
                })
    return out
