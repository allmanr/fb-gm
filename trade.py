#!/usr/bin/env python3
"""Trade evaluator on board.txt weekly Lock-In value (V/wk). Read-only.

Usage: ./trade.py "<we give: names>" "<we get: names>" [--with TEAM]
       ./trade.py --suggest [--top N] [--min V] [--playoff]
       ./trade.py --test
"""
import argparse, concurrent.futures, datetime, itertools, json, os, sys
from draft import PRIVATE, get, players, fill_slots, load_board, name_index, norm
import gm
import rebuild_board as rb

# Bench value = 0.60 x the top 3 bench V. Bench players score only when rotated into an
# unlocked starter slot for an extra lock roll. Measured on 2025-26 logs against
# replacement-level waiver players (the V basis): 0.595, 95% CI 0.53-0.67; 0.45 if
# in-week DNPs are never foreseen, 0.72 with perfect foresight
# (reports/2026-10-20/lockin-backtest.md, Q3).
# One league-wide factor: a guard-heavy bench that overlaps the starters (ours measured 0.42) is worth
# less. sim_value simulates each roster's rotation instead; reports print both until it is trusted.
BENCH_W, BENCH_N = 0.60, 3
ACCEPT_COST = 1.0  # counterparty "plausibly accepts" if it loses under this V/wk, in ITS view
# ponytail: the room drafted near Sleeper's search_rank, so "their view" prices each player
# at the board V of whoever holds that Sleeper rank (rank-matched V, "sv"). Upgrade: fit
# each manager's own valuation from their trades once there are some.
IR_OK = gm.IR_OK  # reserve_allow_out is 0: Out holds a bench spot
# Fantasy playoffs are weeks 21-23; we project a top-2 seed, so our games are the week 22-23 schedules.
PO_WEEKS, PO_SCORED, PO_FPG = (21, 22, 23), (22, 23), 40.0


def playoff_profile(sched, weeks=PO_WEEKS, fpg=PO_FPG):
    """NBA team -> {games, b2b, mult}, one entry per week in weeks. b2b counts second nights of back-to-backs;
    mult is the expected locked score that week / a typical 3.4-game week (0.6 x 3 games + 0.4 x 4, no B2B),
    by rebuild_board.lock_values' optimal stopping at fpg with the backtest DNP correction (gm.play_on: 0.08
    per game, 0.12 on a second night)."""
    dates = {}
    for g in sched:
        for t in (g["home"]["team"], g["away"]["team"]):
            dates.setdefault(t, set()).add(datetime.date.fromisoformat(g["date"]))
    base = 0.6 * gm.wait_value(fpg, [1 - gm.Q_DNP] * 3) + 0.4 * gm.wait_value(fpg, [1 - gm.Q_DNP] * 4)
    out = {t: {"games": [], "b2b": [], "mult": []} for t in dates}
    for w in weeks:
        wg = gm.week_games(sched, w)
        for t, prof in out.items():
            days = sorted(wg.get(t, {}))
            prof["games"].append(len(days))
            prof["b2b"].append(sum(d - datetime.timedelta(1) in dates[t] for d in days))
            prof["mult"].append(gm.wait_value(fpg, [gm.play_on(d, dates[t]) for d in days]) / base)
    return out


def po_mult(lg, pid):
    """Mean PO_SCORED multiplier for the player's NBA team; 1.0 with no team or no schedule."""
    prof = lg.get("po", {}).get(lg["players"][pid].get("team"))
    return sum(prof["mult"][PO_WEEKS.index(w)] for w in PO_SCORED) / len(PO_SCORED) if prof else 1.0


def po_delta(lg, res):
    """Our total delta with each changed starter's V scaled by his playoff multiplier.
    ponytail: V (surplus over a same-schedule replacement) is assumed to scale like the locked score, and the
    bench delta is left unweighted; that ignores waiver streamers' schedules and bench rotation gains from
    4-game weeks. Upgrade: rerun rebuild_board.week_value per player on his team's week 22-23 game counts."""
    P = lg["players"]
    old, new = set(res["us"]["before"][2].values()), set(res["us"]["after"][2].values())
    return res["us"]["d"] + sum((po_mult(lg, p) - 1) * P[p]["v"] for p in new - old) \
        - sum((po_mult(lg, p) - 1) * P[p]["v"] for p in old - new)


def sim_weeks(lg):
    """(regular-season weeks starting after today, scored playoff weeks): the simulation's two horizons."""
    reg = tuple(w for w in range(1, PO_WEEKS[0]) if (gm.week_days(lg["sched"], w) or [lg["today"]])[0] > lg["today"])
    return reg, PO_SCORED


def absences(pool):
    """pid -> chance he misses a whole week: rebuild_board.week_value's cluster x (1 - gp/82), from board-inputs.csv."""
    idx = name_index(pool)
    return {idx[norm(r["name"])]: r["cluster"] * (1 - r["gp"] / 82)
            for r in rb.load_inputs() if r["ppg"] is not None and norm(r["name"]) in idx}


def sim_value(lg, pids, weeks):
    """Expected locked FP/wk over weeks, by gm.py week's model on each week's schedule: base lineup by expected
    locked score, the bench rotation plan, optimal stopping with the DNP correction. Season horizon, like
    team_value: injury tags are ignored and every held player (IR too) is in the pool. Whole-week absences
    (players' "out") are what the bench covers; each enters to first order, E ~ T + sum out_i (T without i - T).
    ponytail: first order ignores two players out the same week (~12% of weeks for 14 players at ~4.5% each).
    Upgrade: second-order pairs, ~7x the cost."""
    memo, key = lg.setdefault("sim", {}), (frozenset(pids), weeks)
    if key not in memo and weeks:
        P = lg["players"]
        d = dict(sched=lg["sched"], team={0: ""}, vals={p: (P[p]["v"], P[p]["fpg"]) for p in pids if P[p].get("fpg")},
                 pool={p: {"team": P[p].get("team"), "fantasy_positions": P[p]["pos"]} for p in pids})

        def week(roster, w):
            days = gm.week_days(lg["sched"], w)
            return gm.team_score(dict(d, rosters=[{"roster_id": 0, "players": roster}], week=w,
                                      today=days[0] if days else lg["today"]), 0, {}, False)[0]
        total = 0.0
        for w in weeks:
            full = week(list(pids), w)
            total += full + sum(P[p].get("out", 0) * (week([q for q in pids if q != p], w) - full) for p in pids)
        memo[key] = total / len(weeks)
    return memo.get(key, 0.0)


def sim_delta(lg, res, side, weeks):
    """Simulated after - before for one side of an evaluated trade (FP/wk; 0 without weeks)."""
    kept = lambda tv: list(tv[2].values()) + tv[3]
    return sim_value(lg, kept(res[side]["after"]), weeks) - sim_value(lg, kept(res[side]["before"]), weeks)


def load_league(cfg):
    """Live league -> {slots, limit, me, teams{rid: {name, players}}, players{pid: {...}}}."""
    lid = cfg["league_id"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        f_lg, f_r, f_u = (ex.submit(get, f"/league/{lid}{p}") for p in ("", "/rosters", "/users"))
        league, rosters, users = f_lg.result(), f_r.result(), f_u.result()
    gm.refuse(gm.validate(cfg, league, rosters))  # scoring, roster slots, IR rules, ownership: as gm.py checks
    names = {u["user_id"]: u["display_name"] for u in users}
    pool = players()
    _, _, notes = load_board(pool)
    vals = gm.board_values(notes)  # same parser as gm.py; unprojected and excluded players are absent
    curve = sorted((v for v, _ in vals.values()), reverse=True)
    by_rank = sorted((p["search_rank"], pid) for pid, p in pool.items() if p.get("team") and p.get("search_rank"))
    sv = {pid: curve[i] if i < len(curve) else 0.0 for i, (_, pid) in enumerate(by_rank)}
    teams, info, out = {}, {}, absences(pool)
    for r in rosters:
        held = list(dict.fromkeys((r.get("players") or []) + (r.get("reserve") or [])))
        teams[r["roster_id"]] = {"name": names.get(r["owner_id"], f"roster {r['roster_id']}"), "players": held}
        for pid in held:
            p = pool.get(pid, {})
            info[pid] = {"name": p.get("full_name", pid), "team": p.get("team"),
                         "pos": p.get("fantasy_positions") or [p.get("position") or "?"],
                         "inj": p.get("injury_status"), "v": vals[pid][0] if pid in vals else 0.0, "proj": pid in vals,
                         "fpg": vals[pid][1] if pid in vals else 0.0, "out": out.get(pid, 0.0),
                         "rank": p.get("search_rank"), "sv": sv.get(pid, 0.0), "ir": pid in (r.get("reserve") or [])}
    me = next((r["roster_id"] for r in rosters if r["owner_id"] == cfg["user_id"]), None)
    if me is None:
        sys.exit(f"REFUSING: user {cfg['user_id']} owns no roster in league {lid}")
    slots = [s for s in league["roster_positions"] if s != "BN"]
    sched = gm.schedule(league["season"])
    return {"slots": slots, "limit": len(league["roster_positions"]), "ir_slots": league["settings"]["reserve_slots"],
            "me": me, "teams": teams, "players": info, "po": playoff_profile(sched) if sched else {},
            "sched": sched, "today": datetime.date.today()}


def team_value(lg, pids, k="v"):
    """Best legal starting lineup by value k (v = our board, sv = their view), plus discounted bench.
    Trade values are season-horizon: an IR-slotted player keeps his board V, which already prices expected
    missed games, so an IR slot changes only who counts toward the active-roster limit, never a team's value
    (valuing IR at 0 made any reserve move swing a trade, e.g. a +1 V/wk upgrade read as -49).
    -> (start V, bench V, {slot: pid}, bench)."""
    memo, key = lg.setdefault("memo", {}), (k, frozenset(pids))  # --suggest re-values the same rosters often
    if key not in memo:
        memo[key] = _team_value(lg, pids, k)
    return memo[key]


def _team_value(lg, pids, k):
    P = lg["players"]
    ranked = sorted(pids, key=lambda p: -P[p][k])
    filled = fill_slots(lg["slots"], [(p, P[p]["pos"]) for p in ranked])
    bench = [p for p in ranked if p not in filled.values()]
    return (sum(P[p][k] for p in filled.values()),
            BENCH_W * sum(P[p][k] for p in bench[:BENCH_N]), filled, bench)


def fit_roster(lg, pids, incoming=(), k="v"):
    """Roster after a trade -> (kept, dropped, IR-slotted). Players already on this team's IR stay there. Only when
    the active roster is over the limit do eligible players (IR/Sus/DNR, incoming or existing) fill open IR slots,
    which costs no value (see team_value); then drop the active players whose removal preserves the most
    lineup-plus-bench value under valuation k."""
    P = lg["players"]
    ir = {p for p in pids if P[p]["ir"] and p not in incoming}
    active = [p for p in pids if p not in ir]
    excess = len(active) - lg["limit"]
    if excess > 0:
        eligible = [p for p in active if (P[p]["inj"] or "").upper() in IR_OK]
        newly = set(eligible[:min(excess, max(0, lg["ir_slots"] - len(ir)))])
        ir |= newly
        active = [p for p in active if p not in newly]
        excess -= len(newly)
    if excess <= 0:
        return list(pids), [], ir
    reserved = [p for p in pids if p in ir]
    # Among equal-value drops, drop projected players first: an unprojected player's 0 V means unknown, not worthless.
    candidates = itertools.combinations(sorted(active, key=lambda p: (not P[p].get("proj", True), P[p][k])), excess)
    drop = list(max(candidates, key=lambda removed: sum(team_value(
        lg, reserved + [p for p in active if p not in removed], k)[:2])))
    return [p for p in pids if p not in drop], drop, ir


def evaluate(lg, give, get, me=None, them=None):
    """Value a trade for both sides. give/get are pid lists; them is found from get if omitted."""
    me = me or lg["me"]
    teams = lg["teams"]
    if not give or not get:
        raise ValueError("a trade needs at least one player on each side")
    if them is None:
        owners = {rid for rid, t in teams.items() for p in get if p in t["players"]}
        if len(owners) != 1:
            raise ValueError("players we get must all come from one other roster")
        them = owners.pop()
    if them == me:
        raise ValueError("players we get are already on our roster")
    for pids, rid in ((give, me), (get, them)):
        bad = [lg["players"].get(p, {}).get("name", p) for p in pids if p not in teams[rid]["players"]]
        if bad:
            raise ValueError(f"not on {teams[rid]['name']}'s roster: {', '.join(bad)}")
    res = {"me": me, "them": them, "give": list(give), "get": list(get)}
    for side, rid, out, inc in (("us", me, give, get), ("they", them, get, give)):
        before = teams[rid]["players"]
        kept, drop, ir = fit_roster(lg, [p for p in before if p not in out] + list(inc), inc)
        b, a = team_value(lg, before), team_value(lg, kept)
        n_active = sum(not lg["players"][p]["ir"] for p in before)
        res[side] = {"before": b, "after": a, "drop": drop, "ir": ir, "open": max(0, n_active - (len(kept) - len(ir))),
                     "d_start": a[0] - b[0], "d_bench": a[1] - b[1], "d": a[0] + a[1] - b[0] - b[1]}
    their_after = [p for p in teams[them]["players"] if p not in get] + list(give)
    kept, drop, ir = fit_roster(lg, their_after, give, "sv")
    bv, av = team_value(lg, teams[them]["players"], "sv"), team_value(lg, kept, "sv")
    res["they"]["d_view"] = av[0] + av[1] - bv[0] - bv[1]
    res["they"]["view_drop"], res["they"]["view_ir"] = drop, ir
    # An unprojected player's 0.0 V means "unknown", not "worthless": flag every one that moves or is dropped.
    moved = list(give) + list(get) + res["us"]["drop"] + res["they"]["drop"] + list(drop)
    res["unproj"] = [p for p in dict.fromkeys(moved) if not lg["players"][p].get("proj", True)]
    return res


def plausible(res):
    """They plausibly accept if, in their Sleeper-rank view, they lose under ACCEPT_COST (printed precision)."""
    return round(res["they"]["d_view"], 1) > -ACCEPT_COST


def resolve(lg, names, rids):
    """Comma-separated names -> pids on the given rosters; exact normalized match, else unique substring."""
    pool = {p: lg["players"][p]["name"] for rid in rids for p in lg["teams"][rid]["players"]}
    out = []
    for raw in filter(None, (n.strip() for n in names.split(","))):
        key = norm(raw)
        hits = [p for p, n in pool.items() if norm(n) == key] or [p for p, n in pool.items() if key and key in norm(n)]
        if len(hits) != 1:
            who = ", ".join(sorted(pool[p] for p in hits)) if hits else "no player on " + "/".join(lg["teams"][r]["name"] for r in rids)
            raise ValueError(f"'{raw}' matches {who}" + (" (ambiguous)" if hits else ""))
        out.append(hits[0])
    if not out:
        raise ValueError("no player names given")
    return out


def find_team(lg, key):
    hits = [rid for rid, t in lg["teams"].items() if str(rid) == key or t["name"].lower() == key.lower()]
    if len(hits) != 1:
        raise ValueError(f"--with {key!r} matches no team; teams: " + ", ".join(t["name"] for t in lg["teams"].values()))
    return hits[0]


def trade_from_names(lg, give_names, get_names, with_team=None):
    me = lg["me"]
    give = resolve(lg, give_names, [me])
    them = find_team(lg, with_team) if with_team else None
    get = resolve(lg, get_names, [them] if them else [r for r in lg["teams"] if r != me])
    return evaluate(lg, give, get, me, them)


def po_tag(lg, pid):
    """', MIL PO 3/3/4 x1.04' (games in weeks 21/22/23, PO_SCORED multiplier); '' without a schedule."""
    team = lg["players"][pid].get("team")
    prof = lg.get("po", {}).get(team)
    return f", {team} PO {'/'.join(map(str, prof['games']))} x{po_mult(lg, pid):.2f}" if prof else ""


def label(lg, pid):
    p = lg["players"][pid]
    inj = p["inj"]
    tag = (f" [{inj}: OUT, no IR - holds a bench spot]" if inj == "Out"
           else f" [{inj}, IR-eligible]" if (inj or "").upper() in IR_OK else f" [{inj}]" if inj else "")
    return f"{p['name']} ({'/'.join(p['pos'])}, V+{p['v']:.1f}, sleeper#{p['rank'] or '?'}{po_tag(lg, pid)}){tag}"


def report(lg, res):
    P, teams = lg["players"], lg["teams"]
    us, they = res["us"], res["they"]
    nm = lambda pids: ", ".join(label(lg, p) for p in pids)
    lines = [f"Trade with {teams[res['them']]['name']}",
             f"  We give: {nm(res['give'])}", f"  We get:  {nm(res['get'])}"]
    for side, rid in (("us", res["me"]), ("they", res["them"])):
        r = res[side]
        lines.append(f"\n{'Us' if side == 'us' else teams[rid]['name']}: starters {r['d_start']:+.1f}, "
                     f"bench {r['d_bench']:+.1f}, total {r['d']:+.1f} V/wk  "
                     f"(start {r['before'][0]:.1f} -> {r['after'][0]:.1f}, bench {r['before'][1]:.1f} -> {r['after'][1]:.1f})")
        b, a = r["before"][2], r["after"][2]
        tag = lambda p: P[p]["name"] + (f" [{P[p]['inj']}]" if P[p]["inj"] else "")
        slot = {p: lg["slots"][i] for d in (b, a) for i, p in d.items()}  # fill_slots reshuffles; show where each mover sits
        for kind, old, new in (("Starters", [b[i] for i in sorted(b)], [a[i] for i in sorted(a)]), ("Bench", r["before"][3], r["after"][3])):
            fmt = lambda p: tag(p) + (f" ({slot[p]})" if kind == "Starters" else "")
            out_, in_ = [fmt(p) for p in old if p not in new], [fmt(p) for p in new if p not in old]
            if out_ or in_:
                lines.append(f"  {kind} out: {', '.join(out_) or '-'} | in: {', '.join(in_) or '-'}")
        hurt = [tag(p) for p in a.values() if P[p]["inj"]]
        if hurt:
            lines.append(f"  Injured starters after (V assumes board availability): {', '.join(hurt)}")
        if r["drop"]:
            lines.append(f"  Must drop (roster full): {nm(r['drop'])}")
        moved_ir = r["ir"] - {p for p in teams[rid]["players"] if P[p]["ir"]}
        if moved_ir:
            lines.append(f"  Move to IR: {nm(sorted(moved_ir))}")
        if r["open"]:
            lines.append(f"  Opens {r['open']} roster spot(s) (waiver replacement ~0 V)")
    if res["unproj"]:
        lines.append(f"\nUNPROJECTED (no board V; 0.0 above is unknown, not worthless): {nm(res['unproj'])} - judge by hand")
    likely = plausible(res)
    verdict = "ACCEPTABLE" if us["d"] > 0 else "NOT ACCEPTABLE"
    lines.append(f"\n{verdict} for us: {us['d']:+.1f}/wk; they {'gain' if they['d'] >= 0 else 'lose'} "
                 f"{abs(they['d']):.1f}/wk on our board, {they['d_view']:+.1f} in their Sleeper-rank view"
                 f" -- {'likely' if likely else 'unlikely'} to accept")
    if lg.get("po"):
        lines.append(f"Playoff-weighted for us: {po_delta(lg, res):+.1f}/wk vs {us['d']:+.1f} regular season "
                     f"(changed starters' V x their week {'-'.join(map(str, PO_SCORED))} schedule multiplier)")
    if lg.get("sched"):
        reg, po = sim_weeks(lg)
        horizon = f"weeks {reg[0]}-{reg[-1]}" if reg else "no regular weeks left"
        lines.append(f"Simulated rotation, FP/wk ({horizon}; playoff weeks {'-'.join(map(str, po))}): us "
                     f"{sim_delta(lg, res, 'us', reg):+.1f} (PO {sim_delta(lg, res, 'us', po):+.1f}) vs flat {us['d']:+.1f}; "
                     f"{teams[res['them']]['name']} {sim_delta(lg, res, 'they', reg):+.1f} vs flat {they['d']:+.1f}"
                     + (" (open roster spots stay empty: a waiver add's bench value isn't counted)"
                        if us["open"] or they["open"] else ""))
    gap = us["d"] - they["d"]
    if us["d"] >= 0 and they["d"] >= 0:
        note = "win-win on our board (fit/bench gains on both sides)"
    elif abs(gap) < 2:
        note = "roughly even"
    else:
        note = f"lopsided toward {'us' if gap > 0 else 'them'} by {abs(gap):.1f}/wk"
    lines.append(f"Fairness: {note} (our board). Acceptance uses their view: board V at each player's Sleeper rank.")
    if set(they["view_drop"]) != set(they["drop"]) or they["view_ir"] != they["ir"]:
        lines.append(f"  Their-view roster fit: drop {nm(they['view_drop']) or '-'}; "
                     f"IR {nm(sorted(they['view_ir'])) or '-'} (separate from our-board fit above)")
    return "\n".join(lines)


def suggest(lg, top=10, min_gain=1.0, playoff=False):
    """1-for-1, 2-for-1 and 1-for-2 trades that gain us >= min_gain while, in their view, they lose < ACCEPT_COST.
    Ranked by our regular-season gain, or with playoff by the playoff-weighted gain (same filter); with a schedule,
    the leaders are then re-ranked by our simulated gain over the same horizon (sim_value)."""
    me, P = lg["me"], lg["players"]
    out = []
    # ponytail: only their top 10 by V are targets (bounds combos to ~1.7k per team);
    # their lower players matter only as drops, which fit_roster still handles.
    ours = lg["teams"][me]["players"]
    for rid, t in lg["teams"].items():
        if rid == me:
            continue
        theirs = sorted(t["players"], key=lambda p: -P[p]["v"])[:10]
        deals = ([((a,), (b,)) for a in ours for b in theirs]
                 + [(g, (b,)) for g in itertools.combinations(ours, 2) for b in theirs]
                 + [((a,), g) for a in ours for g in itertools.combinations(theirs, 2)])
        for give, gt in deals:
            r = evaluate(lg, list(give), list(gt), me, rid)
            # Skip unprojected players only where they touch our value: moved, or dropped by us (their drops don't).
            if r["us"]["d"] >= min_gain and plausible(r) and not any(
                    not P[p].get("proj", True) for p in list(give) + list(gt) + r["us"]["drop"]):
                out.append(r)
    out.sort(key=lambda r: -(po_delta(lg, r) if playoff else r["us"]["d"]))
    if lg.get("sched"):  # re-rank the flat leaders by our simulated gain; acceptance stays their flat view
        # ponytail: only the flat top 3 x top are simulated (~0.5 s per roster). Upgrade: widen the cut if
        # strong simulated deals keep appearing near it.
        weeks = sim_weeks(lg)[1 if playoff else 0]
        out = sorted(out[:3 * top], key=lambda r: -sim_delta(lg, r, "us", weeks))
    return out[:top]


def suggest_line(lg, r):
    nm = lambda pids: " + ".join(f"{lg['players'][p]['name']} ({lg['players'][p]['v']:.1f})" for p in pids)
    drops = "; ".join(f"{who} drop {', '.join(lg['players'][p]['name'] for p in r[s]['drop'])}"
                      for s, who in (("us", "we"), ("they", "they")) if r[s]["drop"])
    view = r["they"]["view_drop"]  # acceptance assumed this drop, so show it when our-board fit drops someone else
    po = f" ({po_delta(lg, r):+5.1f} PO)" if lg.get("po") else ""
    if lg.get("sched"):
        reg, pw = sim_weeks(lg)
        po += f" [sim {sim_delta(lg, r, 'us', reg):+5.1f}, PO {sim_delta(lg, r, 'us', pw):+5.1f}]"
    return (f"{r['us']['d']:+5.1f} us{po} / {r['they']['d']:+5.1f} them ({r['they']['d_view']:+5.1f} their view)"
            f"  {lg['teams'][r['them']]['name']:<14}"
            f" give {nm(r['give'])}  get {nm(r['get'])}" + (f"  ({drops})" if drops else "")
            + (f"  (they'd drop {', '.join(lg['players'][p]['name'] for p in view) or 'nobody'} (their view))"
               if set(view) != set(r["they"]["drop"]) else ""))


def test_forced_drop():
    players = {str(v): dict(pos=["PG"], v=v, ir=False, inj=None) for v in (10, 9, 8, 7, 6)}
    players["c"] = dict(pos=["C"], v=1, ir=False, inj=None)
    lg = dict(players=players, slots=["G", "C"], limit=5, ir_slots=2)
    kept, dropped, ir = fit_roster(lg, list(players))
    assert dropped == ["6"] and "c" in kept, dropped
    assert abs(sum(team_value(lg, kept)[:2]) - 25.4) < 1e-9
    lg["limit"] = 4
    kept, dropped, ir = fit_roster(lg, list(players))
    assert set(dropped) == {"c", "6"}, dropped
    assert abs(sum(team_value(lg, kept)[:2]) - 24.4) < 1e-9


def test_view_drops_and_ir():
    def pl(name, v, sv=None, inj=None):
        return dict(name=name, v=v, sv=v if sv is None else sv, pos=["C"], ir=False, inj=inj, rank=None)

    lg = dict(slots=["C", "UTIL"], limit=3, ir_slots=1, me=1,
              players=dict(u1=pl("U1", 8), u2=pl("U2", 7), t1=pl("T1", 10),
                           t2=pl("T2", 1, 20), t3=pl("T3", 6, 1)),
              teams={1: dict(name="Us", players=["u1", "u2"]),
                     2: dict(name="Them", players=["t1", "t2", "t3"])})
    r = evaluate(lg, ["u1", "u2"], ["t1"])
    assert r["they"]["drop"] == ["t2"] and r["they"]["view_drop"] == ["t3"], r["they"]
    assert abs(r["they"]["d_view"] - 1.6) < 1e-9 and plausible(r), r["they"]
    assert "Their-view roster fit: drop T3" in report(lg, r)
    # --suggest shows the drop acceptance assumed (regression: only the our-board drop T2 was listed).
    # Each side's drop is labelled (regression: "(drop X)" merged both sides' drops).
    assert suggest_line(lg, r).endswith("(they drop T2)  (they'd drop T3 (their view))"), suggest_line(lg, r)
    lg["players"]["t2"]["sv"], lg["players"]["t3"]["sv"], lg["memo"] = 1, 6, {}
    assert "their view))" not in suggest_line(lg, evaluate(lg, ["u1", "u2"], ["t1"]))  # same drop: not repeated

    lg = dict(slots=["C"], limit=2, ir_slots=1, me=1,
              players=dict(a=pl("A", 10), injured=pl("Injured", 1, inj="IR"),
                           b=pl("B", 5), c=pl("C", 4)),
              teams={1: dict(name="Us", players=["a", "injured"]),
                     2: dict(name="Them", players=["b", "c"])})
    for status in ("IR", "Sus", "DNR"):
        lg["players"]["injured"]["inj"] = status
        r = evaluate(lg, ["a"], ["b", "c"])
        assert not r["us"]["drop"] and r["us"]["ir"] == {"injured"}, r["us"]
        assert "Must drop" not in report(lg, r)
    lg["players"]["injured"]["inj"] = "Out"
    r = evaluate(lg, ["a"], ["b", "c"])
    assert r["us"]["drop"] == ["injured"] and not r["us"]["ir"], r["us"]
    lg["ir_slots"] = 0
    lg["players"]["injured"]["inj"] = "IR"
    assert evaluate(lg, ["a"], ["b", "c"])["us"]["drop"] == ["injured"]

    # Regression (PR #6 review): an active IR-eligible star was reserved although the trade already fit the roster,
    # so his V counted before but not after and a +1 V/wk upgrade read as -49. IR moves now happen only to make
    # room and never change value.
    lg = dict(slots=["UTIL", "UTIL"], limit=3, ir_slots=1, me=1,
              players=dict(star=pl("Star", 50, inj="IR"), x=pl("X", 10), y=pl("Y", 11), z=pl("Z", 1), w=pl("W", 4)),
              teams={1: dict(name="Us", players=["star", "x"]), 2: dict(name="Them", players=["y", "z", "w"])})
    r = evaluate(lg, ["x"], ["y"])
    assert abs(r["us"]["d"] - 1.0) < 1e-9 and r["us"]["ir"] == set() and not r["us"]["drop"], r["us"]
    lg["memo"] = {}
    r = evaluate(lg, ["x"], ["y", "z", "w"])  # 4 active > 3: reserving the star makes room at no value cost
    assert r["us"]["ir"] == {"star"} and not r["us"]["drop"], r["us"]
    assert abs(r["us"]["d"] - (50 + 11 + 0.6 * (4 + 1) - (50 + 10))) < 1e-9, r["us"]


def test_unprojected_drops():
    def pl(name, v, proj=True, sv=None):
        return dict(name=name, pos=["C"], v=v, sv=v if sv is None else sv, ir=False, inj=None, rank=None, proj=proj)
    # Our fit keeps an unprojected player when a projected drop costs the same (regression: his 0 V sorted first,
    # so he was always the drop and every 1-for-2 vanished from --suggest). Dropping U, E or T2 all cost 0 here.
    lg = dict(slots=["C"], limit=6, ir_slots=0, me=1,
              players=dict(a=pl("A", 10), b=pl("B", 5, sv=20), c=pl("C", 4), d=pl("D", 3), e=pl("E", 1),
                           u=pl("U", 0, False), t1=pl("T1", 12), t2=pl("T2", 2), t3=pl("T3", 1), t4=pl("T4", 1)),
              teams={1: dict(name="Us", players=list("abcdeu")), 2: dict(name="Them", players=["t1", "t2", "t3", "t4"])})
    r = evaluate(lg, ["b"], ["t1", "t2"])
    assert r["us"]["drop"] == ["e"] and not r["unproj"] and plausible(r), r
    assert (["b"], ["t1", "t2"]) in [(x["give"], x["get"]) for x in suggest(lg, top=50, min_gain=0.0)]
    # Their unprojected drop doesn't touch our value: --suggest keeps the deal and the report still flags him
    # (regression: three live 2-for-1s were hidden by the other side's drop).
    lg = dict(slots=["C"], limit=3, ir_slots=0, me=1,
              players=dict(x=pl("X", 5, sv=12), y=pl("Y", 4, sv=5), z=pl("Z", 1),
                           t1=pl("T1", 12), t2=pl("T2", 2), tu=pl("TU", 0, False)),
              teams={1: dict(name="Us", players=["x", "y", "z"]), 2: dict(name="Them", players=["t1", "t2", "tu"])})
    r = evaluate(lg, ["x", "y"], ["t1"])
    assert r["they"]["drop"] == ["tu"] and r["unproj"] == ["tu"] and plausible(r), r
    assert "UNPROJECTED (no board V" in report(lg, r) and "TU" in report(lg, r)
    assert (["x", "y"], ["t1"]) in [(x["give"], x["get"]) for x in suggest(lg, top=50, min_gain=0.0)]


def test_sim():
    # Week 2 (Mon 2026-10-26): team A plays Mon/Wed/Fri, B Tue/Thu/Sat. Nine A starters; X (A) and Y (B) have the
    # same V and FP/g, so the flat valuation ties them, but only Y fills the starters' idle nights.
    day = lambda i: (datetime.date(2026, 10, 26) + datetime.timedelta(i)).isoformat()
    sched = [{"week": 2, "date": day(i), "home": {"team": t}, "away": {"team": "Z" + t}}
             for t, ds in (("A", (0, 2, 4)), ("B", (1, 3, 5))) for i in ds]

    def pl(name, team, v, fpg, sv=None, out=0.0):
        return dict(name=name, team=team, v=v, fpg=fpg, sv=v if sv is None else sv, out=out,
                    pos=["PG", "SG", "SF", "PF", "C"], ir=False, inj=None, rank=None)
    P = {f"s{i}": pl(f"S{i}", "A", 20, 45, out=0.05) for i in range(9)}
    P.update(u=pl("U", "A", 5, 32, sv=8), x=pl("X", "A", 8, 35, sv=4), y=pl("Y", "B", 8, 35, sv=4))
    lg = dict(slots=gm.SLOTS, limit=14, ir_slots=2, me=1, players=P, sched=sched, today=datetime.date(2026, 10, 20),
              teams={1: dict(name="Us", players=[f"s{i}" for i in range(9)] + ["u"]), 2: dict(name="Them", players=["x", "y"])})
    assert sim_weeks(lg) == ((2,), PO_SCORED), sim_weeks(lg)
    # One player out 5% of weeks keeps 95% of his week (first-order absences are exact for one player).
    one = sim_value(lg, ["s0"], (2,))
    assert one > 0 and abs(one - 0.95 * sim_value(dict(lg, players=dict(P, s0=dict(P["s0"], out=0.0)), sim={}), ["s0"], (2,))) < 1e-9
    rx, ry = evaluate(lg, ["u"], ["x"]), evaluate(lg, ["u"], ["y"])
    assert abs(rx["us"]["d"] - 1.8) < 1e-9 and abs(ry["us"]["d"] - 1.8) < 1e-9, (rx["us"]["d"], ry["us"]["d"])
    sx, sy = sim_delta(lg, rx, "us", (2,)), sim_delta(lg, ry, "us", (2,))
    assert sy > sx + 1, (sx, sy)  # Y adds idle-night rolls; X, like U, only covers absent weeks
    deals = lambda lg: [(r["give"], r["get"]) for r in suggest(lg, top=10, min_gain=0.0)]
    flat = deals(dict(lg, sched=None, memo={}))
    assert flat.index((["u"], ["x"])) < flat.index((["u"], ["y"])), flat  # flat tie keeps roster order
    sim = deals(lg)
    assert sim.index((["u"], ["y"])) < sim.index((["u"], ["x"])), sim  # the simulation ranks the complement higher
    assert f"[sim {sy:+5.1f}," in suggest_line(lg, ry), suggest_line(lg, ry)
    assert f"Simulated rotation, FP/wk (weeks 2-2; playoff weeks 22-23): us {sy:+.1f} (PO +0.0) vs flat +1.8" in report(lg, ry)


def test_errors():
    """A name typo is an ERROR (input), never REFUSING, which the charter reserves for failed league checks; a
    league whose scoring changed is REFUSED (regression: load_league checked only the sport)."""
    import tempfile
    g, tmp = globals(), tempfile.mkdtemp()  # main reads PRIVATE/config.json, which a fresh clone (CI) lacks
    with open(os.path.join(tmp, "config.json"), "w") as f:
        f.write("{}")
    saved = g["load_league"], g["get"], sys.argv, g["PRIVATE"]
    lg = dict(slots=["C"], limit=2, ir_slots=0, me=1, players={"u": dict(name="U", pos=["C"], v=1.0)},
              teams={1: dict(name="Us", players=["u"]), 2: dict(name="Them", players=[])})
    league = {"league_id": "L", "sport": "nba", "roster_positions": gm.ROSTER_POSITIONS, "season": "2026",
              "scoring_settings": dict(rb.SCORING, to=-1.0), "settings": {"reserve_allow_out": 0, "reserve_slots": 2}}
    try:
        g["load_league"], sys.argv, g["PRIVATE"] = (lambda cfg: lg), ["trade.py", "Nobody", "U"], tmp
        try:
            main()
        except SystemExit as e:
            assert str(e.code).startswith("ERROR: 'Nobody' matches no player"), e.code
        else:
            raise AssertionError("a typo was accepted")
        g["get"] = lambda path: {"": league, "/rosters": [{"roster_id": 4, "owner_id": "u4"}], "/users": []}[path[len("/league/L"):]]
        try:
            saved[0]({"league_id": "L", "user_id": "u4"})
        except SystemExit as e:
            assert str(e.code).startswith("REFUSING: scoring is"), e.code
        else:
            raise AssertionError("a scoring change was not refused")
    finally:
        g["load_league"], g["get"], sys.argv, g["PRIVATE"] = saved


def test():
    test_forced_drop()
    test_sim()
    test_view_drops_and_ir()
    def pl(name, pos, v, inj=None, sv=None):
        return {"name": name, "pos": pos, "v": v, "inj": inj, "rank": None, "ir": False, "sv": v if sv is None else sv}
    P = {"a1": pl("Alpha One", ["PG"], 10), "a2": pl("Alpha Two", ["C"], 6), "a3": pl("Alpha Three", ["PG"], 4),
         "b1": pl("Bravo One", ["C"], 9), "b2": pl("Bravo Two", ["SG"], 5), "b3": pl("Bravo Three", ["C"], 2, "Out"),
         "c1": pl("Charlie One", ["PG"], 7), "c2": pl("Alpha Twin", ["C"], 1)}
    lg = {"slots": ["G", "C"], "limit": 3, "ir_slots": 2, "me": 1, "players": P,
          "teams": {1: {"name": "Us", "players": ["a1", "a2", "a3"]},
                    2: {"name": "Bravo", "players": ["b1", "b2", "b3"]},
                    3: {"name": "Charlie", "players": ["c1", "c2"]}}}

    def refuses(fn, text):
        try:
            fn()
        except ValueError as e:
            assert text in str(e), e
        else:
            raise AssertionError("expected refusal: " + text)
    # Name resolution and roster checks
    refuses(lambda: trade_from_names(lg, "Nobody", "Bravo One"), "no player on")
    refuses(lambda: trade_from_names(lg, "Bravo Two", "Bravo One"), "no player on")  # not ours
    refuses(lambda: trade_from_names(lg, "Alpha One", "Bravo One, Charlie One"), "one other roster")
    refuses(lambda: trade_from_names(lg, "Alpha", "Bravo One"), "ambiguous")
    refuses(lambda: trade_from_names(lg, "Alpha One", "Bravo One", "Charlie"), "no player on")
    refuses(lambda: evaluate(lg, ["a1"], ["a2"], 1, 1), "already on our roster")
    assert resolve(lg, "alpha one, bravo two", [1, 2]) == ["a1", "b2"]

    # 1-for-1, hand-checked (BENCH_W 0.6). Us: G a1 10 + C a2 6, bench a3 4*0.6=2.4 -> 18.4.
    # After a1 for b1: G a3 4 + C b1 9 = 13 (-3), bench a2 6*0.6=3.6 (+1.2) -> -1.8.
    # Bravo: G b2 5 + C b1 9 + bench b3 1.2 = 15.2 -> G a1 10 + C b3 2 + bench b2 3.0 = 15.0 (-0.2).
    assert BENCH_W == 0.6
    r = trade_from_names(lg, "Alpha One", "Bravo One", "Bravo")
    assert abs(r["us"]["d_start"] + 3.0) < 1e-9 and abs(r["us"]["d_bench"] - 1.2) < 1e-9, r["us"]
    assert abs(r["they"]["d"] + 0.2) < 1e-9, r["they"]
    assert not r["us"]["drop"] and not r["they"]["drop"]
    out = report(lg, r)
    assert "NOT ACCEPTABLE for us: -1.8/wk" in out and "-- likely to accept" in out, out
    assert "  Starters out: Alpha One (G), Alpha Two (C) | in: Alpha Three (G), Bravo One (C)" in out, out
    assert "  Bench out: Bravo Three [Out] | in: Bravo Two" in out, out
    assert "OUT, no IR" in label(lg, "b3")

    # 2-for-1: a2+a3 for b1. Bravo reaches 4 > limit 3 and drops its worst (b3, V 2).
    # Us: G a1 10 + C b1 9 = 19 vs 18.4 -> +0.6, one open spot.
    # Bravo: C a2 6 + G b2 5 + bench a3 2.4 = 13.4 vs 15.2 -> -1.8.
    r = evaluate(lg, ["a2", "a3"], ["b1"])
    assert r["them"] == 2 and r["they"]["drop"] == ["b3"] and r["us"]["open"] == 1, r
    assert abs(r["us"]["d"] - 0.6) < 1e-9 and abs(r["they"]["d"] + 1.8) < 1e-9, (r["us"]["d"], r["they"]["d"])
    assert "Must drop (roster full): Bravo Three" in report(lg, r)
    # 1-for-2 with Charlie (2 players): we reach 4 and drop c2; Charlie opens a spot.
    r = evaluate(lg, ["a3"], ["c1", "c2"])
    assert r["us"]["drop"] == ["c2"] and not r["they"]["drop"] and r["they"]["open"] == 1, r
    assert suggest_line(lg, r).endswith("  (we drop Alpha Twin)"), suggest_line(lg, r)

    # Suggest on a toy league where positional fit makes one win-win.
    # Us u1 PG10, u2 C6, u3 C5 = 16 + bench 3.0 = 19. Them t1 PG7, t2 PG3 (no C) = 7 + 1.8 = 8.8.
    # u3 for t1: us 16 + bench t1 4.2 = 20.2 (+1.2); them G t2 3 + C u3 5 = 8 (-0.8, plausible).
    # u2 for t1 gains us only +0.2; u3 for t1+t2 costs them 3.8; the rest lose for us.
    toy = {"slots": ["G", "C"], "limit": 3, "ir_slots": 2, "me": 1,
           "players": {"u1": pl("U1", ["PG"], 10), "u2": pl("U2", ["C"], 6), "u3": pl("U3", ["C"], 5),
                       "t1": pl("T1", ["PG"], 7), "t2": pl("T2", ["PG"], 3)},
           "teams": {1: {"name": "Us", "players": ["u1", "u2", "u3"]},
                     2: {"name": "Them", "players": ["t1", "t2"]}}}
    s = suggest(toy, top=5, min_gain=0.4)
    assert [(x["give"], x["get"]) for x in s] == [(["u3"], ["t1"])], s
    assert abs(s[0]["us"]["d"] - 1.2) < 1e-9 and abs(s[0]["they"]["d"] + 0.8) < 1e-9, s[0]
    assert suggest(toy, min_gain=1.3) == []
    # Their view (sv) decides acceptance. If they rate t2 at 9, giving t1 costs them nothing:
    # before G t2 9 + bench t1 4.2 = 13.2; after G t2 9 + C u3 5 = 14 -> +0.8 -> likely.
    toy["players"]["t2"]["sv"], toy["memo"] = 9, {}
    r = evaluate(toy, ["u3"], ["t1"])
    assert abs(r["they"]["d_view"] - 0.8) < 1e-9, r["they"]
    assert plausible(r) and "+0.8 in their Sleeper-rank view -- likely" in report(toy, r), report(toy, r)
    # If they rate t1 at 20 (t2 back to 3): before G t1 20 + bench 1.8; after G t2 3 + C u3 5 -> -13.8.
    toy["players"]["t1"]["sv"], toy["players"]["t2"]["sv"], toy["memo"] = 20, 3, {}
    assert not plausible(evaluate(toy, ["u3"], ["t1"]))

    # IR (regression: an incoming player from their IR stayed IR and we ended with 3 IR for 2 slots; IR
    # players were valued in the lineup and bench). Limit 2 active + 1 IR slot; everyone is a C.
    ir = lambda name, v: dict(pl(name, ["C"], v, "IR"), ir=True)
    irl = {"slots": ["C"], "limit": 2, "ir_slots": 1, "me": 1,
           "players": {"u1": pl("U1", ["C"], 10), "u2": pl("U2", ["C"], 6), "uI": ir("UI", 8),
                       "t1": pl("T1", ["C"], 5), "t2": pl("T2", ["C"], 1), "tI": ir("TI", 9)},
           "teams": {1: {"name": "Us", "players": ["u1", "u2", "uI"]}, 2: {"name": "Them", "players": ["t1", "t2", "tI"]}}}
    assert abs(sum(team_value(irl, ["u1", "u2", "uI"])[:2]) - 18.4) < 1e-9  # u1 10 + bench (uI 8 + u2 6) * 0.6
    r = evaluate(irl, ["u2"], ["tI"])  # our one IR slot is full: TI arrives active, no drop needed
    assert r["us"]["ir"] == {"uI"} and not r["us"]["drop"] and abs(r["us"]["d"] - 1.8) < 1e-9, r["us"]
    assert r["they"]["drop"] == ["t2"] and r["they"]["ir"] == set(), r["they"]
    irl["teams"][1]["players"].remove("uI")
    r = evaluate(irl, ["u2"], ["tI"])  # roster fits, so no IR move; he keeps his season V: bench 9 * 0.6 vs 6 * 0.6
    assert r["us"]["ir"] == set() and abs(r["us"]["d"] - 1.8) < 1e-9 and r["us"]["open"] == 0, r["us"]

    # Playoff schedule. Weeks 22 and 23 start Mon 2027-03-15 and 03-22; each team repeats its pattern in both.
    # A4 Mon/Wed/Fri/Sun, B4 Mon/Tue/Thu/Sat (Tue is a second night), A3 Mon/Wed/Fri, A2 Mon/Wed.
    # A4's Sun 03-21 -> Mon 03-22 is a back-to-back across the week boundary.
    day = lambda w, i: (datetime.date(2027, 3, 15) + datetime.timedelta(7 * (w - 22) + i)).isoformat()
    pat = {"A4": [0, 2, 4, 6], "B4": [0, 1, 3, 5], "A3": [0, 2, 4], "A2": [0, 2]}
    sched = [{"week": w, "date": day(w, i), "home": {"team": t}, "away": {"team": "Z" + t}}
             for w in (22, 23) for t, ds in pat.items() for i in ds]
    po = playoff_profile(sched)
    m = {t: po[t]["mult"][1] for t in pat}
    assert m["A4"] > m["B4"] > m["A3"] > m["A2"] > 0, m
    assert m["A3"] < 1 < m["B4"], m  # the base is a 3.4-game week
    assert po["A4"]["games"] == [0, 4, 4] and po["A4"]["b2b"] == [0, 0, 1] and po["B4"]["b2b"] == [0, 1, 1], po
    assert po["A4"]["mult"][0] == 0 and po["A4"]["mult"][2] < m["A4"], po["A4"]  # no week-21 games; week-23 B2B
    # B2B penalty: one early second night (q 0.12, not 0.08) costs B4 only ~0.25%; a sat game mostly loses one roll.
    assert 0.001 < m["A4"] - m["B4"] < 0.01, m
    # Report: a1 (A4) and a2 (no team) out, a3 (no team) and b1 (A2) in -> -1.8 + (m_A2 - 1) 9 - (m_A4 - 1) 10,
    # each m the mean over PO_SCORED weeks 22-23.
    m = {t: sum(po[t]["mult"][1:]) / 2 for t in pat}
    for pid, t in (("a1", "A4"), ("b1", "A2"), ("b2", "B4")):
        P[pid]["team"] = t
    lg["po"], lg["memo"] = po, {}
    r = trade_from_names(lg, "Alpha One", "Bravo One", "Bravo")
    want = -1.8 + (m["A2"] - 1) * 9 - (m["A4"] - 1) * 10
    assert abs(po_delta(lg, r) - want) < 1e-9 and want < -1.8, (po_delta(lg, r), want)
    out = report(lg, r)
    assert f"Alpha One (PG, V+10.0, sleeper#?, A4 PO 0/4/4 x{m['A4']:.2f})" in out, out
    assert f"Playoff-weighted for us: {want:+.1f}/wk vs -1.8 regular season (changed starters' V x their week 22-23" in out, out
    assert "Alpha Three (PG, V+4.0, sleeper#?)" in label(lg, "a3")  # no team: no PO tag, multiplier 1
    # --playoff re-ranks only. u2 for t1 swaps starter u2 for u3; a 2x u3 schedule lifts it from +0.2 to +5.2,
    # above u3 for t1 (+1.2, starters unchanged so PO = regular).
    toy["players"]["t1"]["sv"], toy["memo"] = 7, {}
    toy["players"]["u3"]["team"], toy["po"] = "U3", {"U3": {"games": [3, 3, 3], "mult": [1.0, 2.0, 2.0]}}
    reg, pof = suggest(toy, min_gain=0.1), suggest(toy, min_gain=0.1, playoff=True)
    assert [x["give"] for x in reg] == [["u3"], ["u2"]] and [x["give"] for x in pof] == [["u2"], ["u3"]], (reg, pof)
    assert abs(po_delta(toy, pof[0]) - 5.2) < 1e-9 and abs(po_delta(toy, pof[1]) - 1.2) < 1e-9
    # Unprojected players (no board V) are unknown, not worthless: --suggest skips deals that move or drop
    # them, and a single report flags them. Giving away unprojected u4 (0.0 V to us, 5 in their view) looks like a free +1.8.
    unp = {"slots": ["G", "C"], "limit": 3, "ir_slots": 2, "me": 1,
           "players": {"u1": pl("U1", ["PG"], 10), "u2": pl("U2", ["C"], 6), "u4": dict(pl("U4", ["PG"], 0, sv=5), proj=False),
                       "t1": pl("T1", ["PG"], 7), "t2": pl("T2", ["C"], 3)},
           "teams": {1: {"name": "Us", "players": ["u1", "u2", "u4"]}, 2: {"name": "Them", "players": ["t1", "t2"]}}}
    r = evaluate(unp, ["u4"], ["t2"])
    assert r["unproj"] == ["u4"] and r["us"]["d"] > 0, r
    assert "UNPROJECTED (no board V" in report(unp, r) and "U4" in report(unp, r)
    assert all("u4" not in x["give"] for x in suggest(unp, top=50, min_gain=0.0)), suggest(unp, top=50, min_gain=0.0)
    unp["players"]["u4"]["proj"], unp["memo"] = True, {}
    assert any(x["give"] == ["u4"] for x in suggest(unp, top=50, min_gain=0.0))
    test_unprojected_drops()
    test_errors()
    print("ok")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("give", nargs="?")
    ap.add_argument("get", nargs="?")
    ap.add_argument("--with", dest="with_team", help="counterparty display name or roster_id")
    ap.add_argument("--suggest", action="store_true")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--min", type=float, default=1.0, help="minimum gain for us in --suggest (V/wk)")
    ap.add_argument("--playoff", action="store_true", help="rank --suggest by the playoff-weighted gain")
    ap.add_argument("--test", action="store_true")
    a = ap.parse_args()
    if a.test:
        return test()
    if not a.suggest and not (a.give and a.get):
        ap.error('give "<names>" and get "<names>", or --suggest')
    if a.playoff and not a.suggest:
        ap.error("--playoff ranks --suggest; a single trade report always shows the playoff-weighted delta")
    lg = load_league(json.load(open(os.path.join(PRIVATE, "config.json"))))
    if a.suggest:
        res = suggest(lg, a.top, a.min, a.playoff)
        print(f"Top {len(res)} trades: we gain >= {a.min:g} V/wk, they lose < {ACCEPT_COST:g} in their Sleeper-rank view"
              + (", ranked by playoff-weighted gain (PO)" if a.playoff else "")
              + (f"; the top {3 * a.top} re-ranked by simulated rotation gain [sim{', PO' if a.playoff else ''}]"
                 if lg.get("sched") else ""))
        for r in res:
            print("  " + suggest_line(lg, r))
        return
    try:
        print(report(lg, trade_from_names(lg, a.give, a.get, a.with_team)))
    except ValueError as e:
        sys.exit(f"ERROR: {e}")  # an input mistake, not a failed league check: REFUSING would halt all advice


if __name__ == "__main__":
    main()
