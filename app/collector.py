"""Collector, scheduler and notice linking (SPEC 8.7, tier 2).

The app never starts this. It fetches the school's boards, so the demo does not
run it either:

    python -m app.collector --once --dry-run     # one list per board, printed
    python -m app.collector --once               # collect, interpret, link
    python -m app.collector --schedule 3600      # the same, every N seconds

Only engine A is parsed (the eight `www.kookmin.ac.kr/user/kmuNews/notice/{n}`
boards, 454 of the 939 crawled notices). The other engines are logged and
skipped. Both engine A rules -- the list rows and the detail body -- are guesses
from the crawl data that the first `--once --dry-run` is meant to correct.
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import date, datetime
from html.parser import HTMLParser
from urllib.parse import urljoin

import httpx

from app import db

SITES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sites.json")
ENGINE = "A"  # the only parser we have
LIST_PATH = re.compile(r"/user/kmuNews/notice/(\d+)/index\.do")
VIEW_PATH = re.compile(r"/user/kmuNews/notice/(\d+)/(\d+)/view\.do")
DATE = re.compile(r"^(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})\.?$")
BODY_CLASS = re.compile(r"view[-_]?cont")
FILE_SUFFIX = re.compile(
    r"\.(pdf|hwpx?|docx?|xlsx?|pptx?|zip|txt|png|jpe?g|gif|bmp|webp)\s*$", re.I)
SKIP_TAGS = ("script", "style")
# A void element never closes, so it must not count towards the frame depth.
VOID_TAGS = ("br", "img", "hr", "input", "meta", "link", "source", "col", "area",
             "base", "embed", "param", "track", "wbr")
BREAK_TAGS = ("br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4")
LINK_DAYS = 30  # how far apart two notices of one program may be posted
LINK_JACCARD = 0.6
LINK_MAX = 5  # candidates handed to the model

log = logging.getLogger("collector")


# ---------------------------------------------------------------- engine A


class Bits(HTMLParser):
    """The page as a flat list: ("link", href, texts) and ("text", chunk).

    Enough for a board list, where a row is one view.do link plus the cells
    around it, and it never needs a DOM.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.bits = []
        self.link = None
        self.quiet = 0

    def handle_starttag(self, tag, attrs):
        if tag in SKIP_TAGS:
            self.quiet += 1
        elif tag == "a":
            self.close_link()
            self.link = [dict(attrs).get("href") or "", []]

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS and self.quiet:
            self.quiet -= 1
        elif tag == "a":
            self.close_link()

    def handle_data(self, data):
        if self.quiet or not data.strip():
            return
        if self.link is not None:
            self.link[1].append(data.strip())
        else:
            self.bits.append(("text", data.strip()))

    def close_link(self):
        if self.link is not None:
            self.bits.append(("link", self.link[0], self.link[1]))
            self.link = None

    def close(self):
        super().close()
        self.close_link()


def bits_of(markup):
    reader = Bits()
    reader.feed(markup or "")
    reader.close()
    return reader.bits


def as_date(text):
    """A cell that holds nothing but a date: 2026.04.30, 2026-4-30, 2026/04/30."""
    found = DATE.match((text or "").strip())
    if not found:
        return None
    year, month, day = (int(x) for x in found.groups())
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def view_id(href, category):
    """The notice id of a `{category}/{id}/view.do` link on this board."""
    found = VIEW_PATH.search(href or "")
    if found and found.group(1) == str(category):
        return found.group(2)
    return None


def category_of(list_url):
    found = LIST_PATH.search(list_url or "")
    return found.group(1) if found else None


def parse_list(markup, list_url):
    """One row per notice on an engine A board list (SPEC 8.7).

    The title is the longest text inside the link; the posted date is the first
    date-only cell between this link and the next row's link. Several links to
    one notice fold into one row. A row missing either is logged and skipped.
    """
    category = category_of(list_url)
    if category is None:
        log.warning("not an engine A list url: %s", list_url)
        return []
    bits = bits_of(markup)
    starts = [i for i, bit in enumerate(bits)
              if bit[0] == "link" and view_id(bit[1], category)]
    rows = {}
    for order, start in enumerate(starts):
        href, texts = bits[start][1], bits[start][2]
        notice_id = view_id(href, category)
        stop = starts[order + 1] if order + 1 < len(starts) else len(bits)
        title = max(texts, key=len) if texts else ""
        posted = None
        for bit in bits[start + 1:stop]:
            posted = as_date(bit[2][0] if bit[0] == "link" and bit[2] else
                             bit[1] if bit[0] == "text" else "")
            if posted:
                break
        row = rows.get(notice_id)
        if row is None:
            rows[notice_id] = {"notice_id": notice_id, "url": urljoin(list_url, href),
                               "title": title, "posted_date": posted}
            continue
        if len(title) > len(row["title"]):  # the same notice linked twice
            row["title"] = title
        row["posted_date"] = row["posted_date"] or posted
    out = []
    for row in rows.values():
        if not row["title"] or not row["posted_date"]:
            log.warning("list row without a title or a date: %s", row["url"])
            continue
        out.append(row)
    return out


class Detail(HTMLParser):
    """Body text of the first `view_cont` frame, and every attachment link."""

    def __init__(self, page_url):
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.body = []
        self.files = []
        self.depth = None
        self.done = False
        self.quiet = 0
        self.link = None

    def handle_starttag(self, tag, attrs):
        pairs = dict(attrs)
        if tag in SKIP_TAGS:
            self.quiet += 1
            return
        if self.depth is not None:
            if tag not in VOID_TAGS:
                self.depth += 1
            if tag in BREAK_TAGS:
                self.body.append("\n")
        elif not self.done and BODY_CLASS.search(pairs.get("class") or ""):
            self.depth = 1
        if tag == "a":
            self.shelve()
            self.link = [pairs.get("href") or "", []]

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS and self.quiet:
            self.quiet -= 1
            return
        if tag == "a":
            self.shelve()
        if self.depth is not None and tag not in VOID_TAGS:
            self.depth -= 1
            if self.depth <= 0:
                self.depth, self.done = None, True

    def handle_data(self, data):
        if self.quiet or not data.strip():
            return
        if self.link is not None:
            self.link[1].append(data.strip())
        if self.depth is not None:
            self.body.append(data.strip() + " ")

    def shelve(self):
        """An attachment is a link whose text reads like a file name (anywhere)."""
        if self.link is None:
            return
        href, texts = self.link
        self.link = None
        name = " ".join(texts).strip()
        # Boards often print the size after the name: 붙임1.hwp (200KB).
        bare = re.sub(r"[(\[][^)\]]*[)\]]\s*$", "", name).strip()
        if name and href and FILE_SUFFIX.search(bare):
            url = urljoin(self.page_url, href)
            if not any(f["url"] == url for f in self.files):
                self.files.append({"name": name, "url": url})

    def close(self):
        super().close()
        self.shelve()


def parse_detail(markup, page_url):
    reader = Detail(page_url)
    reader.feed(markup or "")
    reader.close()
    text = re.sub(r"[ \t]+", " ", "".join(reader.body))
    lines = [line.strip() for line in text.split("\n")]
    return {"body_text": "\n".join(line for line in lines if line),
            "attachments": reader.files}


# ---------------------------------------------------------------- collecting


def load_sites(path=SITES):
    """The 30 boards. Only the engine A ones have a parser (SPEC 8.7)."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def fetch(url):
    res = httpx.get(url, timeout=20.0, follow_redirects=True,
                    headers={"User-Agent": "UniQ collector (class project)"})
    res.raise_for_status()
    return res.text


def collect_once(sites=None, get=None, dry_run=False, conn=None):
    """One pass over the engine A boards -> {"new": [key], "changed": [key]}.

    A board or a notice we cannot fetch is logged; the rest carries on. With
    dry_run the lists are only printed: no detail pages, nothing written.
    """
    get = get or fetch
    sites = load_sites() if sites is None else sites
    own = conn is None and not dry_run
    conn = db.connect() if own else conn
    found = {"new": [], "changed": []}
    try:
        for site in sites:
            if site["engine"] != ENGINE:
                log.info("skipping %s: engine %s has no parser", site["source_id"],
                         site["engine"])
                continue
            try:
                rows = parse_list(get(site["list_url"]), site["list_url"])
            except (httpx.HTTPError, OSError) as exc:
                log.warning("board %s failed: %s", site["source_id"], exc)
                continue
            log.info("%s: %d rows", site["source_id"], len(rows))
            for row in rows:
                if dry_run:
                    print("{}\t{}\t{}\t{}".format(
                        site["source_id"], row["posted_date"], row["title"], row["url"]))
                    continue
                try:
                    store(conn, site, row, get, found)
                except (httpx.HTTPError, OSError) as exc:
                    log.warning("notice %s failed: %s", row["url"], exc)
    finally:
        if own:
            conn.close()
    return found


def store(conn, site, row, get, found):
    """Insert a new notice or update a changed one; skip the rest (SPEC 8.7)."""
    key = "{}:{}".format(site["source_id"], row["notice_id"])
    detail = parse_detail(get(row["url"]), row["url"])
    digest = db.body_hash(row["title"], detail["body_text"])
    old = conn.execute("SELECT body_hash FROM notice WHERE key = ?", (key,)).fetchone()
    if old is not None and old["body_hash"] == digest:
        return
    now = datetime.now().isoformat(timespec="seconds")
    files = json.dumps(detail["attachments"], ensure_ascii=False)
    with conn:
        if old is None:
            conn.execute(
                "INSERT INTO notice (key, source_id, source_name, url, title, posted_date,"
                " department, body_text, attachments, body_hash, crawled_at)"
                " VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)",
                (key, site["source_id"], site["name"], row["url"], row["title"],
                 row["posted_date"], detail["body_text"], files, digest, now))
            found["new"].append(key)
        else:
            # A changed notice updates the notice row only; its card stays put.
            conn.execute(
                "UPDATE notice SET title = ?, body_text = ?, attachments = ?,"
                " body_hash = ?, crawled_at = ? WHERE key = ?",
                (row["title"], detail["body_text"], files, digest, now, key))
            found["changed"].append(key)


# ---------------------------------------------------------------- linking


def normalize_title(title):
    """"2026학년도 1학기 ..." and "2026-1학기 ..." have to come out the same."""
    text = re.sub(r"\[[^\]]*\]|\([^)]*\)|<[^>]*>|【[^】]*】", " ", title or "")
    text = text.replace("학년도", " ")
    return re.sub(r"[^0-9a-z가-힣]", "", text.lower())


def bigrams(text):
    return {text[i:i + 2] for i in range(len(text) - 1)}


def jaccard(left, right):
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def title_score(one, other):
    """1.0 for the same normalized title, otherwise the bigram Jaccard."""
    first, second = normalize_title(one), normalize_title(other)
    if first and first == second:
        return 1.0
    return jaccard(bigrams(first), bigrams(second))


def days_apart(one, other):
    try:
        return abs((date.fromisoformat(one) - date.fromisoformat(other)).days)
    except (TypeError, ValueError):
        return None


def link_candidates(notice, others, limit=LINK_MAX):
    """Rule-picked candidates: same or near title, posted within 30 days.

    `notice` and `others` are rows or dicts with key, title and posted_date.
    The five most alike go to the model, which makes the call (SPEC 8.7).
    """
    scored = []
    for other in others:
        if other["key"] == notice["key"]:
            continue
        gap = days_apart(notice["posted_date"], other["posted_date"])
        if gap is None or gap > LINK_DAYS:
            continue
        score = title_score(notice["title"], other["title"])
        if score < LINK_JACCARD:
            continue
        scored.append((score, other["key"], other))
    scored.sort(key=lambda row: (-row[0], row[1]))
    return [dict(other, score=round(score, 3)) for score, _, other in scored[:limit]]


def pick_lead(cards):
    """The card the group shows: visible, checked, most conditions, longest body."""
    def rank(card):
        return (bool(card["hidden"]), card["check_ok"] != 1,
                -len(json.loads(card["conditions"] or "[]")),
                -len(card["body_text"] or ""), card["notice_key"])

    return sorted(cards, key=rank)[0]


def group_of(conn, key):
    """A card's whole group: its lead and everything linked to that lead."""
    row = conn.execute(
        "SELECT c.*, n.body_text AS body_text FROM card c JOIN notice n ON n.key = c.notice_key"
        " WHERE c.notice_key = ?", (key,)).fetchone()
    if row is None:
        return []
    lead = row["linked_to"] or row["notice_key"]
    return conn.execute(
        "SELECT c.*, n.body_text AS body_text FROM card c JOIN notice n ON n.key = c.notice_key"
        " WHERE c.notice_key = ? OR c.linked_to = ?", (lead, lead)).fetchall()


def apply_link(conn, key, other_key):
    """Put `key` in `other_key`'s group and choose the group's lead again."""
    group = {row["notice_key"]: row for row in group_of(conn, other_key)}
    for row in group_of(conn, key):
        group[row["notice_key"]] = row
    if len(group) < 2:
        return None
    lead = pick_lead(list(group.values()))["notice_key"]
    with conn:
        for member in group:
            conn.execute("UPDATE card SET linked_to = ? WHERE notice_key = ?",
                         (None if member == lead else lead, member))
    return lead


LINK_INSTRUCTIONS = """너는 국민대 공지 둘이 같은 프로그램인지 가리는 판별기다.

출력은 JSON 객체 하나뿐이다: {"same": "<같은 프로그램인 후보 key>"} 또는 {"same": null}
- 같은 프로그램의 다른 회차·다른 안내(1차와 2차, 안내와 결과)면 같은 것으로 본다.
- 이름만 비슷하고 대상이나 시기가 다른 별개 사업이면 null이다.
- 후보 목록 밖의 key는 내지 않는다."""


async def confirm_link(notice, candidates, chat_fn=None):
    """One LLM call. A broken answer or a key we did not offer links nothing."""
    if not candidates:
        return None
    from app import llm  # imported late: linking is the only part that needs it

    lines = ["후보:"] + ["{}: {}".format(c["key"], c["title"]) for c in candidates]
    messages = [
        {"role": "system", "content": LINK_INSTRUCTIONS + "\n\n" + "\n".join(lines) + "\n/no_think"},
        {"role": "user", "content": "{}\n{}".format(notice["key"], notice["title"])},
    ]
    reply = await (chat_fn or llm.chat)(messages)
    same = read_same(reply.get("text") or "")
    return same if any(c["key"] == same for c in candidates) else None


def read_same(text):
    """The first {...} that reads as JSON with a `same` key."""
    decoder = json.JSONDecoder()
    for index, char in enumerate(text or ""):
        if char != "{":
            continue
        try:
            found, _ = decoder.raw_decode(text, index)
        except ValueError:
            continue
        if isinstance(found, dict) and "same" in found:
            return found["same"] if isinstance(found["same"], str) else None
    return None


async def link_notice(conn, key, chat_fn=None):
    """Candidates by rule, one LLM call, then the group's lead again."""
    notice = conn.execute(
        "SELECT key, title, posted_date FROM notice WHERE key = ?", (key,)).fetchone()
    if notice is None:
        return None
    others = conn.execute(
        "SELECT n.key AS key, n.title AS title, n.posted_date AS posted_date"
        " FROM notice n JOIN card c ON c.notice_key = n.key WHERE n.key != ?", (key,)).fetchall()
    candidates = link_candidates(notice, others)
    same = await confirm_link(notice, candidates, chat_fn)
    if not same:
        return None
    return apply_link(conn, key, same)


# ---------------------------------------------------------------- the run


def run_once(dry_run=False):
    """A collection pass plus interpretation and linking for the new keys."""
    found = collect_once(dry_run=dry_run)
    if dry_run:
        return found
    import asyncio

    from app import interpret

    conn = db.connect()
    try:
        for key in found["new"]:
            try:
                report = asyncio.run(interpret.interpret(key))
                if not report.get("ok") or report.get("skipped"):
                    log.info("no card for %s: %s", key, report.get("why") or report.get("skipped"))
                    continue
                lead = asyncio.run(link_notice(conn, key))
                log.info("card for %s (group lead %s)", key, lead or key)
            except Exception:  # one notice never stops the pass (SPEC 8.7)
                log.exception("interpreting or linking %s failed", key)
    finally:
        conn.close()
    log.info("new %d, changed %d", len(found["new"]), len(found["changed"]))
    return found


def main(argv):
    parser = argparse.ArgumentParser(prog="python -m app.collector")
    parser.add_argument("--once", action="store_true", help="one pass")
    parser.add_argument("--dry-run", action="store_true", help="lists only, write nothing")
    parser.add_argument("--schedule", type=int, metavar="N", help="a pass every N seconds")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.schedule:
        while True:
            try:
                run_once()
            except Exception:
                log.exception("this pass failed")
            time.sleep(args.schedule)
    if args.once:
        run_once(dry_run=args.dry_run)
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
