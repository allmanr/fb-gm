"""Issue #9: do win-probability lock calls beat gm.py's EV thresholds? 2025-26 logs replayed as league-weeks.

League-week: 10 teams x 9 slots, one player per slot (no bench rotation), one per 10-rank band of the top 90
by FP/g (40+ games) available that week, and a random 2025-26 week. Pairs (0,1), (2,3), ... play H2H; everyone plays the median.
Every team locks by gm.py's EV rule (lock if score >= stop_value of his remaining games, play_on DNP chances).
Then each team in turn switches to the win-odds rule while the other nine stay on EV: after each game day,
each of its unlocked slots that just played with games left picks LOCK or WAIT to maximize
P(win H2H) + P(beat median), given every slot's current state (locked score, or EV continuation moments).
Outcomes are the real box scores (DNP = 0); the model only sees causal FP/g (q12.causal_ppg).

ponytail: no bench rotation or positions; team totals normal (summed slot moments, as gm.win_odds); a WAIT is
valued as an EV continuation; slots deciding the same night are decided one at a time. Ceiling: a policy with
exact slot distributions and joint decisions could gain a bit more; upgrade only if this one comes close to the gate.
Usage: python3 q9.py [league_weeks=600] [seed=9]
"""
import datetime, math, random, sys
from functools import lru_cache
from statistics import NormalDist
from lib import load, season_stats, r1, REPO  # noqa: F401 (REPO puts gm on sys.path)
from q12 import causal_ppg
import gm

D = load()
W, SS = D['weeks'], season_stats(D['weeks'])
TOP = sorted((p for p, (m, g) in SS.items() if g >= 40), key=lambda p: -SS[p][0])[:120]
CZ = {p: causal_ppg(p) for p in TOP}
PHI = NormalDist().cdf
XS = [NormalDist().inv_cdf((i + 0.5) / 40) for i in range(40)]


@lru_cache(maxsize=None)
def moments(ppg, plays):
    """(mean, second moment) of a slot's locked score under EV stopping over plays (one roll each)."""
    return gm.stop_moments([[(ppg, p)] for p in plays])


def p_beat_median(me, others):
    """P(me > median of all 10 totals) = P(at least 5 of the 9 others score below me). Normal totals."""
    m, v = me
    sd, tot = math.sqrt(max(v, 1e-9)), 0.0
    for z in XS:
        x = m + sd * z
        dist = [1.0]  # Poisson-binomial over 'other team below me'
        for om, ov in others:
            q = PHI((x - om) / math.sqrt(max(ov, 1e-9)))
            dist = [a * (1 - q) + b * q for a, b in zip(dist + [0.0], [0.0] + dist)]
        tot += sum(dist[5:])
    return tot / len(XS)


def objective(me, opp, others):
    h2h = PHI((me[0] - opp[0]) / math.sqrt(max(me[1] + opp[1], 1e-9)))
    return h2h + p_beat_median(me, others)


class Slot:
    def __init__(self, p, w):
        self.games = [(datetime.date.fromisoformat(d), s) for d, s in W[p][w]]
        dates = {d for d, _ in self.games}
        self.ppg = r1(CZ[p][w])
        self.play = {d: gm.play_on(d, dates) for d in dates}
        self.locked = None  # locked score
        self.last = None  # latest game's score (0 on DNP)
        self.done = 0  # games rolled

    def rest(self):
        return tuple(self.play[d] for d, _ in self.games[self.done:])

    def wait(self):
        return moments(self.ppg, self.rest())

    def state(self):
        """(mean, variance) of the slot's final score from now on, EV policy hereafter."""
        if self.locked is not None:
            return self.locked, 0.0
        if not self.rest():
            return self.last or 0.0, 0.0
        m, m2 = self.wait()
        return m, max(0.0, m2 - m * m)

    def can_lock(self, day):
        return (self.locked is None and self.done and self.games[self.done - 1][0] == day
                and self.games[self.done - 1][1] is not None and self.rest())

    def ev_lock(self):
        return self.last >= self.wait()[0]


def total(team):
    ms = [s.state() for s in team]
    return sum(m for m, _ in ms), sum(v for _, v in ms)


def final(team):
    return sum(s.locked if s.locked is not None else (s.last or 0.0) for s in team)


def play_week(teams, w, wp=None):
    """Replay week w; team index wp uses the win-odds rule. -> final totals, wp's decision log."""
    for t in teams:
        for s in t:
            s.locked, s.last, s.done = None, None, 0
    days = sorted({d for t in teams for s in t for d, _ in s.games})
    log = []
    for day in days:
        for t in teams:
            for s in t:
                if s.done < len(s.games) and s.games[s.done][0] == day:
                    s.last = s.games[s.done][1] or 0.0
                    s.done += 1
        for i, t in enumerate(teams):
            if i != wp:
                for s in t:
                    if s.can_lock(day) and s.ev_lock():
                        s.locked = s.last
        if wp is None:
            continue
        me, opp = teams[wp], teams[wp ^ 1]
        others = [total(t) for i, t in enumerate(teams) if i != wp]
        o = total(opp)
        for s in me:
            if not s.can_lock(day):
                continue
            s.locked = s.last
            v_lock = objective(total(me), o, others)
            s.locked = None
            v_wait = objective(total(me), o, others)
            if v_lock > v_wait:
                s.locked = s.last
            log.append((s.ev_lock(), v_lock > v_wait))
    return [final(t) for t in teams], log


def wins(totals, i):
    h2h = 1.0 if totals[i] > totals[i ^ 1] else 0.5 if totals[i] == totals[i ^ 1] else 0.0
    mid = sorted(totals)
    return h2h + (totals[i] > (mid[4] + mid[5]) / 2)


def main(n=600, seed=9):
    rng = random.Random(seed)
    rows = []  # (league_week, pre-week P(H2H), EV wins, WP wins, decisions, flips)
    lw = 0
    while lw < n:
        w = rng.randint(1, 25)
        pool = [p for p in TOP if w in W[p] and any(s is not None for _, s in W[p][w])][:90]  # whole-week outs known
        if len(pool) < 90:
            continue
        bands = [pool[k * len(pool) // 9:(k + 1) * len(pool) // 9] for k in range(9)]
        picks = [rng.sample(b, 10) for b in bands]
        teams = [[Slot(picks[k][t], w) for k in range(9)] for t in range(10)]
        rng.shuffle(teams)
        pre = [total(t) for t in teams]
        base, _ = play_week(teams, w)
        for i in range(10):
            got, log = play_week(teams, w, wp=i)
            me, opp = pre[i], pre[i ^ 1]
            p0 = PHI((me[0] - opp[0]) / math.sqrt(me[1] + opp[1]))
            rows.append((lw, p0, wins(base, i), wins(got, i), len(log), sum(a != b for a, b in log)))
        lw += 1
    return rows


def summarize(rows, B=2000, seed=7):
    rng = random.Random(seed)
    by = {}
    for r in rows:
        by.setdefault(r[0], []).append(r)
    clusters = list(by.values())

    def gain(cs, f=lambda r: True):
        sel = [r for c in cs for r in c if f(r)]
        return 20 * sum(r[3] - r[2] for r in sel) / max(1, len(sel)), len(sel)

    groups = [('all', lambda r: True), ('favourite (pre-week H2H >= 60%)', lambda r: r[1] >= 0.6),
              ('even (40-60%)', lambda r: 0.4 <= r[1] < 0.6), ('underdog (< 40%)', lambda r: r[1] < 0.4)]
    print(f'league-weeks={len(clusters)} team-weeks={len(rows)} decisions={sum(r[4] for r in rows)} '
          f'flipped vs EV={sum(r[5] for r in rows)} ({sum(r[5] for r in rows) / max(1, sum(r[4] for r in rows)):.1%})')
    print(f'EV policy: {sum(r[2] for r in rows) / len(rows):.4f} wins/team-week (H2H + median)')
    for name, f in groups:
        g, k = gain(clusters, f)
        boots = sorted(gain([rng.choice(clusters) for _ in clusters], f)[0] for _ in range(B))
        print(f'  {name:32s} n={k:5d}  win-odds - EV = {g:+.3f} wins/20 weeks  '
              f'95% CI [{boots[int(.025 * B)]:+.3f}, {boots[int(.975 * B)]:+.3f}]')


if __name__ == '__main__':
    t = [[Slot(p, 5) for p in TOP[k::10][:9] if 5 in W[p]] for k in range(10)]
    assert play_week(t, 5)[0] == play_week(t, 5)[0]  # replay resets state
    assert abs(p_beat_median((100, 1), [(100, 1)] * 9) - 0.5) < 0.02
    assert p_beat_median((200, 1), [(100, 1)] * 9) > 0.99
    args = [int(x) for x in sys.argv[1:]]
    summarize(main(*args))
