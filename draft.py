#!/usr/bin/env python3
"""Live draft board for a Sleeper NBA league. Read-only; uses only docs.sleeper.com endpoints.

Usage: ./draft.py [--top N] [--pos C] [--draft DRAFT_ID] [--refresh] [--watch [SEC]] [--test]
"""
import argparse, concurrent.futures, contextlib, datetime, glob, io, json, os, re, sys, time, unicodedata, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PRIVATE = os.path.join(HERE, "private")  # gitignored, its own repo: config.json, notes, GM state (README: Private data)
API = "https://api.sleeper.app/v1"
SLOT_ELIGIBLE = {"PG": {"PG"}, "SG": {"SG"}, "SF": {"SF"}, "PF": {"PF"}, "C": {"C"},
                 "G": {"PG", "SG"}, "F": {"SF", "PF"}, "UTIL": {"PG", "SG", "SF", "PF", "C"}}


def get(path):
    with urllib.request.urlopen(API + path, timeout=8) as r:
        return json.load(r)


PLAYERS_PATH = None  # the tags file players() last read, for gm.py's footer


def players(refresh=False, pre_draft=False):
    """/players/nba (~2.8 MB, injury tags included): today's cached copy, refetched when over 1 h old before the
    draft and 3 h old otherwise, so a pre-tip run never uses the morning's tags. A failed fetch falls back to the
    newest cached copy with a WARNING."""
    global PLAYERS_PATH
    cache = os.path.join(HERE, ".cache", f"players-{datetime.date.today()}.json")
    if os.path.exists(cache) and time.time() - os.path.getmtime(cache) > (3600 if pre_draft else 3 * 3600):
        refresh = True
    if refresh or not os.path.exists(cache):
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        try:
            data = get("/players/nba")
        except OSError as e:  # e.g. the API is slow: use the newest cached file
            old = sorted(glob.glob(os.path.join(HERE, ".cache", "players-*.json")))
            if not old:
                raise
            print(f"WARNING: player fetch failed ({e}); using {os.path.basename(old[-1])}")
            cache = old[-1]
        else:
            with open(cache + ".tmp", "w") as f:
                json.dump(data, f)
            os.replace(cache + ".tmp", cache)
    PLAYERS_PATH = cache
    with open(cache) as f:
        return json.load(f)


def pick_slot(pick_no, teams, reversal_round):
    """Draft slot (1-based) making overall pick `pick_no` in a snake, with optional reversal round."""
    rnd, i = divmod(pick_no - 1, teams)
    rnd += 1
    reverse = rnd % 2 == 0
    if reversal_round and rnd >= reversal_round:
        reverse = not reverse
    return teams - i if reverse else i + 1


def snake_window(nxt, mine_future):
    """Imminent pick range [start, end) before the Owner's next turn (or after a current pair)."""
    if not mine_future or nxt is None:
        return None, None
    if mine_future[0] > nxt:
        return nxt, mine_future[0]
    if len(mine_future) > 1:
        if mine_future[1] == mine_future[0] + 1 and len(mine_future) > 2:
            return mine_future[1] + 1, mine_future[2]
        return mine_future[0] + 1, mine_future[1]
    return None, None


def fill_slots(slots, roster):
    """Max matching of players to starting slots, filling specific (PG/SG/SF/PF/C) before G/F before UTIL.
    roster: [(name, positions)]. Returns {slot_index: name}.
    """
    owner = {}
    order = sorted(range(len(slots)), key=lambda s: len(SLOT_ELIGIBLE[slots[s]]))

    def place(p, seen, max_elig):
        for s in order:
            if s in seen or len(SLOT_ELIGIBLE[slots[s]]) > max_elig:
                continue
            if not SLOT_ELIGIBLE[slots[s]] & set(roster[p][1]):
                continue
            seen.add(s)
            if s not in owner or place(owner[s], seen, max_elig):
                owner[s] = p
                return True
        return False

    for max_elig in (1, 2, 5):
        for p in range(len(roster)):
            if p not in owner.values():
                place(p, set(), max_elig)
    return {s: roster[p][0] for s, p in owner.items()}


def norm(name):
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b\.?", "", s)  # Sleeper often drops suffixes
    return "".join(c for c in s if c.isalnum())


def name_index(pool):
    """norm(name) -> player_id, preferring active players on a team when names collide."""
    by_name = {}
    for pid, p in sorted(pool.items(), key=lambda kv: not (kv[1].get("active") and kv[1].get("team"))):
        by_name.setdefault(norm(p.get("full_name") or ""), pid)
    return by_name


def load_board(pool):
    """board.txt: one player per line, best first (# comments ok). Returns ranked player_ids + unmatched names."""
    path = os.path.join(HERE, "board.txt")
    if not os.path.exists(path):
        return None, [], {}
    by_name = name_index(pool)
    ranked, missing, notes = [], [], {}
    for raw in open(path):
        line, _, note = raw.partition("#")
        line = line.strip()
        if not line:
            continue
        pid = line if line in pool else by_name.get(norm(line))
        (ranked.append(pid) if pid else missing.append(line))
        if pid and note.strip():
            notes[pid] = note.strip()
    return ranked, missing, notes


def fetch_state(cfg, draft_override=None):
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        f_lg = ex.submit(get, f"/league/{cfg['league_id']}")
        f_us = ex.submit(get, f"/league/{cfg['league_id']}/users")
        league = f_lg.result()
        if league.get("sport") != "nba":
            sys.exit(f"REFUSING: league {cfg['league_id']} is sport={league.get('sport')}, expected nba")
        did = draft_override or league["draft_id"]
        f_dr = ex.submit(get, f"/draft/{did}")
        f_pk = ex.submit(get, f"/draft/{did}/picks")
        f_tr = ex.submit(get, f"/draft/{did}/traded_picks")
        users = {u["user_id"]: u["display_name"] for u in f_us.result()}
        return league, f_dr.result(), f_pk.result(), f_tr.result(), users


def render(league, draft, picks, traded, users, pool, board, missing, notes, a, cfg):
    if draft.get("type") != "snake":
        sys.exit(f"REFUSING: draft type {draft.get('type')}; pick math assumes snake")
    st = draft["settings"]
    teams, rounds, rr = st["teams"], st["rounds"], st.get("reversal_round", 0)
    slot_roster = {int(k): v for k, v in (draft.get("slot_to_roster_id") or {}).items()}
    slot_user = {s: users.get(u, u) for u, s in (draft.get("draft_order") or {}).items()}
    me = cfg["user_id"]
    if a.draft:  # test mode against another draft: pretend to be slot 1's user
        me = next(iter(sorted(draft["draft_order"], key=draft["draft_order"].get)), me)
    my_slot = (draft.get("draft_order") or {}).get(me)
    if not my_slot:
        sys.exit(f"REFUSING: user {me} has no slot in draft_order")
    my_roster = slot_roster.get(my_slot)

    print(f"{league['name']} — {draft['status']} — {teams} teams, {rounds} rds, snake"
          + (f", 3RR from round {rr}" if rr else "") + (f", {st.get('pick_timer')}s timer" if draft["status"] != "complete" else ""))
    print("Scoring:", ", ".join(f"{k} {v:+g}" for k, v in league["scoring_settings"].items() if v))
    if traded:
        print(f"WARNING: {len(traded)} traded picks exist; future pick numbers below ignore trades.")

    # Picks & snake window
    made = {p["pick_no"]: p for p in picks}
    total = teams * rounds
    nxt = next((n for n in range(1, total + 1) if n not in made), None)
    mine_future = [n for n in range(1, total + 1) if n not in made and pick_slot(n, teams, rr) == my_slot]
    if nxt:
        on_clock = pick_slot(nxt, teams, rr)
        print(f"\nOn the clock: pick {nxt} (round {(nxt - 1) // teams + 1}), slot {on_clock} = {slot_user.get(on_clock, '?')}")
    win_start, win_end = snake_window(nxt, mine_future)
    if mine_future:
        gap = mine_future[0] - (nxt or 0)
        print(f"Your slot: {my_slot}. Your next picks: {', '.join(map(str, mine_future[:4]))}"
              + (" — YOU ARE ON THE CLOCK" if gap == 0 else f" ({gap} picks away)"))
        if len(mine_future) > 1:
            between = mine_future[1] - mine_future[0] - 1
            if between == 0 and len(mine_future) > 2:
                after_pair = mine_future[2] - mine_future[1] - 1
                print(f"Picks between your next two turns: 0 (back-to-back {mine_future[0]} & {mine_future[1]}, then {after_pair} picks before #{mine_future[2]})")
            else:
                print(f"Picks between your next two turns: {between}")
    else:
        print("You have no picks left.")

    def pos_of(pid):
        p = pool.get(pid, {})
        return p.get("fantasy_positions") or [p.get("position") or "?"]

    def label(pid):
        p = pool.get(pid, {})
        inj = f" [{p['injury_status']}]" if p.get("injury_status") else ""
        return f"{p.get('full_name', pid)} ({'/'.join(pos_of(pid))}, {p.get('team') or 'FA'}){inj}"

    # My roster
    ordered_picks = sorted(picks, key=lambda p: p["pick_no"])
    mine = [p for p in ordered_picks
            if (p.get("roster_id") == my_roster if my_roster else p.get("picked_by") == me)]
    slots = [s for s in league["roster_positions"] if s != "BN"]
    filled = fill_slots(slots, [(label(p["player_id"]), pos_of(p["player_id"])) for p in mine])
    print(f"\nYour roster ({len(mine)}/{rounds}):")
    for i, s in enumerate(slots):
        print(f"  {s:<5}{filled.get(i, '— OPEN —')}")
    bench = [label(p["player_id"]) for p in mine if label(p["player_id"]) not in filled.values()]
    for b in bench:
        print(f"  BN   {b}")
    counts = {}
    for p in mine:
        for pos in pos_of(p["player_id"]):
            counts[pos] = counts.get(pos, 0) + 1
    print("  Eligibility counts:", ", ".join(f"{k} {counts.get(k, 0)}" for k in ["PG", "SG", "SF", "PF", "C"]))

    # Opponent window & Neighbor (Slot 2) needs
    by_slot = {s: [] for s in range(1, teams + 1)}
    for p in ordered_picks:
        s = p.get("draft_slot") or pick_slot(p["pick_no"], teams, rr)
        if s in by_slot:
            by_slot[s].append(p)
    open_by_slot = {}
    for s, spicks in by_slot.items():
        f = fill_slots(slots, [(p["player_id"], pos_of(p["player_id"])) for p in spicks])
        open_by_slot[s] = [slots[i] for i in range(len(slots)) if i not in f]

    if win_start is not None and win_end is not None and win_end > win_start:
        win_picks = list(range(win_start, win_end))
        win_opp = sorted({pick_slot(n, teams, rr) for n in win_picks if pick_slot(n, teams, rr) != my_slot})
        need_str = ", ".join(
            f"{pos} {sum(1 for s in win_opp if pos in open_by_slot[s])}/{len(win_opp)}"
            for pos in ("PG", "SG", "G", "SF", "PF", "F", "C")
        )
        print(f"\nSnake window (picks {win_start}–{win_end - 1}, {len(win_picks)} picks by {len(win_opp)} opp teams):")
        print(f"  Opp teams with open slot: {need_str}")
    neighbor = 2 if my_slot == 1 else (1 if my_slot == 2 else my_slot - 1)
    if neighbor in by_slot and nxt:  # draft-time intel only
        npicks = by_slot[neighbor]
        nfuture = [n for n in range(1, total + 1) if n not in made and pick_slot(n, teams, rr) == neighbor][:3]
        nopen = [s for s in open_by_slot[neighbor] if s != "UTIL"]
        nplayers = ", ".join(f"{pool.get(p['player_id'], {}).get('full_name', '?')} ({'/'.join(pos_of(p['player_id']))})" for p in npicks) or "none yet"
        print(f"  Slot {neighbor} ({slot_user.get(neighbor, '?')}, next {nfuture}): open {'/'.join(nopen) or 'none'} | drafted: {nplayers}")

    # Available
    taken = {p["player_id"] for p in picks}
    excluded = {pid for pid, note in notes.items() if note.startswith("DO NOT DRAFT | ")}
    avail = {pid: p for pid, p in pool.items() if p.get("active") and p.get("team")
             and pid not in taken and pid not in excluded}
    if excluded - taken:
        print("\nBoard exclusions: " + "; ".join(
            f"{pool[pid]['full_name']}: {notes[pid]}" for pid in sorted(excluded - taken)))
    if board is not None:
        order_all = [pid for pid in board if pid in avail]
        gone = [pool[pid]["full_name"] for pid in board if pid in taken]
        src = f"board.txt ({len(order_all)} left, {len(gone)} taken)"
        off = [pool[pid]["full_name"] for pid in board
               if pid not in avail and pid not in taken and pid not in excluded]
        if off:
            print(f"\nboard.txt players hidden (no NBA team in Sleeper): {', '.join(off)}")
        if missing:
            print(f"\nboard.txt names not matched to a Sleeper player: {', '.join(missing)}")
    else:
        order_all, src = [], "none"
    b_idx = {pid: i for i, pid in enumerate(order_all, 1)}
    order = list(order_all)
    rest = sorted((pid for pid in avail if pid not in order and avail[pid].get("search_rank")),
                  key=lambda pid: avail[pid]["search_rank"])
    if a.pos:
        want = a.pos.upper()
        elig = SLOT_ELIGIBLE.get(want, {want})
        order = [pid for pid in order if elig & set(pos_of(pid))]
        rest = [pid for pid in rest if elig & set(pos_of(pid))]
    print(f"\nBest available — board: {src}" + (f", position {a.pos.upper()}" if a.pos else ""))
    for pid in order[: a.top]:
        print(f"  B{b_idx[pid]:<3}{label(pid)}  {notes.get(pid, '')}  sleeper#{avail[pid].get('search_rank')}")
    if len(order) < a.top:
        print("  -- then by Sleeper search_rank (generic, not this league's scoring):")
        for pid in rest[: a.top - len(order)]:
            print(f"  #{avail[pid]['search_rank']:<4}{label(pid)}")

    # Positional cliffs (top 5 available per core position on board)
    if not a.pos and order_all:
        print("\nTop 5 available by position (board rank, name, tier/weekly value, sleeper#):")
        for pos in ("PG", "SG", "SF", "PF", "C"):
            top_p = [pid for pid in order_all if pos in pos_of(pid)][:5]
            items = []
            for pid in top_p:
                p = pool.get(pid, {})
                note_str = notes.get(pid, "")
                mv = re.search(r"(T\d+)\s*\|\s*(V\+\d+(?:\.\d+)?)", note_str)
                mf = re.search(r"(\d+)\s*FP", note_str)
                if mv:
                    val_lbl = f"{mv.group(1)} {mv.group(2)}"
                elif "NO PROJECTION" in note_str:
                    val_lbl = "NO PROJ"
                else:
                    val_lbl = f"{mf.group(1)}FP" if mf else "?FP"
                inj = f"[{p['injury_status']}]" if p.get("injury_status") else ""
                parts = (p.get("full_name") or pid).split()
                if len(parts) >= 2 and parts[-1] in ("Jr.", "III", "II", "IV", "Sr."):
                    parts = parts[:-1]
                sname = f"{parts[0][0]}.{parts[-1]}" if len(parts) >= 2 else parts[0]
                items.append(f"B{b_idx[pid]} {sname}{inj} ({val_lbl}, #{avail[pid].get('search_rank')})")
            print(f"  {pos:<3}" + " | ".join(items))

    # Recent picks
    if ordered_picks:
        print("\nLast 10 picks:")
        for p in ordered_picks[-10:]:
            who = users.get(p.get("picked_by"), "?")
            print(f"  {p['pick_no']:>3}. {who:<16}{label(p['player_id'])}")
    return nxt, mine_future


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--pos", help="only show available players eligible at this position, e.g. C")
    ap.add_argument("--draft", help="override draft id (e.g. a finished mock, for testing)")
    ap.add_argument("--refresh", action="store_true", help="force refresh of cached /players/nba")
    ap.add_argument("--watch", nargs="?", const=3.0, type=float, metavar="SEC",
                    help="poll live draft every SEC seconds (default 3) and reprint on your turn")
    ap.add_argument("--test", action="store_true")
    a = ap.parse_args()
    if a.test:
        return test()

    cfg = json.load(open(os.path.join(PRIVATE, "config.json")))
    league, draft, picks, traded, users = fetch_state(cfg, a.draft)
    pool = players(refresh=a.refresh, pre_draft=(draft.get("status") == "pre_draft"))
    board, missing, notes = load_board(pool)
    render(league, draft, picks, traded, users, pool, board, missing, notes, a, cfg)

    if a.watch:
        seen = {p["pick_no"] for p in picks}
        did = draft["draft_id"]
        print(f"\n[Watching draft {did} every {a.watch:g}s — Ctrl-C to stop]", flush=True)
        try:
            while draft.get("status") != "complete":
                time.sleep(a.watch)
                picks = get(f"/draft/{did}/picks")
                if len(picks) == len(seen):
                    continue
                draft = get(f"/draft/{did}")
                for p in sorted(picks, key=lambda p: p["pick_no"]):
                    if p["pick_no"] not in seen:
                        seen.add(p["pick_no"])
                        who = users.get(p.get("picked_by"), "?")
                        pl = pool.get(p["player_id"], {})
                        ts = datetime.datetime.now().strftime("%H:%M:%S")
                        print(f"[{ts}] Pick {p['pick_no']}: {who} -> {pl.get('full_name', p['player_id'])}", flush=True)
                st = draft["settings"]
                teams, rounds, rr = st["teams"], st["rounds"], st.get("reversal_round", 0)
                my_slot = (draft.get("draft_order") or {}).get(cfg["user_id"])
                nxt = next((n for n in range(1, teams * rounds + 1) if n not in seen), None)
                if nxt and my_slot and pick_slot(nxt, teams, rr) == my_slot:
                    print("\a\n=== YOU ARE ON THE CLOCK ===", flush=True)
                    render(league, draft, picks, traded, users, pool, board, missing, notes, a, cfg)
        except KeyboardInterrupt:
            print("\nStopped watching.")


def test():
    # plain snake, 10 teams
    assert [pick_slot(n, 10, 0) for n in (1, 10, 11, 20, 21)] == [1, 10, 10, 1, 1]
    # third-round reversal: R1 1→10, R2 10→1, R3 10→1, R4 1→10
    assert [pick_slot(n, 10, 3) for n in (1, 10, 11, 20, 21, 30, 31, 40)] == [1, 10, 10, 1, 10, 1, 1, 10]
    assert snake_window(1, [1, 20, 30, 31]) == (2, 20)
    assert snake_window(21, [30, 31, 50, 51]) == (21, 30)
    assert snake_window(30, [30, 31, 50, 51]) == (32, 50)
    assert snake_window(31, [31, 50, 51]) == (32, 50)
    slots = ["PG", "SG", "G", "SF", "PF", "F", "C", "UTIL", "UTIL"]
    # greedy would put the PG/SG in PG and leave SG open; matching must fill both
    got = fill_slots(slots, [("a", ["PG", "SG"]), ("b", ["PG"]), ("c", ["C"])])
    assert sorted(got.values()) == ["a", "b", "c"] and got[0] == "b" and got[1] == "a", got
    # 2 PG + 1 PG/SG must fill PG, SG, G (not spill into UTIL leaving SG open)
    got2 = fill_slots(slots, [("Luka", ["PG"]), ("Harden", ["PG"]), ("Kyrie", ["PG", "SG"])])
    assert set(got2.keys()) == {0, 1, 2} and got2[1] == "Kyrie", got2
    # 6-pick plan must fill PG, SG, SF, PF, C before touching UTIL
    got3 = fill_slots(slots, [("Jokic", ["C"]), ("KD", ["PF", "SF"]), ("Harden", ["PG"]),
                              ("Avdija", ["SF", "PF"]), ("Duren", ["C"]), ("Kyrie", ["PG", "SG"])])
    assert {0, 1, 3, 4, 6} <= set(got3.keys()) and got3[0] == "Harden" and got3[1] == "Kyrie", got3
    assert norm("Nikola Jokić") == norm("nikola jokic")
    pool = {"1": {"full_name": "Jaylin Williams"}, "2": {"full_name": "Jaylin Williams", "active": True, "team": "OKC"}}
    assert name_index(pool)[norm("Jaylin Williams")] == "2"
    assert norm("Jaren Jackson Jr.") == norm("Jaren Jackson") and norm("Robert Williams III") == norm("Robert Williams")

    # Behavioral render checks: snake window (21, 30, 130/131, completed) and T/V + NO PROJ footer
    lg = {
        "name": "TestLg",
        "roster_positions": slots + ["BN"] * 5,
        "scoring_settings": {"pts": 1.0, "reb": 1.5, "ast": 2.0},
    }
    dr = {
        "type": "snake",
        "status": "drafting",
        "settings": {"teams": 10, "rounds": 14, "reversal_round": 3, "pick_timer": 90},
        "slot_to_roster_id": {str(i): i for i in range(1, 11)},
        "draft_order": {f"u{i}": i for i in range(1, 11)},
    }
    us = {f"u{i}": f"User{i}" for i in range(1, 11)}
    pl = {
        str(i): {
            "full_name": f"Player {i}",
            "active": True,
            "team": "BOS",
            "fantasy_positions": [["PG", "SG", "SF", "PF", "C"][i % 5]],
            "search_rank": i,
        }
        for i in range(1, 160)
    }
    brd = [str(i) for i in range(1, 155)]
    nts = {str(i): f"T1 | V+{50 - i * 0.2:.1f}/wk | 40.0/g | season 3000 FP" for i in range(1, 150)}
    for i in range(150, 155):
        nts[str(i)] = f"NO PROJECTION | ECR 200 | sleeper#{i}"
    args_stub = argparse.Namespace(top=5, pos=None, draft=None)
    cfg_stub = {"user_id": "u1"}

    def render_after(n_made, pos_filter=None):
        args_stub.pos = pos_filter
        pks = [
            {
                "pick_no": n,
                "player_id": str(n),
                "roster_id": pick_slot(n, 10, 3),
                "picked_by": f"u{pick_slot(n, 10, 3)}",
                "draft_slot": pick_slot(n, 10, 3),
            }
            for n in range(1, n_made + 1)
        ]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            render(lg, dr, pks, [], us, pl, brd, [], nts, args_stub, cfg_stub)
        return buf.getvalue()

    out21 = render_after(20)  # Next pick is 21 (waiting before 30/31 pair)
    assert "Snake window (picks 21–29, 9 picks by 9 opp teams):" in out21, out21
    assert "B1 P.21 (T1 V+45.8, #21)" in out21, out21

    out30 = render_after(29)  # Next pick is 30 (on the clock at first pick of 30/31 pair)
    assert "Snake window (picks 32–49, 18 picks by 9 opp teams):" in out30, out30

    out130 = render_after(129)  # Final pair: pick 130 (no picks after 130/131)
    assert "Snake window" not in out130, out130

    out131 = render_after(130)  # Final pick 131
    assert "Snake window" not in out131, out131

    out140 = render_after(140)  # Completed draft (140 picks made)
    assert "Snake window" not in out140 and "You have no picks left." in out140, out140
    assert "(NO PROJ, #150)" in out140, out140
    # A frozen exclusion must beat stale Sleeper team/active metadata and its fallback rank.
    nts['141'] = 'DO NOT DRAFT | Waived; role unknown'
    args_stub.top = 200
    out_excluded = render_after(140)
    assert 'Board exclusions: Player 141: DO NOT DRAFT | Waived; role unknown' in out_excluded
    assert not re.search(r'^  (?:B\d+\s*|#141\s*)Player 141', out_excluded, re.MULTILINE)
    assert 'P.141 (' not in out_excluded
    assert 'B1  Player 142 ' in out_excluded, out_excluded

    # Player tags: today's file is refetched once 3 h old in-season (1 h pre-draft); yesterday's file is never reused
    # unless the fetch fails (regression: a 10 am file served 7 pm pre-tip calls, a 10 pm file the next morning).
    import tempfile
    g, calls = globals(), []
    saved = g["HERE"], g["get"]
    with tempfile.TemporaryDirectory() as tmp:
        g["HERE"], g["get"] = tmp, lambda path: calls.append(path) or {"fresh": {}}
        try:
            os.makedirs(os.path.join(tmp, ".cache"))
            today = os.path.join(tmp, ".cache", f"players-{datetime.date.today()}.json")
            old = os.path.join(tmp, ".cache", "players-2000-01-01.json")
            with open(old, "w") as f:
                json.dump({"old": {}}, f)
            assert players() == {"fresh": {}} and len(calls) == 1 and PLAYERS_PATH == today  # yesterday's 0 h file
            for age, pre, fetched in ((2, False, False), (4, False, True), (0.5, True, False), (2, True, True)):
                os.utime(today, (time.time() - age * 3600,) * 2)
                n = len(calls)
                players(pre_draft=pre)
                assert (len(calls) > n) == fetched, (age, pre)
            os.remove(today)

            def down(path):
                raise OSError("offline")
            g["get"] = down
            with contextlib.redirect_stdout(io.StringIO()) as warn:
                assert players() == {"old": {}} and PLAYERS_PATH == old
            assert "WARNING: player fetch failed" in warn.getvalue()
        finally:
            g["HERE"], g["get"] = saved
    print("ok")


if __name__ == "__main__":
    main()
