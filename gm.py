#!/usr/bin/env python3
"""In-season GM facts for a Sleeper NBA Lock-In league (private/config.json). Read-only: the Owner makes every move.

Usage: ./gm.py [--date YYYY-MM-DD] [--refresh] <command>
  roster [team]                 live roster: slot, status, board V/wk and FP/g, games this week
  week [--week N] [--ev]        Mon-Sun game grid, base lineup by expected locked score, bench rotation plan
                                (with same-night slot reuse when two tips are 3 h+ apart), tonight's lock lines
  lock [player score] [--game D] [--remaining N] [--play P] [--slot-of STARTER] [--locked A,B] [--ev]
                                LOCK or WAIT for the slot he occupies (refilled if unlocked); with no
                                player, pending decisions from this week's box scores. In the live week the
                                line is the matchup line (P(win H2H) + P(beat median)); --ev for EV lines
  lock player score --commit    record a lock made in Sleeper, ours or any other team's (week, lock, fa,
  lock player --uncommit        matchup then use it); undo a mistaken record. Records reset each week;
                                --locked overrides ours
  fa [--pos X] [--top N]        board players on no roster vs our drop candidate, in league points;
                                then Sleeper's trending adds, off-board 2026 scorers above replacement,
                                the minutes radar (last-3 min/g >= season + 8) and the best 3 streams this week by team gain (ΔTeam, rotation included)
  matchup [--week N]            opponent, points so far, board strength, median game, win odds (H2H, median)
  review [--week N]             finished week (default: the last one), per slot: points counted vs the lock policy
                                replayed on the same box scores vs hindsight, with each leak's cause
  standings                     W-L incl. median games (regular season only), PF, playoff line
  changes [--no-write]          diff vs private/state/gm-snapshot.json (only the GM advances it)
  --test                        offline self-test
Every command validates the live league first and prints REFUSING on any mismatch.
"""
import argparse, concurrent.futures, contextlib, datetime, functools, glob, io, itertools, json, math, os, random, re, statistics, sys, tempfile, time, urllib.request
import draft
import rebuild_board as rb

HERE = draft.HERE
CACHE = os.path.join(HERE, ".cache")
STATE = os.path.join(draft.PRIVATE, "state")  # GM state worth backing up, unlike .cache
SNAPSHOT = os.path.join(STATE, "gm-snapshot.json")
TRENDING = "https://api.sleeper.app/v1/players/nba/trending/add?lookback_hours=24&limit=50"  # documented endpoint
SCORING = rb.SCORING  # one table: the live validation must check the scoring the board was built with
SLOTS = ["PG", "SG", "G", "SF", "PF", "F", "C", "UTIL", "UTIL"]
ROSTER_POSITIONS = SLOTS + ["BN"] * 5
MY_ROSTER = 4
IR_SLOTS = 1
IR_OK = {"IR", "SUS", "DNR", "OUT"}  # reserve_allow_out is 1 (changed Oct 22): Out fits IR
DAY = "%a %m/%d"
# 2025-26 backtest: regulars sit 8.3% of their next in-week game, 12.4% on a back-to-back's second night.
# rebuild_board.lock_values ignores in-week DNPs and overstates waiting by 8-9%; lock calls use these.
Q_DNP, Q_B2B = 0.08, 0.12
# Sleeper DTD: play chance for his next game (on or after today), then for his later games this week.
# 0.50 is the "Questionable" rate in the NBA's participation key (Probable 75%, Questionable 50%, Doubtful 25%;
# nba.com/kings/blog/injury-kings-clippers); 0.75 ("Probable") for later games is a judgment, not measured.
# ponytail: Sleeper's DTD lumps probable/questionable/doubtful, so 0.50 is a midpoint; the scout's news and
# lock --play override it. Out stays 0 all week (fpg_of): no sourced return rate, so no partial-week credit.
P_DTD = (0.50, 0.75)
# Same-night slot reuse: a second roll in a slot when two tips that night are at least this far apart (an early game
# runs about 2 1/4 h, leaving time to decide its score and swap). Backtest: +0.60 wins/20 wk at 3 h, 0.28 at 3.5 h
# (reports/2026-10-20/slot-reuse.md).
REUSE_GAP = datetime.timedelta(hours=3)
MOVE_COST = 1.0  # FP a lock via another slot must add over locking in place: an extra lineup move to make and forget
DTD = ("DTD", "GTD")  # Sleeper's game-time-decision tag gets the same discount
# The official NBA injury report (a PDF every 15 minutes; official.nba.com lists the day's) overrides P_DTD for the
# games it lists, by the same key; every status is capped at play_on's rate, so Available means a regular's 0.92.
# Terms (nba.com/termsofuse, updated Jul 13 2026): personal, noncommercial download allowed; no automated-access or AI bar.
INJURY_INDEX = "https://official.nba.com/nba-injury-report-{}-{:02d}-season/"
P_REPORT = {"Available": 1.0, "Probable": 0.75, "Questionable": 0.50, "Doubtful": 0.25, "Out": 0.0}
REPORT = {"at": "", "pids": {}}  # set by load: {"at": "10/20 10:45 ET", "pids": {pid: {date: status}}}
# Tip times: ESPN's public scoreboard (undocumented; Owner-approved Oct 20 2026), UTC tips per ET game date.
ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={:%Y%m%d}"
ESPN_TEAM = {"GS": "GSW", "NO": "NOP", "NY": "NYK", "SA": "SAS", "UTAH": "UTA", "WSH": "WAS"}  # ESPN -> Sleeper
CLOCK = {"now": None, "tips": {}}  # set by load: now = naive UTC (None on --date runs), tips = {(date, team): UTC tip}
# fa shows a stream only if ΔTeam >= STREAM_MIN this week and beats STREAM_WEEKS x the season V/wk it costs.
# ponytail: a stream's dropped player is usually gone for good, so 3 weeks is a rough horizon for his lost value,
# not a measured one. Upgrade: price the drop over the weeks until he would be re-addable, if that's ever tracked.
STREAM_MIN, STREAM_WEEKS = 5.0, 3
# fa's minutes radar: last-3 min/g >= season avg + RADAR_MIN after RADAR_GAMES+ games. Backtest (reports/2026-10-20/
# minutes-radar.md): such players (blend <= 35 FP/g) beat the blend's next-2-week FP/g by +6.4 (2025-26) and +5.8
# (2024-25) vs +1.0 for all; L3 min x season FP/min cut RMSE 10.3 -> 8.6 but ran 2.5-3.1 FP/g high.
RADAR_MIN, RADAR_GAMES = 8.0, 6


# ---------- fetch and validate ----------

def fetch(url, raw=False):
    """api.sleeper.com endpoints are undocumented and want a browser User-Agent (so does official.nba.com)."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read() if raw else json.load(r)


def validate(cfg, league, rosters):
    """Problems that make league facts untrustworthy; empty list means OK."""
    league = league or {}
    bad = []
    if league.get("league_id") != cfg["league_id"] or league.get("sport") != "nba":
        bad.append(f"league {league.get('league_id')} (sport {league.get('sport')}) is not config league {cfg['league_id']} (nba)")
    scoring = {k: v for k, v in (league.get("scoring_settings") or {}).items() if v}
    if scoring != SCORING:
        bad.append(f"scoring is {scoring}, expected {SCORING}")
    if league.get("roster_positions") != ROSTER_POSITIONS:
        bad.append(f"roster_positions {league.get('roster_positions')}, expected {ROSTER_POSITIONS}")
    st = league.get("settings") or {}
    if st.get("reserve_allow_out") != 1 or st.get("reserve_slots") != IR_SLOTS:
        bad.append(f"IR rules changed: reserve_allow_out={st.get('reserve_allow_out')}, reserve_slots={st.get('reserve_slots')}")
    mine = [r for r in rosters or [] if r.get("roster_id") == MY_ROSTER]
    if not mine or cfg["user_id"] not in [mine[0].get("owner_id")] + (mine[0].get("co_owners") or []):
        bad.append(f"config user {cfg['user_id']} does not own roster_id {MY_ROSTER}")
    return bad


def refuse(bad):
    if bad:
        sys.exit("REFUSING: " + "; ".join(bad))


def schedule(season):
    """NBA schedule, cached once per day; degrade to the newest cached copy, else None with a visible note."""
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f"schedule-{season}-{datetime.date.today()}.json")
    if not os.path.exists(path):
        try:
            data = fetch(f"https://api.sleeper.com/schedule/nba/regular/{season}")
            assert isinstance(data, list) and data, "empty schedule"
            with open(path + ".tmp", "w") as f:
                json.dump(data, f)
            os.replace(path + ".tmp", path)
        except (OSError, ValueError, AssertionError) as e:
            old = sorted(glob.glob(os.path.join(CACHE, f"schedule-{season}-*.json")))
            if not old:
                print(f"NOTE: NBA schedule unavailable ({e}); game counts and rotation plan omitted.")
                return None
            print(f"NOTE: schedule fetch failed ({e}); using {os.path.basename(old[-1])}.")
            path = old[-1]
    with open(path) as f:
        return json.load(f)


def espn_tips(data):
    """ESPN scoreboard JSON -> [[away, home, "YYYY-MM-DDTHH:MMZ"]] in Sleeper team codes."""
    out = []
    for e in data.get("events") or []:
        side = {c["homeAway"]: c["team"]["abbreviation"] for c in e["competitions"][0]["competitors"]}
        out.append([ESPN_TEAM.get(side["away"], side["away"]), ESPN_TEAM.get(side["home"], side["home"]), e["date"]])
    return out


def tip_times(sched, days):
    """{(date, Sleeper team): naive UTC tip} for days, from ESPN cached per game date (refetched once a day; a failed
    fetch keeps an older copy). Only games whose team pair is on Sleeper's schedule that date count; the rest of
    Sleeper's games print a NOTE and keep date-level deadlines."""
    def one(day):
        path = os.path.join(CACHE, f"tips-{day}.json")
        try:
            if not (os.path.exists(path) and datetime.date.fromtimestamp(os.path.getmtime(path)) == datetime.date.today()):
                games = espn_tips(fetch(ESPN.format(day)))
                with open(path + ".tmp", "w") as f:
                    json.dump(games, f)
                os.replace(path + ".tmp", path)
        except (OSError, ValueError, KeyError) as e:
            if not os.path.exists(path):
                return day, None, e
        with open(path) as f:
            return day, json.load(f), None

    os.makedirs(CACHE, exist_ok=True)
    tips, missing = {}, []
    with concurrent.futures.ThreadPoolExecutor(7) as ex:
        for day, games, err in ex.map(one, days):
            want = {(g["away"]["team"], g["home"]["team"]) for g in sched or [] if g["date"] == day.isoformat()}
            got = {(aw, h): datetime.datetime.strptime(t, "%Y-%m-%dT%H:%MZ") for aw, h, t in games or []}
            for aw, h in want:
                if (aw, h) in got:
                    tips[(day, aw)] = tips[(day, h)] = got[(aw, h)]
                else:
                    missing.append(f"{day:%a} {aw}@{h}" + (f" ({err})" if err else ""))
    if missing:
        print(f"NOTE: no ESPN tip time for {len(missing)} game(s) ({', '.join(missing[:4])}"
              + (", ..." if len(missing) > 4 else "") + "); their deadlines are date-level: check the tip time in Sleeper.")
    return tips


def ct(utc):
    """Naive UTC -> US Central clock time. Python 3.8 has no zoneinfo, so the US DST rule by hand:
    CDT (UTC-5) from 2 AM CST on March's second Sunday (08:00 UTC) to 2 AM CDT on November's first (07:00 UTC)."""
    y = utc.year
    start = datetime.datetime(y, 3, 8 + (6 - datetime.date(y, 3, 8).weekday()) % 7, 8)
    end = datetime.datetime(y, 11, 1 + (6 - datetime.date(y, 11, 1).weekday()) % 7, 7)
    return utc - datetime.timedelta(hours=5 if start <= utc < end else 6)


def tip_text(day, team):
    """"Wed 10/21 6:10 PM CT tip" from ESPN's tip time, else the date-level "Wed 10/21's tip"."""
    t = CLOCK["tips"].get((day, team))
    if not t:
        return f"{day:{DAY}}'s tip"
    c = ct(t)
    return f"{c:{DAY}} {c.hour % 12 or 12}:{c:%M} {'AM' if c.hour < 12 else 'PM'} CT tip"


GAME_FINAL = datetime.timedelta(hours=3)  # a game runs about 2 1/4 h; week_over uses the same margin


def final(day, team):
    """Whether team's game on day is probably final: it tipped GAME_FINAL ago (False without a tip time or clock)."""
    t = CLOCK["tips"].get((day, team))
    return bool(t and CLOCK["now"] and t + GAME_FINAL <= CLOCK["now"])


def tipped(day, team):
    """His team's game on day has tipped by the real clock (never on a --date dry run, which has no clock)."""
    t = CLOCK["tips"].get((day, team))
    return bool(t and CLOCK["now"] and t <= CLOCK["now"])


def deadline(pool, pid, after, fills):
    """When pid's finished score must be decided -> (day, team, who) or None: the earlier of his next tip (after:
    his later game dates) and the slot's next tip in the plan (fills: slot_rest's [(day, who)]), because a score
    must be decided before he leaves the slot. who is the player whose tip it is. A fill whose tip has passed is
    skipped: either it happened (he left the slot) or the Owner didn't make it, so it no longer bounds the score (#20)."""
    team = lambda p: pool.get(p, {}).get("team")
    opts = ([(after[0], pid)] if after else []) + [f for f in fills if not tipped(f[0], team(f[1]))][:1]
    if not opts:
        return None
    day, who = min(opts, key=lambda o: (o[0], CLOCK["tips"].get((o[0], team(o[1]))) or datetime.datetime.min))
    return day, team(who), who


def pdf_words(data):
    """PDF bytes -> per page [(y, x, word)] in PDF points (y up). pypdf is pure Python (~/.local here, not stdlib):
    without it injury_report falls back to Sleeper tags."""
    import pypdf
    pages = []
    for page in pypdf.PdfReader(io.BytesIO(data)).pages:
        words = []

        def visit(text, cm, tm, *_):
            if text.strip():
                m = pypdf.mult(tm, cm)
                words.append((m[5], m[4], text.strip()))
        page.extract_text(visitor_text=visit)
        pages.append(words)
    return pages


def report_rows(pages):
    """[(date iso, "First Last", status)] from the injury report's words (pages in order). Columns start at the
    header's Player/Current/Reason x; a game date carries down to the rows below it, across pages."""
    cols, day, out = None, None, []
    for words in pages:
        rows = {}
        for y, x, w in words:
            rows.setdefault(round(y), []).append((x, w))
        for y in sorted(rows, reverse=True):
            line = sorted(rows[y])
            if {"Player", "Current", "Reason"} <= {w for _, w in line}:
                cols = {w: x - 3 for x, w in line}
                continue
            if cols is None:
                continue
            day = next((w for x, w in line if x < cols["Player"] and re.fullmatch(r"\d\d/\d\d/\d{4}", w)), day)
            name = " ".join(w for x, w in line if cols["Player"] <= x < cols["Current"])
            st = " ".join(w for x, w in line if cols["Current"] <= x < cols["Reason"])
            if day and "," in name and st:
                last, first = name.split(",", 1)
                out.append((datetime.datetime.strptime(day, "%m/%d/%Y").date().isoformat(), f"{first.strip()} {last.strip()}", st))
    return out


def injury_report(season, pool):
    """Latest official NBA injury report into REPORT, each report parsed once to .cache/injury-<date>-<HHMM ET>.json.
    If that fails: today's newest cached report, else a NOTE and Sleeper tags (REPORT stays empty)."""
    try:
        html = fetch(INJURY_INDEX.format(season, (season + 1) % 100), raw=True).decode("utf-8", "replace")
        m = max(re.finditer(r'https://[^"\s]+/Injury-Report_(\d{4}-\d\d-\d\d)_(\d\d)_(\d\d)([AP]M)\.pdf', html),
                key=lambda m: (m[1], m[4], int(m[2]) % 12, m[3]))
        path = os.path.join(CACHE, f"injury-{m[1]}-{int(m[2]) % 12 + 12 * (m[4] == 'PM'):02d}{m[3]}.json")
        if not os.path.exists(path):
            rows = report_rows(pdf_words(fetch(m[0], raw=True)))
            assert rows, f"no player rows parsed from {m[0]}"
            with open(path + ".tmp", "w") as f:
                json.dump(rows, f)
            os.replace(path + ".tmp", path)
    except Exception as e:  # network, no link yet, pypdf missing or a changed layout: all degrade to Sleeper tags
        old = sorted(glob.glob(os.path.join(CACHE, f"injury-{datetime.date.today()}-*.json")))
        if not old:
            print(f"NOTE: NBA injury report unavailable ({e}); play chances use Sleeper tags "
                  f"(DTD {P_DTD[0]:.2f} next game, {P_DTD[1]:.2f} later).")
            return
        print(f"NOTE: NBA injury report fetch failed ({e}); using {os.path.basename(old[-1])}.")
        path = old[-1]
    with open(path) as f:
        rows = json.load(f)
    by_name, pids = draft.name_index(pool), {}
    for day, name, st in rows:  # ponytail: name-only match (name_index prefers rostered NBA players); add team if collisions bite
        if draft.norm(name) in by_name and st in P_REPORT:
            pids.setdefault(by_name[draft.norm(name)], {})[datetime.date.fromisoformat(day)] = st
    t = re.search(r"injury-\d{4}-(\d\d)-(\d\d)-(\d\d)(\d\d)", path)
    REPORT.update(at=f"{t[1]}/{t[2]} {t[3]}:{t[4]} ET", pids=pids)


def board_values(notes):
    """pid -> (V/wk, FP/g) parsed from board.txt notes; unprojected and excluded players are absent.
    FP/g is the one behind V: a blended note's "-> X/g", else the ECR-calibrated "cal X/g", else the raw projection."""
    out = {}
    for pid, n in notes.items():
        v = re.search(r"V\+([\d.]+)/wk", n)
        g = re.search(r"-> ([\d.]+)/g", n) or re.search(r"\| cal ([\d.]+)/g", n) or re.search(r"\| ([\d.]+)/g", n)
        if v and g and not n.startswith("DO NOT DRAFT"):
            out[pid] = (float(v.group(1)), float(g.group(1)))
    return out


def out_all_week(st):
    """Out, or an IR-eligible tag (IR/Sus/DNR/Out) on an active-roster player: no games this week."""
    return st == "Out" or st.upper() in IR_OK


def fpg_of(d, pid):
    """Board FP/g for the Lock-In math; an unprojected player, or one out all week, is 0."""
    return 0.0 if out_all_week(status(d["pool"], pid)) else d["vals"].get(pid, (0, 0.0))[1]


def load(a):
    cfg = json.load(open(os.path.join(draft.PRIVATE, "config.json")))
    lid = cfg["league_id"]
    paths = {"league": f"/league/{lid}", "rosters": f"/league/{lid}/rosters",
             "users": f"/league/{lid}/users", "state": "/state/nba"}
    try:
        with concurrent.futures.ThreadPoolExecutor(4) as ex:
            futs = {k: ex.submit(draft.get, p) for k, p in paths.items()}
            d = {k: f.result() for k, f in futs.items()}
    except (OSError, ValueError) as e:
        refuse([f"live Sleeper fetch failed ({e}); fresh advice unavailable"])
    refuse(validate(cfg, d["league"], d["rosters"]))
    pool = draft.players(refresh=a.refresh)
    board, missing, notes = draft.load_board(pool)
    today, sched = a.date or datetime.date.today(), schedule(d["league"]["season"])
    week = getattr(a, "week", None) or (a.date and week_of(sched, today)) or d["state"]["week"]
    d.update(cfg=cfg, pool=pool, board=board or [], notes=notes, vals=board_values(notes),
             names={u["user_id"]: u["display_name"] for u in d["users"]}, today=today, week=week, sched=sched)
    days = week_days(sched, week)
    if days and not days[0] <= today <= days[-1] and a.cmd != "review":  # review reads a finished week
        print(f"WARN: today {today:%a %m/%d} is outside week {week} ({days[0]:%a %m/%d} – {days[-1]:%a %m/%d}): "
              f"days left, game counts and lock calls assume that week.")
    d["team"] = {r["roster_id"]: d["names"].get(r["owner_id"], f"roster {r['roster_id']}") for r in d["rosters"]}
    if missing:
        print(f"NOTE: board.txt names not matched to Sleeper: {', '.join(missing)}")
    if a.cmd not in ("standings", "changes", "review"):  # the commands that price play chances (review: as healthy)
        injury_report(int(d["league"]["season"]), pool)
    if a.cmd in ("week", "lock", "fa", "matchup") and sched:  # deadlines and feeds need tip times
        CLOCK.update(now=None if a.date else datetime.datetime.utcnow(),
                     tips=tip_times(sched, days))  # past tips also establish pending-score eligibility
    if not a.date and week == d["state"]["week"] and a.cmd != "review" and not getattr(a, "no_write", False):
        path = os.path.join(STATE, f"lineups-{d['league']['season']}-w{week}.json")
        d["lineup_since"], d["lineup_runs"] = observe_lineups(d["rosters"], datetime.datetime.utcnow(), path)
    return d


def observe_lineups(rosters, now, path):
    """-> ({rid: {pid: first observation of each current starter since his last observed absence}}, [every run's time]).
    The run times show when an absence was observed: a run between a game's tip and his streak's start saw him out."""
    try:
        old = json.load(open(path))
        if not isinstance(old, dict) or "since" not in old:  # pre-run-log format: {rid: {pid: since}}, no runs known
            old = {"since": old, "runs": []}
        since, runs = old["since"], old["runs"]
        if not isinstance(since, dict) or not isinstance(runs, list) or any(not isinstance(v, dict) for v in since.values()):
            raise ValueError("invalid lineup history")
        for stamp in runs + [x for roster in since.values() for x in roster.values()]:
            stamp = datetime.datetime.fromisoformat(stamp)
            if stamp.tzinfo is not None or stamp > now:
                raise ValueError("invalid observation time")
    except (OSError, ValueError, TypeError, AttributeError):
        since, runs = {}, []
    new = {str(r["roster_id"]): {p: since.get(str(r["roster_id"]), {}).get(p, now.isoformat())
                               for p in r.get("starters") or [] if p != "0"} for r in rosters}
    runs = runs + [now.isoformat()]
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".tmp", "w") as f:
            json.dump({"since": new, "runs": runs}, f)
        os.replace(path + ".tmp", path)
    except OSError as e:
        # A failed bench observation must not leave pre-bench evidence reusable on the next run.
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError:
            try:
                with open(path, "w") as f:
                    f.write("{}")
            except OSError:
                sys.exit(f"Lineup history unsafe after save failure: remove {path} before running again.")
        print(f"NOTE: lineup observations could not be saved ({e}); lock eligibility is unobserved this run.")
        return {}, []
    return {int(rid): players for rid, players in new.items()}, runs


def observed_start(d, rid, pid, day):
    """True: observed starting before this game's tip, with no observed benching since. False: a run at or after the
    tip saw him out of the starting lineup (benched, or played from the bench). None: no run in between, unknown (e.g.
    the week's first run came after the tip); gaps between runs are always unknown."""
    since = (d.get("lineup_since") or {}).get(rid, {}).get(pid)
    since = datetime.datetime.fromisoformat(since) if since else datetime.datetime.max
    # Compare UTC timestamps, never UTC calendar dates against the schedule's ET game dates.
    # Without a tip, a start counts only if observed before the ET game date began, an absence only after it ended.
    tip = CLOCK["tips"].get((day, d["pool"].get(pid, {}).get("team")))
    if since < (tip or datetime.datetime.combine(day, datetime.time(4))):
        return True
    out_from = tip or datetime.datetime.combine(day + datetime.timedelta(1), datetime.time(5))
    if any(out_from <= datetime.datetime.fromisoformat(t) < since for t in d.get("lineup_runs") or []):
        return False
    return None


def board_basis(text, sched):
    """"frozen Oct 19", or "blended through week N" from the in-season blend header rebuild_board writes."""
    m = re.search(r"^# In-season blend:.*games through (\d{4}-\d{2}-\d{2})", text, re.M)
    if not m:
        return "frozen Oct 19"
    day = datetime.date.fromisoformat(m.group(1))
    week = week_of(sched, day)
    return f"blended through week {week}" if week else f"blended through {day:%b %d}"


def footer(d):
    with open(os.path.join(HERE, "board.txt")) as f:
        basis = board_basis(f.read(), d.get("sched"))
    tags = draft.PLAYERS_PATH
    tags = (f"{os.path.basename(tags)} fetched {datetime.datetime.fromtimestamp(os.path.getmtime(tags)):%m/%d %H:%M}"
            if tags and os.path.exists(tags) else "(no tags file read)")
    print(f"\nData: live Sleeper league/rosters (validated); player tags from {tags} "
          f"(refetched when 3 h old; --refresh to force); board.txt V/FP from {basis}"
          + (f"; play chances from the official NBA injury report {REPORT['at']} where it lists a game" if REPORT["at"] else "")
          + f"; today={d['today']}.")


# ---------- small helpers ----------

def pos_of(pool, pid):
    p = pool.get(pid, {})
    return p.get("fantasy_positions") or [p.get("position") or "?"]


def status(pool, pid):
    return pool.get(pid, {}).get("injury_status") or ""


def short(pool, pid, n=22):
    if pid in (None, "0"):  # Sleeper's empty starter slot
        return "empty slot"
    return (pool.get(pid, {}).get("full_name") or pid)[:n]


def week_games(sched, week):
    """team -> {date: 'OPP' (home) or '@OPP' (away)} for one Sleeper week."""
    out = {}
    for g in sched or []:
        if g["week"] == week:
            day, h, aw = datetime.date.fromisoformat(g["date"]), g["home"]["team"], g["away"]["team"]
            out.setdefault(h, {})[day] = aw
            out.setdefault(aw, {})[day] = "@" + h
    return out


def week_days(sched, week):
    dates = sorted({datetime.date.fromisoformat(g["date"]) for g in sched or [] if g["week"] == week})
    if not dates:
        return []
    mon = dates[0] - datetime.timedelta(dates[0].weekday())
    return [mon + datetime.timedelta(i) for i in range(7)]


def week_of(sched, day):
    """The schedule week whose Mon–Sun contains day, else None."""
    return next((w for w in sorted({g["week"] for g in sched or []}) if day in week_days(sched, w)), None)


def games_of(d, pid, wg):
    """{date: opponent} for the player's NBA team this week ({} if none)."""
    return wg.get(d["pool"].get(pid, {}).get("team"), {})


def find_roster(d, key):
    for r in d["rosters"]:
        if str(r["roster_id"]) == str(key) or d["team"][r["roster_id"]].lower() == str(key).lower():
            return r
    sys.exit(f"No team matches {key!r}: " + ", ".join(d["team"].values()))


# ---------- Lock-In math (rebuild_board's fitted model) ----------

@functools.lru_cache(maxsize=None)
def draws(ppg):
    """Same per-game score grid as rebuild_board.lock_values (fitted CV curve, 200 normal quantiles)."""
    cv = min(0.6, max(0.2, rb.CV_A + rb.CV_B * math.log(max(ppg, 1))))
    return tuple(max(0.0, ppg * (1 + cv * z)) for z in rb.Z_GRID)


def stop_value(days):
    """Expected locked score for one slot by optimal stopping over chronological game days.

    days: per day, the options for who fills the slot, as [(FP/g, play probability)]. Backward
    induction: a day's value is the best option's p*E[max(X, V_next)] + (1-p)*V_next. With no lock the
    final game counts (0 if he sits), hence V = 0 after the last day.
    """
    return _stop_value(tuple(map(tuple, days)))


@functools.lru_cache(maxsize=1 << 16)  # trade.py's season simulation re-values the same slot weeks many times
def _stop_value(days):
    v = 0.0
    for opts in reversed(days):
        v = max([v] + [p * sum(max(x, v) for x in draws(g)) / len(rb.Z_GRID) + (1 - p) * v for g, p in opts])
    return v


def slot_options(days, mine, fpg, feeders):
    """Per day, who can fill a slot: the starter on his game days (mine: {day: play chance}) plus each
    bench feeder (FP/g, {game date: play chance}) who plays that day. Days without the starter are feeder-only."""
    return [([(fpg, mine[day])] if day in mine else []) + [(g, dates[day]) for g, dates in feeders if day in dates]
            for day in days]


def play_on(day, dates):
    """Chance a regular plays a game: 2025-26 backtest DNP rate, higher on the second night of a back-to-back."""
    return 1 - (Q_B2B if day - datetime.timedelta(1) in dates else Q_DNP)


def play_map(dates, st="", today=None, pid=None):
    """{game date: chance he plays}: play_on's rule, lowered for a DTD player's next game on or after today
    (P_DTD[0]) and his later ones (P_DTD[1]); a game the NBA injury report lists for pid takes P_REPORT instead.
    Week's `games` holds these maps, so `day in games[p]` still works."""
    out = {day: play_on(day, dates) for day in dates}
    if st in DTD:
        for k, day in enumerate(sorted(day for day in dates if today is None or day >= today)):
            out[day] = min(out[day], P_DTD[0] if k == 0 else P_DTD[1])
    for day, s in REPORT["pids"].get(pid, {}).items():
        if day in out:
            out[day] = min(play_on(day, dates), P_REPORT[s])
    return out


def stop_moments(days):
    """stop_value's policy (lock when the score reaches the value of waiting) -> (mean, second moment)
    of the slot's locked score, by the same backward induction."""
    v = v2 = 0.0
    for opts in reversed(days):
        best = (v, v2)
        for g, p in opts:
            xs = draws(g)
            m = p * sum(max(x, v) for x in xs) / len(xs) + (1 - p) * v
            if m > best[0]:
                best = (m, p * sum(x * x if x >= v else v2 for x in xs) / len(xs) + (1 - p) * v2)
        v, v2 = best
    return v, v2


def wait_value(ppg, plays):
    """DNP-corrected continuation over his remaining games (plays: chance he plays each one).
    V1 = (1-q)E[X]; Vk = (1-q)E[max(X, V(k-1))] + q V(k-1). q = 0 is rebuild_board.lock_values."""
    return stop_value([[(ppg, p)] for p in plays])


def thresholds(ppg, q=None, n=5):
    """Score needed to lock with k = 1..n games left (default q: Q_DNP)."""
    q = Q_DNP if q is None else q
    return [wait_value(ppg, [1 - q] * k) for k in range(1, n + 1)]


def best_lineup(players, value, slots=SLOTS):
    """Exact max-value legal lineup. players: [(pid, positions)]; at most C(14, 9) = 2002 subsets."""
    players = [p for p in players if value.get(p[0], 0) > 0] or players
    for r in range(min(len(slots), len(players)), 0, -1):
        best, best_sum = None, -1.0
        for combo in itertools.combinations(players, r):
            total = sum(value.get(p[0], 0) for p in combo)
            if total <= best_sum:  # can't win: skip the slot fit (same result, ~10x faster for fa's stream search)
                continue
            fit = draft.fill_slots(slots, list(combo))
            if len(fit) == r:
                best, best_sum = fit, total
        if best is not None:
            return best
    return {}


def keep_slots(base, sleeper, fixed, pos):
    """base's players re-slotted so the most Sleeper starters keep their Sleeper slot (same players, same
    expected score): the moves to reach it are then only the slots whose occupant changes. fixed: {slot: pid}
    always kept (locked players). At most 2^9 small matchings, and only when starters are set."""
    keep = [(i, p) for i, p in sleeper.items() if i not in fixed and p in base.values()]
    for r in range(len(keep), -1, -1):
        for pins in itertools.combinations(keep, r):
            pinned = {**fixed, **dict(pins)}
            rest = [p for p in base.values() if p not in pinned.values()]
            free = [i for i in range(len(SLOTS)) if i not in pinned]
            fit = draft.fill_slots([SLOTS[i] for i in free], [(p, pos[p]) for p in rest])
            if len(fit) == len(rest):
                return {**pinned, **{free[j]: p for j, p in fit.items()}}
    return base


def rotation(slots, base, bench, games, days, pos, fpg, blocked=(), gone=(), floor=None):
    """Day by day, put each bench player who plays (best first) into the idle-starter slot where his game
    adds the most expected locked score for the week. Locked (blocked) slots take no feeds, and a bench player
    whose game has tipped ((pid, day) in gone) can't be moved in.

    base: {slot_index: pid}; bench: pids; games: {pid: {date: play chance}} (play_map); floor: {slot_index: a standing
    score the slot keeps unless its rolls beat it}. Returns {day: {slot_index: pid}}.
    """
    # ponytail: greedy by marginal gain, not a joint optimum; benching a playing starter is left to judgment.
    plan = {day: {} for day in days}

    def value(i):
        return max((floor or {}).get(i, 0.0),
                   stop_value(slot_days(days, base.get(i), {day: plan[day][i] for day in days if i in plan[day]}, games, fpg)))

    for day in days:
        for p in sorted((p for p in bench if day in games.get(p, ()) and (p, day) not in gone), key=lambda p: -fpg.get(p, 0)):
            best, best_gain = None, 1e-9
            for i in range(len(slots)):
                if (i in blocked or i in plan[day] or plays(base.get(i), day, games, fpg)
                        or not draft.SLOT_ELIGIBLE[slots[i]] & set(pos[p])):
                    continue
                before = value(i)
                plan[day][i] = p
                gain = value(i) - before
                del plan[day][i]
                if gain > best_gain:
                    best, best_gain = i, gain
            if best is not None:
                plan[day][best] = p
        # Seat the rest in any idle slot they fit, even at no gain to that slot alone: a bench score can be locked
        # against a cheaper slot it reaches (joint_locks), so an extra roll is never worthless (issue #26).
        rest = [p for p in bench if plays(p, day, games, fpg) and (p, day) not in gone and p not in plan[day].values()]
        idle = [i for i in range(len(slots)) if i not in blocked and i not in plan[day] and not plays(base.get(i), day, games, fpg)]
        fit = draft.fill_slots([slots[i] for i in idle], [(p, pos[p]) for p in rest])
        plan[day].update({idle[j]: p for j, p in fit.items()})
    return plan


def reuse(slots, base, bench, games, days, pos, fpg, plan, tips, blocked=(), gone=()):
    """Same-night slot reuse after rotation's plan: a bench player who plays a day but feeds no slot takes a slot
    whose roll that day tips at least REUSE_GAP from his own tip, before it (he plays early, the slot's player
    returns for the late tip) or after it (the slot's early game is final and decided, then he goes in).
    tips: {(pid, day): naive UTC tip}; no tip time, no reuse. Returns {day: {slot_index: (pid, late)}}."""
    # ponytail: greedy on top of rotation's greedy plan, at most one extra roll per slot per night; the
    # backtest measured this version. Upgrade: plan jointly if 3-tip nights (weekend afternoons) show up often.
    extra = {day: {} for day in days}

    def value(i):
        feeds = {day: plan[day][i] for day in days if i in plan[day]}
        return stop_value(slot_days(days, base.get(i), feeds, games, fpg, {day: extra[day][i] for day in days if i in extra[day]}))

    for day in days:
        for p in sorted((p for p in bench if plays(p, day, games, fpg) and (p, day) not in gone
                         and p not in plan[day].values() and tips.get((p, day))), key=lambda p: -fpg.get(p, 0)):
            t, best, best_gain = tips[(p, day)], None, 1e-9
            for i in range(len(slots)):
                occ = slot_who(day, base.get(i), {day: plan[day][i]} if i in plan[day] else {}, games, fpg)
                if (i in blocked or i in extra[day] or occ is None or not tips.get((occ, day))
                        or abs(t - tips[(occ, day)]) < REUSE_GAP or not draft.SLOT_ELIGIBLE[slots[i]] & set(pos[p])):
                    continue
                before = value(i)
                extra[day][i] = (p, t > tips[(occ, day)])
                gain = value(i) - before
                del extra[day][i]
                if gain > best_gain:
                    best, best_gain = i, gain
            if best is not None:
                extra[day][best] = (p, t > tips[(slot_who(day, base.get(best), {day: plan[day][best]} if best in plan[day] else {},
                                                          games, fpg), day)])
    return extra


def plays(p, day, games, fpg):
    """A scheduled roll with nonzero play chance and FP/g; ruled-out games leave the slot idle."""
    return games.get(p, {}).get(day, 0) > 0 and fpg.get(p, 0) > 0


def slot_who(day, starter, feeds, games, fpg):
    """Who fills a slot on a day: its starter on his game days, else that day's feeder (or None)."""
    return starter if plays(starter, day, games, fpg) else feeds.get(day)


def slot_days(days, starter, feeds, games, fpg, extra=None):
    """Per-day options for one slot: its starter on his game days, else that day's feeder; plus a same-night
    reuse roll (extra: {day: (pid, late)}) after that roll when late, else before it."""
    out = []
    for day in days:
        who = slot_who(day, starter, feeds, games, fpg)
        rolls = [who] if who else []
        if extra and day in extra:
            q, late = extra[day]
            rolls = rolls + [q] if late else [q] + rolls
        out += [[(fpg.get(p, 0.0), games[p][day])] for p in rolls] or [[]]
    return out


def feeds_of(w, i):
    """Slot i's rotation feeds {day: pid} and same-night reuse rolls {day: (pid, late)} over the days left."""
    return ({day: w["plan"][day][i] for day in w["left"] if i in w["plan"][day]},
            {day: w["extra"][day][i] for day in w["left"] if i in w.get("extra", {}).get(day, {})})


def slot_rest(w, i, after, pid=None, moments=False):
    """Slot i after pid's finished game on day after -> (wait value, [(day, who)]), plus the locked score's second
    moment under that policy when moments (stop_moments' rule, for the matchup line's variance).
    Allow available bench players to replace a playing occupant too: the live occupant may be yesterday's
    feeder, not the player who should return. Do not steal a feeder already assigned to another slot, or feed a
    bench player whose game has tipped. On a night with a same-night reuse roll in slot i, the plan's two rolls
    count in tip order, and on pid's own night only the roll that tips after his game."""
    if i in w["blocked"]:
        return (0.0, [], 0.0) if moments else (0.0, [])
    days = [day for day in w["left"] if day > after]
    cutoff = max(w["today"], after + datetime.timedelta(1))
    games = {p: play_map(gm, w["statuses"][p], cutoff, p) for p, gm in w["games"].items()}
    for p, override in w.get("game_overrides", {}).items():
        if p in games:
            games[p].update(override)
    games_on = lambda day: w["games"] if day == after else games  # the cutoff drops a DTD discount on pid's own night
    s, elig = w["base"].get(i), draft.SLOT_ELIGIBLE[SLOTS[i]]
    value, m2, fills = 0.0, 0.0, []

    def expected(p, day):
        probability = games_on(day)[p][day]
        return probability * sum(max(x, value) for x in draws(w["fpg"][p])) / len(rb.Z_GRID) + (1 - probability) * value

    def roll(p, day):
        """p takes the slot's roll on day: the value and second moment before it (ties lock, as stop_moments)."""
        nonlocal value, m2
        probability, xs = games_on(day)[p][day], draws(w["fpg"][p])
        m2 = probability * sum(x * x if x >= value else m2 for x in xs) / len(xs) + (1 - probability) * m2
        value = expected(p, day)
        fills.append((day, p))

    def rolls(day):
        """The plan's rolls in slot i on a reuse night, latest tip first (backward induction)."""
        q, late = w["extra"][day][i]
        occ = slot_who(day, s, {day: w["plan"][day][i]} if i in w["plan"][day] else {}, games_on(day), w["fpg"])
        return [p for p in ([q, occ] if late else [occ, q]) if p and plays(p, day, games_on(day), w["fpg"])]

    for day in reversed(days):
        if i in w.get("extra", {}).get(day, {}):
            for who in rolls(day):
                roll(who, day)
            continue
        assigned = {p for j, p in w["plan"][day].items() if j != i} | {q for j, (q, _) in w.get("extra", {}).get(day, {}).items() if j != i}
        candidates = [s] + [p for p in w["bench"] if p not in assigned and elig & set(w["pos"][p])
                            and (p, day) not in w.get("tipped", ())]
        available = [p for p in candidates if plays(p, day, games, w["fpg"])]
        who = max(available, key=lambda p: expected(p, day), default=None)
        if who is not None:
            roll(who, day)
    if i in w.get("extra", {}).get(after, {}):
        later = rolls(after)
        later = later[:later.index(pid)] if pid in later else later[:1]  # the rolls after pid's (the late one)
        for who in later:
            roll(who, after)
    return (value, list(reversed(fills))) + ((m2,) if moments else ())


def lanes_after(w, day, occ=None):
    """Each open slot after day's games -> {i: (occupant on day, wait value, fills, second moment)}. occ: {i: pid} known
    occupants (a box score's starter); otherwise the plan's (slot_who)."""
    out = {}
    for i in range(len(SLOTS)):
        if i in w["blocked"]:
            continue
        feeds = w["plan"].get(day, {})
        who = (occ or {}).get(i) or slot_who(day, w["base"].get(i), {day: feeds[i]} if i in feeds else {}, w["games"], w["fpg"])
        out[i] = (who,) + slot_rest(w, i, day, who, moments=True)
    return out


def feed_reach(w, lanes):
    """{i: {j}}: for each bench player's score (occupant not the slot's base starter, with later players in his
    slot), the other open slots it can close. One hop: lock him in slot i, every later player of slot i moves to
    slot j whole (each must be eligible for it), and j's starter goes to the bench. A last roll counts in place."""
    fits = lambda p, j: draft.SLOT_ELIGIBLE[SLOTS[j]] & set(w["pos"].get(p, ()))
    return {i: {j for j in lanes if j != i and all(fits(p, j) for _, p in fills)}
            for i, (who, _, fills, _) in lanes.items() if who and who != w["base"].get(i) and fills}


def joint_locks(feeds, prices, reach):
    """Which bench scores to lock, and which slot each closes. feeds: {i: score} in slot i; prices: {j: price},
    an open slot's wait value (or its starter's standing score, if higher); reach: feed_reach. Locking feed i
    closes slot i or a slot it reaches; each slot is touched once. Maximizes sum(score - price), less MOVE_COST per
    lock in another slot: with free reach, the best score takes the cheapest slot, the next the next-cheapest
    (issue #26) -> {i: j}."""
    order = sorted(feeds, key=lambda i: (-feeds[i], i))
    best = [(0.0, 0), {}]

    def go(k, used, chosen, gain):
        key = (round(gain, 9), len(chosen))  # ties lock, as stop_value does
        if key > best[0]:
            best[:] = [key, dict(chosen)]
        if k == len(order):
            return
        go(k + 1, used, chosen, gain)
        i = order[k]
        for j in ([] if i in used else [i] + sorted(reach.get(i, ()))):
            if j not in used and j in prices and feeds[i] >= prices[j]:
                chosen[i] = j
                go(k + 1, used | {i, j}, chosen, gain + feeds[i] - prices[j] - (MOVE_COST if j != i else 0))
                del chosen[i]

    go(0, frozenset(), {}, 0.0)
    return best[1]


def game_fp(stats):
    s = dict(stats)
    s.setdefault("ftmi", s.get("fta", 0) - s.get("ftm", 0))
    return sum(s.get(k, 0) * w for k, w in SCORING.items())


# ---------- commands ----------

def play_note(st, pm, today, pid=None):
    """The play chances the math uses for a tagged or injury-report-listed player's games from today on, with
    their source once the report loaded ("" if untagged and listed at most Available)."""
    rep = REPORT["pids"].get(pid, {})
    if not st and set(rep.values()) <= {"Available"}:
        return ""
    if out_all_week(st):
        return f"play 0 all week ({st})"
    days = [day for day in sorted(pm) if day >= today]
    src = (f" (NBA report {REPORT['at']})" if any(day in rep for day in days) else
           f" (Sleeper tag; not on NBA report {REPORT['at']})" if REPORT["at"] else "")
    return "play " + (" ".join(f"{day:%a} {pm[day]:.2f}" + (f" {rep[day]}" if day in rep else "") for day in days)
                      or "no games left") + src


def slot_warnings(slot, name, st, n_reserve):
    """Roster WARN lines for one player in a slot (BN, IR or a starting slot) with Sleeper status st."""
    warn = []
    if st.upper() in IR_OK and slot != "IR":
        warn.append(f"{name} is {st} but not on IR: move to IR to free a spot ({IR_SLOTS - n_reserve} IR open)")
    if slot == "IR" and st.upper() not in IR_OK:
        warn.append(f"{name} on IR but status {st or 'healthy'}: Sleeper blocks adds until he's moved off IR "
                    f"(unverified), and he needs a bench spot")
    if st and slot not in ("BN", "IR"):
        warn.append(f"{name} starts at {slot} with status {st}: confirm before tip")
    return warn


def cmd_roster(d, a):
    r = find_roster(d, a.team) if a.team else find_roster(d, MY_ROSTER)
    pool, wg = d["pool"], week_games(d["sched"], d["week"])
    starters, reserve = r.get("starters") or [], r.get("reserve") or []
    bench = [p for p in r["players"] if p not in starters and p not in reserve]
    rank = {pid: i for i, pid in enumerate(d["board"], 1)}
    print(f"{d['team'][r['roster_id']]} (roster {r['roster_id']}) — week {d['week']} — "
          f"{len(r['players'])} players, IR {len(reserve)}/{IR_SLOTS}")
    print(f"  {'Slot':<5}{'Player':<23}{'Pos':<10}{'Team':<5}{'Status':<8}{'Board':>6}{'V/wk':>6}{'FP/g':>6}  Games this week")
    rows = [(SLOTS[i] if i < len(SLOTS) else "?", p) for i, p in enumerate(starters)] + \
           [("BN", p) for p in bench] + [("IR", p) for p in reserve]
    warn = []
    for slot, pid in rows:
        if pid in ("0", None):
            print(f"  {slot:<5}— EMPTY —")
            warn.append(f"{slot} is empty")
            continue
        v, g = d["vals"].get(pid, (None, None))
        gm = games_of(d, pid, wg)
        days = " ".join(day.strftime("%a") for day in sorted(gm)) if d["sched"] else "?"
        st = status(pool, pid)
        note = play_note(st, play_map(gm, st, d["today"], pid), d["today"], pid) if d["sched"] else ""
        print(f"  {slot:<5}{short(pool, pid):<23}{'/'.join(pos_of(pool, pid)):<10}"
              f"{pool.get(pid, {}).get('team') or 'FA':<5}{st or '-':<8}{('#' + str(rank[pid])) if pid in rank else '-':>6}"
              f"{f'{v:.1f}' if v is not None else 'NOPROJ':>6}{f'{g:.1f}' if g is not None else '':>6}  "
              f"{len(gm) if d['sched'] else '?'} {days}"
              + (f"  | {note}" if note else ""))
        warn += slot_warnings(slot, short(pool, pid), st, len(reserve))
    for w in warn:
        print("WARN: " + w)
    footer(d)


def week_context(d, sleeper_base=False, rid=MY_ROSTER):
    """A team's (default the Owner's) players, this week's games, base lineup by expected locked score, and
    the rotation plan. sleeper_base: keep Sleeper's lineup as the base (lock calls judge the slots as they stand)."""
    pool, r = d["pool"], find_roster(d, rid)
    wg, days = week_games(d["sched"], d["week"]), week_days(d["sched"], d["week"])
    left = [day for day in days if day >= d["today"]]
    reserve = r.get("reserve") or []
    active = [p for p in r["players"] if p not in reserve]
    adds = d.get("adds") or {}  # {pid: first date that counts}: after an add only later games score
    games = {p: play_map({day: o for day, o in games_of(d, p, wg).items() if day >= adds.get(p, day)},
                         status(pool, p), d["today"], p) for p in active}
    for p, override in d.get("game_overrides", {}).items():
        if p in games:
            games[p].update(override)
    for p in set(active) - set(r.get("starters") or []):  # benched at tip: that game can't count in any slot
        games[p].update({day: 0.0 for day in left if day in games[p] and tipped(day, pool.get(p, {}).get("team"))})
    fpg = {p: fpg_of(d, p) for p in active}
    exp = {p: wait_value(fpg[p], [games[p][day] for day in left if day in games[p]]) for p in active}
    for p, x in (d.get("standing") or {}).items():  # lock's team comparison: a posted score he can still lock
        if p in exp:
            exp[p] = max(exp[p], x)
    sleeper = {i: p for i, p in enumerate(r.get("starters") or []) if p in active}
    locked = set(d.get("locked") or []) & set(active)  # pids, from locked_pids
    base = {i: p for i, p in sleeper.items() if p in locked}  # a locked player stays in his slot; the rest is re-optimized
    free = [i for i in range(len(SLOTS)) if i not in base]
    fit = best_lineup([(p, pos_of(pool, p)) for p in active if p not in locked], exp, [SLOTS[i] for i in free])
    base.update({free[j]: p for j, p in fit.items()})
    base = keep_slots(base, sleeper, {i: p for i, p in base.items() if p in locked}, {p: pos_of(pool, p) for p in active})
    gain = sum(exp[p] for p in base.values()) - sum(exp[p] for p in sleeper.values())
    if gain < 2.0 or sleeper_base:  # within noise: keep Sleeper's slots so the plan matches the app
        base = sleeper
    blocked = {i for i, p in base.items() if p in locked}  # a locked player keeps his slot all week
    starters = set(base.values())
    bench = sorted((p for p in active if p not in starters and p not in locked), key=lambda p: -fpg[p])
    gone = {(p, day) for p in bench for day in left if day in games[p] and tipped(day, pool.get(p, {}).get("team"))}
    pos = {p: pos_of(pool, p) for p in active}
    standing = d.get("standing") or {}  # lock's team comparison: posted scores feeds must beat
    plan = rotation(SLOTS, base, bench, games, left, pos, fpg, blocked, gone, {i: standing[p] for i, p in base.items() if p in standing})
    tips = {(p, day): CLOCK["tips"].get((day, pool.get(p, {}).get("team"))) for p in active for day in games[p]}
    extra = reuse(SLOTS, base, bench, games, left, pos, fpg, plan, tips, blocked, gone)
    return dict(blocked=blocked, tipped=gone, gain=gain, r=r, wg=wg, days=days, left=left, games=games, fpg=fpg, exp=exp, base=base, bench=bench, plan=plan,
                extra=extra,
                today=d["today"], statuses={p: status(pool, p) for p in active},
                pos={p: pos_of(pool, p) for p in active}, game_overrides=d.get("game_overrides", {}))


def cmd_week(d, a):
    if not d["sched"]:
        print("Schedule unavailable: no game grid or rotation plan. Use Sleeper's schedule view.")
        return footer(d)
    d["locked"] = locked_pids(d, a.locked)
    for item in filter(str.strip, (getattr(a, "play", None) or "").split(",")):  # "Name=P": his play chance from today
        name, _, p = item.rpartition("=")
        pid = find_mine(d, find_roster(d, MY_ROSTER)["players"], name.strip())
        try:
            p = float(p)
        except ValueError:
            p = -1
        if not name or not 0 <= p <= 1:
            sys.exit(f"--play wants Name=P with P from 0 to 1, e.g. --play \"LeBron James=0.8\" (got {item!r}).")
        d.setdefault("game_overrides", {})[pid] = {day: p for day in games_of(d, pid, week_games(d["sched"], d["week"])) if day >= d["today"]}
        if p > 0 and out_all_week(status(d["pool"], pid)):  # news says he returns: drop the Out tag's zero FP/g
            d["pool"] = {**d["pool"], pid: dict(d["pool"][pid], injury_status="")}
        print(f"--play: {short(d['pool'], pid)} plays each game from today with chance {p:.2f}.")
    pool, w = d["pool"], week_context(d)
    days, plan, base, games, fpg = w["days"], w["plan"], w["base"], w["games"], w["fpg"]
    if not days:
        print(f"No NBA games in week {d['week']}.")
        return footer(d)
    now = {p: (SLOTS[i] if i < len(SLOTS) else "?") for i, p in enumerate(w["r"].get("starters") or [])}
    print(f"Week {d['week']}: {days[0].strftime(DAY)} – {days[-1].strftime(DAY)} | today {d['today'].strftime(DAY)} | "
          f"{len(w['left'])} days left")
    print(f"  {'Base':<5}{'Player':<20}{'Now':<5}{'G':>2} " + "".join(f"{day.strftime('%a'):<6}" for day in days) + "E(left)")
    order = [base[i] for i in sorted(base)] + w["bench"]
    for p in order:
        slot = next(("LOCK" if i in w["blocked"] else SLOTS[i] for i, q in base.items() if q == p), "BN")
        gm = games_of(d, p, w["wg"])
        cells = "".join(f"{gm.get(day, '.'):<6}" for day in days)
        st = f" [{status(pool, p)}]" if status(pool, p) else ""
        print(f"  {slot:<5}{(short(pool, p, 19 - len(st)) + st):<20}{now.get(p, 'BN'):<5}{len(gm):>2} {cells}{w['exp'][p]:.1f}")
    notes = [f"{short(pool, p)} [{status(pool, p) or 'NBA report'}] {n}" for p in order
             for n in [play_note(status(pool, p), games[p], d["today"], p)] if n]
    if notes:
        print("Play chance used for tagged players: " + "; ".join(notes))
    sleeper = dict(enumerate(w["r"].get("starters") or []))
    swaps = [(i, p) for i, p in sorted(base.items()) if sleeper.get(i) != p]  # every slot that changes: the full move set
    mc = matchup_for(d, w, a) if w["left"] else None
    if swaps:
        print(f"Base lineup changes vs Sleeper (+{w['gain']:.1f} expected locked FP with games left; make all of them):")
        for i, p in swaps:
            old = sleeper.get(i)
            # Benching a starter discards his unlocked posted score, and E(left) can't see it (regression: Saturday
            # night's base benched Jokić's 90.0 for Poeltl's 30.9).
            team = pool.get(old, {}).get("team")
            # His latest tipped game must be final: one in progress has expired the earlier score and isn't lockable yet.
            last = max((day for day in w["games"].get(old, {}) if day < d["today"] or tipped(day, team)), default=None)
            posted = old not in base.values() and last is not None and (last < d["today"] or final(last, team))
            line = slot_line(mc, i, *stop_moments(slot_days(w["left"], p, *feeds_of(w, i)[:1], games, fpg, feeds_of(w, i)[1])))
            print((f"  move {short(pool, p)} from {now[p]} to {SLOTS[i]}" if p in now else
                   f"  start {short(pool, p)} ({w['exp'][p]:.1f}) at {SLOTS[i]}")
                  + (f" (for {short(pool, old)}" + (f"; first lock {short(pool, old)}'s posted score instead if it's "
                                                    f"≥ {line:.1f}, record it with lock --commit and rerun week" if posted else "") + ")"
                     if old not in (None, "0") else ""))
    print("Rotation plan (move bench player into the slot before tip on days its starter is idle; "
          "keep the score only if it beats the lock threshold):")
    for day in w["left"]:
        moves = [f"{short(pool, p)}→{SLOTS[i]}" + (f" (for {short(pool, base[i])})" if i in base else "")
                 for i, p in sorted(plan[day].items())]
        playing = [short(pool, base[i]) for i in sorted(base) if plays(base[i], day, games, fpg)]
        print(f"  {day.strftime(DAY)}: starters playing {len(playing)}" + (f"; feed {', '.join(moves)}" if moves else ""))
        for i, (q, late) in sorted(w["extra"][day].items()):
            occ = slot_who(day, base.get(i), {day: plan[day][i]} if i in plan[day] else {}, games, fpg)
            first, then = (occ, q) if late else (q, occ)
            team = lambda p: pool.get(p, {}).get("team")
            print(f"    same night, {SLOTS[i]}: {short(pool, first)} plays the {tip_text(day, team(first))}; once that game is final, "
                  f"decide his score (lock or pass), then put {short(pool, then)} in {SLOTS[i]} before the "
                  f"{tip_text(day, team(then)).split(' ', 2)[2]}" + (f" ({short(pool, q)} starts {SLOTS[i]} before the early tip)" if not late else ""))
    tot_alone = tot_rot = tot_reuse = 0.0
    flags, tonight, pooled = [], [], False
    lanes = lanes_after(w, w["left"][0]) if w["left"] else {}
    reach = feed_reach(w, lanes)
    lane_line = {j: slot_line(mc, j, lane[1], lane[3]) for j, lane in lanes.items()}
    for i, s in sorted(base.items()):
        if i in w["blocked"]:
            continue
        feeds, extra = feeds_of(w, i)
        alone = stop_value(slot_days(w["left"], s, {}, games, fpg))
        with_rot = stop_value(slot_days(w["left"], s, feeds, games, fpg))
        with_reuse = stop_value(slot_days(w["left"], s, feeds, games, fpg, extra))
        tot_alone, tot_rot, tot_reuse = tot_alone + alone, tot_rot + with_rot, tot_reuse + with_reuse
        first = w["left"][0] if w["left"] else None
        who = slot_who(first, s, feeds, games, fpg)
        q, late = extra.get(first, (None, True))
        for who in [p for p in ([who, q] if late else [q, who]) if p]:
            # tonight's lock line: the slot's wait value over the rest of the week, with the plan's feeds
            ev, fills, m2 = slot_rest(w, i, first, who, moments=True)
            rest = slot_line(mc, i, ev, m2)
            due = deadline(pool, who, sorted(day for day in games[who] if day > first), fills)
            # a bench score can also close a cheaper idle slot its slot's later players can move into
            alts = [(x, j) for x, j in sorted((lane_line[j] + MOVE_COST, j)
                                              for j in reach.get(i, ()) if who == lanes[i][0] and lanes[j][0] != base.get(j))
                    if x < rest]
            tonight.append(f"{short(pool, who)} ({SLOTS[i]}{'' if who == s else ' for ' + short(pool, s)}) ≥ {rest:.1f}"
                           + (f" (EV {ev:.1f})" if mc and abs(rest - ev) >= 0.5 else "")
                           + "".join(f" or ≥ {x:.1f} via {SLOTS[j]}" + (f" ({short(pool, base[j])}'s)" if j in base else "")
                                     for x, j in alts)
                           + (f" before {tip_text(*due[:2])}" + ("" if due[2] == who else f" ({short(pool, due[2])} in)")
                              if due else ""))
            pooled = pooled or bool(alts)
        n = len([day for day in w["left"] if plays(s, day, games, fpg)])
        if n <= 1:
            flags.append(f"{SLOTS[i]} {short(pool, s)} has {n} game left" + (": no lock choice" if n == 1 else ": slot scores 0 unless fed"))
    if tonight:
        print(f"Lock lines for {w['left'][0].strftime(DAY)}'s games (lock if the score reaches it, before the slot's next tip; \"X in\": the plan moves X into it): "
              + "; ".join(tonight))
    if pooled:
        print("Bench scores share the cheaper slots (\"via\"): rank tonight's bench scores; the best takes the lowest line it "
              "reaches, the next the next-lowest (a \"via\" line includes 1 FP for the extra move). Locking one via another slot: before that slot's next tip, move his slot's "
              "next player into it and bench its starter. ./gm.py lock decides them jointly once games are final.")
    open_slots = "base 9" if not w["blocked"] else f"{len(base) - len(w['blocked'])} unlocked slots"
    in_locked = {base[i] for i in w["blocked"]}
    locked_pts = sum(x for p, x in saved_locks(d).items() if p in in_locked) if a.locked is None else 0.0
    print(f"Expected locked score, {open_slots}: {tot_alone:.1f}; with rotation {tot_reuse:.1f} (+{tot_reuse - tot_alone:.1f} FP this week"
          + (f", same-night reuse +{tot_reuse - tot_rot:.1f} of it" if tot_reuse > tot_rot + 0.05 else "") + ")"
          + (f"; plus {locked_pts:.1f} already locked = {tot_reuse + locked_pts:.1f} for the week" if locked_pts else ""))
    if any(w["extra"].values()):
        print("NOTE: same-night swaps need the early game final before the late tip; skip one if it runs long. Their gain "
              "above is the model's; real 2025-26 scores paid about 4x it (reports/2026-10-20/slot-reuse.md).")
    if w["left"] == days[-1:]:
        print("NOTE: last day: the gains above assume every earlier unlocked score is below its lock line, since an idle "
              "starter's already-played unlocked game counts as 0 here, but in Sleeper it stands unless his slot plays "
              "today. Record locks with ./gm.py lock \"<player>\" <score> --commit.")
    if not w["blocked"]:
        print("No slot locked yet. After you lock in Sleeper, record it: ./gm.py lock \"<player>\" <score> --commit "
              "(a locked player keeps his slot and can't feed).")
    elif a.locked is None:
        print("Locked this week (recorded with lock --commit; --locked overrides): "
              + ", ".join(f"{short(pool, p)} {x:.1f}" for p, x in saved_locks(d).items() if p in d["locked"]))
    for f in flags:
        print("FLAG: " + f)
    footer(d)


def lock_report(name, score, fpg, plays, slot=None, mline=None):
    """plays: chance he plays each remaining game, in order. slot: (wait value, description, upper bound)
    of the slot he occupies; when given it decides the verdict, since an unlocked slot is refilled.
    mline: the slot's matchup line (win_line), which decides instead when given."""
    cont, n_left = wait_value(fpg, plays), len(plays)
    own = f"{score:.1f} FP vs board {fpg:.1f} FP/g, {n_left} game(s) left"
    if slot is None:
        verdict = "LOCK (or leave it: his final game counts anyway)" if n_left == 0 else "LOCK" if score >= cont else "WAIT"
        return [f"{name}: {own} → {verdict} (wait value {cont:.1f})"]
    s_cont, desc, upper = slot[:3]
    line = s_cont if mline is None else mline
    verdict = "LOCK (nothing left fills this slot)" if s_cont == 0 else "LOCK" if score >= line else "WAIT"
    lines = [f"{name}: {score:.1f} FP → {verdict} ("
             + ("" if mline is None or s_cont == 0 else f"matchup line {mline:.1f}; EV ") + f"slot wait value {s_cont:.1f}: {desc})",
             f"  his own games only: {own}, wait value {cont:.1f}"]
    if upper > s_cont + 0.05:
        lines.append(f"  if every eligible bench player fed only this slot: wait value {upper:.1f}")
    return lines


def dtd_free(d):
    """d with every DTD/GTD tag cleared, so play_map applies no P_DTD discount."""
    return dict(d, pool={p: dict(v, injury_status="") if v.get("injury_status") in DTD else v for p, v in d["pool"].items()})


def dtd_flip(score, value, healthy):
    """Note for a LOCK (score >= the deciding wait value) that undiscounted DTD play chances would make a WAIT."""
    return (f"LOCK depends on DTD play chance {P_DTD[0]:.2f}: confirm news; rerun with --play 0.9 if probable"
            if value <= score < healthy - 1e-9 else "")


def lock_slot(d, pid, anchor, game_day):
    """Slot verdict inputs for pid's game on game_day, in the slot whose Sleeper starter is anchor
    (pid himself, or the starter he was rotated in for; None: the slot week's plan fed him into that day).
    Judged on week's base lineup and plan, as week's lock lines are (a base that benches the anchor still judges
    his Sleeper slot, as pending_locks' feed does), unless that base moves the anchor to another slot (or, for a
    feed, doesn't feed him): then on Sleeper's lineup as it stands.
    -> (wait value, description, upper bound, fills: [(day, who)], week context, slot index, second moment) or None."""
    pool, sleeper = d["pool"], find_roster(d, MY_ROSTER).get("starters") or []
    for w in (week_context(d), week_context(d, sleeper_base=True)):
        if anchor is None:
            i = next((i for i, p in w["plan"].get(game_day, {}).items() if p == pid), None)
            i = next((j for j, (q, _) in w["extra"].get(game_day, {}).items() if q == pid), i)
            how = " (assumed from week's rotation plan; --slot-of to override)"
        else:
            i, how = next((i for i, p in w["base"].items() if p == anchor), None), ""
            if i is None and sleeper.index(anchor) in w["base"]:  # base benches him: his score feeds his Sleeper slot (pending_locks' feed)
                i = sleeper.index(anchor)
        if i is not None and (anchor is None or sleeper.index(anchor) == i):
            break
    if i is None:
        return None
    if i in w["blocked"]:
        sys.exit(f"{SLOTS[i]} is already locked; it cannot take another score.")
    anchor = w["base"].get(i)
    cont, fills, m2 = slot_rest(w, i, game_day, pid, moments=True)
    desc = f"{SLOTS[i]}" + ("" if anchor == pid else f" for {short(pool, anchor)}") + how + ", then " + (
        ", ".join(f"{day:%a} {short(pool, p)}" for day, p in fills) or "nobody") + " available continuation"
    elig = draft.SLOT_ELIGIBLE[SLOTS[i]]
    cands = [p for p in w["games"] if p == anchor or p == pid or (p in w["bench"] and elig & set(pos_of(pool, p)))]
    days = [day for day in w["left"] if day > game_day]
    cutoff = max(d["today"], game_day + datetime.timedelta(1))
    upper = stop_value(slot_options(days, {}, 0, [(w["fpg"][p], {**play_map(w["games"][p], status(pool, p), cutoff, p),
                                                               **w.get("game_overrides", {}).get(p, {})})
                                                 for p in cands if w["fpg"][p] > 0]))
    return cont, desc, upper, fills, w, i, m2


def lock_game(dates, today, game=None, team=None):
    """Which game the score is from and his games after it -> (game, after, error or None).
    Default: his latest game on or before today (a score run the next morning is from yesterday's game), skipping
    today's game while the clock says it hasn't tipped."""
    if game is not None and game not in dates:
        return game, [], f"no game on {game:%a %m/%d}"
    if game is None:
        t = CLOCK["tips"].get((today, team))  # without a tip time or clock (--date), today's game may count
        past = [day for day in dates if day < today or day == today and not (t and CLOCK["now"] and CLOCK["now"] < t)]
        if not past:
            return None, [], "no game on or before today this week; pass --game YYYY-MM-DD"
        game = max(past)
    return game, sorted(day for day in dates if day > game), None


def name_matches(pool, pids, raw):
    """(pids whose normalized name is raw, pids whose name contains it)."""
    key = draft.norm(raw)
    name = {p: draft.norm(pool.get(p, {}).get("full_name") or "") for p in pids}
    return [p for p in pids if name[p] == key], [p for p in pids if key and key in name[p]]


def name_hits(pool, pids, raw):
    """pids whose name matches raw: exact normalized matches, else those containing it."""
    exact, partial = name_matches(pool, pids, raw)
    return exact or partial


def find_mine(d, pids, raw):
    """One Owner player by name (exact normalized match, else a unique substring), else exit with the matches."""
    pool, hits = d["pool"], name_hits(d["pool"], pids, raw)
    if len(hits) != 1:
        sys.exit(f"Player {raw!r} matches {len(hits)} Owner players" + (": " if hits else "") + ", ".join(short(pool, p) for p in hits))
    return hits[0]


def find_rostered(d, raw):
    """A player for a lock record, on any roster (other teams' locks feed the matchup lines) -> (pid, his roster).
    Exact names on every roster come before substrings; at each stage an Owner match wins, and an ambiguous one exits."""
    pool, mine = d["pool"], find_roster(d, MY_ROSTER)
    owner = {p: r for r in d["rosters"] for p in r["players"]}
    theirs = [p for p in owner if owner[p]["roster_id"] != MY_ROSTER]
    for stage in (0, 1):  # exact, then substring
        for pids, who in ((mine["players"], "Owner players"), (theirs, "players on other teams")):
            hits = name_matches(pool, pids, raw)[stage]
            if len(hits) > 1:
                sys.exit(f"Player {raw!r} matches {len(hits)} {who}: " + ", ".join(
                    f"{short(pool, p)} ({d['team'].get(owner[p]['roster_id'], '?')})" for p in hits))
            if hits:
                return hits[0], owner[hits[0]]
    sys.exit(f"Player {raw!r} matches no rostered player.")


def lock_path(d):
    """This week's lock records: private/state/locks-<season>-w<NN>.json, so a new week starts empty. None without a
    league (test fixtures), so tests never read the real records."""
    if "lock_path" in d:
        return d["lock_path"]
    lg = d.get("league")
    return os.path.join(STATE, f"locks-{lg['season']}-w{d['week']:02d}.json") if lg else None


def lock_records(d):
    """{pid: (locked score, roster_id that locked him, his slot index or None)} as recorded this week; a bare score (an
    older record) is ours, slot unknown. Missing or unreadable = none."""
    try:
        with open(lock_path(d)) as f:
            return {str(p): (float(x[0]), int(x[1]), int(x[2]) if len(x) > 2 else None) if isinstance(x, list)
                    else (float(x), MY_ROSTER, None) for p, x in json.load(f).items()}
    except (TypeError, OSError, ValueError, AttributeError, IndexError):
        return {}


def saved_locks(d):
    """{pid: locked score} recorded this week with `lock <player> <score> --commit`, any team. A record whose player has
    since moved to another roster is left out: his locked score stays with the team that locked it."""
    now = {p: r["roster_id"] for r in d.get("rosters") or [] for p in r["players"]}
    return {p: x for p, (x, rid, _) in lock_records(d).items() if now.get(p, rid) == rid}


def kept_locks(d):
    """{roster_id: {slot index: locked score}} for recorded locks whose player has left that roster (trade, drop): the
    score stays with the team that locked it, in the slot it was locked in (slot_states applies it)."""
    now = {p: r["roster_id"] for r in d.get("rosters") or [] for p in r["players"]}
    out = {}
    for p, (x, rid, slot) in lock_records(d).items():
        if slot is not None and now.get(p) != rid:
            out.setdefault(rid, {})[slot] = x
    return out


def locked_pids(d, names):
    """--locked "A,B" -> pids, overriding the records ("" = none locked); each name must match exactly one Owner
    player. Omitted (None) -> this week's `lock --commit` records still on our roster."""
    r = find_roster(d, MY_ROSTER)
    if names is None:
        return [p for p in saved_locks(d) if p in r["players"]]
    return [find_mine(d, r["players"], n.strip()) for n in names.split(",") if n.strip()]


def commit_lock(d, a):
    """lock <player> <score> --commit records a lock made in Sleeper; --uncommit removes one. The player may be on
    any team: other teams' locks (seen in Sleeper's matchup view) make the matchup lines sharper."""
    pool, path = d["pool"], lock_path(d)
    if a.player is None or path is None:
        sys.exit("--commit/--uncommit needs a player: ./gm.py lock \"<player>\" <score> --commit")
    if "state" in d and d["week"] != d["state"]["week"]:
        sys.exit(f"--commit/--uncommit records Sleeper's current week ({d['state']['week']}); "
                 f"drop --date/--week (this run is week {d['week']}).")
    if os.path.exists(path) and not lock_records(d) and open(path).read().strip() not in ("", "{}"):
        sys.exit(f"{path} exists but can't be read; fix or delete it before recording, so no lock record is lost.")
    (pid, r), locks = find_rostered(d, a.player), lock_records(d)
    if a.uncommit:
        if pid not in locks:
            sys.exit(f"{short(pool, pid)} has no lock recorded this week.")
        del locks[pid]
    else:
        if a.score is None:
            sys.exit("--commit needs the locked score: ./gm.py lock \"<player>\" <score> --commit")
        if pid not in (r.get("starters") or []):
            sys.exit(f"{short(pool, pid)} isn't in a starting slot in Sleeper, and a locked player always is. "
                     "Check the lock in the app, then retry.")
        locks[pid] = (a.score, r["roster_id"], r["starters"].index(pid))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as f:
        json.dump({p: [x, rid] + ([slot] if slot is not None else []) for p, (x, rid, slot) in locks.items()}, f)
    os.replace(path + ".tmp", path)
    listed = lambda mine: ", ".join(f"{short(pool, p)} {x:.1f}" for p, (x, rid, _) in locks.items() if (rid == MY_ROSTER) == mine)
    print(f"{'Removed lock record for' if a.uncommit else 'Recorded lock:'} {short(pool, pid)}"
          + ("" if r["roster_id"] == MY_ROSTER else f" ({d['team'].get(r['roster_id'], 'other team')})")
          + ("" if a.uncommit else f" at {a.score:.1f}") + f". Locked this week (week {d['week']}): "
          + (listed(True) or "none") + (f"; other teams: {listed(False)}" if listed(False) else ""))


def cmd_lock(d, a):
    pool, r = d["pool"], find_roster(d, MY_ROSTER)
    wg = week_games(d["sched"], d["week"])
    starters = r.get("starters") or []
    if getattr(a, "commit", False) or getattr(a, "uncommit", False):
        return commit_lock(d, a)
    d["locked"] = locked_pids(d, a.locked)
    if a.player is None:
        return pending_locks(d, r, wg, a)
    pid = find_mine(d, r["players"], a.player)
    if pid in d["locked"]:
        print(f"{short(pool, pid)}: already locked; no decision remains.")
        return footer(d)
    anchor = find_mine(d, starters, a.slot_of) if a.slot_of else pid if pid in starters else None
    if a.slot_of and pid in starters:
        sys.exit(f"{short(pool, pid)} already starts at {SLOTS[starters.index(pid)]} in Sleeper; drop --slot-of.")
    if pid not in d["vals"]:
        sys.exit(f"{short(pool, pid)} has no board projection; judge the lock by hand.")
    fpg = d["vals"][pid][1]
    gm = games_of(d, pid, wg)
    if d["sched"] or a.game:
        game, after, err = lock_game(set(gm), d["today"], a.game, pool[pid].get("team"))
        if err:
            sys.exit(f"{short(pool, pid)}: {err}. His games this week: " + (" ".join(f"{day:%a %m/%d}" for day in sorted(gm)) or "none"))
    else:
        game, after = d["today"], []
    n_left = a.remaining if a.remaining is not None else len(after)

    def plays_for(st):
        """Play chances for his last n_left games: --play, else play_map's (status-aware) for those dates."""
        if a.play is not None:
            return [a.play] * n_left
        if not d["sched"]:
            return [1 - Q_DNP] * n_left
        pm = play_map(gm, st, max(d["today"], game + datetime.timedelta(1)), pid)
        return [pm[day] for day in after[len(after) - n_left:]]

    def with_plays(dd, plays, always=False):
        if always or a.remaining is not None or a.play is not None:
            # --remaining N keeps the last N dates (e.g. the next game is ruled out); other players' games stay intact.
            kept = after[len(after) - n_left:]
            override = {day: 0.0 for day in after if day not in kept}
            override.update(dict(zip(kept, plays)))
            dd = dict(dd, game_overrides={**dd.get("game_overrides", {}), pid: override})
        return dd

    def slot_for(dd, plays):
        return lock_slot(with_plays(dd, plays), pid, anchor, game)

    plays = plays_for(status(pool, pid))
    if a.remaining is None and not d["sched"]:
        sys.exit("Schedule unavailable: pass --remaining N.")
    src = "--remaining" if a.remaining is not None else "schedule after " + game.strftime(DAY) + ": " + (
        " ".join(day.strftime("%a") for day in after) or "none")
    earlier = [day for day in gm if day < game]
    print(f"Score assumed from his game {game.strftime(DAY)} {gm.get(game, '')}".rstrip()
          + ("" if a.game else " (his latest game on or before today" + (
              f"; if it's from {max(earlier).strftime(DAY)}, rerun with --game {max(earlier)}" if earlier and game == d["today"] else "")
             + ")"))
    if after and (after[0] < d["today"] or tipped(after[0], pool[pid].get("team"))):
        sys.exit(f"Lock window closed: his next game ({after[0].strftime(DAY)}) has tipped; "
                 f"the score from {game.strftime(DAY)} cannot be locked.")
    slot = None
    if d["sched"]:
        if a.remaining is not None or a.play is not None:
            if n_left > len(after) or n_left < 0:
                sys.exit(f"--remaining must be between 0 and {len(after)} scheduled games after {game}.")
            print("NOTE: --remaining/--play change only his future games; other slot options are retained.")
        slot = slot_for(d, plays)
        if slot is None:
            print(f"NOTE: {short(pool, pid)} is not in Sleeper's starters and week's plan doesn't feed him then: a game "
                  f"he didn't start can't be locked. If you rotated him in, pass --slot-of \"<starter he replaced>\".")
    elif a.remaining is not None or a.play is not None:
        print("NOTE: schedule unavailable; the verdict covers his own games only.")
    # Off the slot once its Sleeper starter or a planned fill tipped there after his game: the score is gone
    # (deadline() skips past-tip fills, #20, so it can't say so).
    gone = None
    if slot and pid not in starters:
        now_in = starters[slot[5]] if slot[5] < len(starters) else None
        gone = next((w for day, w in [(day, now_in) for day in slot[4]["games"].get(now_in, {}) if day > game] + slot[3]
                     if w not in (None, pid) and tipped(day, pool.get(w, {}).get("team"))), None)
    if gone:
        sys.exit(f"Lock window closed: {short(pool, gone)} has played in his slot since {game.strftime(DAY)}; "
                 "that score cannot be locked.")
    st = f" [{status(pool, pid)}]" if status(pool, pid) else ""
    print(f"Remaining games from {src}{st}")
    mc = matchup_for(d, slot[4], a) if slot else None
    mline = slot_line(mc, slot[5], slot[0], slot[6]) if mc else None
    for line in lock_report(short(pool, pid), a.score, fpg, plays, slot, mline):
        print(line)
    if slot and pid in starters:
        # Locking also frees the bench players the plan fed into his slot for other slots (regression: Fox's 41.0 was
        # a one-slot WAIT but +3.3 for the team). Both arms replan week's base, as week --locked does.
        # Both arms use his plays as lock computed them (play_map from today would count the scored game as a DTD's next).
        dw, locks = dict(with_plays(d, plays, True), kept_locks=kept_locks(d)), saved_locks(d)
        # The score's own game is spent either way (slot_states would still count an unfinished one as to come).
        spent = {day: 0.0 for day in gm if day <= game}
        dw = dict(dw, game_overrides={**dw.get("game_overrides", {}), pid: {**dw.get("game_overrides", {}).get(pid, {}), **spent}})
        dl = dict(dw, locked=d["locked"] + [pid], lock_scores={**locks, pid: a.score})
        dw = dict(dw, lock_scores=locks)
        # Other starters' finished, unlocked scores stand in both arms (slot_states keeps one that reaches its wait value).
        try:
            box = box_scores(d) if d.get("league") else {}
        except (OSError, ValueError) as e:
            box = None
            print(f"  NOTE: box scores unavailable ({e}); whole-team comparison withheld (it needs other starters' scores).")
        standing = {}
        for p in starters if box is not None else []:
            team = pool.get(p, {}).get("team")
            # His latest tipped game: a DNP voids the score before it, and one still in progress has no standing score.
            last = max((day for day in games_of(d, p, wg) if day < d["today"] or tipped(day, team)), default=None)
            if (p != pid and p not in d["locked"] and last in box.get(p, {}) and (last < d["today"] or final(last, team))
                    and observed_start(d, r["roster_id"], p, last) is not False):
                standing[p] = box[p][last]

        # Standing scores floor their slots in the rotation plan (feeds go where they beat them) and in slot_states.
        # With no game left of his own, waiting leaves his score standing like the others' (a later feed can still beat it).
        mine = {**standing, pid: a.score} if not after else standing
        dw, dl = dict(dw, standing=mine), dict(dl, standing=standing)

        if box is not None:
            # Either arm may keep Sleeper's lineup (week's base can bench a finished starter, dropping his standing score).
            lock_t = max(team_score(dl, MY_ROSTER, standing, sb)[0] for sb in (False, True))
            wait_t = max(team_score(dw, MY_ROSTER, mine, sb)[0] for sb in (False, True))
            print(f"  whole team (EV, week's plan replanned): lock {a.score:.1f} → {lock_t:.1f}; wait → {wait_t:.1f} "
                  f"({lock_t - wait_t:+.1f} for locking)")
    if mc:
        _, lock_odds, wait_odds = win_line(mc, slot[5], (slot[0], max(0.0, slot[6] - slot[0] ** 2)))
        print(f"  matchup odds: lock {a.score:.1f} → {odds_text(lock_odds(a.score))}; wait → {odds_text(wait_odds)}"
              + (" (a big favourite locks lower, an underdog waits for more)" if abs(mline - slot[0]) >= 0.5 else ""))
    if slot and slot[4]["base"].get(slot[5]) != pid:  # a bench score may close a cheaper slot it reaches
        w, i = slot[4], slot[5]
        lanes = lanes_after(w, game, {i: pid})
        own = slot[0] if mline is None else mline
        alts = sorted((slot_line(mc, j, lanes[j][1], lanes[j][3]) + MOVE_COST, j) for j in feed_reach(w, lanes).get(i, ()))
        alts = [(x, j) for x, j in alts if x < own]
        for x, j in alts[:2]:
            print(f"  or via {SLOTS[j]} ({short(pool, w['base'][j]) + chr(39) + 's slot' if j in w['base'] else 'empty slot'}): "
                  f"{'LOCK' if a.score >= x else 'WAIT'} at {x:.1f}, moving {short(pool, lanes[i][2][0][1])} to {SLOTS[j]} "
                  f"before that slot's next tip" + (f" and benching {short(pool, w['base'][j])}" if j in w["base"] else ""))
        if alts:
            print("  Other bench scores from that night may claim the cheaper slot first: ./gm.py lock decides them jointly.")
    value = (slot[0] if mline is None else mline) if slot else wait_value(fpg, plays)
    if a.score >= value:  # would undiscounted DTD play chances (his or the slot's other options) say WAIT?
        healthy_plays = plays_for("" if status(pool, pid) in DTD else status(pool, pid))
        healthy = slot_for(dtd_free(d), healthy_plays) if slot else None
        note = dtd_flip(a.score, value, (healthy[0] if mline is None else slot_line(mc, slot[5], healthy[0], healthy[6]))
                        if healthy else wait_value(fpg, healthy_plays))
        if note:
            print("  " + note)
    q = 1 - a.play if a.play is not None else Q_DNP
    print(f"Thresholds at {fpg:.1f} FP/g, DNP chance {q:.2f} per game: " +
          " | ".join(f"{k} left {t:.1f}" for k, t in enumerate(thresholds(fpg, q), 1)))
    print(f"Plays used: {', '.join(f'{p:.2f}' for p in plays) or 'none'} ("
          + ("--play" if a.play is not None else f"{1 - Q_DNP:.2f}, {1 - Q_B2B:.2f} on a back-to-back's second night"
             + (f"; {status(pool, pid)}: {P_DTD[0]:.2f} next game, {P_DTD[1]:.2f} later" if status(pool, pid) in DTD else "")
             + "".join(f"; NBA report {REPORT['at']}: {day:%a} {s}"
                       for day, s in sorted(REPORT["pids"].get(pid, {}).items()) if day in after))
          + "). A final game he sits scores 0. If his next game is ruled out, rerun with --remaining set to the games after it.")
    due = deadline(pool, pid, after, slot[3] if slot else [])
    if due:
        print(f"Deadline: lock before {tip_text(*due[:2])}" + ("" if due[2] == pid else
              f", when the plan moves {short(pool, due[2])} into his slot: decide before benching him") + ".")
    if status(pool, pid):
        print(f"NOTE: status {status(pool, pid)}; if he may sit, rerun with a lower --play or --remaining.")
    footer(d)


def box_scores(d):
    """{pid: {date: FP}} from the week's Sleeper box scores: games he played (a DNP has no entry)."""
    out = {}
    for row in fetch(f"https://api.sleeper.com/stats/nba/{d['league']['season']}/{d['week']}?season_type=regular"):
        if row.get("date") and (row.get("stats") or {}).get("sp"):
            out.setdefault(str(row.get("player_id")), {})[datetime.date.fromisoformat(row["date"])] = game_fp(row["stats"])
    return out


def eligible_reported(d, ms):
    """Reported scores the win model may fix, minus latest-game scores a run saw benched at or after tip (an
    unobserved start counts, as Sleeper shows it). Manual locks stay exact."""
    try:
        box = box_scores(d)
    except (OSError, ValueError) as e:
        print(f"NOTE: score eligibility unavailable ({e}); unrecorded reported scores omitted from win model.")
        return {}
    reported = {}
    for m in ms:
        for pid, score in zip(m.get("starters") or [], m.get("starters_points") or []):
            games = {day: fp for day, fp in box.get(pid, {}).items() if day <= d["today"]}
            if games:
                day = max(games)
                # An earlier score surviving a later completed game exposes a lock (#3), regardless of observations.
                earlier = (games[day] != score and score in [fp for dd, fp in games.items() if dd < day]
                           and (day < d["today"] or final(day, d["pool"].get(pid, {}).get("team"))))
                if earlier or (games[day] == score and observed_start(d, m["roster_id"], pid, day) is not False):
                    reported[pid] = score
    print("NOTE: win model drops latest scores a run saw benched at or after tip; it keeps other reported scores and recorded locks.")
    return reported


def pending_locks(d, r, wg, a=None):
    """For each current starter, his latest box score this week and the LOCK/WAIT call (on matchup lines when Sleeper's
    matchup is available, unless a.ev)."""
    pool = d["pool"]
    if not d["sched"]:
        print("Schedule unavailable: pending lock verdicts omitted. Check remaining games in Sleeper.")
        return footer(d)
    try:
        box = box_scores(d)
    except (OSError, ValueError) as e:
        print(f"NOTE: box scores unavailable ({e}); use ./gm.py lock <player> <score>.")
        return footer(d)
    played = {p: g for p, g in ((p, [(day, fp) for day, fp in g.items() if day <= d["today"]]) for p, g in box.items()) if g}
    starters = r.get("starters") or []
    # Judge each slot on week's base and plan when that base keeps him in his Sleeper slot (as lock does), else on
    # Sleeper's lineup. healthy: the same without the DTD discount, built only when a LOCK might depend on it.
    ws = (week_context(d), week_context(d, sleeper_base=True)) if d["sched"] else None
    healthy_ws = {}
    # Each row's matchup state is its own lineup context: week's base, or Sleeper's lineup for an sb row.
    # ponytail: a via lock's price keeps the feed's own slot at its EV state; small next to the win model's
    # overconfidence (#5).
    mc = matchup_for(d, ws[0], a)
    mcs = (mc, matchup_in(mc, ws[1]))
    print(f"Pending lock calls, week {d['week']} (current starters; you can only lock a game he started; skip slots already locked):")
    print("  Eligibility from observed lineups; moves between tool runs are invisible, so confirm in Sleeper the score is still lockable.")
    rows, out = [], []  # out: printed lines, or a row index whose call is decided jointly below
    for i, pid in enumerate(starters):
        if pid in d.get("locked", []):
            out.append(f"  {short(pool, pid)}: already locked; no decision remains.")
            continue
        if pid not in played or pid not in d["vals"]:
            continue
        last_day, score = max(played[pid])
        seen = observed_start(d, r["roster_id"], pid, last_day)
        if seen is False:
            out.append(f"  {short(pool, pid)}: {last_day.strftime(DAY)} score not lockable (a run at or after tip saw him "
                       "out of the starting lineup); no lock verdict. Check Sleeper if that's wrong.")
            continue
        gm = games_of(d, pid, wg)
        if not gm:
            out.append(f"  {short(pool, pid)}: schedule unavailable for his team; no lock verdict.")
            continue
        after = sorted(day for day in gm if day > last_day)
        if after and (after[0] < d["today"] or tipped(after[0], pool[pid].get("team"))):
            out.append(f"  {short(pool, pid)}: lock window closed for {last_day.strftime(DAY)} "
                       f"when his {after[0].strftime(DAY)} game tipped.")
            continue
        pm = play_map(gm, status(pool, pid), max(d["today"], last_day + datetime.timedelta(1)), pid)
        # A bench player in a week-base starter's slot is that slot's feed; any other starter missing from week's
        # base is judged on Sleeper's lineup, as before.
        feed = i in ws[0]["base"] and pid not in ws[0]["base"].values() and i not in ws[0]["blocked"]
        sb = ws[0]["base"].get(i) != pid and not feed
        rows.append(dict(i=i, pid=pid, day=last_day, score=score, after=after, sb=sb, feed=feed, unseen=seen is None,
                         plays=[pm[day] for day in sorted(gm) if day > last_day],
                         log=", ".join(f"{day.strftime('%a')} {fp:.1f}" for day, fp in sorted(played[pid]))))
        out.append(len(rows) - 1)
    # Bench scores from the same night are decided together: each may close its own slot or a cheaper one it reaches.
    calls, w0 = {}, ws[0]
    for day in sorted({row["day"] for row in rows if row["feed"]}):
        here = [row for row in rows if row["day"] == day and not row["sb"]]
        lanes = lanes_after(w0, day, {row["i"]: row["pid"] for row in here})
        reach = feed_reach(w0, lanes)
        standing = {row["i"]: row["score"] for row in rows if not row["feed"] and not row["sb"]}
        prices = {j: max(slot_line(mc, j, lane[1], lane[3]), standing.get(j, 0.0)) for j, lane in lanes.items()}
        feeds = {row["i"]: row["score"] for row in here if row["feed"] and row["i"] in reach}
        choice = joint_locks(feeds, prices, reach)
        for row in rows:  # this night's bench scores, and any standing score in a slot one of them closes
            if (row in here and row["feed"] and row["i"] in reach) or (
                    not row["sb"] and row["i"] in choice.values() and row["i"] not in choice):
                calls[row["i"]] = (choice, lanes, reach, prices)
    for item in out:
        if isinstance(item, str):
            print(item)
            continue
        row = rows[item]
        i, pid, score, after = row["i"], row["pid"], row["score"], row["after"]
        tail = (f"  [{row['log']}]" + (" (today: confirm final)" if row["day"] == d["today"] else "")
                + (" (start before tip unobserved: confirm he started it)" if row["unseen"] else ""))
        w = ws[row["sb"]]
        if i in calls:
            choice, lanes, reach, prices = calls[i]
            if i in choice.values() and i not in choice:  # another bench score's lock closes this slot
                f = next(k for k, j in choice.items() if j == i)
                print(f"  {SLOTS[i]:<5}{short(pool, pid)}: {score:.1f} FP → PASS ({short(pool, rows_at(rows, f))}'s lock in "
                      f"{SLOTS[f]} closes this slot; see that call){tail}")
                continue
            print(f"  {SLOTS[i]:<5}" + feed_call(pool, w0, row, choice, lanes, reach, prices, "slot line" if mc else "slot wait value") + tail)
            continue
        slot, fills, mline = None, [], None
        if i in w["base"]:
            cont, fills, m2 = slot_rest(w, i, row["day"], pid, moments=True)
            slot = (cont, ", ".join(f"{day:%a} {short(pool, p)}" for day, p in fills) or "nobody left", 0)
            mline = slot_line(mcs[row["sb"]], i, cont, m2) if mc else None
        due = deadline(pool, pid, after, fills)
        print(f"  {SLOTS[i]:<5}" + lock_report(short(pool, pid), score, d["vals"][pid][1], row["plays"], slot, mline)[0] + tail
              + (f" (lock before {tip_text(*due[:2])}" + ("" if due[2] == pid else f"; {short(pool, due[2])} moves in")
                 + ")" if due else ""))
        value = (slot[0] if mline is None else mline) if slot else wait_value(d["vals"][pid][1], row["plays"])
        if score >= value:
            gm = games_of(d, pid, wg)
            st = "" if status(pool, pid) in DTD else status(pool, pid)
            pm = play_map(gm, st, max(d["today"], row["day"] + datetime.timedelta(1)), pid)
            if slot:
                if row["sb"] not in healthy_ws:
                    healthy_ws[row["sb"]] = week_context(dtd_free(d), sleeper_base=row["sb"])
                h, _, hm2 = slot_rest(healthy_ws[row["sb"]], i, row["day"], pid, moments=True)
                healthy = h if mline is None else slot_line(mcs[row["sb"]], i, h, hm2)
            else:
                healthy = wait_value(d["vals"][pid][1], [pm[day] for day in sorted(gm) if day > row["day"]])
            note = dtd_flip(score, value, healthy)
            if note:
                print("        " + note)
    if not out:
        print("  No starter has a box score yet this week.")
    footer(d)


def rows_at(rows, i):
    return next(row["pid"] for row in rows if row["i"] == i)


def first_due(pool, *dues):
    """The earliest of several deadline() results (None skipped)."""
    team_tip = lambda due: CLOCK["tips"].get((due[0], due[1])) or datetime.datetime.min
    dues = [due for due in dues if due]
    return min(dues, key=lambda due: (due[0], team_tip(due))) if dues else None


def feed_call(pool, w, row, choice, lanes, reach, prices, label="slot wait value"):
    """One bench score's joint call: LOCK in place, LOCK via a cheaper slot (with the move it needs), or WAIT.
    prices: each open slot's line (its own: the feed's slot's line); label names what the line is."""
    i, pid, score = row["i"], row["pid"], row["score"]
    own, fills = prices[i], lanes[i][2]
    name, starter = short(pool, pid), lambda j: short(pool, w["base"][j]) + "'s slot" if j in w["base"] else "empty slot"
    mine = deadline(pool, pid, row["after"], fills)
    desc = f"{label} {own:.1f}: " + (", ".join(f"{day:%a} {short(pool, p)}" for day, p in fills) or "nobody left")
    if i in choice and choice[i] != i:
        j = choice[i]
        due = first_due(pool, mine, deadline(pool, pid, [], lanes[j][2]))
        verdict = (f"LOCK via {SLOTS[j]} {prices[j] + MOVE_COST:.1f} ({starter(j)}): move {short(pool, fills[0][1])} to {SLOTS[j]} and "
                   f"bench " + (short(pool, w["base"][j]) if j in w["base"] else "nobody") + f" ({desc})")
    else:
        taken = set(choice) | set(choice.values())
        alts = sorted((prices[j] + MOVE_COST, j) for j in reach[i] if j not in taken and prices[j] + MOVE_COST < own)
        due = mine
        verdict = ("LOCK" if i in choice else "WAIT") + f" ({desc}" + (
            f"; cheapest other slot he reaches: {alts[0][0]:.1f} via {SLOTS[alts[0][1]]}, {starter(alts[0][1])}"
            if alts and i not in choice else "") + ")"
    return (f"{name}: {score:.1f} FP → {verdict}" + (f" (lock before {tip_text(*due[:2])}"
            + ("" if due[2] == pid else f"; {short(pool, due[2])} moves in") + ")" if due else ""))


def replay(base, rolls, days, games, fpg, box, pos):
    """The lock policy on actual scores, night by night as `lock` decides them. rolls: {slot: [(day, pid)]} in date
    order; box: {pid: {date: FP}} (a DNP has no entry). Each night the slots' players post their scores (a DNP is 0
    and replaces an unlocked score); a starter's score locks when it reaches its slot's value of waiting over the
    slot's later rolls, and the night's bench scores are decided jointly (joint_locks, one-hop feed reach). A via
    lock moves the feed's later rolls into the closed slot. A locked player's later rolls drop from every slot;
    unlocked, a slot's final roll counts.
    -> ({slot: (pid whose score counts there, policy points)}, {(pid, day): the lowest line his score could close},
    via locks)."""
    # ponytail: same policy as reports/2026-10-20/backtest/q26.py's pooled arm, which the backtest measured.
    lanes = {i: dict(slot=i, rolls=list(rs), last=0.0, who=None) for i, rs in rolls.items()}
    out, lines, vias, gone = {}, {}, 0, set()
    value = lambda rs: stop_value([[(fpg[p], games[p][day])] for day, p in rs])
    for day in days:
        posted = {}
        for i, ln in lanes.items():
            ln["rolls"] = [(dd, p) for dd, p in ln["rolls"] if p not in gone]
            if ln["rolls"] and ln["rolls"][0][0] == day:
                p = ln["rolls"].pop(0)[1]
                ln["last"], ln["who"] = box.get(p, {}).get(day, 0.0), p
                if day in box.get(p, {}):
                    posted[i] = p
        floor = {i: value(ln["rolls"]) for i, ln in lanes.items()}
        feeds = {i: lanes[i]["last"] for i, p in posted.items() if p != base.get(i) and lanes[i]["rolls"]}
        fits = lambda p, j: draft.SLOT_ELIGIBLE[SLOTS[lanes[j]["slot"]]] & set(pos.get(p, ()))
        reach = {i: {j for j in lanes if j != i and all(fits(p, j) for _, p in lanes[i]["rolls"])} for i in feeds}
        own = {i: lanes[i]["last"] for i in posted if i not in feeds}
        prices = {j: max(floor[j], own.get(j, 0.0)) for j in lanes}
        for i, p in posted.items():
            lines[(p, day)] = min([floor[i]] + [prices[j] + MOVE_COST for j in reach.get(i, ())])
        choice = joint_locks(feeds, prices, reach)
        closed = set(choice.values()) - set(choice)
        for i, j in choice.items():
            out[lanes[i]["slot"]] = (posted[i], lanes[i]["last"])
            gone.add(posted[i])
            if j != i:
                vias += 1
                lanes[i].update(slot=lanes[j]["slot"], last=0.0, who=None)
                del lanes[j]
            else:
                del lanes[i]
        for i, s in own.items():
            if i not in closed and i in lanes and s >= floor[i] and lanes[i]["rolls"]:
                out[lanes[i]["slot"]] = (posted[i], s)
                gone.add(posted[i])
                del lanes[i]
    out.update({ln["slot"]: (ln["who"], ln["last"]) for ln in lanes.values()})
    return out, lines, vias


def week_over(sched, last, today, now):
    """Whether the week ending on day last is over: a later day, or that day once every game on it tipped 3 h ago
    (a game runs about 2 1/4 h; a missing tip time keeps it open). now None (a --date dry run) counts that day over."""
    if today != last:
        return today > last
    if now is None:
        return True
    games, tips = [g for g in sched or [] if g["date"] == last.isoformat()], tip_times(sched, [last])
    return len(tips) >= 2 * len(games) and all(t + GAME_FINAL <= now for t in tips.values())


def cmd_review(d, a):
    """A finished week, per slot: points counted vs the lock policy replayed on the same box scores vs hindsight."""
    pool, days = d["pool"], week_days(d["sched"], d["week"])
    now = None if getattr(a, "date", None) else datetime.datetime.utcnow()
    over = lambda days: week_over(d["sched"], days[-1], d["today"], now)
    if days and not over(days) and a.week is None:  # the current week is still running: review the one before
        if d["week"] <= 1:
            sys.exit(f"No finished week yet: week 1 ends {days[-1].strftime(DAY)}.")
        d = dict(d, week=d["week"] - 1)
        days = week_days(d["sched"], d["week"])
    if not days:
        sys.exit(f"Schedule unavailable for week {d['week']}: no review.")
    if not over(days):
        sys.exit(f"Week {d['week']} ends {days[-1].strftime(DAY)}; review it after its last game (or pass --date).")
    print(f"Week {d['week']} review ({days[0].strftime(DAY)} – {days[-1].strftime(DAY)}): points counted vs lock policy vs hindsight, per slot")
    try:
        box = box_scores(d)
    except (OSError, ValueError) as e:
        print(f"  Box scores unavailable ({e}): counted, policy and hindsight unknown.")
        return footer(d)
    try:
        me = next(m for m in draft.get(f"/league/{d['league']['league_id']}/matchups/{d['week']}") if m["roster_id"] == MY_ROSTER)
    except (OSError, ValueError, StopIteration) as e:
        print(f"NOTE: matchup unavailable ({e}); slots are this session's Sleeper starters.")
        me = {}
    starters = me.get("starters") or find_roster(d, MY_ROSTER).get("starters") or []
    reported = dict(zip(starters, me.get("starters_points") or []))  # Sleeper's points per slot at week end
    locks = {p: x for p, (x, rid, _) in lock_records(d).items() if rid == MY_ROSTER}  # ours then, whoever has him now
    # ponytail: no tag history, so the policy treats everyone as healthy at the week's start; it judges lock timing,
    # not injury calls. Upgrade: snapshot each day's play chances if injury calls turn out to be the leak.
    w = week_context(dict(d, today=days[0], pool={p: dict(v, injury_status="") for p, v in pool.items()}))
    print(f"  {'Slot':<5}{'Player':<20}{'Counted':>8} {'(from)':<11}{'Policy':>7}{'Hindsight':>10}{'Leak':>6}  Cause")
    totals, worst, agree, unknown = [0.0, 0.0, 0.0], None, [], 0
    slot_rolls = {i: [(day, p) for day in days for p in [slot_who(day, w["base"].get(i), feeds_of(w, i)[0], w["games"], w["fpg"])] if p]
                  for i in range(len(SLOTS))}
    pol, lines, vias = replay(w["base"], slot_rolls, days, w["games"], w["fpg"], box, w["pos"])
    # Pair each Sleeper slot with the policy slot whose points belong to the same player (a via lock moves players
    # between slots), else the same index, else a leftover.
    anchors = [starters[i] if i < len(starters) and starters[i] != "0" else None for i in range(len(SLOTS))]
    held = {who: k for k, (who, _) in pol.items() if who}
    pair = {i: held[p] for i, p in enumerate(anchors) if p in held}
    left = [k for k in range(len(SLOTS)) if k not in pair.values()]
    for i in range(len(SLOTS)):
        if i not in pair:
            pair[i] = i if i in left else left[0]
            left.remove(pair[i])
    for i, slot in enumerate(SLOTS):
        s, (feeds, _), rolls = w["base"].get(i), feeds_of(w, i), slot_rolls[i]
        who, policy = pol.get(pair[i], (None, 0.0))
        anchor = anchors[i]
        gm = games_of(d, anchor, w["wg"]) if anchor else {}
        hind = max((box[p][day] for day, p in rolls + [(day, anchor) for day in gm] if day in box.get(p, {})), default=0.0)
        no_proj = [p for p in dict.fromkeys((s, anchor)) if p and not d["vals"].get(p, (0, 0.0))[1] and games_of(d, p, w["wg"])]
        if no_proj:  # the policy can't value his games: unknown, not 0
            policy, unknown = None, unknown + 1
        causes = ([f"no board projection for {', '.join(short(pool, p) for p in no_proj)}: policy unknown"] if no_proj
                  else [f"{len(rolls)}-game slot"] if len(rolls) <= 1 else [])
        dnp = sum(day not in box.get(p, {}) for day, p in rolls)
        causes += [f"{dnp} DNP"] if dnp else []
        if anchor in locks:
            counted, src = locks[anchor], "lock"
            if anchor in reported:
                agree.append(abs(reported[anchor] - counted) < 0.05)
            # the same score twice: take the latest such game, whose line is lowest, so a valid late lock isn't flagged.
            # The line is the lowest his score could close that night, so a lock via a cheaper slot isn't flagged.
            hit = max((day for rs in slot_rolls.values() for day, p in rs if p == anchor and abs(box.get(p, {}).get(day, 1e9) - counted) < 0.05), default=None)
            line = lines.get((anchor, hit))
            if line is not None and counted < line - 0.05:
                causes.append(f"locked below line {line:.1f}")
        else:
            final = box.get(anchor, {}).get(max(gm)) if gm else None
            counted, src = ((reported[anchor], "Sleeper") if anchor in reported else (final or 0.0, "final game") if gm
                            else (0.0, "no games") if anchor else (0.0, "empty slot"))
            causes += ["no lock recorded" + (" (his final game: DNP)" if final is None else " (final game counted)")] if gm else []
        if feeds:
            causes.append(f"{len(feeds)} feed(s) planned, adherence unknown")
        leak = None if policy is None else policy - counted
        if leak is not None:  # an unknown slot stays out of all three totals, so they compare like with like
            totals = [totals[0] + counted, totals[1] + policy, totals[2] + hind]
            if worst is None or leak > worst[1]:
                worst = (slot, leak, "; ".join(causes))
        policy_who = "" if who in (None, anchor) else f" (policy: {short(pool, who, 12)})"
        num = lambda x, n: f"{'n/a':>{n}}" if x is None else f"{x:>{n}.1f}"
        print(f"  {slot:<5}{short(pool, anchor, 19):<20}{counted:>8.1f} {('(' + src + ')'):<11}{num(policy, 7)}{hind:>10.1f}{num(leak, 6)}  "
              + "; ".join(causes) + policy_who)
    gap = f" (policy unknown in {unknown} slot(s); totals leave them out)" if unknown else ""
    print(f"  Totals: counted {totals[0]:.1f} | policy {totals[1]:.1f} | hindsight {totals[2]:.1f} (an upper bound, not a target){gap}")
    if agree:
        print(f"Sleeper's reported points equal the lock record in {sum(agree)} of {len(agree)} locked slot(s)"
              + ("" if all(agree) else ": Sleeper shows the latest game, not the lock (issue allmanr/fb-gm#3)") + ".")
    print(f"Outcome line: week {d['week']} execution: counted {totals[0]:.1f}, policy {totals[1]:.1f}, hindsight {totals[2]:.1f}; "
          f"policy − counted {totals[1] - totals[0]:+.1f}{gap}; "
          + (f"largest leak {worst[0]} {worst[1]:+.1f} ({worst[2]})." if worst and worst[1] > 0.05 else "no slot below policy."))
    print("NOTE: policy replays week's Monday base lineup and plan with this session's roster and board, everyone healthy and no "
          "same-night reuse; it is not the board as it stood that week. It decides each night's bench scores jointly, as lock does"
          + (f" ({vias} via lock(s); a row's \"policy: X\" names whose points the policy counts there)" if vias else "")
          + ". Counted uses lock records, else Sleeper's slot points.")
    footer(d)


def rostered(rosters):
    return {p: r["roster_id"] for r in rosters for p in (r.get("players") or []) + (r.get("reserve") or [])}


def free_agents(board, vals, notes, pool, taken, want=None):
    """Board players with an NBA team on no roster, best first; excluded and unprojected players skipped."""
    out = []
    for i, pid in enumerate(board, 1):
        p = pool.get(pid, {})
        if pid in taken or pid not in vals or not (p.get("active") and p.get("team")):
            continue
        if want and not want & set(pos_of(pool, pid)):
            continue
        out.append((i, pid))
    return out


def trending_adds(path=os.path.join(CACHE, "trending-add.json")):
    """Sleeper's trending adds [(pid, adds in 24h)], cached an hour; None with a NOTE if unavailable."""
    try:
        if not (os.path.exists(path) and time.time() - os.path.getmtime(path) < 3600):
            data = fetch(TRENDING)
            assert isinstance(data, list), "not a list"
            os.makedirs(CACHE, exist_ok=True)
            with open(path + ".tmp", "w") as f:
                json.dump(data, f)
            os.replace(path + ".tmp", path)
        with open(path) as f:
            return [(str(t["player_id"]), t.get("count", 0)) for t in json.load(f)]
    except (OSError, ValueError, AssertionError, KeyError, TypeError) as e:
        print(f"NOTE: Sleeper trending adds unavailable ({e}); trending section omitted.")
        return None


def beyond_board(d, trend, logs, replacement, left, n=6):
    """Lines for free agents fa's board table can't show: Sleeper's trending adds, non-board players whose
    2026 box-score FP/g (3+ games) is at least the board's replacement level, and the minutes radar (role
    jumps the blend is slow to see). None skips a section."""
    pool, taken, on_board = d["pool"], rostered(d["rosters"]), set(d["board"])

    def row(p, tail):
        st = status(pool, p)
        return (f"  {short(pool, p):<23}{'/'.join(pos_of(pool, p)):<10}{pool.get(p, {}).get('team') or 'FA':<5}"
                f"{st or '-':<8}{left(p) if d['sched'] else '?':>2} G  {tail}")

    lines = []
    if trend is not None:
        fas = [(p, c) for p, c in trend if p not in taken]
        lines.append(f"Trending adds (Sleeper, 24h): {len(fas)} of {len(trend)} are free agents here" + (":" if fas else "."))
        for p, c in fas[:n]:
            v = d["vals"].get(p)
            lines.append(row(p, (f"V+{v[0]:.1f}/wk {v[1]:.1f}/g" if v else "on board, no V" if p in on_board else "not on board")
                             + f" | {c} adds"))
    if logs is not None:
        hot = sorted(((sum(g[2] for g in gs) / len(gs), len(gs), p) for p, gs in logs.items()
                      if p not in taken and p not in on_board and len(gs) >= 3), reverse=True)
        hot = [h for h in hot if h[0] >= replacement]
        lines.append(f"Not on board, 2026 box scores ≥ {replacement:.1f} FP/g (replacement), 3+ games: "
                     + (f"{len(hot)}" if hot else "none"))
        lines += [row(p, f"{fp:.1f} FP/g in {k} G") for fp, k, p in hot[:n]]
        radar = []
        for p, gs in logs.items():
            m, l3 = sum(g[3] for g in gs), sum(g[3] for g in gs[-3:]) / 3
            if p not in taken and pool.get(p, {}).get("team") and len(gs) >= RADAR_GAMES and l3 - m / len(gs) >= RADAR_MIN:
                radar.append((l3 - m / len(gs), p, l3, m / len(gs), sum(g[2] for g in gs) / m))
        radar.sort(reverse=True)
        lines.append(f"Minutes radar, free agents with last-3 min/g ≥ season avg + {RADAR_MIN:g} ({RADAR_GAMES}+ games): "
                     + (f"{len(radar)} (L3 min × FP/min ran ~3 FP/g high in the backtest, the blend ~6 low)" if radar else "none"))
        lines += [row(p, f"min {l3:.1f} vs {avg:.1f} | {rate:.2f} FP/min → {l3 * rate:.1f}/g at L3 min") for _, p, l3, avg, rate in radar[:n]]
    return lines


def drop_candidate(players, vals, pool):
    """Lowest board V/wk among the Owner's non-IR players with a board value (None if none has one).
    Unprojected players aren't candidates: no V says nothing about their worth, so they're judged by hand."""
    return min((p for p in players if p in vals), key=lambda p: vals[p], default=None)


def stream_gains(d, fas, drops, first):
    """[(ΔTeam, fa, drop)] for each free agent with his best drop, best first. ΔTeam: our expected locked score
    for the rest of the week (week's base and rotation) with roster - drop + fa, minus the current roster's.
    Both sides retain locked slots and optimize the remaining lineup. first: {fa: first date that counts}.
    drops: bench pids, never one with V/wk >= the FA's + 5."""
    r = find_roster(d, MY_ROSTER)
    locked = set(d.get("locked") or [])
    starters = [p if p in locked else "0" for p in r.get("starters") or []]

    def score(players, adds):
        rs = [dict(x, players=players, starters=starters) if x["roster_id"] == MY_ROSTER else x for x in d["rosters"]]
        return team_score(dict(d, rosters=rs, adds=adds), MY_ROSTER, {}, False)[0]

    now, out = score(r["players"], {}), []
    for fa in fas:
        ok = [p for p in drops if p not in locked and d["vals"][p][0] < d["vals"][fa][0] + 5]
        best = max(((score([p for p in r["players"] if p != x] + [fa], {fa: first[fa]}) - now, x) for x in ok), default=None)
        if best:
            out.append((best[0], fa, best[1]))
    return sorted(out, key=lambda t: -t[0])


def cmd_fa(d, a):
    pool, r = d["pool"], find_roster(d, MY_ROSTER)
    d["locked"] = locked_pids(d, a.locked)
    wg, days = week_games(d["sched"], d["week"]), week_days(d["sched"], d["week"])
    taken = rostered(d["rosters"])
    want = draft.SLOT_ELIGIBLE.get(a.pos.upper(), {a.pos.upper()}) if a.pos else None
    fas = free_agents(d["board"], d["vals"], d["notes"], pool, taken, want)
    mine = [p for p in r["players"] if p not in (r.get("reserve") or [])]
    drop = drop_candidate([p for p in mine if p not in d["locked"]], d["vals"], pool)
    if drop is None:
        sys.exit("No Owner player has a board value: judge drops by hand.")

    def left(pid):
        return len([day for day in games_of(d, pid, wg) if day >= d["today"]]) if d["sched"] else 0

    def exp(pid):
        pm = play_map(games_of(d, pid, wg), status(pool, pid), d["today"], pid)
        return wait_value(fpg_of(d, pid), [pm[day] for day in sorted(pm) if day >= d["today"]])

    def played(pid):
        """His team's games this week that have tipped (before today; today too on a past --date or after ESPN's tip
        time). With waiver_after_game_start he is then on waivers until the clear day (waiver_day_of_week 0, day unverified)."""
        return sorted(day for day in games_of(d, pid, wg)
                      if day < d["today"] or day == d["today"] < datetime.date.today() or tipped(day, pool[pid].get("team")))

    on_waivers = {}
    st = d["league"]["settings"]
    for wk in {d["week"], max(1, d["week"] - 1)}:
        try:
            txns = draft.get(f"/league/{d['league']['league_id']}/transactions/{wk}")
        except (OSError, ValueError):
            txns = []
        for t in txns:
            for pid in (t.get("drops") or {}):
                until = datetime.datetime.fromtimestamp(t["created"] / 1000).date() + datetime.timedelta(st["waiver_clear_days"])
                if until >= d["today"]:
                    on_waivers[pid] = until
    dv, dg = d["vals"].get(drop, (0, 0))
    print(f"Free agents on board ({len(fas)}{', ' + a.pos.upper() if a.pos else ''}); drop candidate "
          f"{short(pool, drop)} (V+{dv:.1f}/wk, {dg:.1f}/g, {left(drop)} games left, E {exp(drop):.1f})")
    unproj = [short(pool, p) for p in mine if p not in d["vals"]]
    if unproj:
        print(f"  unprojected: {', '.join(unproj)} — judge by hand")
    print(f"  {'Board':<6}{'Player':<23}{'Pos':<10}{'Team':<5}{'V/wk':>5}{'FP/g':>6}{'G':>3}  {'ΔV/wk':>6}{'ΔE wk':>7}  Status")
    for rank, pid in fas[: a.top]:
        v, g = d["vals"][pid]
        flag = " ".join(x for x in (status(pool, pid), f"WAIVERS until {on_waivers[pid]:%a %m/%d}" if pid in on_waivers else "",
                                    f"WAIVERS (played {played(pid)[0]:%a})" if played(pid) else "") if x)
        print(f"  #{rank:<5}{short(pool, pid):<23}{'/'.join(pos_of(pool, pid)):<10}{pool[pid].get('team'):<5}"
              f"{v:>5.1f}{g:>6.1f}{left(pid):>3}  {v - dv:>+6.1f}{exp(pid) - exp(drop):>+7.1f}  {flag}")
    print(f"ΔV/wk = season weekly Lock-In surplus vs the drop; ΔE wk = this week's expected locked score with games left.")
    trend = trending_adds()
    if d["sched"] and days:
        # waiver_after_game_start: today's game counts only if this is a live run (add before his tip); a claim
        # on a dropped player still on waivers counts from the day after he clears. A free agent whose team already
        # played this week is on waivers until the clear day (unverified), so he is no stream this week.
        live = d["today"] == datetime.date.today()
        start = d["today"] if live else d["today"] + datetime.timedelta(1)
        hot = [p for p, _ in trend or [] if p not in taken and p in d["vals"] and pool.get(p, {}).get("team")][:10]
        cands = [p for p in dict.fromkeys([p for _, p in fas[:15]] + hot) if p in on_waivers or not played(p)]
        first = {p: max(start, on_waivers[p] + datetime.timedelta(1)) if p in on_waivers else start for p in cands}
        bench = [p for p in mine if p not in (r.get("starters") or []) and p in d["vals"]]
        print(f"Stream this week (ΔTeam = our expected locked score, rest of week with week's rotation, vs now; "
              f"best bench drop, never one with V/wk ≥ his + 5; shown if ΔTeam ≥ {STREAM_MIN:g} and > "
              f"{STREAM_WEEKS} × the season V/wk it costs):")
        pairs = stream_gains(d, cands, bench, first)
        rows = [(g, p, x) for g, p, x in pairs
                if g >= STREAM_MIN and g > STREAM_WEEKS * max(0.0, d["vals"][x][0] - d["vals"][p][0])][:3]
        if not d["locked"]:
            print('  Assumes no slots are locked: record each lock with ./gm.py lock "<player>" <score> --commit.')
        if not pairs:
            print("  no pair: no projected bench player under the V/wk guard, or no candidates")
        elif not rows:
            print("  No stream beats its season cost this week.")
        for gain, p, x in rows:
            today_g = d["today"] in games_of(d, p, wg)
            tail = (f"add before {tip_text(d['today'], pool[p].get('team'))}" if live else f"his {d['today']:%a} game not counted") if today_g else ""
            if p in on_waivers:
                tail = f"WAIVERS until {on_waivers[p]:%a %m/%d}: claim costs priority, counts from {first[p]:%a}"
            print(f"  ΔTeam {gain:+5.1f}  add {short(pool, p)} ({pool[p].get('team')}, "
                  f"{len([day for day in games_of(d, p, wg) if day >= first[p]])} G) drop {short(pool, x)} | "
                  f"season ΔV/wk {d['vals'][p][0] - d['vals'][x][0]:+.1f}" + (f" | {tail}" if tail else ""))
    try:
        logs = rb.game_logs(rb.season_weeks(int(d["league"]["season"]), d["week"]))
    except (OSError, ValueError) as e:
        print(f"NOTE: 2026 box scores unavailable ({e}); off-board scorers omitted.")
        logs = None
    rep = re.search(r"healthy ([\d.]+)/game replacement", open(os.path.join(HERE, "board.txt")).read())
    for line in beyond_board(d, trend, logs, float(rep.group(1)) if rep else float("inf"), left):
        print(line)
    print(f"Waivers: rolling priority (waiver_type 0; FAAB is 2). We are #{r['settings'].get('waiver_position')} of 10 "
          f"(1 claims first); a successful claim sends us last. Dropped players take ~{st['waiver_clear_days']} days to clear. "
          f"Free agents become waiver claims once their team tips (waiver_after_game_start=1) and clear on the waiver day "
          f"(waiver_day_of_week=0, day unverified): a WAIVERS (played <day>) row is no add this week. "
          f"After an add or trade only later games count; locked scores stay with the old team.")
    footer(d)


def slot_states(d, w, reported):
    """[(mean, variance)] of each slot's weekly locked score in week context w: week's model (base player plus the
    rotation plan's feeds, optimal stopping with the DNP correction). A recorded lock (d["locked"] pid with a
    d["lock_scores"] score, any team) is that score exactly. reported: {pid: points as reported by Sleeper}; an
    unrecorded slot whose reported score reaches its value of waiting is taken as locked at that score. Once the slot's
    game today is probably final (final), that roll is the reported score, so the value of waiting starts tomorrow; while
    it's in progress the roll still counts as to come (its partial score isn't a final one). A lock kept from a
    player who has left the roster (d["kept_locks"], kept_locks) fixes its slot at that score."""
    out, today = [], w["today"]
    kept = (d.get("kept_locks") or {}).get(w["r"]["roster_id"], {})
    for i in range(len(SLOTS)):
        s, days = w["base"].get(i), w["left"]
        feeds, extra = feeds_of(w, i)
        who = slot_who(today, s, feeds, w["games"], w["fpg"]) if days and days[0] == today else None
        # ponytail: a same-night reuse roll still to come tonight is dropped with a final early one.
        if who and final(today, d["pool"].get(who, {}).get("team")):
            days = days[1:]
        m, m2 = stop_moments(slot_days(days, s, feeds, w["games"], w["fpg"], extra))
        x = reported.get(who if who in reported and days is not w["left"] else s, 0.0)
        if s in d.get("locked", []) and s in d.get("lock_scores", {}):
            m = d["lock_scores"][s]  # a recorded lock is that team's known score for the slot
            m2 = m * m
        elif x > 0 and x >= m:  # ponytail: assumes a reported score is still lockable; a late-night --date run may double-count today
            m, m2 = x, x * x
        if i in kept:  # ponytail: our own lock lines still plan feeds into such a slot; only the states know it's closed
            m = kept[i]
            m2 = m * m
        out.append((m, max(0.0, m2 - m * m)))
    return out


def team_score(d, rid, reported, sleeper_base):
    """(mean, variance) of a team's weekly locked score: the sum of its slot_states."""
    states = slot_states(d, week_context(d, sleeper_base, rid), reported)
    return sum(m for m, _ in states), sum(v for _, v in states)


def win_odds(scores, me, opp, median=True, n=2000, seed=2026):
    """scores: {rid: (mean, variance)} -> (P(beat opp) or None, P(beat the league median) or None).
    Median = average of the middle two of all teams' scores (Sleeper's median game)."""
    # ponytail: each team's total is normal with the summed slot variances (slots and teams independent;
    # per-game scores from the fitted CV curve, DNPs at Q_DNP/Q_B2B). Ignores pace/blowout correlation,
    # injury news and manager mistakes, so odds are overconfident; widen the sd if a backtest says so.
    rng, rids = random.Random(seed), sorted(scores)
    h2h = med = 0
    for _ in range(n):
        x = {r: rng.gauss(scores[r][0], math.sqrt(scores[r][1])) for r in rids}
        h2h += opp is not None and x[me] > x[opp]
        mid = sorted(x.values())
        med += x[me] > (mid[(len(mid) - 1) // 2] + mid[len(mid) // 2]) / 2
    return (h2h / n if opp is not None else None), (med / n if median else None)


# Matchup-aware lock lines (Owner-requested Oct 22 2026; backtest: reports/2026-10-20/winodds-locks.md, +0.24 wins/20 wk,
# 95% CI +0.18 to +0.30, with every team's state known). A slot locks when that maximizes P(win H2H) + P(beat median)
# given every team's current state, the rule the backtest measured. WIN_EPS: within this many expected wins of
# indifferent, the EV line decides, so a decided matchup doesn't throw away points (points for breaks ties).
WIN_EPS = 0.002
NORMAL = statistics.NormalDist()
MEDIAN_Z = [NORMAL.inv_cdf((k + 0.5) / 40) for k in range(40)]


def p_beat_median(me, others):
    """P(our total beats the league median) = P(at least half of the other teams finish below us), with each total
    normal (mean, variance) and independent: Poisson-binomial over the others, averaged over our total."""
    m, sd, need, tot = me[0], math.sqrt(max(me[1], 1e-9)), (len(others) + 1) // 2, 0.0
    for z in MEDIAN_Z:
        x, dist = m + sd * z, [1.0]  # dist[k]: P(exactly k others below x)
        for om, ov in others:
            q = NORMAL.cdf((x - om) / math.sqrt(max(ov, 1e-9)))
            dist = [lo * (1 - q) + hi * q for lo, hi in zip(dist + [0.0], [0.0] + dist)]
        tot += sum(dist[need:])
    return tot / len(MEDIAN_Z)


def win_parts(me, opp, others):
    """(P(beat opp) or None, P(beat median) or None) for our total me = (mean, variance)."""
    h2h = NORMAL.cdf((me[0] - opp[0]) / math.sqrt(max(me[1] + opp[1], 1e-9))) if opp else None
    return h2h, (p_beat_median(me, others) if others else None)


def matchup_live(d):
    """Matchup lines need Sleeper's current matchup: the live week only (no --date or --week N dry run)."""
    return "league" in d and CLOCK["now"] is not None and d["week"] == (d.get("state") or {}).get("week")


def all_locks(d):
    """Recorded locks on any roster -> (pids, {pid: score}): ours and other teams' (lock --commit)."""
    rostered = {p for r in d["rosters"] for p in r["players"]}
    locks = {p: x for p, x in saved_locks(d).items() if p in rostered}
    return list(locks), locks


def matchup_context(d, w):
    """Every team's state for matchup lines: our slots in w (week's context for our roster), the opponent's total
    and the other teams' totals (each (mean, variance), recorded locks exact, Sleeper's reported points otherwise)
    -> (dict, ""), or (None, why) when unavailable (then the EV lines stand)."""
    if not matchup_live(d):
        return None, "not the live week (--date/--week dry run)"
    try:
        ms = draft.get(f"/league/{d['league']['league_id']}/matchups/{d['week']}")
        me = next(m for m in ms if m["roster_id"] == MY_ROSTER)
    except (OSError, ValueError, StopIteration) as e:
        return None, f"Sleeper matchup unavailable ({e})"
    opp = next((m["roster_id"] for m in ms if me.get("matchup_id") is not None and m["matchup_id"] == me["matchup_id"]
                and m["roster_id"] != MY_ROSTER), None)
    median = d["week"] < d["league"]["settings"]["playoff_week_start"]
    if opp is None and not median:
        return None, "no opponent this week"
    reported = eligible_reported(d, ms)
    pids, scores = all_locks(d)
    ours = set(find_roster(d, MY_ROSTER)["players"])
    dd = dict(d, locked=list(d.get("locked") or []) + [p for p in pids if p not in ours], lock_scores=scores,  # ours as w has them
              kept_locks=kept_locks(d))
    any_pts = any(m.get("points") for m in ms)
    totals = {r["roster_id"]: team_score(dd, r["roster_id"], reported, any_pts) for r in d["rosters"] if r["roster_id"] != MY_ROSTER}
    opp_r = find_roster(d, opp) if opp is not None else {}
    return dict(mine=slot_states(dd, w, reported), opp=totals.get(opp), others=list(totals.values()) if median else None,
                opp_name=d["team"].get(opp, "BYE"), opp_locked=[p for p in opp_r.get("starters") or [] if p in scores],
                dd=dd, reported=reported), ""


def matchup_in(mc, w):
    """mc with our slot states rebuilt in week context w (a lock judged on another lineup than mc's), else None."""
    return mc and dict(mc, mine=slot_states(mc["dd"], w, mc["reported"]))


def win_line(mc, i, wait):
    """Matchup line for slot i: the score at which locking it wins as much as waiting does (wait: (mean, variance) of
    the slot's continuation under the EV rule, as the backtest valued a WAIT). Within WIN_EPS of indifference the EV line
    (wait's mean) decides. -> (line, odds if locked at x: x -> {"h2h", "med"}, odds if waiting); line inf: no score does."""
    rest = [s for j, s in enumerate(mc["mine"]) if j != i]
    R, VR = sum(m for m, _ in rest), sum(v for _, v in rest)
    u = lambda me: sum(x for x in win_parts(me, mc["opp"], mc["others"]) if x is not None)
    u_wait = u((R + wait[0], VR + wait[1]))
    hi = wait[0] + 6 * math.sqrt(wait[1]) + 100

    def first(target):
        """Smallest locked score x with u(R + x) >= target (u rises with x)."""
        if u((R, VR)) >= target:
            return 0.0
        if u((R + hi, VR)) < target:
            return math.inf
        lo, top = 0.0, hi
        for _ in range(20):  # to within 0.0002 FP
            mid = (lo + top) / 2
            lo, top = (lo, mid) if u((R + mid, VR)) >= target else (mid, top)
        return top

    line = min(max(wait[0], first(u_wait - WIN_EPS)), first(u_wait + WIN_EPS))
    odds = lambda me: dict(zip(("h2h", "med"), win_parts(me, mc["opp"], mc["others"])))
    return line, lambda x: odds((R + x, VR)), odds((R + wait[0], VR + wait[1]))


def odds_text(o):
    return ", ".join(f"{label} {o[k]:.0%}" for k, label in (("h2h", "H2H"), ("med", "median")) if o[k] is not None)


def slot_line(mc, i, value, m2):
    """The line a slot's score must reach to lock: its matchup line when mc is available, else its EV wait value."""
    return value if mc is None else win_line(mc, i, (value, max(0.0, m2 - value * value)))[0]


def matchup_for(d, w, a):
    """matchup_context for a lock or week run (None with --ev), printing why EV lines stand when it's unavailable."""
    if getattr(a, "ev", False):
        return None
    mc, why = matchup_context(d, w)
    if mc is None:
        print(f"NOTE: matchup lines unavailable ({why}); lines below are EV wait values.")
    else:
        terms = "P(beat median)" if mc["opp"] is None else "P(win H2H)" + (" + P(beat median)" if mc["others"] else "")
        print(f"Matchup lines vs {mc['opp_name']} ({terms}, every team's current state" + ("" if mc["opp"] is None else
              f"; opponent locks recorded: {len(mc['opp_locked'])} of 9" + (
                  "; record theirs with ./gm.py lock \"<their player>\" <score> --commit" if len(mc["opp_locked"]) < 9 else ""))
              + "). --ev for EV lines.")
    return mc


def cmd_matchup(d, a):
    pool = d["pool"]
    try:
        ms = draft.get(f"/league/{d['league']['league_id']}/matchups/{d['week']}")
    except (OSError, ValueError) as e:
        print(f"Matchups unavailable ({e}); fresh matchup advice unavailable.")
        return footer(d)
    me = next(m for m in ms if m["roster_id"] == MY_ROSTER)
    opp = next((m for m in ms if me["matchup_id"] is not None and m["matchup_id"] == me["matchup_id"]
                and m["roster_id"] != MY_ROSTER), None)  # matchup_id None: no opponent (bye or not set)
    wg = week_games(d["sched"], d["week"])
    left = [day for day in week_days(d["sched"], d["week"]) if day >= d["today"]]
    rosters = {r["roster_id"]: r for r in d["rosters"]}

    def strength(rid):
        rr = rosters[rid]
        act = [(p, pos_of(pool, p)) for p in rr["players"] if p not in (rr.get("reserve") or [])]
        v = {p: d["vals"].get(p, (0, 0))[0] for p, _ in act}
        pm = {p: play_map(games_of(d, p, wg), status(pool, p), d["today"], p) for p, _ in act}
        e = {p: wait_value(fpg_of(d, p), [pm[p][day] for day in left if day in pm[p]]) for p, _ in act}
        return sum(v[p] for p in best_lineup(act, v).values()), sum(e[p] for p in best_lineup(act, e).values())

    print(f"Week {d['week']}: {d['team'][MY_ROSTER]} vs {d['team'][opp['roster_id']] if opp else 'BYE'}")
    _, recorded = all_locks(d)
    for m in [me] + ([opp] if opp else []):
        sv, se = strength(m["roster_id"])
        print(f"  {d['team'][m['roster_id']]:<14} Sleeper points {m.get('points') or 0:>6.1f} | best-9 board V+{sv:.1f}/wk | "
              f"expected locked with games left {se:.1f} (best 9, no rotation)" if d["sched"] else f"  {d['team'][m['roster_id']]:<14} Sleeper points {m.get('points') or 0:.1f} | best-9 V+{sv:.1f}/wk")
        pts = ", ".join(f"{short(pool, p).split()[-1]} " + (f"LOCKED {recorded[p]:.1f}" if p in recorded else f"{x:.1f}")
                        for p, x in zip(m.get("starters") or [], m.get("starters_points") or []) if p != "0")
        print(f"    starters (LOCKED: recorded with lock --commit; others as reported by Sleeper; latest-game locks need confirmation): {pts}")
    allpts = sorted((m.get("points") or 0) for m in ms)
    median = (allpts[len(allpts) // 2 - 1] + allpts[len(allpts) // 2]) / 2
    rank = 1 + sum(x > (me.get("points") or 0) for x in allpts)
    if d["week"] >= d["league"]["settings"]["playoff_week_start"]:
        print("Playoff week: no median game.")
    else:
        print(f"Median game: separate W/L vs the league median each week. Median so far {median:.1f}; "
              f"we rank {rank}/{len(allpts)} (top {len(allpts) // 2} beat it).")
    if not any(allpts):
        print("NOTE: no points scored yet this week; points columns are placeholders until games finish.")
    if d["sched"]:
        reported = eligible_reported(d, ms)
        d["locked"], d["lock_scores"] = all_locks(d)  # every team's recorded locks, ours and theirs
        d["kept_locks"] = kept_locks(d)
        scores = {rid: team_score(d, rid, reported, any(allpts)) for rid in rosters}
        p_h2h, p_med = win_odds(scores, MY_ROSTER, opp and opp["roster_id"], d["week"] < d["league"]["settings"]["playoff_week_start"])
        print(f"Win odds (2,000 draws, normal per team; week's slot model with rotation"
              + (", Sleeper lineups as set, reported points as reported by Sleeper" if any(allpts) else ", week's base lineups")
              + "): " + " | ".join(x for x in (p_h2h is not None and f"H2H {p_h2h:.0%}", p_med is not None and f"beat median {p_med:.0%}") if x))
        print("  Expected locked score (±1 sd): " + ", ".join(
            f"{d['team'][rid]}{'*' if rid == MY_ROSTER else ''} {m:.0f}±{math.sqrt(v):.0f}"
            for rid, (m, v) in sorted(scores.items(), key=lambda kv: -kv[1][0])))
        if opp:
            n_opp = sum(p in recorded for p in opp.get("starters") or [])
            print(f"  Opponent locks recorded: {n_opp} of 9. Their unrecorded slots are modeled (an eligible reported score at or above "
                  f"its wait value counts as locked). Record each lock you see in Sleeper's matchup view: "
                  f"./gm.py lock \"<their player>\" <score> --commit. lock and week then set matchup lines from these odds.")
    footer(d)


def standing_rows(rosters):
    """Rosters in standings order from Sleeper's official records (H2H plus median games; locked scores): wins
    (ties half), then PF -> [(roster_id, "W-L-T", PF, PA)]."""
    pts = lambda s, k: s.get(k, 0) + s.get(k + "_decimal", 0) / 100
    rows = [(r["roster_id"], r.get("settings") or {}) for r in rosters]
    rows.sort(key=lambda x: (-(x[1].get("wins", 0) + x[1].get("ties", 0) / 2), -pts(x[1], "fpts")))
    return [(rid, f"{s.get('wins', 0)}-{s.get('losses', 0)}-{s.get('ties', 0)}", pts(s, "fpts"), pts(s, "fpts_against"))
            for rid, s in rows]


def cmd_standings(d, a):
    # Not rebuilt from /matchups/<w>: once a week closes, those points revert to each starter's final game.
    print("Standings (Sleeper's records: H2H + median game each week; ties by PF, Sleeper tiebreak unverified)")
    print(f"  {'#':<3}{'Team':<15}{'W-L-T':<8}{'PF':>8}{'PA':>8}")
    for n, (rid, wlt, pf, pa) in enumerate(standing_rows(d["rosters"]), 1):
        mark = " bye" if n <= 2 else " playoff" if n <= 6 else ""
        print(f"  {n:<3}{d['team'][rid] + ('*' if rid == MY_ROSTER else ''):<15}{wlt:<8}{pf:>8.1f}{pa:>8.1f}{mark}")
        if n == 6:
            print("  " + "-" * 40 + " playoff line (top 6; top 2 bye; weeks 21-23)")
    footer(d)


def snapshot(rosters, pool, txn_ids, week):
    return {"taken": datetime.datetime.now().isoformat(timespec="minutes"), "week": week,
            "rosters": {str(r["roster_id"]): sorted((r.get("players") or []) + (r.get("reserve") or [])) for r in rosters},
            "status": {p: pool.get(p, {}).get("injury_status") or "" for r in rosters for p in (r.get("players") or [])},
            "txns": sorted(txn_ids)}


def diff(old, new, txns, team, name):
    """Lines describing what changed; the Owner's roster first."""
    out = []
    for t in txns:
        if t["transaction_id"] in old["txns"]:
            continue
        adds, drops = t.get("adds") or {}, t.get("drops") or {}
        who = sorted(set(adds.values()) | set(drops.values()) | set(t.get("roster_ids") or []))
        desc = "; ".join(f"{team(rid)} +{', '.join(name(p) for p, x in adds.items() if x == rid) or '—'}"
                         f" -{', '.join(name(p) for p, x in drops.items() if x == rid) or '—'}" for rid in who)
        bid = (t.get("settings") or {}).get("waiver_bid")
        out.append((MY_ROSTER not in who, f"TXN {t.get('type')} ({t.get('status')}{f', ${bid}' if bid else ''}): {desc}"))
    for rid, now in new["rosters"].items():
        before = set(old["rosters"].get(rid, []))
        plus, minus = set(now) - before, before - set(now)
        if plus or minus:
            out.append((rid != str(MY_ROSTER), f"ROSTER {team(int(rid))}: +{', '.join(map(name, sorted(plus))) or '—'} "
                                               f"-{', '.join(map(name, sorted(minus))) or '—'}"))
    owner = {p: rid for rid, ps in new["rosters"].items() for p in ps}
    for p, st in new["status"].items():
        if p in old["status"] and old["status"][p] != st:
            rid = owner.get(p)
            out.append((rid != str(MY_ROSTER), f"STATUS {name(p)} ({team(int(rid)) if rid else '?'}): "
                                               f"{old['status'][p] or 'healthy'} → {st or 'healthy'}"))
    return [line for _, line in sorted(out, key=lambda x: x[0])]


def cmd_changes(d, a):
    lid = d["league"]["league_id"]
    old = json.load(open(SNAPSHOT)) if os.path.exists(SNAPSHOT) else None
    weeks = range(min(old["week"], d["week"]) if old else d["week"], d["week"] + 1)
    try:
        txns = [t for w in weeks for t in draft.get(f"/league/{lid}/transactions/{w}")]
    except (OSError, ValueError) as e:
        refuse([f"transactions fetch failed ({e})"])
    new = snapshot(d["rosters"], d["pool"], [t["transaction_id"] for t in txns], d["week"])
    if old is None:
        print("No snapshot yet: baseline saved." if not a.no_write else "No snapshot yet (and --no-write): nothing to compare.")
    else:
        lines = diff(old, new, txns, lambda rid: d["team"].get(rid, f"roster {rid}"), lambda p: short(d["pool"], p))
        print(f"Changes since {old['taken']}:" if lines else f"No changes since {old['taken']}.")
        for line in lines:
            print("  " + line)
    if not a.no_write:
        os.makedirs(STATE, exist_ok=True)
        with open(SNAPSHOT + ".tmp", "w") as f:
            json.dump(new, f)
        os.replace(SNAPSHOT + ".tmp", SNAPSHOT)
        print(f"Snapshot advanced to {new['taken']}.")
    footer(d)


# ---------- self-test ----------

def lock_fixture():
    """Inline league for lock/week tests: eight starters who play daily, A (C, 40/g) at UTIL plays days 2-3,
    bench B (C, 30/g) plays days 1 and 3; today is day 1."""
    d1 = datetime.date(2026, 10, 20)
    days = [d1 + datetime.timedelta(i) for i in range(3)]
    plays = {f"s{i}": days for i in range(len(SLOTS) - 1)}
    plays.update(a=days[1:], b=[days[0], days[2]])
    one = {"G": "PG", "F": "SF", "UTIL": "C"}
    pos = {f"s{i}": [one.get(s, s)] for i, s in enumerate(SLOTS[:-1])}
    pos.update(a=["C"], b=["C"])
    pool = {p: {"full_name": p.upper(), "team": "T" + p, "fantasy_positions": pos[p]} for p in plays}
    sched = [{"week": 1, "date": day.isoformat(), "home": {"team": "T" + p}, "away": {"team": "Z" + p}}
             for p, ds in plays.items() for day in ds]
    starters = [f"s{i}" for i in range(len(SLOTS) - 1)] + ["a"]
    vals = {p: (10.0, 40.0 if p != "b" else 30.0) for p in plays}
    return {"pool": pool, "rosters": [{"roster_id": MY_ROSTER, "players": starters + ["b"], "starters": starters, "reserve": []}],
            "team": {MY_ROSTER: "Us"}, "sched": sched, "week": 1, "today": d1, "vals": vals, "locked": [], "board": [], "lock_path": None,
            "lineup_since": {MY_ROSTER: {p: "2026-10-19T12:00:00" for p in plays}}}


def test_pending_states():
    from unittest.mock import patch
    for case in ("missing schedule", "expired", "locked", "missing team", "open", "next game today"):
        d = lock_fixture()
        d["league"] = {"season": "2026"}
        d["today"] = datetime.date(2026, 10, 23) if case == "expired" else datetime.date(2026, 10, 21)
        if case == "missing schedule":
            d["sched"] = None
        if case == "missing team":
            d["pool"]["a"]["team"] = None
        if case == "next game today":
            d["today"] = datetime.date(2026, 10, 22)
        rows = [{"player_id": "a", "date": "2026-10-21", "stats": {"sp": 1, "pts": 10}},
                {"player_id": "a", "date": "2026-10-22", "stats": {"sp": 0}}]
        out = io.StringIO()
        with patch(__name__ + ".fetch", return_value=rows), contextlib.redirect_stdout(out):
            cmd_lock(d, argparse.Namespace(player=None, locked="A" if case == "locked" else None))
        text = out.getvalue()
        if case in ("open", "next game today"):
            assert "→ WAIT" in text, text
            if case == "next game today":
                assert "(lock before Thu 10/22's tip)" in text, text
        else:
            assert "→ LOCK" not in text and "→ WAIT" not in text, (case, text)
            assert {"missing schedule": "Schedule unavailable", "expired": "window closed",
                    "locked": "already locked", "missing team": "schedule unavailable"}[case] in text, text
    for locked in (None, "A"):
        d = lock_fixture()
        d["today"] = datetime.date(2026, 10, 23)
        args = argparse.Namespace(player="A", score=60, locked=locked, slot_of=None,
                                  game=datetime.date(2026, 10, 21), remaining=None, play=None)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            try:
                cmd_lock(d, args)
            except SystemExit as error:
                assert locked is None and "window closed" in str(error), error
            else:
                assert locked and "already locked" in out.getvalue(), out.getvalue()
        assert "→ LOCK" not in out.getvalue() and "→ WAIT" not in out.getvalue()


def test_lineup_eligibility():
    """A score a run saw benched at or after tip never gets a pending call; an unobserved start gets one, marked."""
    from unittest.mock import patch
    d = lock_fixture()
    d["league"] = {"season": "2026"}
    day = datetime.date(2026, 10, 21)
    d["today"] = day
    rows = [dict(player_id="a", date=day.isoformat(), stats=dict(sp=1, pts=100))]
    ms = [dict(roster_id=MY_ROSTER, starters=["a"], starters_points=[100.0])]
    # (first seen starting, run times, verdict): no tip time, so the game spans the ET day (04:00 to 05:00 next day UTC).
    for since, runs, verdict in ((None, [], "unseen"),  # regression: the week's first run after tip blinded every call
                                 ("2026-10-22T06:00:00", ["2026-10-21T12:00:00"], "unseen"),  # out only before tip
                                 ("2026-10-22T06:00:00", ["2026-10-22T05:30:00"], None),  # a run after the game saw him out
                                 ("2026-10-20T12:00:00", [], "seen")):
        d["lineup_since"], d["lineup_runs"] = {MY_ROSTER: {"a": since} if since else {}}, runs
        with patch(__name__ + ".fetch", return_value=rows), contextlib.redirect_stdout(io.StringIO()) as out:
            pending_locks(d, d["rosters"][0], week_games(d["sched"], 1))
        assert ("A: 100.0 FP → LOCK" in out.getvalue()) == bool(verdict), out.getvalue()
        assert ("start before tip unobserved" in out.getvalue()) == (verdict == "unseen"), out.getvalue()
        assert ("score not lockable" in out.getvalue()) == (verdict is None), out.getvalue()
        with patch(__name__ + ".fetch", return_value=rows), contextlib.redirect_stdout(io.StringIO()):
            assert eligible_reported(d, ms) == ({"a": 100.0} if verdict else {})
    with patch(__name__ + ".fetch", side_effect=OSError("offline")), contextlib.redirect_stdout(io.StringIO()):
        assert eligible_reported(d, ms) == {}
    # #3: an earlier locked score survives a later completed game, even after an observed benching.
    d["today"] = datetime.date(2026, 10, 23)
    boxes = {"a": {day: 100.0, day + datetime.timedelta(1): 20.0}}
    with patch(__name__ + ".box_scores", return_value=boxes), contextlib.redirect_stdout(io.StringIO()):
        assert eligible_reported(d, ms) == {"a": 100.0}
        d["today"] = day + datetime.timedelta(1)
        with patch.dict(CLOCK, now=datetime.datetime(2026, 10, 22, 23), tips={(d["today"], "Ta"): datetime.datetime(2026, 10, 22, 22)}):
            assert eligible_reported(d, ms) == {}, "an in-progress game cannot prove an earlier lock"
    # Observations survive a restart and starting-slot swaps; an observed benching after tip disqualifies the game.
    import tempfile
    with tempfile.TemporaryDirectory() as tmp, patch.dict(CLOCK, tips={(day, "Ta"): datetime.datetime(2026, 10, 21, 23)}):
        path = os.path.join(tmp, "lineups.json")
        rosters = d["rosters"]
        before, after, back = (datetime.datetime(2026, 10, 21, 12), datetime.datetime(2026, 10, 22, 1),
                               datetime.datetime(2026, 10, 22, 2))
        first, _ = observe_lineups(rosters, before, path)
        assert first[MY_ROSTER]["a"] == before.isoformat()
        rosters[0]["starters"][6], rosters[0]["starters"][8] = "a", "s6"
        assert observe_lineups(rosters, after, path)[0][MY_ROSTER]["a"] == before.isoformat()
        rosters[0]["starters"][6] = "b"
        assert "a" not in observe_lineups(rosters, after, path)[0][MY_ROSTER]
        rosters[0]["starters"][6] = "a"
        d["lineup_since"], d["lineup_runs"] = observe_lineups(rosters, back, path)
        assert observed_start(d, MY_ROSTER, "a", day) is False
        assert observe_lineups(rosters, after, os.path.join(tmp, "week2.json"))[0][MY_ROSTER]["a"] == after.isoformat()
        # Same-day pre-tip observations count; a first observation at/after tip with no earlier run is unknown.
        d["lineup_since"], d["lineup_runs"] = first, []
        assert observed_start(d, MY_ROSTER, "a", day) is True
        d["lineup_since"][MY_ROSTER]["a"] = "2026-10-21T23:00:00"
        assert observed_start(d, MY_ROSTER, "a", day) is None
        # The pre-run-log format keeps its starts; a corrupt file starts over.
        with open(path, "w") as f:
            f.write('{"4": {"a": "2026-10-21T12:00:00"}}')
        assert observe_lineups(rosters, after, path) == ({MY_ROSTER: {**{p: after.isoformat() for p in rosters[0]["starters"]},
                                                                      "a": before.isoformat()}}, [after.isoformat()])
        with open(path, "w") as f:
            f.write('{"4": {"a": "bad timestamp"}}')
        assert observe_lineups(rosters, after, path)[0][MY_ROSTER]["a"] == after.isoformat()
        rosters[0]["starters"][6] = "b"
        with patch("os.replace", side_effect=OSError("disk full")), contextlib.redirect_stdout(io.StringIO()) as out:
            assert observe_lineups(rosters, after, path) == ({}, [])
        assert "could not be saved" in out.getvalue()
        rosters[0]["starters"][6] = "a"
        d["lineup_since"], d["lineup_runs"] = observe_lineups(rosters, back, path)
        # ponytail: a failed save loses its benching; the call is then unknown (marked), never verified.
        assert observed_start(d, MY_ROSTER, "a", day) is None, "failed bench observation left old evidence reusable"


def test_posted_swap():
    """A base change that benches a starter with a posted score says to decide that score first (regression: Saturday
    night's base benched Jokić's 90.0 for Poeltl)."""
    d = lock_fixture()
    thu = d["today"] + datetime.timedelta(2)
    d["today"] = thu
    d["sched"] = [g for g in d["sched"] if not (g["home"]["team"] == "Ts0" and g["date"] == thu.isoformat())]
    d["sched"].append({"week": 1, "date": thu.isoformat(), "home": {"team": "Tg"}, "away": {"team": "Zg"}})
    d["pool"]["g"] = {"full_name": "G", "team": "Tg", "fantasy_positions": ["PG"]}
    d["vals"]["g"] = (10.0, 40.0)
    d["rosters"][0]["players"].append("g")
    with contextlib.redirect_stdout(io.StringIO()) as out:
        cmd_week(d, argparse.Namespace(locked=None))
    assert "start G (36.8) at PG (for S0; first lock S0's posted score instead if it's ≥ 36.8" in out.getvalue(), out.getvalue()
    # Codex P2: no guard while A's latest game is in progress (his Wed score expired; Thu's isn't lockable yet).
    from unittest.mock import patch
    d2 = lock_fixture()
    d2["today"] = thu
    d2["sched"].append({"week": 1, "date": thu.isoformat(), "home": {"team": "Tg"}, "away": {"team": "Zg"}})
    d2["pool"]["g"], d2["vals"]["g"] = {"full_name": "G", "team": "Tg", "fantasy_positions": ["PG"]}, (10.0, 90.0)
    d2["rosters"][0]["players"].append("g")
    with patch.dict(CLOCK, now=datetime.datetime(2026, 10, 23, 0, 30), tips={(thu, "Ta"): datetime.datetime(2026, 10, 23),
                                                                           (thu, "Tg"): datetime.datetime(2026, 10, 23, 1)}), \
            contextlib.redirect_stdout(io.StringIO()) as out:
        cmd_week(d2, argparse.Namespace(locked=None, ev=True))
    assert "start G (82.8) at UTIL (for A)" in out.getvalue(), out.getvalue()
    # Codex P2: the line is the slot's value with its feeds, not the incoming player's own games (H feeds PG Wed).
    d["today"] = thu - datetime.timedelta(1)
    d["sched"] = [g for g in d["sched"] if not (g["home"]["team"] == "Ts0" and g["date"] >= d["today"].isoformat())]
    d["sched"].append({"week": 1, "date": d["today"].isoformat(), "home": {"team": "Th"}, "away": {"team": "Zh"}})
    d["pool"]["h"], d["vals"]["h"] = {"full_name": "H", "team": "Th", "fantasy_positions": ["PG"]}, (10.0, 40.0)
    d["rosters"][0]["players"].append("h")
    with contextlib.redirect_stdout(io.StringIO()) as out:
        cmd_week(d, argparse.Namespace(locked=None))
    line = float(re.search(r"first lock S0's posted score instead if it's ≥ ([\d.]+)", out.getvalue()).group(1))
    assert line > 40, out.getvalue()


def test_whole_team():
    """lock prints the replanned team delta (equal to the slot's own when nothing else moves); week takes --play."""
    from unittest.mock import patch
    d = lock_fixture()
    args = argparse.Namespace(player="S0", score=100.0, locked=None, slot_of=None, game=None, remaining=None, play=None, ev=True)
    with contextlib.redirect_stdout(io.StringIO()) as out:
        cmd_lock(d, args)
    wait = float(re.search(r"slot wait value ([\d.]+)", out.getvalue()).group(1))
    lock_t, wait_t = map(float, re.search(r"lock 100.0 → ([\d.]+); wait → ([\d.]+)", out.getvalue()).groups())
    assert abs(lock_t - wait_t - (100 - wait)) < 0.15, out.getvalue()
    total = lambda play: float(re.search(r"with rotation ([\d.]+)", week_out(d, play)).group(1))
    assert total("S0=0") < total(None) and "--play: S0 plays each game from today with chance 0.00" in week_out(d, "S0=0")
    # Codex P2s: --play overrides an Out tag; a DTD's team arms use lock's plays (scored game spent, not his "next");
    # a final score with no later roll in his slot is kept by waiting (delta 0, not +score).
    d["pool"]["s0"]["injury_status"] = "Out"
    out_t, healthy = total(None), None
    d["pool"]["s0"]["injury_status"] = ""
    healthy = total(None)
    d["pool"]["s0"]["injury_status"] = "Out"
    assert out_t < healthy and abs(total("S0=0.92") - healthy) < 1, (out_t, healthy, total("S0=0.92"))
    d["pool"]["s0"]["injury_status"] = "DTD"
    with contextlib.redirect_stdout(io.StringIO()) as out:
        cmd_lock(d, args)
    wait = float(re.search(r"slot wait value ([\d.]+)", out.getvalue()).group(1))
    lock_t, wait_t = map(float, re.search(r"lock 100.0 → ([\d.]+); wait → ([\d.]+)", out.getvalue()).groups())
    assert abs(lock_t - wait_t - (100 - wait)) < 0.15, out.getvalue()
    d["pool"]["s0"]["injury_status"], d["today"] = "", d["today"] + datetime.timedelta(2)
    with contextlib.redirect_stdout(io.StringIO()) as out:
        cmd_lock(d, args)
    assert re.search(r"wait → [\d.]+ \([+-]0\.0 for locking\)", out.getvalue()), out.getvalue()
    # Codex P2: week's base benches a finished starter (E 0); waiting in Sleeper's lineup still keeps his Wed score.
    d["sched"] = [g for g in d["sched"] if g["home"]["team"] == "Tb" or g["date"] != d["today"].isoformat()]  # only B left
    with contextlib.redirect_stdout(io.StringIO()) as out:
        cmd_lock(d, argparse.Namespace(**{**vars(args), "game": d["today"] - datetime.timedelta(1)}))
    assert re.search(r"wait → [\d.]+ \([+-]0\.0 for locking\)", out.getvalue()), out.getvalue()
    # Codex P2s: a later game he'll sit (--play 0) still replaces an unlocked score; and another starter's standing
    # 100 isn't free for the plan to feed over. S0 (PG) and S2 (G, a PG) are done Thu; bench G2 (PG) plays Thu.
    delta = lambda o: float(re.search(r"\(([+-][\d.]+) for locking\)", o).group(1))
    dd = lock_fixture()
    with contextlib.redirect_stdout(io.StringIO()) as out:
        cmd_lock(dd, argparse.Namespace(**{**vars(args), "play": 0.0}))
    assert abs(delta(out.getvalue()) - 100) < 0.1, out.getvalue()
    thu = dd["today"] + datetime.timedelta(2)
    dd["today"], dd["league"] = thu, {"season": "2026"}
    dd["sched"] = [g for g in dd["sched"] if g["home"]["team"] not in ("Ts0", "Ts2") or g["date"] != thu.isoformat()]
    dd["sched"].append({"week": 1, "date": thu.isoformat(), "home": {"team": "Tg2"}, "away": {"team": "Zg2"}})
    dd["pool"]["g2"], dd["vals"]["g2"] = {"full_name": "G2", "team": "Tg2", "fantasy_positions": ["PG"]}, (10.0, 40.0)
    dd["rosters"][0]["players"].append("g2")
    wed = thu - datetime.timedelta(1)
    with patch(__name__ + ".box_scores", return_value={"s0": {wed: 20.0}, "s2": {wed: 100.0}}), \
            contextlib.redirect_stdout(io.StringIO()) as out:
        cmd_lock(dd, argparse.Namespace(**{**vars(args), "score": 20.0, "game": wed}))
    assert delta(out.getvalue()) <= 0, out.getvalue()
    wait0 = float(re.search(r"wait → ([\d.]+)", out.getvalue()).group(1))
    # Codex P2s: a failed fetch withholds the comparison; a Wed DNP voids S2's Tue score (no standing 100).
    with patch(__name__ + ".box_scores", side_effect=OSError("offline")), contextlib.redirect_stdout(io.StringIO()) as out:
        cmd_lock(dd, argparse.Namespace(**{**vars(args), "score": 20.0, "game": wed}))
    assert "whole-team comparison withheld" in out.getvalue() and "whole team (EV" not in out.getvalue(), out.getvalue()
    with patch(__name__ + ".box_scores", return_value={"s0": {wed: 20.0}, "s2": {wed - datetime.timedelta(1): 100.0}}), \
            contextlib.redirect_stdout(io.StringIO()) as out:
        cmd_lock(dd, argparse.Namespace(**{**vars(args), "score": 20.0, "game": wed}))
    assert float(re.search(r"wait → ([\d.]+)", out.getvalue()).group(1)) < wait0 - 50, out.getvalue()  # no 100
    # Codex P2: S2's Wed game is in progress, so his Tue 100 has expired; it must not stand.
    d3 = lock_fixture()
    tue, wed = d3["today"], d3["today"] + datetime.timedelta(1)
    d3["today"], d3["league"] = wed, {"season": "2026"}
    deltas = []  # whole-team lines (totals too: an expired score would raise both arms alike)
    for box in ({"s0": {tue: 20.0}}, {"s0": {tue: 20.0}, "s2": {tue: 100.0}}):
        with patch(__name__ + ".box_scores", return_value=box), contextlib.redirect_stdout(io.StringIO()) as out, \
                patch.dict(CLOCK, now=datetime.datetime(2026, 10, 22, 1), tips={(wed, "Ts2"): datetime.datetime(2026, 10, 22, 0)}):
            cmd_lock(d3, argparse.Namespace(**{**vars(args), "score": 20.0, "game": tue}))
        deltas.append(re.search(r"whole team .*", out.getvalue()).group(0))
    assert deltas[0] == deltas[1], deltas
    # Codex P2: replanning keeps S2's standing 100 while still starting a much better bench C (C2) over S6.
    dd["sched"].append({"week": 1, "date": thu.isoformat(), "home": {"team": "Tc2"}, "away": {"team": "Zc2"}})
    dd["pool"]["c2"], dd["vals"]["c2"] = {"full_name": "C2", "team": "Tc2", "fantasy_positions": ["C"]}, (10.0, 90.0)
    dd["rosters"][0]["players"].append("c2")
    with patch(__name__ + ".box_scores", return_value={"s0": {wed: 20.0}, "s2": {wed: 100.0}}), \
            contextlib.redirect_stdout(io.StringIO()) as out:
        cmd_lock(dd, argparse.Namespace(**{**vars(args), "score": 20.0, "game": wed}))
    assert delta(out.getvalue()) < -10 and float(re.search(r"wait → ([\d.]+)", out.getvalue()).group(1)) > wait0 + 30, out.getvalue()
    # Codex P2: a bench player whose game has tipped can't be promoted for that game (he was benched at tip).
    d5 = lock_fixture()
    with patch.dict(CLOCK, now=datetime.datetime(2026, 10, 21, 1), tips={(d5["today"], "Tb"): datetime.datetime(2026, 10, 21, 0)}):
        w5 = week_context(d5)
    assert w5["games"]["b"][d5["today"]] == 0.0 and w5["exp"]["b"] == wait_value(30.0, [1 - Q_DNP]), w5["exp"]["b"]
    # Codex P2: S0 has no game left, so waiting keeps his 60 while the replan still upgrades C (C2 over S6): no gain
    # from locking. (G2 can feed G only once S2's 100 is passed, so both arms keep it.)
    with patch(__name__ + ".box_scores", return_value={"s0": {wed: 60.0}, "s2": {wed: 100.0}}), \
            contextlib.redirect_stdout(io.StringIO()) as out:
        cmd_lock(dd, argparse.Namespace(**{**vars(args), "score": 60.0, "game": wed}))
    assert abs(delta(out.getvalue())) < 0.05, out.getvalue()
    # Codex P2: an unrecorded standing 100 that beats his remaining games closes his slot like a recorded lock would.
    import tempfile
    lines = []
    with tempfile.TemporaryDirectory() as tmp:
        for rec in ({}, {"s2": [100.0, MY_ROSTER, 2]}):
            with open(os.path.join(tmp, "locks.json"), "w") as f:
                json.dump(rec, f)
            with patch(__name__ + ".box_scores", return_value={"s0": {wed: 40.0}, "s2": {wed: 100.0}}), \
                    contextlib.redirect_stdout(io.StringIO()) as out:
                cmd_lock(dict(dd, lock_path=os.path.join(tmp, "locks.json")),
                         argparse.Namespace(**{**vars(args), "score": 40.0, "game": wed}))
            lines.append(delta(out.getvalue()))
    assert lines[0] == lines[1], lines
    # Codex P2s: a recorded lock ignores the box score; a standing 20 whose slot G2 can feed (36.8) isn't banked.
    with tempfile.TemporaryDirectory() as tmp:
        dl_ = dict(dd, lock_path=os.path.join(tmp, "locks.json"))
        outs = []
        for s2_box in (60.0, 80.0):
            with open(dl_["lock_path"], "w") as f:
                json.dump({"s2": [60.0, MY_ROSTER, 2]}, f)
            with patch(__name__ + ".box_scores", return_value={"s0": {wed: 40.0}, "s2": {wed: s2_box}}), \
                    contextlib.redirect_stdout(io.StringIO()) as out:
                cmd_lock(dl_, argparse.Namespace(**{**vars(args), "score": 40.0, "game": wed}))
            outs.append(re.search(r"whole team .*", out.getvalue()).group(0))
    assert outs[0] == outs[1], outs
    outs = []
    for box in ({"s0": {wed: 43.0}, "s2": {wed: 20.0}}, {"s0": {wed: 43.0}}):  # G2's feed beats the 20 either way
        with patch(__name__ + ".box_scores", return_value=box), contextlib.redirect_stdout(io.StringIO()) as out:
            cmd_lock(dd, argparse.Namespace(**{**vars(args), "score": 43.0, "game": wed}))
        outs.append(re.search(r"whole team .*", out.getvalue()).group(0))
    assert outs[0] == outs[1], outs
    # Codex P2: a standing 100 at G floors G in the rotation plan. On Wed, W2 (PG/SF) feeds SF (idle Wed; S3 plays Thu)
    # instead of G, whose 100 already beats a roll: the same totals as recording S2's lock.
    d6 = lock_fixture()
    tue6, wed6 = d6["today"], d6["today"] + datetime.timedelta(1)
    d6["today"], d6["league"] = wed6, {"season": "2026"}
    d6["sched"] = [g for g in d6["sched"] if not (g["home"]["team"] == "Ts2" and g["date"] > tue6.isoformat())
                   and not (g["home"]["team"] == "Ts3" and g["date"] == wed6.isoformat())]
    d6["sched"].append({"week": 1, "date": wed6.isoformat(), "home": {"team": "Tw2"}, "away": {"team": "Zw2"}})
    d6["pool"]["w2"], d6["vals"]["w2"] = {"full_name": "W2", "team": "Tw2", "fantasy_positions": ["PG", "SF"]}, (10.0, 40.0)
    d6["rosters"][0]["players"].append("w2")
    outs = []
    with tempfile.TemporaryDirectory() as tmp:
        for rec in ({}, {"s2": [100.0, MY_ROSTER, 2]}):
            with open(os.path.join(tmp, "locks.json"), "w") as f:
                json.dump(rec, f)
            with patch(__name__ + ".box_scores", return_value={"s0": {tue6: 50.0}, "s2": {tue6: 100.0}}), \
                    contextlib.redirect_stdout(io.StringIO()) as out:
                cmd_lock(dict(d6, lock_path=os.path.join(tmp, "locks.json")),
                         argparse.Namespace(**{**vars(args), "player": "S0", "score": 50.0, "game": tue6}))
            outs.append(re.search(r"whole team .*", out.getvalue()).group(0))
    assert outs[0] == outs[1], outs
    # Codex P2: a departed player's recorded lock keeps its slot's score in both totals.
    import tempfile
    totals = lambda o: re.search(r"lock 100.0 → ([\d.]+); wait → ([\d.]+)", o).groups()
    with tempfile.TemporaryDirectory() as tmp:
        d4 = dict(lock_fixture(), lock_path=os.path.join(tmp, "locks.json"))
        with contextlib.redirect_stdout(io.StringIO()) as before:
            cmd_lock(d4, args)
        with open(d4["lock_path"], "w") as f:
            json.dump({"gone": [100.0, MY_ROSTER, 3]}, f)  # locked at SF, since traded
        with contextlib.redirect_stdout(io.StringIO()) as after:
            cmd_lock(d4, args)
    assert all(float(y) > float(x) + 50 for x, y in zip(totals(before.getvalue()), totals(after.getvalue()))), after.getvalue()


def week_out(d, play):
    with contextlib.redirect_stdout(io.StringIO()) as out:
        cmd_week(dict(d, game_overrides={}), argparse.Namespace(locked=None, play=play, ev=True))
    return out.getvalue()


def test_pooled_locks():
    """Bench scores pool across idle starters' slots (issue #26): seat every bench player, rank scores vs lines."""
    from unittest.mock import patch
    # Sorted pairing: the best score takes the cheapest slot; 60 and 50 vs 48.3/53.3 locks 60 only (113.3 > 110).
    assert joint_locks({1: 60.0, 2: 50.0}, {1: 70, 2: 70, 3: 48.3, 4: 53.3}, {1: {3, 4}, 2: {3, 4}}) == {1: 3}
    assert joint_locks({1: 60.0, 2: 55.0}, {1: 70, 2: 70, 3: 48.3, 4: 53.3}, {1: {3, 4}, 2: {3, 4}}) == {1: 3, 2: 4}
    # A feed whose own slot another feed closes can't lock there (9 = 60 - 50 - MOVE_COST beats 58 - 50).
    assert joint_locks({1: 60.0, 2: 58.0}, {1: 70, 2: 50}, {1: {2}}) == {1: 2}
    assert joint_locks({1: 40.0}, {1: 70, 3: 48.3}, {1: {3}}) == {}

    d = lock_fixture()
    tue, wed = d["today"], d["today"] + datetime.timedelta(1)
    # S6 (C) sits Tue, A (C, UTIL) is strong; bench B (C) and W (C/PF, 28/g) both play Tue.
    d["sched"] = [g for g in d["sched"] if not (g["home"]["team"] == "Ts6" and g["date"] == tue.isoformat())]
    d["sched"].append({"week": 1, "date": tue.isoformat(), "home": {"team": "Tw"}, "away": {"team": "Zw"}})
    d["vals"].update(a=(30.0, 70.0), w=(10.0, 28.0))
    d["pool"]["w"] = {"full_name": "W", "team": "Tw", "fantasy_positions": ["C", "PF"]}
    d["rosters"][0]["players"].append("w")
    d["lineup_since"][MY_ROSTER]["w"] = "2026-10-19T12:00:00"
    # W can't beat A's line alone, but he is seated and his score can close S6's cheaper C slot.
    assert week_context(d)["plan"][tue] == {6: "b", 8: "w"}
    with contextlib.redirect_stdout(io.StringIO()) as out:
        cmd_week(d, argparse.Namespace(locked=None))
    assert "W (UTIL for A) ≥ 72.4 or ≥ 44.3 via C (S6's)" in out.getvalue(), out.getvalue()

    d["today"], d["league"] = wed, {"season": "2026"}
    d["rosters"][0]["starters"][6], d["rosters"][0]["starters"][8] = "b", "w"
    for w_pts, want in ((50, ["C    B: 45.0 FP → LOCK (slot wait value 43.3",
                              "UTIL W: 50.0 FP → LOCK via UTIL 43.9 (S7's slot): move A to UTIL and bench S7",
                              "S7: 40.0 FP → PASS (W's lock in UTIL closes this slot"]),
                        (40, ["C    B: 45.0 FP → LOCK (slot wait value 43.3",
                              "W: 40.0 FP → WAIT (slot wait value 72.4: Wed A, Thu A; cheapest other slot he reaches: "
                              "43.9 via UTIL, S7's slot)", "S7: 40.0 FP → WAIT"])):
        rows = [dict(player_id=p, date=tue.isoformat(), stats=dict(sp=1, pts=x)) for p, x in (("b", 45), ("w", w_pts), ("s7", 40))]
        with patch(__name__ + ".fetch", return_value=rows), contextlib.redirect_stdout(io.StringIO()) as out:
            pending_locks(d, d["rosters"][0], week_games(d["sched"], 1))
        for line in want:
            assert line in out.getvalue(), (line, out.getvalue())


def test_lock_continuations():
    """Applied feeder rotations and injury overrides must retain a stronger returner's future roll."""
    from unittest.mock import patch
    d = lock_fixture()
    tue, wed, thu = [d["today"] + datetime.timedelta(i) for i in range(3)]
    d["vals"].update({f"s{i}": (50.0, 100.0) for i in range(8)})
    d["vals"]["a"] = (30.0, 70.0)
    d["sched"] = [g for g in d["sched"] if not (g["home"]["team"] == "Ta" and g["date"] == wed.isoformat())]
    d["today"], d["league"] = wed, {"season": "2026"}
    args = argparse.Namespace(player="B", score=40, locked=None, slot_of=None, game=tue, remaining=None, play=None)
    d["rosters"][0]["starters"][-1] = "b"  # Tuesday's feed has actually been applied in Sleeper.
    expected = wait_value(70, [1 - Q_DNP])
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        cmd_lock(d, args)
    assert f"B: 40.0 FP → WAIT (slot wait value {expected:.1f}:" in out.getvalue(), out.getvalue()
    assert "Thu A" in out.getvalue(), out.getvalue()
    out = io.StringIO()
    with patch(__name__ + ".fetch", return_value=[dict(player_id="b", date=tue.isoformat(), stats=dict(sp=1, pts=40))]), \
            contextlib.redirect_stdout(out):
        pending_locks(d, d["rosters"][0], week_games(d["sched"], 1))
    assert f"B: 40.0 FP → WAIT (slot wait value {expected:.1f}:" in out.getvalue(), out.getvalue()

    # A feeder already allocated elsewhere that day is not available to this slot.
    w = week_context(d, sleeper_base=True)
    w["plan"][thu][6] = "a"
    assert abs(slot_rest(w, 8, tue)[0] - wait_value(30, [1 - Q_DNP])) < 1e-9

    # Explicit anchors and either override must retain the returning player, even when B has no future roll.
    d["rosters"][0]["starters"][-1] = "a"
    args.slot_of = "A"
    for remaining, probability in ((None, 0.0), (0, None), (0, 0.0), (1, 0.92)):
        args.remaining, args.play = remaining, probability
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cmd_lock(d, args)
        assert f"B: 40.0 FP → WAIT (slot wait value {expected:.1f}:" in out.getvalue(), out.getvalue()
        assert "other slot options are retained" in out.getvalue(), out.getvalue()

    # Overrides also affect the starter itself; the bench remains usable on his ruled-out date.
    args.player, args.slot_of, args.score, args.remaining, args.play = "A", None, 25, 0, None
    d["sched"].append(dict(week=1, date=tue.isoformat(), home=dict(team="Ta"), away=dict(team="Za")))
    args.game = tue
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        cmd_lock(d, args)
    assert "A: 25.0 FP → WAIT (slot wait value 27.7:" in out.getvalue(), out.getvalue()
    assert "Thu B" in out.getvalue(), out.getvalue()

    # A count override skips the earliest dates, not the final one, without removing A's Thursday roll.
    sun = tue + datetime.timedelta(5)
    d["sched"].append(dict(week=1, date=sun.isoformat(), home=dict(team="Tb"), away=dict(team="Zb")))
    args.player, args.slot_of, args.score, args.remaining = "B", "A", 40, 1
    expected = stop_value([[(70, 1 - Q_DNP)], [(30, 1 - Q_DNP)]])
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        cmd_lock(d, args)
    assert f"B: 40.0 FP → WAIT (slot wait value {expected:.1f}:" in out.getvalue(), out.getvalue()
    assert "Thu A, Sun B" in out.getvalue(), out.getvalue()
    args.locked = "A"
    with contextlib.redirect_stdout(io.StringIO()):
        try:
            cmd_lock(d, args)
        except SystemExit as error:
            assert "already locked" in str(error), error
        else:
            raise AssertionError("a locked anchor accepted another score")


def run_fa(d):
    """cmd_fa on a lock_fixture league, offline (no transactions, trending adds or box scores)."""
    from unittest.mock import patch
    d = dict(d, league={"league_id": "L", "season": "2026", "settings": {"waiver_clear_days": 2}}, notes={})
    d["rosters"][0].setdefault("settings", {"waiver_position": 10})
    out = io.StringIO()
    with patch("draft.get", return_value=[]), patch(__name__ + ".trending_adds", return_value=None), \
            patch.object(rb, "season_weeks", side_effect=OSError("offline")), contextlib.redirect_stdout(out):
        cmd_fa(d, argparse.Namespace(locked=None, pos=None, top=15))
    return out.getvalue()


def fa_fixture():
    """lock_fixture on Wed: free agents F (plays Thu) and G (played Tue, plays Thu), both C at 80 FP/g."""
    d = lock_fixture()
    tue, thu = d["today"], d["today"] + datetime.timedelta(2)
    d["today"] = tue + datetime.timedelta(1)
    for p, days in (("f", [thu]), ("g", [tue, thu])):
        d["pool"][p] = {"full_name": p.upper(), "team": "T" + p, "fantasy_positions": ["C"], "active": True}
        d["sched"] += [{"week": 1, "date": day.isoformat(), "home": {"team": "T" + p}, "away": {"team": "Z" + p}} for day in days]
        d["vals"][p] = (10.0, 80.0)
    d["board"] = ["f", "g"]
    return d


def test_fa_waivers():
    # waiver_after_game_start (regression: G, whose team played yesterday, was offered as an instant add and stream).
    text = run_fa(fa_fixture())
    assert "add F (Tf" in text and "add G" not in text, text
    assert "WAIVERS (played Tue)" in next(line for line in text.splitlines() if line.strip().startswith("#2")), text
    assert "become waiver claims once their team tips" in text, text
    # A stream must gain >= 5 FP this week and beat 3x its season cost (regression: a +0.6 stream that cost
    # -1.8 V/wk led the list). F at 47 FP/g gains +4.4 at no season cost; at 50 FP/g, +6.2 vs 3 x (4 - 0) = 12
    # is hidden and vs 3 x (4 - 3) = 3 is shown.
    for fpg, v_fa, shown in ((47.0, 10.0, False), (50.0, 0.0, False), (50.0, 3.0, True)):
        d = fa_fixture()
        d["vals"].update(f=(v_fa, fpg), b=(4.0, 30.0))
        text = run_fa(d)
        assert ("add F (Tf" in text) == shown and ("No stream beats its season cost this week." in text) != shown, text


def test_lock_commits():
    """lock --commit records persist per week and feed week/fa/matchup; --locked overrides them."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        dd = lock_fixture()
        assert lock_path(dd) is None and saved_locks(dd) == {} and locked_pids(dd, None) == []  # fixtures never read private/state
        dd["lock_path"] = os.path.join(tmp, "locks.json")
        args = lambda player, score=None, commit=True, uncommit=False: argparse.Namespace(
            player=player, score=score, commit=commit, uncommit=uncommit, locked=None, slot_of=None, game=None, remaining=None, play=None)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            cmd_lock(dd, args("S0", 55))
        assert saved_locks(dd) == {"s0": 55.0} and "Recorded lock: S0 at 55.0" in out.getvalue(), out.getvalue()
        assert locked_pids(dd, None) == ["s0"] and locked_pids(dd, "") == [] and locked_pids(dd, "A") == ["a"]
        dd["locked"] = locked_pids(dd, None)
        assert week_context(dd)["blocked"] == {0}  # week (and fa, via locked_pids) treat the slot as locked, no flag
        with contextlib.redirect_stdout(io.StringIO()) as out:
            cmd_week(dd, argparse.Namespace(locked=None))
        assert "plus 55.0 already locked" in out.getvalue() and "S0 55.0" in out.getvalue(), out.getvalue()
        for bad in (args("B", 40), args("S1")):  # B is on the bench; a commit needs the score
            try:
                cmd_lock(dd, bad)
            except SystemExit:
                pass
            else:
                raise AssertionError(bad)
        # A record for a player Sleeper shows on the bench adds nothing to the week total (no double count).
        bench_rec = dict(dd, locked=["b"], rosters=[dict(dd["rosters"][0])])
        with open(dd["lock_path"], "w") as f:
            json.dump({"b": 40.0}, f)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            cmd_week(bench_rec, argparse.Namespace(locked=None))
        assert "already locked" not in out.getvalue(), out.getvalue()
        with open(dd["lock_path"], "w") as f:
            json.dump({"s0": 55.0}, f)
        # Unreadable records block a commit rather than being overwritten; a non-current week is refused.
        with open(dd["lock_path"], "w") as f:
            f.write("{not json")
        for bad_d in (dd, dict(dd, state={"week": 2})):
            try:
                cmd_lock(bad_d, args("S1", 40))
            except SystemExit:
                pass
            else:
                raise AssertionError("commit should refuse")
        with open(dd["lock_path"], "w") as f:
            json.dump({"s0": 55.0}, f)
        # The recorded score is our known score for that slot in win odds (zero variance).
        dd["lock_scores"] = {"s0": 55.0}
        hi = team_score(dd, MY_ROSTER, {}, True)
        dd["lock_scores"] = {"s0": 0.0}
        lo = team_score(dd, MY_ROSTER, {}, True)
        assert abs(hi[0] - lo[0] - 55.0) < 1e-9 and abs(hi[1] - lo[1]) < 1e-9, (hi, lo)
        with contextlib.redirect_stdout(io.StringIO()):
            cmd_lock(dd, args("S0", commit=False, uncommit=True))
        assert saved_locks(dd) == {}
        # Each week has its own file, so records reset when the week changes.
        wk = dict(lock_fixture(), league={"season": "2026"})
        del wk["lock_path"]  # use the real naming rule (path only; nothing is read or written)
        p1 = lock_path(wk)
        wk["week"] = 2
        assert p1.endswith("locks-2026-w01.json") and lock_path(wk).endswith("locks-2026-w02.json")


def test_tip_clock():
    """ESPN tips (trimmed from the Nov 1 2026 scoreboard), CT across both DST changes, the Sleeper cross-check and
    fallback, slot deadlines, and no feeds after a tip."""
    import tempfile
    from unittest.mock import patch
    U = datetime.datetime
    for utc, want in ((U(2026, 10, 20, 23), U(2026, 10, 20, 18)), (U(2026, 11, 1, 6, 59), U(2026, 11, 1, 1, 59)),
                      (U(2026, 11, 1, 7), U(2026, 11, 1, 1)), (U(2026, 11, 3), U(2026, 11, 2, 18)),
                      (U(2027, 3, 14, 7, 59), U(2027, 3, 14, 1, 59)), (U(2027, 3, 14, 8), U(2027, 3, 14, 3))):
        assert ct(utc) == want, (utc, ct(utc))
    espn = {"events": [{"date": "2026-11-01T20:30Z", "competitions": [{"competitors": [
        {"homeAway": "home", "team": {"abbreviation": "ORL"}}, {"homeAway": "away", "team": {"abbreviation": "BOS"}}]}]},
        {"date": "2026-11-02T01:30Z", "competitions": [{"competitors": [
            {"homeAway": "home", "team": {"abbreviation": "GS"}}, {"homeAway": "away", "team": {"abbreviation": "LAC"}}]}]}]}
    assert espn_tips(espn) == [["BOS", "ORL", "2026-11-01T20:30Z"], ["LAC", "GSW", "2026-11-02T01:30Z"]]
    nov1 = datetime.date(2026, 11, 1)
    sched = [{"week": 3, "date": "2026-11-01", "away": {"team": aw}, "home": {"team": h}}
             for aw, h in (("BOS", "ORL"), ("LAC", "GSW"), ("BKN", "IND"))]  # ESPN lacks BKN@IND: date-level
    with tempfile.TemporaryDirectory() as tmp, patch(__name__ + ".CACHE", tmp):
        out = io.StringIO()
        with patch(__name__ + ".fetch", return_value=espn) as f, contextlib.redirect_stdout(out):
            tips = tip_times(sched, [nov1])
            assert tip_times(sched, [nov1]) == tips and f.call_count == 1  # cached for the day
        assert "no ESPN tip time for 1 game(s) (Sun BKN@IND)" in out.getvalue(), out.getvalue()
    with tempfile.TemporaryDirectory() as tmp, patch(__name__ + ".CACHE", tmp), \
            patch(__name__ + ".fetch", side_effect=OSError("offline")), contextlib.redirect_stdout(io.StringIO()) as out:
        assert tip_times(sched, [nov1]) == {} and "(offline)" in out.getvalue()
    with patch.dict(CLOCK, tips=tips):
        assert tip_text(nov1, "ORL") == "Sun 11/01 2:30 PM CT tip" and tip_text(nov1, "GSW") == "Sun 11/01 7:30 PM CT tip"
        assert tip_text(nov1, "BKN") == "Sun 11/01's tip" and not tipped(nov1, "ORL")  # --date run: no clock

    # The deadline is the slot's next tip, not his own next game (regression: B fed into A's UTIL on Tue, next game
    # Thu, printed "lock before Thu" while the plan moves A back into the slot for his Wed game).
    d = lock_fixture()
    tue, wed, thu = [d["today"] + datetime.timedelta(i) for i in range(3)]
    d["rosters"][0]["starters"][-1] = "b"
    args = argparse.Namespace(player="B", score=40, locked=None, slot_of=None, game=tue, remaining=None, play=None)
    for tips, want in (({}, "Deadline: lock before Wed 10/21's tip, when the plan moves A into his slot"),
                       ({(wed, "Ta"): U(2026, 10, 21, 23)}, "Deadline: lock before Wed 10/21 6:00 PM CT tip, when")):
        with patch.dict(CLOCK, tips=tips), contextlib.redirect_stdout(io.StringIO()) as out:
            cmd_lock(d, args)
        assert want in out.getvalue(), out.getvalue()

    # No feed for a bench player whose game has tipped: B (Tue) fills idle UTIL until Tb tips on a live clock.
    d = lock_fixture()
    w = week_context(d)
    assert w["plan"][tue] == {8: "b"} and slot_rest(w, 8, tue - datetime.timedelta(1))[1][0] == (tue, "b")
    with patch.dict(CLOCK, now=U(2026, 10, 20, 23, 30), tips={(tue, "Tb"): U(2026, 10, 20, 23)}):
        w = week_context(d)
        assert w["plan"][tue] == {} and slot_rest(w, 8, tue - datetime.timedelta(1))[1][0] == (wed, "a")
        # fa: a free agent whose team tipped today is a waiver claim, not a stream (F also plays Wed here).
        d = fa_fixture()
        d["sched"].append({"week": 1, "date": wed.isoformat(), "home": {"team": "Tf"}, "away": {"team": "Zf"}})
        CLOCK.update(now=U(2026, 10, 21, 23, 30), tips={(wed, "Tf"): U(2026, 10, 21, 23)})
        text = run_fa(d)
        assert "WAIVERS (played Wed)" in next(x for x in text.splitlines() if x.strip().startswith("#1")) and "add F" not in text, text


def test_reuse():
    """Same-night slot reuse: needs both tip times at least REUSE_GAP apart, skips locked slots, orders the rolls by
    tip, moves the early score's deadline to the late tip, and prints the swap in week."""
    from unittest.mock import patch
    U = datetime.datetime
    d = lock_fixture()  # Thu: every starter and bench B (C, 30/g) play, so B feeds nothing without reuse
    tue, wed, thu = [d["today"] + datetime.timedelta(i) for i in range(3)]
    early = {(thu, "T" + p): U(2026, 10, 23, 0) for p in ["a"] + [f"s{i}" for i in range(len(SLOTS) - 1)]}

    def ctx(b_tip, dd=d):
        with patch.dict(CLOCK, tips={**early, (thu, "Tb"): b_tip}):
            return week_context(dd)
    assert not any(ctx(None)["extra"].values()) and not any(ctx(U(2026, 10, 23, 2, 30))["extra"].values())  # no tip; 2.5 h
    w = ctx(U(2026, 10, 23, 3))
    (i, (q, late)), = w["extra"][thu].items()
    assert q == "b" and late and SLOTS[i] in ("C", "UTIL") and not w["plan"][thu], w["extra"]
    feeds, extra = feeds_of(w, i)
    assert stop_value(slot_days(w["left"], w["base"][i], feeds, w["games"], w["fpg"], extra)) > \
        stop_value(slot_days(w["left"], w["base"][i], feeds, w["games"], w["fpg"]))
    with patch.dict(CLOCK, tips={**early, (thu, "Tb"): U(2026, 10, 23, 3)}):
        assert team_score(d, MY_ROSTER, {}, False)[0] > team_score(dict(d, pool={**d["pool"], "b": dict(d["pool"]["b"], team="Tx")}),
                                                                   MY_ROSTER, {}, False)[0]
    # The early starter's Thu score now has a same-night continuation (B), due at B's tip; B's own score has none.
    dt = dict(d, today=thu)
    with patch.dict(CLOCK, tips={**early, (thu, "Tb"): U(2026, 10, 23, 3)}):
        w = week_context(dt)
        (i, _), = w["extra"][thu].items()
        occ = w["base"][i]
        rest, fills = slot_rest(w, i, thu, occ)
        assert fills == [(thu, "b")] and abs(rest - wait_value(30, [w["games"]["b"][thu]])) < 1e-9, (rest, fills)
        assert slot_rest(w, i, thu, "b") == (0.0, [])
        assert deadline(dt["pool"], occ, [], fills) == (thu, "Tb", "b")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            cmd_week(dt, argparse.Namespace(locked=None))
        text = out.getvalue()
        assert f"same night, {SLOTS[i]}: {occ.upper()} plays the Thu 10/22 7:00 PM CT tip; once that game is final" in text, text
        assert "then put B in" in text and "before the 10:00 PM CT tip" in text and "same-night reuse +" in text, text
    # B early, the slot's starter late: B goes first and the starter returns for the late tip.
    with patch.dict(CLOCK, tips={**{k: U(2026, 10, 23, 3) for k in early}, (thu, "Tb"): U(2026, 10, 23, 0)}):
        w = week_context(dt)
        (i, (q, late)), = w["extra"][thu].items()
        assert q == "b" and not late
        assert slot_rest(w, i, thu, "b")[1] == [(thu, w["base"][i])]
    # A later night's reuse rolls count in a score's continuation, and the early swap sets its deadline: A's Wed
    # score, then B early Thu in A's slot (the starters' Thu tips match B's, so only A's slot qualifies), A late.
    tips = {**{k: U(2026, 10, 23, 0) for k in early}, (thu, "Ta"): U(2026, 10, 23, 3), (thu, "Tb"): U(2026, 10, 23, 0)}
    dw = dict(d, today=wed, league={"season": "2026"})
    with patch.dict(CLOCK, tips=tips):
        w = week_context(dw)
        assert w["extra"][thu] == {8: ("b", False)}, w["extra"]
        rest, fills = slot_rest(w, 8, wed, "a")
        assert fills == [(thu, "b"), (thu, "a")], fills
        assert abs(rest - stop_value([[(30, w["games"]["b"][thu])], [(40, w["games"]["a"][thu])]])) < 1e-9, rest
        assert deadline(dw["pool"], "a", [thu], fills) == (thu, "Tb", "b")
        with patch.dict(CLOCK, now=U(2026, 10, 23, 1)):  # #20: B's tip passed with A still in the slot
            assert deadline(dw["pool"], "a", [thu], fills) == (thu, "Ta", "a")
            # ...but once B tipped in that slot with A benched, the fill happened and A's Wed score is gone.
            r0 = dw["rosters"][0]
            moved = dict(dw, rosters=[dict(r0, starters=[p if p != "a" else "b" for p in r0["starters"]])] + dw["rosters"][1:])
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    cmd_lock(moved, argparse.Namespace(player="A", score=35, locked=None, slot_of="B", game=wed,
                                                       remaining=None, play=None))
            except SystemExit as e:
                assert "B has played in his slot" in str(e), e
            else:
                raise AssertionError("benched A's score after B's tip was lockable")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            cmd_lock(dw, argparse.Namespace(player="A", score=35, locked=None, slot_of=None, game=wed, remaining=None, play=None))
        assert "then Thu B, Thu A available" in out.getvalue() and "lock before Thu 10/22 7:00 PM CT tip" in out.getvalue(), out.getvalue()
    # A DTD late roll keeps tonight's injury discount: A's early Thu score faces B at 0.50, not 0.92.
    tips = {**{k: U(2026, 10, 23, 3) for k in early}, (thu, "Ta"): U(2026, 10, 23, 0), (thu, "Tb"): U(2026, 10, 23, 3)}
    dd = dict(dt, pool={**d["pool"], "b": dict(d["pool"]["b"], injury_status="DTD")}, league={"season": "2026"})
    with patch.dict(CLOCK, tips=tips):
        w = week_context(dd)
        assert w["extra"][thu] == {8: ("b", True)} and w["games"]["b"][thu] == P_DTD[0], (w["extra"], w["games"]["b"])
        assert abs(slot_rest(w, 8, thu, "a")[0] - wait_value(30, [P_DTD[0]])) < 1e-9
        with contextlib.redirect_stdout(io.StringIO()) as out:
            cmd_lock(dd, argparse.Namespace(player="A", score=20, locked=None, slot_of=None, game=thu, remaining=None, play=None))
        assert "A: 20.0 FP → LOCK" in out.getvalue(), out.getvalue()
    # A locked slot takes no reuse roll.
    dl = dict(d, locked=["a"])
    with patch.dict(CLOCK, tips={**early, (thu, "Tb"): U(2026, 10, 23, 3)}):
        w = week_context(dl)
        assert all(w["base"][j] != "a" for j in w["extra"][thu]), w["extra"]


def test_review():
    """review: a lock at/below the line, no lock with a DNP final, a 0-game slot, a feed, unknown box scores."""
    from unittest.mock import patch
    d = lock_fixture()
    d1, d2, d3 = (datetime.date(2026, 10, 20 + k) for k in range(3))
    d.update(league={"season": "2026", "league_id": "L"}, today=datetime.date(2026, 10, 26))
    d["pool"]["s3"]["team"] = "TX"  # SF: no games this week
    scores = {p: {day: 40.0 for day in (d1, d2, d3)} for p in ("s4", "s5", "s6", "s7")}
    scores.update(s0={d1: 60.0, d2: 30.0, d3: 30.0}, s1={d1: 35.0, d2: 50.0, d3: 20.0}, s2={d1: 30.0, d2: 30.0},
                  a={d2: 20.0, d3: 45.0}, b={d1: 25.0, d3: 30.0})
    rows = [{"player_id": p, "date": day.isoformat(), "stats": {"sp": 30, "pts": fp}} for p, g in scores.items() for day, fp in g.items()]
    tmp = tempfile.TemporaryDirectory()
    d["lock_path"] = os.path.join(tmp.name, "locks.json")
    with open(d["lock_path"], "w") as f:
        json.dump({"s0": 60.0, "s1": 35.0, "s5": 40.0}, f)  # s5 scored 40 in all three games
    del d["vals"]["s4"]  # PF: played every game, no board projection

    def run(fetched, matchups):
        out = io.StringIO()
        with patch(__name__ + ".fetch", side_effect=fetched), patch("draft.get", side_effect=matchups), contextlib.redirect_stdout(out):
            cmd_review(d, argparse.Namespace(week=1))
        return out.getvalue()

    text = run([rows], OSError("offline"))
    row = {}  # slot -> (counted, from, policy, hindsight, leak, cause); the second UTIL as "UTIL2"
    for line in text.splitlines():
        m = re.match(r"  (\S+)\s+\S+\s+(-?[\d.]+) \(([^)]*)\)\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)  (.*)", line)
        if m and m.group(1) in SLOTS:
            key = m.group(1) + ("2" if m.group(1) in row else "")
            row[key] = tuple(float(x) if k in (1, 3, 4, 5) else x for k, x in enumerate(m.groups()) if k)
    assert row["PG"][:3] == (60.0, "lock", 60.0) and "below line" not in row["PG"][5], row["PG"]
    assert row["SG"][:3] == (35.0, "lock", 50.0) and row["SG"][4] == 15.0 and "locked below line" in row["SG"][5], row["SG"]
    assert row["G"][:2] == (0.0, "final game") and "his final game: DNP" in row["G"][5], row["G"]
    assert row["SF"][:4] == (0.0, "no games", 0.0, 0.0) and "0-game slot" in row["SF"][5], row["SF"]
    assert row["F"][:3] == (40.0, "lock", 40.0) and "below line" not in row["F"][5], row["F"]  # Codex P2: the later 40
    pf = next(line for line in text.splitlines() if line.startswith("  PF"))
    assert "PF" not in row and " n/a " in pf and "no board projection for S4: policy unknown" in pf and "0-game" not in pf, pf
    assert "policy unknown in 1 slot(s)" in text and "counted 260.0 | policy 275.0 | hindsight 305.0" in text, text
    assert row["UTIL2"][:2] == (45.0, "final game") and "1 feed(s) planned, adherence unknown" in row["UTIL2"][5], row["UTIL2"]
    assert "Outcome line: week 1 execution" in text and "largest leak SG" in text, text
    # Sleeper's slot points: shows the latest game for a locked slot -> flagged for issue #3.
    ms = [{"roster_id": MY_ROSTER, "starters": d["rosters"][0]["starters"], "starters_points": [30.0, 35.0] + [0.0] * 7}]
    text = run([rows], [ms])
    assert "equal the lock record in 1 of 3" in text and "issue allmanr/fb-gm#3" in text, text
    text = run(OSError("offline"), [ms])
    assert "counted, policy and hindsight unknown" in text and "Totals" not in text, text
    tmp.cleanup()
    # The week is over on a later day, or on its last day once every game there tipped 3 h ago (Codex P2: Sunday night).
    sun, now = datetime.date(2026, 10, 25), datetime.datetime(2026, 10, 26, 3, 0)
    sched = [{"date": "2026-10-25", "home": {"team": "H"}, "away": {"team": "A"}}]
    assert week_over(sched, sun, sun + datetime.timedelta(1), now) and not week_over(sched, sun, sun - datetime.timedelta(1), now)
    assert week_over(sched, sun, sun, None)  # a --date dry run
    for tip, over in ((now - datetime.timedelta(hours=3), True), (now - datetime.timedelta(hours=2), False), (None, False)):
        with patch(__name__ + ".tip_times", return_value={(sun, "A"): tip, (sun, "H"): tip} if tip else {}):
            assert week_over(sched, sun, sun, now) is over, (tip, over)


def test_review_pooled():
    """review replays pooled locks (issue #26): a via lock is credited, paired by player, and judged on its via line."""
    from unittest.mock import patch
    # replay, q26's case: b's 45 Mon in UTIL (j's) closes C via one hop (j moves to C); j's 70 then stands in C.
    d1, d2 = datetime.date(2025, 11, 3), datetime.date(2025, 11, 4)
    games = {"j": {d2: 0.92}, "c": {d2: 0.92}, "b": {d1: 0.92}}
    out, lines, vias = replay({7: "j", 6: "c"}, {7: [(d1, "b"), (d2, "j")], 6: [(d2, "c")]}, [d1, d2], games,
                              {"j": 80.0, "c": 40.0, "b": 30.0}, {"b": {d1: 45.0}, "j": {d2: 70.0}, "c": {d2: 30.0}},
                              {p: ["C"] for p in "jcb"})
    assert out == {7: ("b", 45.0), 6: ("j", 70.0)} and vias == 1, (out, vias)
    assert abs(lines[("b", d1)] - (stop_value([[(40.0, 0.92)]]) + MOVE_COST)) < 1e-9, lines  # C's line + 1, not j's

    # test_pooled_locks' week: W (bench, UTIL for A) scores 50 Tue; the Owner locked him via S7's UTIL (A moves there).
    d = lock_fixture()
    tue, wed, thu = (d["today"] + datetime.timedelta(k) for k in range(3))
    d["sched"] = [g for g in d["sched"] if not (g["home"]["team"] == "Ts6" and g["date"] == tue.isoformat())]
    d["sched"].append({"week": 1, "date": tue.isoformat(), "home": {"team": "Tw"}, "away": {"team": "Zw"}})
    d["vals"].update(a=(30.0, 70.0), w=(10.0, 28.0))
    d["pool"]["w"] = {"full_name": "W", "team": "Tw", "fantasy_positions": ["C", "PF"]}
    d["rosters"][0]["players"].append("w")
    d["rosters"][0]["starters"][7], d["rosters"][0]["starters"][8] = "a", "w"
    d.update(league={"season": "2026", "league_id": "L"}, today=datetime.date(2026, 10, 26))
    scores = {p: {day: 40.0 for day in (tue, wed, thu)} for p in ("s0", "s1", "s2", "s3", "s4", "s5", "s7")}
    scores.update(s6={wed: 40.0, thu: 40.0}, a={wed: 40.0, thu: 60.0}, b={tue: 45.0, thu: 30.0})
    tmp = tempfile.TemporaryDirectory()
    d["lock_path"] = os.path.join(tmp.name, "locks.json")
    for w_pts, want in ((50.0, ["  UTIL W                       50.0 (lock)        50.0      50.0   0.0  \n",
                                "  UTIL A                       60.0 (final game)   60.0",
                                "counted 390.0 | policy 395.0", "largest leak C +5.0", "(policy: B)", "1 via lock(s)"]),
                        (42.0, ["locked below line 43.", "counted 382.0 | policy 385.0"])):
        sc = dict(scores, w={tue: w_pts})
        rows = [{"player_id": p, "date": day.isoformat(), "stats": {"sp": 30, "pts": fp}} for p, g in sc.items() for day, fp in g.items()]
        with open(d["lock_path"], "w") as f:
            json.dump({"w": w_pts}, f)
        out = io.StringIO()
        with patch(__name__ + ".fetch", return_value=rows), patch("draft.get", side_effect=OSError("offline")), contextlib.redirect_stdout(out):
            cmd_review(d, argparse.Namespace(week=1))
        for line in want:
            assert line in out.getvalue(), (line, out.getvalue())
    tmp.cleanup()


def matchup_fixture():
    """lock_fixture plus an opponent (roster 1): O0-O8 copy our starters' positions, NBA teams and FP/g (no bench), so
    the two teams start the week about even; live week 1 with no points yet."""
    dd = lock_fixture()
    ours = dd["rosters"][0]["starters"]
    opp = [f"o{k}" for k in range(len(ours))]
    for o, p in zip(opp, ours):
        dd["pool"][o] = dict(dd["pool"][p], full_name=o.upper())
        dd["vals"][o] = dd["vals"][p]
    dd["rosters"].append({"roster_id": 1, "players": opp, "starters": opp, "reserve": []})
    dd.update(team={MY_ROSTER: "Us", 1: "Them"}, league={"league_id": "L", "season": "2026", "settings": {"playoff_week_start": 21}},
              state={"week": 1})
    ms = [{"roster_id": r["roster_id"], "matchup_id": 1, "points": 0, "starters": r["starters"],
           "starters_points": [0.0] * len(SLOTS)} for r in dd["rosters"]]
    return dd, ms


def test_matchup_lines():
    """Matchup lines (fb-gm-private#9's backtested rule): P(win H2H) + P(beat median) decides a lock, and recorded opponent
    locks set the opponent's state."""
    from unittest.mock import patch
    # slot_rest's second moment is stop_moments' over the same rolls.
    dd = lock_fixture()
    w = week_context(dd)
    v, fills, m2 = slot_rest(w, 8, dd["today"], moments=True)
    want = stop_moments([[(w["fpg"][p], w["games"][p][day])] for day, p in fills])
    assert abs(v - want[0]) < 1e-9 and abs(m2 - want[1]) < 1e-9 and (v, fills) == slot_rest(w, 8, dd["today"])
    # The median game: even with nine equal teams, a sure thing above all, and none with no other teams.
    assert abs(p_beat_median((100, 400), [(100, 400)] * 9) - 0.5) < 0.02 and p_beat_median((200, 1), [(100, 1)] * 9) > 0.99
    assert win_parts((100, 0), None, None) == (None, None)
    # A favourite locks below the EV line, an underdog waits above it; even, or already decided, the EV line stands.
    wait = (45.0, 100.0)

    def line(opp, league, late):
        v = 0.0 if late else 144.0
        ov = (2 if late else 9) * 144.0
        mc = dict(mine=[(45.0, v)] * 7 + [(45.0, 144.0), (0.0, 0.0)], opp=(opp, ov), others=[(opp, ov)] + [(league, ov)] * 8)
        return win_line(mc, 8, wait)
    assert abs(line(405, 405, True)[0] - 45.0) < 0.05
    assert line(380, 380, True)[0] < 43 and line(430, 430, True)[0] > 47, (line(380, 380, True)[0], line(430, 430, True)[0])
    assert line(380, 380, False)[0] < 45 < line(430, 430, False)[0]  # smaller shifts while every slot is still open
    assert abs(line(330, 330, True)[0] - 45.0) < 1e-9 and abs(line(480, 480, True)[0] - 45.0) < 1e-9  # decided: points
    x, lock_odds, wait_odds = line(430, 430, True)
    u = lambda o: o["h2h"] + o["med"]
    assert u(lock_odds(x + 0.01)) >= u(wait_odds) - WIN_EPS > u(lock_odds(x - 0.01))  # the band's edge above the EV line
    # Live: Sleeper's matchup sets the states; off the live week, or with --ev, the EV lines stand.
    dd, ms = matchup_fixture()
    w = week_context(dd)
    assert matchup_context(dd, w) == (None, "not the live week (--date/--week dry run)")
    with patch.dict(CLOCK, now=datetime.datetime(2026, 10, 20, 12)), patch("draft.get", return_value=ms), \
            patch(__name__ + ".fetch", return_value=[]), \
            tempfile.TemporaryDirectory() as tmp:
        dd["lock_path"] = os.path.join(tmp, "locks.json")
        mc, why = matchup_context(dd, w)
        assert mc and abs(mc["opp"][0] - sum(m for m, _ in mc["mine"])) < 2 and mc["opp_locked"] == []  # our bench B: +1
        assert len(mc["others"]) == 1  # two teams: the median game is the H2H game again
        ev = slot_rest(w, 0, dd["today"], "s0")[0]
        assert abs(slot_line(mc, 0, *slot_rest(w, 0, dd["today"], "s0", moments=True)[::2]) - ev) < 0.5  # even: EV
        args = lambda player, score=None, commit=False, ev=False: argparse.Namespace(
            player=player, score=score, commit=commit, uncommit=False, locked=None, slot_of=None, game=None, remaining=None,
            play=None, ev=ev)
        # Record the opponent's locks (any team's player resolves): three big scores make us the underdog.
        for o in ("O0", "O1", "O2"):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                cmd_lock(dd, args(o, 75.0, commit=True))
        assert "(Them) at 75.0" in out.getvalue() and "other teams: O0 75.0, O1 75.0, O2 75.0" in out.getvalue(), out.getvalue()
        assert saved_locks(dd) == {"o0": 75.0, "o1": 75.0, "o2": 75.0} and locked_pids(dd, None) == []
        legacy = dict(dd, lock_path=os.path.join(tmp, "legacy.json"))
        with open(legacy["lock_path"], "w") as f:
            json.dump({"s0": 55.0}, f)  # an older record: a bare score is ours, slot unknown
        with contextlib.redirect_stdout(io.StringIO()):
            cmd_lock(legacy, args("O0", 75.0, commit=True))
        assert json.load(open(legacy["lock_path"])) == {"s0": [55.0, MY_ROSTER], "o0": [75.0, 1, 0]}
        assert saved_locks(legacy) == {"s0": 55.0, "o0": 75.0} and kept_locks(legacy) == {}
        for raw, why in (("S", "Owner players"), ("O", "players on other teams"), ("Q", "no rostered player")):
            try:
                find_rostered(dd, raw)
            except SystemExit as e:
                assert why in str(e), e
            else:
                raise AssertionError(raw)
        # An exact name on another team beats a substring of ours (and an exact name of ours beats theirs).
        jr = dict(dd, pool={**dd["pool"], "b": dict(dd["pool"]["b"], full_name="Jalen Smithson"),
                            "o8": dict(dd["pool"]["o8"], full_name="Jalen Smith")})
        assert find_rostered(jr, "Jalen Smith")[0] == "o8" and find_rostered(jr, "Jalen Smithson")[0] == "b"
        assert find_rostered(jr, "len Smi")[0] == "b"  # no exact match anywhere: ours first among substrings
        tie = dict(jr, pool={**jr["pool"], "b": dict(jr["pool"]["b"], full_name="Jalen Smith Jr.")})
        assert find_rostered(tie, "Jalen Smith")[0] == "b"  # norm drops suffixes: a true tie, and ours wins it
        # An opponent's player off their starting slots can't carry a lock; an opponent record can be undone.
        benched = dict(dd, rosters=[dd["rosters"][0], dict(dd["rosters"][1], players=dd["rosters"][1]["players"] + ["o9"])],
                       pool={**dd["pool"], "o9": dict(dd["pool"]["o8"], full_name="O9")})
        try:
            cmd_lock(benched, args("O9", 50.0, commit=True))
        except SystemExit as e:
            assert "isn't in a starting slot" in str(e), e
        else:
            raise AssertionError("bench lock recorded")
        with contextlib.redirect_stdout(io.StringIO()):
            cmd_lock(dd, args("O2", 75.0, commit=True))  # re-recording replaces, not duplicates
        assert json.load(open(dd["lock_path"]))["o2"] == [75.0, 1, 2]  # score, roster that locked, slot
        # A record follows the team that locked: once his player is ours, it is no longer anyone's current lock.
        theirs = [p for p in dd["rosters"][1]["players"] if p != "o2"]
        moved = dict(dd, rosters=[dict(dd["rosters"][0], players=dd["rosters"][0]["players"] + ["o2"]),
                                  dict(dd["rosters"][1], players=theirs, starters=[p if p != "o2" else "0" for p in dd["rosters"][1]["starters"]])])
        assert "o2" not in saved_locks(moved) and locked_pids(moved, None) == [] and "o2" in all_locks(dd)[1]
        # ...but the team that locked him keeps the score in that slot (regression: it lost it after a trade).
        assert kept_locks(moved) == {1: {2: 75.0}} and kept_locks(dd) == {}
        opp_w = week_context(moved, True, 1)
        assert slot_states(dict(moved, kept_locks=kept_locks(moved)), opp_w, {})[2] == (75.0, 0.0)
        with patch("draft.get", return_value=ms):
            gone, kept = matchup_context(dict(moved, lock_path=None), w)[0], matchup_context(moved, w)[0]
        assert kept["opp"][0] > gone["opp"][0] + 30, (kept["opp"], gone["opp"])
        mc, _ = matchup_context(dd, w)
        assert mc["opp_locked"] == ["o0", "o1", "o2"] and mc["opp"][0] > sum(m for m, _ in mc["mine"])
        cont, _, m2 = slot_rest(w, 0, dd["today"], "s0", moments=True)
        under = slot_line(mc, 0, cont, m2)
        assert under > cont + 0.3, (under, cont)
        score = (under + cont) / 2  # above the EV line, below the matchup line: the matchup decides WAIT
        with contextlib.redirect_stdout(io.StringIO()) as out:
            cmd_lock(dd, args("S0", score))
        text = out.getvalue()
        assert "Matchup lines vs Them" in text and "opponent locks recorded: 3 of 9" in text, text
        assert f"→ WAIT (matchup line {under:.1f}; EV slot wait value {cont:.1f}" in text and "matchup odds: lock" in text, text
        with contextlib.redirect_stdout(io.StringIO()) as out:
            cmd_lock(dd, args("S0", score, ev=True))
        assert "→ LOCK (slot wait value" in out.getvalue() and "Matchup lines" not in out.getvalue(), out.getvalue()
        # week prints the matchup line beside the EV one; matchup shows the recorded locks.
        with contextlib.redirect_stdout(io.StringIO()) as out:
            cmd_week(dict(dd, locked=[]), argparse.Namespace(locked=None, ev=False))
        assert f"S0 (PG) ≥ {under:.1f} (EV {cont:.1f})" in out.getvalue(), out.getvalue()
        with contextlib.redirect_stdout(io.StringIO()) as out:
            cmd_matchup(dd, argparse.Namespace(week=None))
        assert "LOCKED 75.0" in out.getvalue() and "Opponent locks recorded: 3 of 9" in out.getvalue(), out.getvalue()
        # Pending calls use the same lines: S0's starter score on its own line, bench B's (fed into A's slot) jointly.
        fed = dict(dd, rosters=[dict(dd["rosters"][0], starters=dd["rosters"][0]["starters"][:8] + ["b"]), dd["rosters"][1]])
        with patch(__name__ + ".box_scores", return_value={"s0": {dd["today"]: score}, "b": {dd["today"]: 20.0}}), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            cmd_lock(fed, args(None))
        text = out.getvalue()
        assert f"S0: {score:.1f} FP → WAIT (matchup line {under:.1f}" in text and "B: 20.0 FP → WAIT (slot line" in text, text
        # Tonight's tipped roll is the slot's reported score, not a roll still to come (regression: S1's state counted a
        # phantom extra roll today, overstating our other slots on every lock night).
        cont1 = slot_rest(w, 1, dd["today"], "s1")[0]
        played = [dict(m, starters_points=[0.0, x] + [0.0] * 7) if m["roster_id"] == MY_ROSTER else m
                  for m in ms for x in [20.0]]
        posted = {"s1": {dd["today"]: 20.0}}
        with patch.dict(CLOCK, tips={(dd["today"], "Ts1"): datetime.datetime(2026, 10, 20, 0)}), \
                patch("draft.get", return_value=played), patch(__name__ + ".box_scores", return_value=posted):
            low = matchup_context(dd, w)[0]["mine"][1]
            played[0]["starters_points"][1] = cont1 + 5
            posted["s1"][dd["today"]] = cont1 + 5
            high = matchup_context(dd, w)[0]["mine"][1]
        assert abs(low[0] - cont1) < 1e-9 and low[1] > 0 and high == (cont1 + 5, 0.0), (low, high, cont1)
        assert matchup_context(dd, w)[0]["mine"][1][0] > cont1 + 1  # untipped: tonight's roll is still to come
        played[0]["starters_points"][1] = 20.0
        with patch("draft.get", return_value=played):
            untipped = matchup_context(dd, w)[0]["mine"][1]
            with patch.dict(CLOCK, tips={(dd["today"], "Ts1"): datetime.datetime(2026, 10, 20, 10)}):
                live = matchup_context(dd, w)[0]["mine"][1]  # tipped 2 h ago: in progress, its 20 so far isn't final
        assert live == untipped and live[0] > cont1 + 1 and live[1] > 0, (live, cont1)
        # A row judged on another lineup gets the matchup state rebuilt in that lineup's context.
        w_sb = week_context(dd, sleeper_base=True)
        assert matchup_in(mc, w_sb)["mine"] == slot_states(mc["dd"], w_sb, mc["reported"]) and matchup_in(None, w_sb) is None
        # A bye week: median only, and no opponent locks to ask for.
        bye = [dict(m, matchup_id=None) for m in ms]
        with patch("draft.get", return_value=bye), contextlib.redirect_stdout(io.StringIO()) as out:
            mc = matchup_for(dd, w, argparse.Namespace(ev=False))
        assert mc["opp"] is None and "vs BYE (P(beat median), every team's current state)" in out.getvalue(), out.getvalue()
        assert slot_line(mc, 0, cont, m2) > 0
        with patch("draft.get", return_value=bye), patch.dict(dd, week=21, state={"week": 21}):
            assert matchup_context(dd, w) == (None, "no opponent this week")  # playoffs: no median game either
    # Off the live week the output is --ev's plus one NOTE line, so the EV calls are unchanged.
    with contextlib.redirect_stdout(io.StringIO()) as dry, patch("draft.get", return_value=ms):
        cmd_lock(dd, args("S0", score))
    with contextlib.redirect_stdout(io.StringIO()) as ev_out:
        cmd_lock(dd, args("S0", score, ev=True))
    lines = dry.getvalue().splitlines()
    assert [x for x in lines if not x.startswith("NOTE: matchup lines unavailable")] == ev_out.getvalue().splitlines()
    assert len(lines) == len(ev_out.getvalue().splitlines()) + 1
    # Sleeper's matchup failing leaves the EV lines, with a NOTE.
    with patch.dict(CLOCK, now=datetime.datetime(2026, 10, 20, 12)), patch("draft.get", side_effect=OSError("down")):
        assert matchup_context(dd, w)[0] is None
        with contextlib.redirect_stdout(io.StringIO()) as out:
            assert matchup_for(dd, w, argparse.Namespace(ev=False)) is None
        assert "matchup lines unavailable (Sleeper matchup unavailable (down))" in out.getvalue()


def test():
    from unittest.mock import patch
    with patch(__name__ + ".fetch", side_effect=OSError("tests run offline")):  # a test that needs data patches fetch
        run_tests()


def run_tests():
    test_review()
    test_review_pooled()
    test_matchup_lines()
    test_reuse()
    test_tip_clock()
    test_lock_commits()
    test_pending_states()
    test_lineup_eligibility()
    test_posted_swap()
    test_whole_team()
    test_lock_continuations()
    test_pooled_locks()
    test_fa_waivers()
    assert SCORING is rb.SCORING and len(SCORING) == 11  # regression: gm.py once kept its own copy (issue #7)
    cfg = {"league_id": "L", "user_id": "u4"}
    league = {"league_id": "L", "sport": "nba", "roster_positions": list(ROSTER_POSITIONS),
              "scoring_settings": dict(SCORING, dd=0.0, bonus_pt_40p=0.0),
              "settings": {"reserve_allow_out": 1, "reserve_slots": 1}}
    rosters = [{"roster_id": 4, "owner_id": "u4", "players": [], "starters": []}]
    assert validate(cfg, league, rosters) == []
    for broken in (dict(league, scoring_settings=dict(SCORING, to=-1.0)),
                   dict(league, roster_positions=ROSTER_POSITIONS[:-1]),
                   dict(league, settings={"reserve_allow_out": 0, "reserve_slots": 1}),
                   dict(league, settings={"reserve_allow_out": 1, "reserve_slots": 2}),
                   dict(league, sport="nfl"), None):
        assert validate(cfg, broken, rosters), broken
    assert validate(cfg, league, [{"roster_id": 4, "owner_id": "x"}]) and validate(cfg, league, [])
    assert validate(cfg, league, [{"roster_id": 4, "owner_id": "x", "co_owners": ["u4"]}]) == []
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            refuse(validate(cfg, dict(league, sport="nfl"), rosters))
    except SystemExit as e:
        assert str(e.code).startswith("REFUSING:") and e.code != 0
    else:
        raise AssertionError("validation mismatch did not refuse")

    # Lock math: q = 0 is rebuild_board.lock_values (1-left threshold = mean); thresholds rise with games left.
    for ppg in (30, 48.5, 73.9):
        assert all(abs(stop_value([[(ppg, 1.0)]] * k) - rb.lock_values(ppg, 5)[k]) < 1e-9 for k in range(6))
        t = thresholds(ppg)
        assert abs(t[0] - (1 - Q_DNP) * ppg) < 0.5 and all(x < y for x, y in zip(t, t[1:])), t
        assert all(x < y for x, y in zip(thresholds(ppg, 0.12), thresholds(ppg)))  # B2B risk lowers the wait value
        t0 = thresholds(ppg, 0.0)
        assert abs(t0[0] - ppg) < 0.5 and all(abs(x - y) < 1e-9 for x, y in zip(t0, rb.lock_values(ppg, 5)[1:]))
    # Backtest oracle (2025-26 logs): lock thresholds as a multiple of FP/g with 1-4 games left at q = 0.08.
    for ppg, want in ((30, (0.92, 1.13, 1.24, 1.32)), (50, (0.92, 1.08, 1.17, 1.22)), (75, (0.92, 1.04, 1.11, 1.15))):
        got = [x / ppg for x in thresholds(ppg)[:4]]
        assert all(abs(g - w) <= 0.01 for g, w in zip(got, want)), (ppg, got)
    d0 = datetime.date(2026, 10, 24)
    assert play_on(d0, {d0 - datetime.timedelta(1)}) == 1 - Q_B2B and play_on(d0, {d0 - datetime.timedelta(2)}) == 1 - Q_DNP
    assert "→ LOCK (wait value" in lock_report("A", 50, 48.5, [0.92])[0]
    assert "WAIT" in lock_report("A", 46, 48.5, [1.0])[0] and "LOCK" in lock_report("A", 46, 48.5, [0.92])[0]
    assert "LOCK" in lock_report("A", 10, 48.5, [])[0]
    # Slot options on a day only a feeder plays (regression: KeyError on the starter's play chance).
    d1, d2, d3 = (datetime.date(2026, 10, 20) + datetime.timedelta(i) for i in range(3))
    opts = slot_options([d1, d2, d3], {d1: 0.92, d3: 0.92}, 40, [(35, play_map({d2, d3}))])
    assert opts == [[(40, 0.92)], [(35, 1 - Q_DNP)], [(40, 0.92), (35, 1 - Q_B2B)]], opts
    alone = stop_value([[(40, 1.0)], [], [(40, 1.0)]])
    fed = stop_value([[(40, 1.0)], [(35, 1.0)], [(40, 1.0)]])
    assert fed > alone and abs(alone - thresholds(40, 0.0)[1]) < 1e-9

    # Lock judges the slot, not the player (regression: a bench player rotated into a starter's slot was
    # called LOCK on his own games while the starter refills the slot; week's lock line said WAIT).
    dd = lock_fixture()
    a_slot = len(SLOTS) - 1
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        cmd_week(dd, argparse.Namespace(locked=None))
    w = week_context(dd, sleeper_base=True)
    assert w["plan"][dd["today"]] == {a_slot: "b"}, w["plan"]
    want = slot_rest(w, a_slot, dd["today"])[0]
    assert f"B (UTIL for A) ≥ {want:.1f}" in out.getvalue(), out.getvalue()
    for anchor in ("a", None):  # --slot-of A, or inferred from week's plan
        slot = lock_slot(dd, "b", anchor, dd["today"])
        assert slot[0] == want and slot[2] >= want, slot
        lines = lock_report("B", 36, 30, [0.92], slot)
        assert "→ WAIT (slot wait value" in lines[0] and "LOCK" in lock_report("B", 36, 30, [0.92])[0], lines
    assert lock_slot(dd, "b", None, dd["today"] + datetime.timedelta(1)) is None  # not fed that day: no slot
    # The plan feeds B into an empty Sleeper slot ("0") (regression: TypeError naming the slot's missing starter).
    # Week's base starts A there, so lock judges the slot as week does; with A Out, B joins week's base instead,
    # isn't fed, and lock falls back to Sleeper's lineup and its plan.
    for tag, slot_name in (("", "UTIL for A"), ("Out", "UTIL for empty slot")):
        dd = lock_fixture()
        dd["rosters"][0]["starters"][-1], dd["pool"]["a"]["injury_status"] = "0", tag
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cmd_lock(dd, argparse.Namespace(player="B", score=40, locked=None, slot_of=None, game=None, remaining=None, play=None))
        assert "(slot wait value" in out.getvalue() and slot_name in out.getvalue(), out.getvalue()
    # --locked fixes only the locked slot; the rest is re-optimized (regression: any lock pinned Sleeper's lineup).
    dd = lock_fixture()
    dd["vals"]["b"], dd["locked"] = (10.0, 60.0), locked_pids(dd, "S0")
    w = week_context(dd)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        cmd_week(dd, argparse.Namespace(locked="S0"))
    assert "  start B (" in out.getvalue(), out.getvalue()  # regression: bench-to-start changes were never listed
    assert w["base"][0] == "s0" and w["blocked"] == {0} and "b" in w["base"].values() and "a" not in w["base"].values(), w["base"]
    # Week's base benches Sleeper starter A for B: lock A's score judges his Sleeper slot on week's base, as the joint
    # pending call does (regression #12: lock fell back to Sleeper's lineup, where the plan feeds B elsewhere on day 3).
    dd = lock_fixture()
    d2, d3 = dd["today"] + datetime.timedelta(1), dd["today"] + datetime.timedelta(2)
    dd["vals"].update(a=(10.0, 20.0), b=(10.0, 60.0))
    dd["today"] = d2
    dd["sched"] = [g for g in dd["sched"] if (g["home"]["team"], g["date"]) != ("Ts6", d3.isoformat())]
    w = week_context(dd)
    assert w["base"][a_slot] == "b" and "a" not in w["base"].values(), w["base"]
    want = lanes_after(w, d2, {a_slot: "a"})[a_slot][1:3]
    slot = lock_slot(dd, "a", "a", d2)
    assert (slot[0], slot[3]) == want and want[1] == [(d3, "b")], (slot, want)
    assert want[0] > slot_rest(week_context(dd, sleeper_base=True), a_slot, d2, "a")[0] + 5  # the bases really differ
    # An adopted base keeps every starter in his Sleeper slot when legal and prints every changed slot, and lock
    # judges a slot on that base (regression: fill_slots reshuffled eight starters, week listed only "start B",
    # and lock judged S0's slot on Sleeper's lineup, where bench B feeds it Thursday: a higher line than week's).
    dd = lock_fixture()
    dd["pool"]["b"]["fantasy_positions"], dd["vals"]["b"] = ["PG"], (10.0, 60.0)
    dd["rosters"][0]["players"] = ["b"] + dd["rosters"][0]["starters"]
    d1 = dd["today"]
    dd["sched"] = [g for g in dd["sched"] if (g["home"]["team"], g["date"]) != ("Ts0", (d1 + datetime.timedelta(2)).isoformat())]
    w = week_context(dd)
    assert w["base"] == {**dict(enumerate(dd["rosters"][0]["starters"])), a_slot: "b"}, w["base"]
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        cmd_week(dd, argparse.Namespace(locked=None))
    moves = [x for x in out.getvalue().split("make all of them):\n")[1].split("Rotation plan")[0].splitlines()]
    assert moves == [f"  start B ({w['exp']['b']:.1f}) at UTIL (for A)"], out.getvalue()
    want = slot_rest(w, 0, d1)[0]
    assert f"S0 (PG) ≥ {want:.1f}" in out.getvalue() and lock_slot(dd, "s0", "s0", d1)[0] == want, out.getvalue()
    assert want < slot_rest(week_context(dd, sleeper_base=True), 0, d1)[0] - 0.5  # the bases really differ for this slot
    # The last day says its gains assume earlier unlocked scores are below their lock lines (regression: a bench
    # swap for a starter whose Saturday score stood read as a pure gain).
    assert "NOTE: last day" not in out.getvalue(), out.getvalue()
    dd["today"] = datetime.date(2026, 10, 25)
    with contextlib.redirect_stdout(io.StringIO()) as out:
        cmd_week(dd, argparse.Namespace(locked=None))
    assert "NOTE: last day: the gains above assume every earlier unlocked score is below its lock line" in out.getvalue(), out.getvalue()
    # An Out starter's slot takes feeds on his game days (regression: his scheduled game blocked them), and so does
    # an active-roster IR/Sus/DNR one (regression: valued as healthy at 0.92).
    for tag in ("Out", "IR", "Sus", "DNR"):
        dd = lock_fixture()
        dd["pool"]["a"]["injury_status"] = tag
        w, d3 = week_context(dd, sleeper_base=True), dd["today"] + datetime.timedelta(2)
        assert w["fpg"]["a"] == 0 and w["plan"][d3] == {a_slot: "b"}, (tag, w["plan"])
        assert slot_rest(w, a_slot, dd["today"])[1] == [(d3, "b")] and play_note(tag, {}, d3) == f"play 0 all week ({tag})"
    # DTD lowers his next game's play chance, later games partly recover; untagged and past games unchanged
    # (regression: Sleeper's most common tag was ignored, so a questionable starter counted as a 92% play).
    dt = lock_fixture()
    tue, wed, thu = dt["today"], dt["today"] + datetime.timedelta(1), dt["today"] + datetime.timedelta(2)
    assert play_map({tue, wed, thu}) == {tue: 1 - Q_DNP, wed: 1 - Q_B2B, thu: 1 - Q_B2B}
    assert play_map({tue, wed, thu}, "DTD", wed) == {tue: 1 - Q_DNP, wed: P_DTD[0], thu: P_DTD[1]}
    # Sleeper's GTD gets the DTD discount everywhere (regression: only "DTD" was checked, so GTD counted as 0.92).
    assert play_map({tue, wed, thu}, "GTD", wed) == play_map({tue, wed, thu}, "DTD", wed)
    assert dtd_free({"pool": {"a": {"injury_status": "GTD"}}})["pool"]["a"]["injury_status"] == ""
    base_exp, base_team = week_context(dt)["exp"]["a"], team_score(dt, MY_ROSTER, {}, False)[0]
    dt["pool"]["a"]["injury_status"] = "DTD"
    w = week_context(dt)
    assert w["games"]["a"] == {wed: P_DTD[0], thu: P_DTD[1]} and w["exp"]["a"] < base_exp - 5, w["exp"]
    assert team_score(dt, MY_ROSTER, {}, False)[0] < base_team, "team score ignores DTD"
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        cmd_week(dt, argparse.Namespace(locked=None))
    assert "Play chance used for tagged players: A [DTD] play Wed 0.50 Thu 0.75" in out.getvalue(), out.getvalue()
    assert play_note("Out", {}, tue) == "play 0 all week (Out)" and play_note("", {wed: 0.5}, tue) == ""
    # Official injury report (words laid out as the Oct 20 2026 PDF): columns from the header, a game date carries
    # down and across pages, wrapped reasons and NOT YET SUBMITTED rows add nothing, "Last Jr., First" reorders.
    hdr = [(480, x, w) for x, w in ((23, "Game"), (53, "Date"), (200, "Matchup"), (425, "Player"), (457, "Name"),
                                    (586, "Current"), (624, "Status"), (666, "Reason"))]
    p1 = hdr + [(533, 288, "Injury"), (459, 24, "10/20/2026"), (459, 201, "BOS@DET"), (459, 426, "Carter,"), (459, 456, "Devin"),
                (459, 587, "Out"), (459, 667, "Illness"), (436, 426, "Jackson"), (436, 460, "Jr.,"), (436, 480, "Jaren"),
                (436, 587, "Questionable"), (429, 667, "Tear")]
    p2 = [(505, 426, "Fall,Tacko"), (505, 587, "Doubtful"), (482, 24, "10/21/2026"), (482, 265, "Atlanta"),
          (482, 667, "NOT"), (459, 426, "Young,"), (459, 460, "Trae"), (459, 587, "Probable")]
    assert report_rows([p1, p2]) == [("2026-10-20", "Devin Carter", "Out"), ("2026-10-20", "Jaren Jackson Jr.", "Questionable"),
                                     ("2026-10-20", "Tacko Fall", "Doubtful"), ("2026-10-21", "Trae Young", "Probable")]
    # A listed game takes the report's chance over DTD (capped at a regular's); unlisted games keep the tag, and the
    # printed chances cite the report or say they come from the Sleeper tag.
    try:
        REPORT.update(at="10/20 10:45 ET", pids={"a": {wed: "Probable", thu: "Available"}, "x": {wed: "Out"}, "y": {thu: "Available"}})
        assert play_map({tue, wed, thu}, "DTD", wed, "a") == {tue: 1 - Q_DNP, wed: 0.75, thu: 1 - Q_B2B}
        assert play_note("", play_map({wed}, "", wed, "x"), wed, "x") == "play Wed 0.00 Out (NBA report 10/20 10:45 ET)"
        assert play_note("DTD", play_map({thu}, "DTD", wed, "b"), wed, "b") == "play Thu 0.50 (Sleeper tag; not on NBA report 10/20 10:45 ET)"
        assert play_note("", play_map({thu}, "", wed, "y"), wed, "y") == ""  # listed Available only: no note
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cmd_week(dt, argparse.Namespace(locked=None))
        assert "A [DTD] play Wed 0.75 Probable Thu 0.88 Available (NBA report 10/20 10:45 ET)" in out.getvalue(), out.getvalue()
    finally:
        REPORT.update(at="", pids={})
    # A finished Wednesday game must not consume the next-game DTD discount.
    dt["today"] = wed
    args = argparse.Namespace(locked=None, player="A", score=25.0, slot_of=None,
                              game=wed, remaining=None, play=None)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        cmd_lock(dt, args)
    # His own DTD-adjusted wait is still 20, but healthy B's Thursday roll is now a legal alternative.
    assert "A: 25.0 FP → WAIT (slot wait value 27.7:" in out.getvalue(), out.getvalue()
    assert "his own games only:" in out.getvalue() and "wait value 20.0" in out.getvalue(), out.getvalue()
    assert "Plays used: 0.50" in out.getvalue(), out.getvalue()
    # --remaining keeps his status-aware play chances (regression: it used a flat 0.92 while printing the DTD rates).
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        cmd_lock(dt, argparse.Namespace(**dict(vars(args), remaining=1)))
    assert "Plays used: 0.50 (0.92, 0.88 on a back-to-back's second night; DTD: 0.50 next game" in out.getvalue(), out.getvalue()
    dt["pool"]["a"]["injury_status"] = "GTD"
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        cmd_lock(dt, argparse.Namespace(**dict(vars(args), score=30.0)))
    assert "Plays used: 0.50 (0.92, 0.88 on a back-to-back's second night; GTD: 0.50 next game" in out.getvalue(), out.getvalue()
    assert "LOCK depends on DTD play chance" in out.getvalue(), out.getvalue()  # dtd_free and the healthy rerun see GTD too
    dt["pool"]["a"]["injury_status"] = "DTD"
    out = io.StringIO()
    original_fetch = globals()["fetch"]
    globals()["fetch"] = lambda url: [{"player_id": "a", "date": wed.isoformat(), "stats": {"sp": 1, "pts": 25}}]
    dt["league"] = {"season": "2026"}
    try:
        with contextlib.redirect_stdout(out):
            pending_locks(dt, dt["rosters"][0], week_games(dt["sched"], 1))
    finally:
        globals()["fetch"] = original_fetch
    assert "A: 25.0 FP → WAIT (slot wait value 27.7:" in out.getvalue(), out.getvalue()
    # A LOCK that only the DTD discount produces says so (regression: P_DTD's 0.50 midpoint silently decided it).
    # 30 beats the slot's DTD-discounted 27.7 (B's Thursday) but not A's undiscounted Thursday back-to-back (~35).
    flip = f"LOCK depends on DTD play chance {P_DTD[0]:.2f}: confirm news; rerun with --play 0.9 if probable"
    for score, want in ((30.0, True), (40.0, False), (25.0, False)):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cmd_lock(dt, argparse.Namespace(**dict(vars(args), score=score)))
        globals()["fetch"] = lambda url: [{"player_id": "a", "date": wed.isoformat(), "stats": {"sp": 1, "pts": score}}]
        try:
            with contextlib.redirect_stdout(out):
                pending_locks(dt, dt["rosters"][0], week_games(dt["sched"], 1))
        finally:
            globals()["fetch"] = original_fetch
        assert out.getvalue().count(flip) == (2 if want else 0), (score, out.getvalue())
    # --locked names match one Owner player each (regression: "James" locked LeBron James and James Harden).
    dd["pool"].update(s1={"full_name": "LeBron James"}, s2={"full_name": "James Harden"}, s3={"full_name": "Kevin Love"},
                      s4={"full_name": "Kevin Lovelace"})
    assert locked_pids(dd, "james harden, kevin love,s0") == ["s2", "s3", "s0"]
    for bad in ("James", "Nobody", "S0,Kev"):
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                locked_pids(dd, bad)
        except SystemExit as e:
            assert "matches" in str(e.code), e.code
        else:
            raise AssertionError(f"--locked {bad!r} was accepted")
    # --date picks the week from the schedule (regression: --date 2026-10-27 stayed in week 1 with 0 days left).
    sched2 = [{"week": w, "date": day} for w, day in ((1, "2026-10-20"), (1, "2026-10-25"), (2, "2026-10-27"))]
    assert [week_of(sched2, datetime.date(2026, 10, n)) for n in (19, 25, 26, 27)] == [1, 1, 2, 2]
    assert week_of(sched2, datetime.date(2026, 12, 1)) is None
    # The footer names the board's basis (regression: it said "frozen" after rebuild_board --blend --write).
    blended = ("# Use Sleeper positions and roster needs WITHIN tiers; no fixed center premium.\n# In-season blend: FP/g -> "
               "prior + n/(n+6.5)*(actual - prior) after n games (210 players, games through 2026-10-27); board-actuals.csv.\n")
    assert board_basis(blended, sched2) == "blended through week 2" and board_basis(blended, None) == "blended through Oct 27"
    assert board_basis(blended.split("\n")[0], sched2) == "frozen Oct 19"
    # ... and when the player tags were fetched (regression: "the daily players-*.json" hid a 9-hour-old file).
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".json") as tags:
        os.utime(tags.name, (0, datetime.datetime(2026, 10, 20, 10, 1).timestamp()))
        saved, draft.PLAYERS_PATH = draft.PLAYERS_PATH, tags.name
        try:
            with contextlib.redirect_stdout(io.StringIO()) as out:
                footer({"today": d0})
        finally:
            draft.PLAYERS_PATH = saved
    assert f"player tags from {os.path.basename(tags.name)} fetched 10/20 10:01 (refetched when 3 h old" in out.getvalue(), out.getvalue()
    # The score's game, not today, starts the count (regression: Friday's score judged on Saturday had 0 left).
    tue, fri, sat, sun = (datetime.date(2026, 10, 20) + datetime.timedelta(i) for i in (0, 3, 4, 5))
    fox = {tue, fri, sat}
    assert lock_game(fox, sat, fri) == (fri, [sat], None)
    from unittest.mock import patch
    # Regression: before Fri's tip, the default is Tue's score with Fri and Sat to come, not an unplayed Fri.
    with patch.dict(CLOCK, now=datetime.datetime(2026, 10, 23, 18), tips={(fri, "SAC"): datetime.datetime(2026, 10, 24)}):
        assert lock_game(fox, fri, team="SAC") == (tue, [fri, sat], None)
        CLOCK["now"] = datetime.datetime(2026, 10, 24, 1)
        assert lock_game(fox, fri, team="SAC") == (fri, [sat], None)
    assert lock_game(fox, sun) == (sat, [], None) and lock_game(fox, fri) == (fri, [sat], None)
    assert lock_game(fox, sat, sun)[2] and lock_game({sat}, fri)[2]

    # Win odds (regression: matchup had no P(win)): stop_moments' mean is stop_value; team_score is week's
    # with-rotation total; a reported score at or above the wait value is taken as locked.
    days3 = [[(40, 0.92)], [(35, 0.88)], [(40, 0.92)]]
    m, m2 = stop_moments(days3)
    assert abs(m - stop_value(days3)) < 1e-9 and m2 > m * m
    xs = draws(40)
    assert abs(stop_moments([[(40, 0.9)]])[1] - 0.9 * sum(x * x for x in xs) / len(xs)) < 1e-9
    dd = lock_fixture()
    w = week_context(dd)
    rot = sum(stop_value(slot_days(w["left"], s, {day: w["plan"][day][i] for day in w["left"] if i in w["plan"][day]},
                                   w["games"], w["fpg"])) for i, s in w["base"].items())
    mean, var = team_score(dd, MY_ROSTER, {}, False)
    assert abs(mean - rot) < 1e-9 and var > 0, (mean, rot)
    mean2, var2 = team_score(dd, MY_ROSTER, {"s0": 500.0}, True)
    assert mean2 > mean + 400 and var2 < var, (mean2, var2)
    assert win_odds({4: (100, 0), 1: (90, 0), 2: (80, 0)}, 4, 1) == (1.0, 1.0)
    assert win_odds({4: (80, 0), 1: (90, 0), 2: (100, 0)}, 4, None, median=False) == (None, None)
    h, md = win_odds({r: (100, 400) for r in range(1, 11)}, 4, 1)
    assert abs(h - 0.5) < 0.05 and abs(md - 0.5) < 0.05, (h, md)
    h, md = win_odds({**{r: (100, 400) for r in range(1, 11)}, 4: (130, 400)}, 4, 1)
    assert 0.8 < h < 0.9 and md > 0.9, (h, md)  # +30 at sd 20 each: Φ(30/28.3) = 0.86
    # matchup's header number is labelled as the no-rotation best 9 (regression: it read as the table's total).
    dd = dict(lock_fixture(), league={"league_id": "L", "season": "2026", "settings": {"playoff_week_start": 21}})
    with patch("draft.get", return_value=[{"roster_id": MY_ROSTER, "matchup_id": None, "points": 0}]), \
            contextlib.redirect_stdout(io.StringIO()) as out:
        cmd_matchup(dd, argparse.Namespace())
    assert "expected locked with games left " in out.getvalue() and "(best 9, no rotation)" in out.getvalue(), out.getvalue()

    # Lineup and rotation: exact best lineup, bench feeds only idle-starter days, one slot per player per day.
    pos = {"pg": ["PG"], "pg2": ["PG"], "sg": ["SG"], "c": ["C"], "c2": ["C"], "f": ["SF", "PF"]}
    val = {"pg": 50, "pg2": 10, "sg": 30, "c": 60, "c2": 20, "f": 5}
    lineup = best_lineup(list(pos.items()), val, ["PG", "SG", "C", "UTIL"])
    assert sorted(lineup.values()) == ["c", "c2", "pg", "sg"], lineup
    d1, d2 = datetime.date(2026, 10, 20), datetime.date(2026, 10, 21)
    base = {0: "pg", 1: "sg", 2: "c"}
    games = {p: play_map(ds) for p, ds in {"pg": {d2}, "sg": {d1, d2}, "c": {d2}, "pg2": {d1}, "c2": {d1}, "f": {d1}}.items()}
    o = {"pg": 50, "sg": 30, "c": 60, "pg2": 30, "c2": 20, "f": 5}
    plan = rotation(["PG", "SG", "C", "UTIL"], base, ["c2", "pg2", "f"], games, [d1, d2], pos, o)
    # pg2's roll is worth most in the empty UTIL. c2 (20/g) can't beat c's wait value, but it still sits at idle C, since a
    # bench score can close a cheaper slot (issue #26); f (SF/PF) fits no idle slot.
    assert plan[d1] == {3: "pg2", 2: "c2"}, plan
    assert plan[d2] == {}, plan  # every bench player is idle on d2
    assert rotation(["PG", "SG", "C", "UTIL"], base, ["c2", "pg2", "f"], games, [d1, d2], pos, o, blocked={3})[d1] == {0: "pg2", 2: "c2"}
    # A bench player ruled out (play 0) is never seated.
    out_c2 = dict(games, c2={d1: 0.0})
    assert rotation(["PG", "SG", "C", "UTIL"], base, ["c2", "pg2", "f"], out_c2, [d1, d2], pos, o)[d1] == {3: "pg2"}
    # The weakest idle starter's slot gets the extra roll (the Edgecombe-into-Allen's-UTIL case).
    two = rotation(["PG", "UTIL"], {0: "pg", 1: "c"}, ["pg2"], games, [d1, d2], pos, {"pg": 50, "c": 35, "pg2": 30})
    assert two[d1] == {1: "pg2"}, two
    feeds = {d1: "pg2"}
    assert stop_value(slot_days([d1, d2], "pg", feeds, games, o)) > stop_value(slot_days([d1, d2], "pg", {}, games, o))

    # FA diff: rostered, excluded, unprojected and teamless players are skipped; drop is our lowest V.
    pool = {str(i): {"full_name": f"P{i}", "active": True, "team": "BOS", "fantasy_positions": ["C" if i % 2 else "PG"]}
            for i in range(1, 7)}
    pool["5"]["team"] = None
    board = ["1", "2", "3", "4", "5", "6"]
    notes = {"1": "T1 | V+20.0/wk | 45.0/g | ECR 9 | 61 GP | season 2745 FP", "2": "T2 | V+9.0/wk | 35.0/g", "3": "DO NOT DRAFT | Waived",
             "4": "NO PROJECTION | ECR ?", "5": "T3 | V+5.0/wk | 30.0/g", "6": "T3 | V+4.0/wk | 31.0/g"}
    vals = board_values(notes)
    assert set(vals) == {"1", "2", "5", "6"} and vals["1"] == (20.0, 45.0)
    assert board_values({"j": "T1 | V+40.2/wk | 73.9/g | ECR 1 | 10 G 40.0/g -> 53.4/g | 70 GP"})["j"] == (40.2, 53.4)
    # The calibrated FP/g behind V beats the raw projection (regression: lock math used Banchero's raw 47.6, not 49.1).
    paolo = "T7 | V+22.6/wk | 47.6/g | cal 49.1/g | ECR 12 | 74 GP"
    assert board_values({"p": paolo})["p"] == (22.6, 49.1)
    assert board_values({"p": paolo.replace("ECR 12", "ECR 12 | 4 G 40.0/g -> 45.0/g")})["p"] == (22.6, 45.0)
    fas = free_agents(board, vals, notes, pool, {"1": 4}, None)
    assert fas == [(2, "2"), (6, "6")], fas
    assert free_agents(board, vals, notes, pool, {"1": 4}, {"PG"}) == [(2, "2"), (6, "6")]
    assert free_agents(board, vals, notes, pool, {"1": 4}, {"C"}) == []
    # Unprojected players are never the drop (regression: no board V counted as 0, so a hot pickup was "worst").
    assert drop_candidate(["1", "4", "6"], vals, pool) == "6" and drop_candidate(["4"], vals, pool) is None

    # fa beyond the board (regression: breakouts and new signings off board.txt were invisible).
    pool["7"], pool["8"] = {"full_name": "Hot Rookie", "team": "SAC", "fantasy_positions": ["SG"]}, {"full_name": "Cold"}
    pool["10"] = {"full_name": "Role Jump", "team": "UTA", "fantasy_positions": ["PF"]}
    dfa = {"pool": pool, "rosters": [{"roster_id": 4, "players": ["1"]}], "board": board, "vals": vals, "sched": [1]}
    jump = [("d", "g", 10.0, 18)] * 3 + [("e", "g", 25.0, 34)] * 3  # season 26.0 min/g, last 3 34.0: +8.0
    logs = {"7": [("d", "g", 30.0, 30)] * 3, "8": [("d", "g", 26.0, 30)] * 3, "1": jump,
            "2": [("d", "g", 60.0, 30)] * 3, "9": [("d", "g", 90.0, 30)] * 2, "10": jump,
            "6": jump[:-1] + [("e", "g", 25.0, 33.9)]}  # rostered "1" and a 7.97-minute jump stay off the radar
    lines = beyond_board(dfa, [("1", 99), ("7", 50), ("2", 40), ("4", 30)], logs, 26.9, lambda p: 3)
    assert lines[0] == "Trending adds (Sleeper, 24h): 3 of 4 are free agents here:" and "P1" not in "".join(lines), lines
    assert "not on board | 50 adds" in lines[1] and "V+9.0/wk 35.0/g | 40 adds" in lines[2] and "on board, no V" in lines[3], lines
    assert lines[4].endswith(": 1") and "Hot Rookie" in lines[5] and "30.0 FP/g in 3 G" in lines[5], lines
    assert "Minutes radar" in lines[6] and ": 1 (" in lines[6] and "Role Jump" in lines[7], lines
    assert "min 34.0 vs 26.0 | 0.67 FP/min → 22.9/g at L3 min" in lines[7], lines
    assert len(lines) == 8 and beyond_board(dfa, None, None, 26.9, lambda p: 3) == []

    # Stream: team gain via rotation, best bench drop (not the lowest V), the V+5 guard, and after-add dates
    # (regression: ΔE wk compared standalone scores, so a streamer feeding an idle slot looked worthless).
    # UTIL (A) idle Tue/Wed: bench B feeds Tue, C feeds Wed. FA F plays Tue only.
    dd = lock_fixture()
    tue, wed = dd["today"], dd["today"] + datetime.timedelta(1)
    dd["sched"] = [g for g in dd["sched"] if not (g["home"]["team"] == "Ta" and g["date"] == wed.isoformat())]
    dd["sched"] += [{"week": 1, "date": day.isoformat(), "home": {"team": "T" + p}, "away": {"team": "Z" + p}} for p, day in (("c", wed), ("f", tue))]
    dd["pool"].update({p: {"full_name": p.upper(), "team": "T" + p, "fantasy_positions": ["C"]} for p in "cf"})
    dd["vals"].update(b=(10.0, 30.0), c=(5.0, 30.0), f=(10.0, 35.0))
    dd["rosters"][0]["players"].append("c")
    (gain, fa, drop), = stream_gains(dd, ["f"], ["b", "c"], {"f": tue})
    assert fa == "f" and drop == "b" and gain > 0 and drop_candidate(["b", "c"], dd["vals"], dd["pool"]) == "c", (gain, drop)
    dd["vals"]["b"] = (15.0, 30.0)  # V/wk ≥ his 10 + 5: never dropped to stream
    assert stream_gains(dd, ["f"], ["b", "c"], {"f": tue})[0][2] == "c"
    assert stream_gains(dd, ["f"], ["b", "c"], {"f": wed})[0][0] < 0  # his Tue game no longer counts

    # A locked UTIL cannot take another roll, and its player cannot be the drop.
    dl = lock_fixture()
    dl["locked"] = ["a"]
    dl["vals"].update({f"s{i}": (30.0, 100.0) for i in range(len(SLOTS) - 1)})
    dl["pool"]["f"] = {"full_name": "F", "team": "Tf", "fantasy_positions": ["C"]}
    dl["vals"]["f"] = (11.0, 60.0)
    dl["sched"].append({"week": 1, "date": tue.isoformat(), "home": {"team": "Tf"}, "away": {"team": "Zf"}})
    assert stream_gains(dl, ["f"], ["b"], {"f": tue}) == [(0.0, "f", "b")]
    assert stream_gains(dl, ["f"], ["a"], {"f": tue}) == []

    # IR slot holding a player who is no longer IR/Sus/DNR (regression: no warning).
    assert slot_warnings("IR", "P", "Out", 1) == []
    assert any("move to IR" in x for x in slot_warnings("BN", "P", "Out", 0))
    assert any("status healthy" in x for x in slot_warnings("IR", "P", "", 1)) and slot_warnings("IR", "P", "Sus", 1) == []

    # Changes diff: transactions, roster moves and status changes, Owner first; seen transactions skipped.
    old = {"taken": "t0", "week": 1, "txns": ["x0"], "rosters": {"4": ["1", "2"], "3": ["6"]},
           "status": {"1": "", "2": "", "6": ""}}
    pool2 = {k: dict(v) for k, v in pool.items()}
    pool2["6"]["injury_status"] = "Out"
    new = snapshot([{"roster_id": 4, "players": ["1", "5"]}, {"roster_id": 3, "players": ["6", "2"]}], pool2, ["x0", "x1"], 1)
    txns = [{"transaction_id": "x0", "type": "free_agent", "adds": {"9": 3}},
            {"transaction_id": "x1", "type": "trade", "status": "complete", "adds": {"2": 3, "5": 4}, "drops": {"2": 4, "5": 3}}]
    lines = diff(old, new, txns, lambda rid: f"T{rid}", lambda p: f"P{p}")
    assert lines[0].startswith("TXN trade") and "T4 +P5 -P2" in lines[0] and "T3 +P2 -P5" in lines[0], lines
    assert "ROSTER T4: +P5 -P2" in lines and "ROSTER T3: +P2 -—" in lines, lines
    assert "STATUS P6 (T3): healthy → Out" in lines and not any("P9" in x for x in lines), lines
    assert lines.index("ROSTER T4: +P5 -P2") < lines.index("ROSTER T3: +P2 -—")

    # Standings from Sleeper's records (regression: rebuilt from reverted matchup points, they misplaced 2 teams).
    st = lambda w, l, f: {"wins": w, "losses": l, "ties": 0, "fpts": f, "fpts_decimal": 50, "fpts_against": 400}
    rows = standing_rows([{"roster_id": 1, "settings": st(0, 2, 453)}, {"roster_id": 2, "settings": st(1, 1, 474)},
                          {"roster_id": 3, "settings": st(1, 1, 438)}])
    assert rows == [(2, "1-1-0", 474.5, 400), (3, "1-1-0", 438.5, 400), (1, "0-2-0", 453.5, 400)], rows
    assert game_fp({"pts": 20, "reb": 10, "ast": 5, "stl": 1, "blk": 1, "to": 3, "fgm": 8, "fga": 15,
                    "ftm": 2, "fta": 3, "tpm": 2}) == 48  # prep-notes' literal box-score check
    print("ok: validation refusal, lock math, win odds, lineup/rotation, FA diff and beyond-board, changes diff, "
          "standings, box-score scoring")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", type=datetime.date.fromisoformat, help="pretend today is this date (dry runs)")
    ap.add_argument("--refresh", action="store_true", help="force a fresh /players/nba download")
    ap.add_argument("--test", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("roster").add_argument("team", nargs="?")
    p = sub.add_parser("week")
    p.add_argument("--week", type=int)
    p.add_argument("--locked", help="comma-separated players already locked this week")
    p.add_argument("--ev", action="store_true", help="EV lock lines (skip the matchup lines)")
    p.add_argument("--play", help='comma-separated Name=P: chance each player plays each game from today (as lock --play)')
    sub.add_parser("matchup").add_argument("--week", type=int)
    p = sub.add_parser("lock")
    p.add_argument("--week", type=int)
    p.add_argument("player", nargs="?")
    p.add_argument("score", nargs="?", type=float)
    p.add_argument("--remaining", type=int)
    p.add_argument("--play", type=float, help="chance he plays each remaining game (default 0.92, 0.88 on a back-to-back's second night)")
    p.add_argument("--game", type=datetime.date.fromisoformat,
                   help="date of the game the score is from (default: his latest game on or before today)")
    p.add_argument("--slot-of", help="the starter whose slot he was rotated into (when Sleeper doesn't show the move yet)")
    p.add_argument("--locked", help="comma-separated players already locked this week (as for week)")
    p.add_argument("--commit", action="store_true", help="record that you locked this player at this score in Sleeper")
    p.add_argument("--uncommit", action="store_true", help="remove a mistaken lock record")
    p.add_argument("--ev", action="store_true", help="EV lock lines (skip the matchup lines)")
    p = sub.add_parser("fa")
    p.add_argument("--pos")
    p.add_argument("--top", type=int, default=15)
    p.add_argument("--locked", help="comma-separated players already locked this week (as for week)")
    sub.add_parser("standings")
    sub.add_parser("review").add_argument("--week", type=int)
    sub.add_parser("changes").add_argument("--no-write", action="store_true")
    a = ap.parse_args()
    if a.test:
        return test()
    if not a.cmd:
        ap.error("choose a command")
    if a.cmd == "lock" and a.commit and a.uncommit:
        ap.error("use --commit or --uncommit, not both")
    if a.cmd == "lock" and not a.uncommit and (a.player is None) != (a.score is None):
        ap.error("lock needs both <player> and <score>, or neither for pending calls")
    d = load(a)
    globals()["cmd_" + a.cmd](d, a)


if __name__ == "__main__":
    main()
