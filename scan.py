#!/usr/bin/env python3
"""Job watch: a weekly scan of public job board APIs for roles that match a profile.

It pulls Greenhouse, Ashby and Lever boards plus a few aggregator APIs, keeps a list of
postings it has already shown, and prints only the new matches as a short digest.

Run:  python3 scan.py                    prints the digest and updates the seen list
      python3 scan.py --dry              prints the digest, leaves the seen list alone
      python3 scan.py --all              prints every current match, ignores the seen list
      python3 scan.py --profile p.json   uses another profile file (default: profile.json)

Standard library only. No API keys, no accounts, no language model.

A posting has to pass three gates: the title (include and exclude patterns from the profile),
the location (open to the home country), and the job description itself, which has to say
remote. Hybrid, "three days in the office", relocation and "US only" postings are dropped even
when the board flags them as remote, because the boards' remote flag turned out to be
unreliable.
"""
import datetime
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SEEN = os.path.join(HERE, "seen.json")
LOG = os.path.join(HERE, "log.txt")
UA = {"User-Agent": "Mozilla/5.0 (job-watch)"}
TODAY = datetime.date.today().isoformat()
KEEP_DAYS = 180  # a posting leaves the seen list after this many days, so a repost shows up again

# ---- location rules --------------------------------------------------------------------------
# Written for a candidate based in Austria who can work anywhere in Europe. The profile adds the
# words that name the home country (see "home_words" in profile.json).
EU_OK = re.compile(r"remote|europe|emea|worldwide|anywhere|global|austria|germany|netherlands|ireland|\buk\b|united kingdom|"
                   r"spain|portugal|poland|denmark|sweden|finland|norway|belgium|switzerland|czech|italy|france|\bcet\b|home based", re.I)
NOT_EU = re.compile(r"united states|\bus\b|\busa\b|america|canada|latam|india|apac|australia|philippines|brazil|mexico|"
                    r"colombia|argentina|chile|singapore|japan|korea|israel|new york|san francisco|boston|austin|lincoln|"
                    r"melbourne|sydney|toronto|vancouver|dubai|riyadh|cairo|lagos|nairobi|pakistan|vietnam|indonesia", re.I)
STRONG_EU = re.compile(r"europe|emea|worldwide|anywhere|global|home based", re.I)
EU_COUNTRIES = re.compile(r"\b(germany|netherlands|ireland|uk|united kingdom|spain|portugal|poland|denmark|sweden|finland|norway|belgium|"
                          r"switzerland|czech(ia)?|italy|france|hungary|romania|greece|lithuania|latvia|estonia|croatia|serbia|slovakia|"
                          r"slovenia|bulgaria|luxembourg|turkey|ukraine)\b", re.I)
# A title that pins the role to one city or country is out: "Deployment Strategist, Italy", "... (Paris)".
TITLE_PINNED = re.compile(r"[-\u2013(,/]\s*(italy|spain|france|portugal|poland|netherlands|belgium|sweden|denmark|norway|finland|ireland|uk|"
                          r"united kingdom|switzerland|czech(ia)?|romania|hungary|greece|turkey|paris|london|berlin|madrid|milan|amsterdam|"
                          r"dublin|warsaw|lisbon|stockholm|copenhagen|oslo|helsinki|zurich|munich|hamburg|barcelona|rome|prague|"
                          r"new york|san francisco|nyc|sf)\b", re.I)
AI_WORDS = re.compile(r"\bai\b|artificial intelligence|automation|\bllm|agents?\b|claude|openai|gpt|copilot", re.I)

# ---- remote verification from the description ------------------------------------------------
TAG = re.compile(r"<[^>]+>")
NEG = re.compile(r"\bhybrid\b|\bon[- ]?site\b|\bin[- ]office\b|\boffice[- ]based\b|office[- ]first|"
                 r"days? (per|a|each) week (in|at) (the |our )?office|\d ?(x|days?) ?(per|a|/) ?week (in|at) (the |our )?office|"
                 r"\d days? (in|at) (the |our )?office|relocat(e|ion|ing)|work(ing)? from (our|the) [\w ]{0,20}office|"
                 r"based (in|at|out of) (our|the) [\w ]{0,20}office|come (in)?to the office|commut|in person at")
POS_STRONG = re.compile(r"fully[- ]remote|100 ?% remote|remote[- ]first|work from anywhere|anywhere in (europe|the world|the eu|emea)|"
                        r"remote (within|in|across|from|throughout) (europe|the eu|emea|the european union)|remote \((europe|eu|emea)|"
                        r"home[- ]based|distributed team|remote[- ]only|permanently remote|entirely remote|all[- ]remote")
POS = re.compile(r"\bremote\b|work from home|\bwfh\b|home office|telework")
EU_WORDS = re.compile(r"europe|emea|austria|\beu\b|european|anywhere|worldwide|global|\bcet\b|\bcest\b")
RESTRICTED = re.compile(r"\b(us|u\.s\.|united states|usa|uk|united kingdom|canada|india|australia)[- ](only|based)\b|"
                        r"(must|need to|needs to|should|have to) (be )?(based|located|residing|reside|living|live|physically located) in (the )?"
                        r"(us\b|u\.s\.|united states|usa|uk\b|united kingdom|canada|germany|netherlands|spain|france|india|australia|poland)|"
                        r"\b(pst|pdt|est|edt|cst|cdt|mst)\b time ?zones?|us time ?zones?|north america(n)? (time ?zones?|hours)|"
                        r"(authori[sz]ed|eligible|right) to work in the (us|u\.s\.|united states|uk|united kingdom)\b")

DROPPED = {"hybrid/on-site": 0, "country-restricted": 0, "no remote signal": 0, "title": 0, "location": 0}


class Profile:
    """The part that is personal: which boards to read and which titles count as a match."""

    def __init__(self, data):
        t = data["title"]
        self.name = data.get("name", "")
        self.include = re.compile(t["include"], re.I)
        self.exclude = re.compile(t["exclude"], re.I)
        self.other_language = re.compile(t["other_language"], re.I) if t.get("other_language") else None
        self.generic = re.compile(t["generic"], re.I) if t.get("generic") else None
        self.home = re.compile(data["home_words"], re.I)
        self.boards = data.get("boards", {})
        self.aggregators = data.get("aggregators", {})


def load_profile(path):
    with open(path, encoding="utf-8") as f:
        return Profile(json.load(f))


def clean(text):
    if not text:
        return ""
    t = html.unescape(html.unescape(text))
    t = TAG.sub(" ", t)
    return re.sub(r"\s+", " ", t).lower()


def remote_verdict(desc, workplace=None):
    """True = verified remote and open to Europe, False = verified not, None = unknown (no description)."""
    if workplace:
        w = workplace.lower()
        if w in ("hybrid", "onsite", "on-site", "office"):
            return False
    d = clean(desc)
    if not d:
        return True if (workplace or "").lower() == "remote" else None
    if RESTRICTED.search(d) and not EU_WORDS.search(d):
        DROPPED["country-restricted"] += 1
        return False
    if POS_STRONG.search(d) or (workplace or "").lower() == "remote":
        return True
    if NEG.search(d):
        DROPPED["hybrid/on-site"] += 1
        return False
    if POS.search(d):
        return True
    DROPPED["no remote signal"] += 1
    return False


def home_ok(loc, p):
    """False when the posting is pinned to other European countries and the home country is not among them."""
    loc = loc or ""
    if STRONG_EU.search(loc) or p.home.search(loc):
        return True
    return not EU_COUNTRIES.search(loc)


def loc_ok(loc):
    loc = loc or ""
    if not EU_OK.search(loc):
        return False
    if NOT_EU.search(loc) and not STRONG_EU.search(loc):
        return False
    return True


def title_ok(title, p):
    if p.other_language and p.other_language.search(title):
        return False
    if re.search(r"\bfounder'?s?\s+associate\b", title, re.I):
        return not re.search(r"junior|intern", title, re.I)
    if TITLE_PINNED.search(title) and not (p.home.search(title) or re.search(r"europe|emea", title, re.I)):
        return False
    return bool(p.include.search(title)) and not p.exclude.search(title)


def add(out, p, title, company, loc, url, date="", desc=None, workplace=None):
    """Runs one posting through the three gates and keeps it when it passes."""
    if not url or not title:
        return
    if not title_ok(title, p):
        DROPPED["title"] += 1
        return
    if p.generic and p.generic.search(title) and not re.search(r"\bai\b|automation|agent|llm", title, re.I):
        # "Head of Operations", "Chief of Staff": only when the posting itself is about AI or automation work
        if not AI_WORDS.search(clean(desc)):
            DROPPED["title"] += 1
            return
    if not home_ok(loc, p):
        DROPPED["location"] += 1
        return
    verdict = remote_verdict(desc, workplace)
    if verdict is False:
        return
    if verdict is None and not loc_ok(loc):
        DROPPED["location"] += 1
        return
    if verdict is True and NOT_EU.search(loc or "") and not STRONG_EU.search(loc or ""):
        # the text says remote, but the posting is pinned to a location outside Europe
        DROPPED["location"] += 1
        return
    out[url] = {"title": title.strip(), "company": (company or "").strip(), "loc": (loc or "").strip(), "date": date or ""}


def get(url, timeout=25):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
            return r.read().decode("utf-8", "ignore")
    except Exception:
        return None


def get_json(url):
    t = get(url)
    if not t:
        return None
    try:
        return json.loads(t)
    except Exception:
        return None


# ---- sources ---------------------------------------------------------------------------------
def greenhouse(out, p, board):
    d = get_json(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true")
    for j in (d or {}).get("jobs", []):
        add(out, p, j.get("title"), board, (j.get("location") or {}).get("name"), j.get("absolute_url"),
            (j.get("updated_at") or "")[:10], desc=j.get("content"))


def ashby(out, p, board):
    d = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{board}")
    for j in (d or {}).get("jobs", []):
        loc = j.get("location") or ""
        secs = ",".join(s.get("location", "") for s in (j.get("secondaryLocations") or []))
        if j.get("isRemote") and not loc.lower().startswith("remote"):
            loc = "Remote " + loc
        add(out, p, j.get("title"), board, f"{loc} {secs}", j.get("jobUrl"), (j.get("publishedAt") or "")[:10],
            desc=j.get("descriptionPlain") or j.get("descriptionHtml"), workplace="remote" if j.get("isRemote") else None)


def lever(out, p, board):
    d = get_json(f"https://api.lever.co/v0/postings/{board}?mode=json")
    for j in d or []:
        c = j.get("categories", {}) or {}
        wt = (j.get("workplaceType") or "").lower()
        add(out, p, j.get("text"), board, f"{c.get('location', '')} {wt}", j.get("hostedUrl"),
            desc=(j.get("descriptionPlain") or "") + " " + (j.get("additionalPlain") or ""), workplace=wt or None)


def arbeitnow(out, p):
    for page in range(1, 9):
        d = get_json(f"https://www.arbeitnow.com/api/job-board-api?remote=true&page={page}")
        if not d:
            break
        for j in d.get("data", []):
            loc = ("Remote " if j.get("remote") else "") + (j.get("location") or "")
            add(out, p, j.get("title"), j.get("company_name"), loc, j.get("url"), desc=j.get("description"))


def remotive(out, p, queries):
    for q in queries:
        d = get_json(f"https://remotive.com/api/remote-jobs?search={urllib.parse.quote(q)}&limit=30")
        for j in (d or {}).get("jobs", []):
            add(out, p, j.get("title"), j.get("company_name"), "Remote " + (j.get("candidate_required_location") or ""),
                j.get("url"), (j.get("publication_date") or "")[:10], desc=j.get("description"))


def remoteok(out, p):
    d = get_json("https://remoteok.com/api")
    for j in (d or [None])[1:]:
        add(out, p, j.get("position"), j.get("company"), "Remote " + (j.get("location") or "Worldwide"), j.get("url"),
            (j.get("date") or "")[:10], desc=j.get("description"))


def jobicy(out, p, geos):
    for geo in geos:
        d = get_json(f"https://jobicy.com/api/v2/remote-jobs?count=50&geo={geo}")
        for j in (d or {}).get("jobs", []):
            add(out, p, j.get("jobTitle"), j.get("companyName"), "Remote " + (j.get("jobGeo") or ""), j.get("url"),
                (j.get("pubDate") or "")[:10], desc=j.get("jobDescription") or j.get("jobExcerpt"))


def himalayas(out, p, queries):
    for q in queries:
        d = get_json(f"https://himalayas.app/jobs/api?limit=30&q={urllib.parse.quote(q)}")
        for j in (d or {}).get("jobs", []):
            locs = ",".join(j.get("locationRestrictions") or []) or "Worldwide"
            add(out, p, j.get("title"), j.get("companyName"), "Remote " + locs, j.get("applicationLink") or j.get("guid"),
                desc=j.get("description"))


def scan(p):
    """Reads every source in the profile and returns {url: posting} for everything that passed."""
    found = {}
    for b in p.boards.get("greenhouse", []):
        greenhouse(found, p, b)
    for b in p.boards.get("ashby", []):
        ashby(found, p, b)
    for b in p.boards.get("lever", []):
        lever(found, p, b)
    a = p.aggregators
    if a.get("arbeitnow"):
        arbeitnow(found, p)
    if a.get("remotive"):
        remotive(found, p, a["remotive"])
    if a.get("remoteok"):
        remoteok(found, p)
    if a.get("jobicy"):
        jobicy(found, p, a["jobicy"])
    if a.get("himalayas"):
        himalayas(found, p, a["himalayas"])
    return found


# ---- digest ----------------------------------------------------------------------------------
def group_matches(new):
    """The same role posted once per country (some boards do this) collapses to one line."""
    groups = {}
    for u, v in new.items():
        key = (v["company"].lower(), re.sub(r"[^a-z0-9]+", " ", v["title"].lower()).strip())
        g = groups.setdefault(key, {"v": v, "url": u, "locs": []})
        g["locs"].append(v["loc"])
    return sorted(groups.values(), key=lambda g: (g["v"]["company"].lower(), g["v"]["title"].lower()))


def digest(found, new, groups, today=TODAY):
    lines = []
    for g in groups:
        v = g["v"]
        loc = v["loc"] if len(g["locs"]) == 1 else f"{len(g['locs'])} countries incl. {v['loc']}"
        lines.append(f"{v['title']} | {v['company']} | {loc}\n{g['url']}")
    header = f"Job watch {today}: {len(groups)} new match(es) ({len(new)} postings) out of {len(found)} current"
    return header + "\n\n" + ("\n\n".join(lines) if lines else "(none)")


def load_seen():
    if not os.path.exists(SEEN):
        return {}
    try:
        with open(SEEN, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_seen(seen, found):
    cutoff = (datetime.date.today() - datetime.timedelta(days=KEEP_DAYS)).isoformat()
    seen = {u: d for u, d in seen.items() if d >= cutoff}
    for u in found:
        seen.setdefault(u, TODAY)
    with open(SEEN, "w", encoding="utf-8") as f:
        json.dump(seen, f, indent=0)


def main(argv):
    args = list(argv)
    profile_path = os.path.join(HERE, "profile.json")
    if "--profile" in args:
        i = args.index("--profile")
        profile_path = args[i + 1]
        del args[i:i + 2]
    mode = args[0] if args else ""

    p = load_profile(profile_path)
    found = scan(p)
    seen = load_seen()
    new = found if mode == "--all" else {u: v for u, v in found.items() if u not in seen}
    print(digest(found, new, group_matches(new)))

    if mode in ("--dry", "--all"):
        print(f"[dropped: {DROPPED}]", file=sys.stderr)
        return
    save_seen(seen, found)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.datetime.now().isoformat(timespec='minutes')} scanned={len(found)} new={len(new)}\n")


if __name__ == "__main__":
    main(sys.argv[1:])
