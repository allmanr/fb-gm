"""Q3 by simulation (issue #10): the bench factor implied by trade.sim_value on the 2026 board and schedule.

Same measure as q3.py's V-basis top 3: factor = [sim(top 9 + bench 10-12) - sim(top 9 + 3 replacements)]
/ (V of bench 10-12 - V of the 3 replacements), top 9 by board V. Random rosters take one player from each
10-rank band of the board's top 140 (players on an NBA team); replacements come from ranks 141-180. Pooled
sum N / sum D with a 2000-resample bootstrap, as q3_boot.py. Needs the network: live roster, Sleeper players
and the NBA schedule (cached daily in .cache/). Usage, from the repo root:
    python3 reports/2026-10-20/backtest/q3_sim.py [n_random=40] > reports/2026-10-20/backtest/q3_sim.out
"""
import json, os, random, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, ROOT)
import draft, gm, trade  # noqa: E402

lg = trade.load_league(json.load(open(os.path.join(ROOT, "private", "config.json"))))
pool = draft.players()
ranked, _, notes = draft.load_board(pool)
vals, out = gm.board_values(notes), trade.absences(pool)
board = [p for p in ranked if p in vals and pool[p].get("team")]
for p in board:
    lg["players"].setdefault(p, dict(team=pool[p]["team"], pos=gm.pos_of(pool, p), v=vals[p][0], fpg=vals[p][1],
                                     out=out.get(p, 0.0)))
P, weeks = lg["players"], trade.sim_weeks(lg)[0]
print(f"weeks {weeks[0]}-{weeks[-1]}; board players on a team {len(board)}; V at rank 140 {vals[board[139]][0]:.1f}, "
      f"ranks 141-180 mean V {sum(vals[p][0] for p in board[140:180]) / 40:.2f}")


def factor(roster, reps):
    r = sorted(roster, key=lambda p: -P[p]["v"])
    n = trade.sim_value(lg, r[:12], weeks) - trade.sim_value(lg, r[:9] + reps, weeks)
    return n, sum(P[p]["v"] for p in r[9:12]) - sum(P[p]["v"] for p in reps)


def pooled(rows):
    return sum(n for n, _ in rows) / sum(d for _, d in rows)


random.seed(7)
ours = [p for p in lg["teams"][lg["me"]]["players"] if P[p]["proj"]]
r = sorted(ours, key=lambda p: -P[p]["v"])
n, d = factor(ours, random.sample(board[140:180], 3))
print(f"ours: bench {', '.join(P[p]['name'] for p in r[9:12])}; team gain {n:+.1f} / V {d:.1f} = {n / d:.3f}")
rows = []
while len(rows) < (int(sys.argv[1]) if len(sys.argv) > 1 else 40):
    rows.append(factor([random.choice(board[i * 10:(i + 1) * 10]) for i in range(14)], random.sample(board[140:180], 3)))
boots = sorted(pooled([random.choice(rows) for _ in rows]) for _ in range(2000))
print(f"random rosters n={len(rows)}: pooled {pooled(rows):.3f} [{boots[50]:.3f},{boots[1949]:.3f}] "
      f"(backtest realistic V3: 0.595 [0.53,0.67]; ours 0.42)")
