"""T18: collector, scheduler and notice linking (SPEC 8.7).

Saved HTML fragments and a fake fetch. No network, no llm-x.
"""

import asyncio
import json

import pytest

from app import collector, db

LIST_URL = "https://www.kookmin.ac.kr/user/kmuNews/notice/7/index.do"

# A board list the way engine A prints it: a NEW badge inside the link, a "-"
# cell that is not a date, one notice linked twice, another board's row, and a
# row with no date at all.
LIST_HTML = """
<table><tbody>
<tr><td><a href="/user/kmuNews/notice/7/11792/view.do"><span>NEW</span>성적우수 장학금 안내</a></td>
    <td>학생지원팀</td><td>2026.03.05</td><td>1,203</td></tr>
<tr><td><a href="/user/kmuNews/notice/7/11793/view.do">국가장학금 2차 신청</a></td>
    <td>-</td><td>2026-03-09</td></tr>
<tr><td><a href="https://www.kookmin.ac.kr/user/kmuNews/notice/7/11794/view.do">붙임 안내</a>
    <a href="/user/kmuNews/notice/7/11794/view.do">붙임 안내 자세히 보기</a></td>
    <td>2026/03/10</td></tr>
<tr><td><a href="/user/kmuNews/notice/8/999/view.do">다른 게시판 글</a></td><td>2026.03.11</td></tr>
<tr><td><a href="/user/kmuNews/notice/7/11795/view.do">날짜가 없는 행</a></td><td>공지</td></tr>
</tbody></table>
"""

DETAIL_HTML = """
<html><body>
<div class="view_top"><h2>성적우수 장학금 안내</h2><span>2026.03.05</span></div>
<div class="board_view_cont">
  <p>지원 자격: 직전 학기 평점평균 3.5 이상</p><br>
  <p>신청 기간: 2026-03-09 ~ 2026-03-20</p>
  <a href="https://other.example/apply">신청 사이트</a>
</div>
<div class="file_list">
  <a href="/download.do?id=7">붙임1. 신청서.hwp (200KB)</a>
  <a href="/download.do?id=8">붙임2.pdf</a>
  <a href="/user/kmuNews/notice/7/11793/view.do">다음 글</a>
</div>
<div class="view_cont">두 번째 틀은 본문이 아니다</div>
</body></html>
"""


# ------------------------------------------------------------------ engine A


def test_the_list_gives_one_row_per_notice():
    rows = collector.parse_list(LIST_HTML, LIST_URL)
    assert [r["notice_id"] for r in rows] == ["11792", "11793", "11794"]
    first = rows[0]
    assert first["title"] == "성적우수 장학금 안내"  # the longest text in the link
    assert first["posted_date"] == "2026-03-05"
    assert first["url"] == "https://www.kookmin.ac.kr/user/kmuNews/notice/7/11792/view.do"
    assert rows[1]["posted_date"] == "2026-03-09"  # the "-" cell is not a date
    assert rows[2]["title"] == "붙임 안내 자세히 보기"  # two links, one row
    assert rows[2]["posted_date"] == "2026-03-10"


def test_a_row_without_a_date_is_skipped_and_other_boards_are_ignored():
    keys = [r["notice_id"] for r in collector.parse_list(LIST_HTML, LIST_URL)]
    assert "11795" not in keys  # no date
    assert "999" not in keys  # board 8


def test_a_list_url_of_another_engine_gives_nothing():
    assert collector.parse_list(LIST_HTML, "https://biz.kookmin.ac.kr/community/notice") == []


@pytest.mark.parametrize("text, iso", [
    ("2026.04.30", "2026-04-30"),
    ("2026-4-30", "2026-04-30"),
    ("2026/04/30", "2026-04-30"),
    ("2026.04.30.", "2026-04-30"),
    (" 2026.04.30 ", "2026-04-30"),
    ("2026.04.30 10:00", None),  # not a date-only cell
    ("2026.13.30", None),
    ("-", None),
    ("조회 1,203", None),
    ("", None),
])
def test_only_a_date_only_cell_counts_as_the_posted_date(text, iso):
    assert collector.as_date(text) == iso


def test_the_detail_body_is_the_first_view_cont_frame():
    detail = collector.parse_detail(DETAIL_HTML, "https://www.kookmin.ac.kr/x/view.do")
    body = detail["body_text"]
    assert "직전 학기 평점평균 3.5 이상" in body
    assert "신청 기간: 2026-03-09 ~ 2026-03-20" in body
    assert "신청 사이트" in body  # a link inside the frame is still body text
    assert "두 번째 틀은 본문이 아니다" not in body  # the frame closed, <br> and all
    assert "붙임1" not in body and "성적우수 장학금 안내" not in body


def test_attachments_are_file_named_links_anywhere_on_the_page():
    detail = collector.parse_detail(DETAIL_HTML, "https://www.kookmin.ac.kr/x/view.do")
    assert detail["attachments"] == [
        {"name": "붙임1. 신청서.hwp (200KB)",
         "url": "https://www.kookmin.ac.kr/download.do?id=7"},
        {"name": "붙임2.pdf", "url": "https://www.kookmin.ac.kr/download.do?id=8"},
    ]  # "다음 글" and the apply link are not file names


def test_every_site_is_listed_and_only_engine_a_has_a_parser():
    sites = collector.load_sites()
    assert len(sites) == 30
    assert all(set(s) == {"source_id", "name", "engine", "list_url"} for s in sites)
    assert all(s["list_url"].startswith("https://") for s in sites)
    engine_a = [s for s in sites if s["engine"] == collector.ENGINE]
    assert len(engine_a) == 8  # the www.kookmin.ac.kr boards (SPEC 8.7)
    assert all(collector.category_of(s["list_url"]) for s in engine_a)
    assert {s["source_id"] for s in engine_a} == {
        "hq_cat4", "hq_cat5", "hq_cat6", "hq_cat7", "hq_cat8", "hq_cat9",
        "hq_cat10", "hq_cat11"}


# ------------------------------------------------------------------ collecting


SITES = [
    {"source_id": "hq_cat7", "name": "본부-장학공지", "engine": "A", "list_url": LIST_URL},
    # No parser: fetching this one would blow up the fake, which is the point.
    {"source_id": "biz", "name": "경영대학", "engine": "C",
     "list_url": "https://biz.kookmin.ac.kr/community/notice"},
]


@pytest.fixture
def world(tmp_path, monkeypatch):
    path = str(tmp_path / "collect.db")
    monkeypatch.setenv("DB_PATH", path)
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init(path)
    return path


def serve(list_html=LIST_HTML, body=DETAIL_HTML):
    asked = []

    def get(url):
        asked.append(url)
        if url.endswith("index.do"):
            return list_html
        if "view.do" in url:
            return body
        raise AssertionError("the collector fetched " + url)

    get.asked = asked
    return get


def keys_in(path):
    conn = db.connect(path)
    rows = conn.execute("SELECT key, title, body_hash FROM notice ORDER BY key").fetchall()
    conn.close()
    return {r["key"]: (r["title"], r["body_hash"]) for r in rows}


def test_the_first_pass_is_all_new(world):
    get = collector.collect_once(sites=SITES, get=serve())
    assert get["new"] == ["hq_cat7:11792", "hq_cat7:11793", "hq_cat7:11794"]
    assert get["changed"] == []
    assert len(keys_in(world)) == 3


def test_the_second_pass_finds_nothing_and_a_changed_body_is_reported(world):
    collector.collect_once(sites=SITES, get=serve())
    again = collector.collect_once(sites=SITES, get=serve())
    assert again == {"new": [], "changed": []}

    changed = DETAIL_HTML.replace("3.5 이상", "3.0 이상")
    found = collector.collect_once(sites=SITES, get=serve(body=changed))
    assert found["new"] == []
    assert found["changed"] == ["hq_cat7:11792", "hq_cat7:11793", "hq_cat7:11794"]
    stored = keys_in(world)
    conn = db.connect(world)
    row = conn.execute("SELECT body_text FROM notice WHERE key = 'hq_cat7:11792'").fetchone()
    conn.close()
    assert "3.0 이상" in row["body_text"]
    assert stored["hq_cat7:11792"][0] == "성적우수 장학금 안내"


def test_a_changed_title_alone_counts_as_changed(world):
    collector.collect_once(sites=SITES, get=serve())
    before = keys_in(world)["hq_cat7:11792"][1]
    renamed = LIST_HTML.replace("성적우수 장학금 안내", "성적우수 장학금 안내(수정)")
    found = collector.collect_once(sites=SITES, get=serve(list_html=renamed))
    assert "hq_cat7:11792" in found["changed"]
    assert keys_in(world)["hq_cat7:11792"][1] != before  # body_hash covers the title


def test_a_dry_run_writes_nothing_and_never_opens_a_detail(world, capsys):
    get = serve()
    found = collector.collect_once(sites=SITES, get=get, dry_run=True)
    assert found == {"new": [], "changed": []}
    assert keys_in(world) == {}
    assert get.asked == [LIST_URL]  # the list only
    assert "성적우수 장학금 안내" in capsys.readouterr().out


def test_a_board_that_fails_does_not_stop_the_pass(world):
    def get(url):
        if url == LIST_URL:
            raise OSError("boom")
        raise AssertionError("nothing else should be fetched")

    assert collector.collect_once(sites=SITES, get=get) == {"new": [], "changed": []}


# ------------------------------------------------------------------ linking


@pytest.mark.parametrize("one, other, same", [
    ("2026학년도 1학기 국가장학금 안내", "2026-1학기 국가장학금 안내", True),
    # A bracket tag and a round suffix in brackets both come off (SPEC 8.7).
    ("[장학] 성적우수 장학생 모집", "성적우수 장학생 모집(2차)", True),
    ("국가근로장학금 2차 모집", "국가근로장학금 3차 모집", False),
])
def test_the_title_is_normalized_before_it_is_compared(one, other, same):
    assert (collector.normalize_title(one) == collector.normalize_title(other)) is same


def notice(key, title, posted="2026-03-05"):
    return {"key": key, "title": title, "posted_date": posted}


def test_candidates_need_a_near_title_and_a_near_date():
    new = notice("a:1", "2026학년도 1학기 국가근로장학금 2차 모집 안내")
    others = [
        notice("a:2", "2026-1학기 국가근로장학금 2차 모집 안내"),  # same after normalizing
        notice("a:3", "2026학년도 1학기 국가근로장학금 3차 모집 안내"),  # close enough
        notice("a:4", "교내 도서관 휴관 안내"),  # nothing alike
        notice("a:5", "2026학년도 1학기 국가근로장학금 2차 모집 안내", "2026-01-05"),  # 60 days
        notice("a:6", "2026학년도 1학기 국가근로장학금 2차 모집 안내", None),  # no date
    ]
    keys = [c["key"] for c in collector.link_candidates(new, others)]
    assert keys[0] == "a:2"  # the exact match ranks first
    assert "a:3" in keys
    assert "a:4" not in keys and "a:5" not in keys and "a:6" not in keys


def test_at_most_five_candidates_go_to_the_model():
    new = notice("a:0", "2026학년도 1학기 국가근로장학금 2차 모집 안내")
    others = [notice(f"a:{i}", "2026학년도 1학기 국가근로장학금 2차 모집 안내") for i in range(1, 9)]
    assert len(collector.link_candidates(new, others)) == collector.LINK_MAX


def test_a_notice_is_never_its_own_candidate():
    one = notice("a:1", "국가근로장학금 2차 모집")
    assert collector.link_candidates(one, [one]) == []


def card_row(key, hidden=0, check_ok=1, conditions=1, body="본문"):
    return {"notice_key": key, "hidden": hidden, "check_ok": check_ok,
            "conditions": json.dumps([{"id": f"c{i}"} for i in range(conditions)]),
            "body_text": body}


def test_the_group_lead_is_visible_checked_and_the_fullest():
    hidden = card_row("a:hidden", hidden=1, conditions=9, body="아주 긴 본문" * 10)
    unchecked = card_row("a:unchecked", check_ok=None, conditions=9)
    thin = card_row("a:thin", conditions=1, body="짧은 본문")
    full = card_row("a:full", conditions=3, body="긴 본문" * 5)
    assert collector.pick_lead([hidden, unchecked, thin, full])["notice_key"] == "a:full"
    assert collector.pick_lead([hidden, unchecked])["notice_key"] == "a:unchecked"
    longer = card_row("a:longer", conditions=3, body="긴 본문" * 9)
    assert collector.pick_lead([full, longer])["notice_key"] == "a:longer"


@pytest.mark.parametrize("text, same", [
    ('{"same": "a:2"}', "a:2"),
    ('생각: {깨짐} ```json\n{"same": "a:2"}\n```', "a:2"),
    ('{"same": null}', None),
    ("답을 못 하겠어요", None),
    ('{"other": "a:2"}', None),
])
def test_the_models_answer_is_read_loosely_but_checked(text, same):
    assert collector.read_same(text) == same


def fake_llm(text):
    calls = []

    async def chat_fn(messages):
        calls.append(messages)
        return {"text": text, "input_tokens": 9, "output_tokens": 9, "tps": None,
                "seconds": 0.01}

    chat_fn.calls = calls
    return chat_fn


def confirm(text, candidates):
    chat_fn = fake_llm(text)
    new = notice("a:1", "국가근로장학금 2차 모집")
    got = asyncio.run(collector.confirm_link(new, candidates, chat_fn))
    return got, chat_fn


def test_a_key_outside_the_candidates_links_nothing():
    got, chat_fn = confirm('{"same": "z:9"}', [notice("a:2", "국가근로장학금 2차 모집 안내")])
    assert got is None and len(chat_fn.calls) == 1


def test_the_candidates_go_to_the_system_message_and_the_key_to_the_user_message():
    got, chat_fn = confirm('{"same": "a:2"}', [notice("a:2", "국가근로장학금 2차 모집 안내")])
    system, user = chat_fn.calls[0]
    assert got == "a:2"
    assert "a:2: 국가근로장학금 2차 모집 안내" in system["content"]
    assert user["content"] == "a:1\n국가근로장학금 2차 모집"


def test_without_a_candidate_the_model_is_not_called():
    chat_fn = fake_llm('{"same": "a:2"}')
    assert asyncio.run(collector.confirm_link(notice("a:1", "x"), [], chat_fn)) is None
    assert chat_fn.calls == []


def add_card(path, key, conditions=1, check_ok=1, hidden=0, linked_to=None, body="본문"):
    conn = db.connect(path)
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO notice (key, source_id, source_name, url, title,"
            " posted_date, department, body_text, attachments, body_hash, crawled_at)"
            " VALUES (?, 'hq', '게시판', 'https://x/1', ?, '2026-03-05', NULL, ?, '[]', 'h', 'c')",
            (key, "국가근로장학금 2차 모집 " + key, body))
        conn.execute(
            "INSERT OR REPLACE INTO card (notice_key, title, sub, dept, category, apply_start,"
            " apply_end, conditions, fields, trace, linked_to, check_ok, hidden, demo_new,"
            " interpreted_by) VALUES (?, ?, '', '팀', '장학', NULL, '2026-03-20', ?, '[]', '[]',"
            " ?, ?, ?, 0, 'agent')",
            (key, key, json.dumps([{"id": f"c{i}"} for i in range(conditions)]),
             linked_to, check_ok, hidden))
    conn.close()


def test_linking_puts_the_new_card_in_the_group_and_picks_the_lead_again(world):
    add_card(world, "a:1", conditions=1)  # the old lead
    add_card(world, "a:2", conditions=1, linked_to="a:1")
    add_card(world, "a:9", conditions=4)  # the newcomer knows more
    conn = db.connect(world)
    lead = collector.apply_link(conn, "a:9", "a:2")
    rows = {r["notice_key"]: r["linked_to"]
            for r in conn.execute("SELECT notice_key, linked_to FROM card")}
    conn.close()
    assert lead == "a:9"
    assert rows == {"a:1": "a:9", "a:2": "a:9", "a:9": None}


def test_link_notice_asks_the_model_once_and_stores_the_answer(world):
    add_card(world, "a:1", conditions=3)
    add_card(world, "a:9", conditions=1)
    conn = db.connect(world)
    chat_fn = fake_llm('{"same": "a:1"}')
    lead = asyncio.run(collector.link_notice(conn, "a:9", chat_fn))
    linked = conn.execute("SELECT linked_to FROM card WHERE notice_key = 'a:9'").fetchone()[0]
    conn.close()
    assert len(chat_fn.calls) == 1
    assert lead == "a:1" and linked == "a:1"


def test_a_no_from_the_model_leaves_the_card_alone(world):
    add_card(world, "a:1", conditions=3)
    add_card(world, "a:9", conditions=1)
    conn = db.connect(world)
    lead = asyncio.run(collector.link_notice(conn, "a:9", fake_llm('{"same": null}')))
    linked = conn.execute("SELECT linked_to FROM card WHERE notice_key = 'a:9'").fetchone()[0]
    conn.close()
    assert lead is None and linked is None
