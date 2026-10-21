"""Shared loaders + DP helpers for the Lock-In backtest (stdlib only)."""
import glob, json, math, os, sys, urllib.request
from collections import defaultdict
from functools import lru_cache

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..', '..'))  # reports/<date>/backtest -> repo root
sys.path.insert(0, REPO)
import rebuild_board as rb  # noqa: E402
from fit_lockin import SCORING  # noqa: E402

CACHE = os.path.join(HERE, 'games.json')
SEASONS = {'data': 2025, 'data24': 2024}  # folder -> Sleeper stats season


def week_file(folder, w):
    """Raw Sleeper weekly game logs, downloaded on first use (folders are gitignored)."""
    path = os.path.join(HERE, folder, f'w{w}.json')
    if not os.path.exists(path):
        url = f'https://api.sleeper.com/stats/nba/{SEASONS[folder]}/{w}?season_type=regular'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + '.tmp', 'wb') as f:
            f.write(data)
        os.replace(path + '.tmp', path)
    return path


def player_snapshot():
    """Sleeper /players/nba snapshot for fantasy_positions: $BACKTEST_PLAYERS, else the newest repo
    .cache/players-*.json, else a fresh download via draft.players(). The published run used the
    2026-10-19 snapshot; a later one can shift a few players' eligibility."""
    path = os.environ.get('BACKTEST_PLAYERS') or (sorted(glob.glob(os.path.join(REPO, '.cache', 'players-*.json'))) or [None])[-1]
    if not path:
        import draft
        draft.players()
        path = sorted(glob.glob(os.path.join(REPO, '.cache', 'players-*.json')))[-1]
    print(f'players snapshot: {path}', file=sys.stderr)
    return json.load(open(path))


def fp(stats):
    return sum((stats.get(k) or 0.0) * w for k, w in SCORING.items())


def _load_season(folder):
    """-> rows deduped by (pid, game_id): (week, date, team, gid, pid, fp or None)."""
    seen = {}
    for w in range(1, 26):
        for r in json.load(open(week_file(folder, w))):
            pid = str(r.get('player_id') or '')
            gid, team = r.get('game_id'), r.get('team')
            if not (pid.isdigit() and gid and team):
                continue
            s = r.get('stats') or {}
            score = fp(s) if (s.get('sp') or 0) > 0 else None
            key = (pid, gid)
            if key not in seen or seen[key][5] is None:
                seen[key] = (w, r['date'], team, gid, pid, score)
            if pid not in NAMES and r.get('player'):
                p = r['player']
                NAMES[pid] = f"{p.get('first_name','')} {p.get('last_name','')}".strip()
    return list(seen.values())


NAMES = {}


def build():
    """weeks[pid][week] = sorted [(date, fp or None)] over the player's team's games that week."""
    rows = _load_season('data')
    team_games = defaultdict(dict)  # (week, team) -> {gid: date}
    for w, d, t, g, p, s in rows:
        team_games[(w, t)][g] = d
    # A player belongs to team T in week w if he has any row (played or DNP row) for T that week.
    player_team_week = defaultdict(set)
    played = {}
    for w, d, t, g, p, s in rows:
        player_team_week[(p, w)].add(t)
        played[(p, g)] = s
    weeks = defaultdict(dict)
    for (p, w), teams in player_team_week.items():
        sched = []
        for t in teams:  # traded mid-week: union of both teams' games (rare)
            for g, d in team_games[(w, t)].items():
                sched.append((d, played.get((p, g))))
        sched.sort(key=lambda x: (x[0], x[1] is None))
        # same-date duplicates only happen on mid-week trades; keep the played one
        dedup = {}
        for d, s in sched:
            if d not in dedup or dedup[d] is None:
                dedup[d] = s
        weeks[p][w] = sorted(dedup.items())
    prior = defaultdict(list)
    for w, d, t, g, p, s in _load_season('data24'):
        if s is not None:
            prior[p].append(s)
    prior = {p: (sum(v) / len(v), len(v)) for p, v in prior.items()}
    return {'weeks': weeks, 'names': NAMES, 'prior': prior}


def load():
    if not os.path.exists(CACHE):
        json.dump(build(), open(CACHE, 'w'))
    d = json.load(open(CACHE))
    d['weeks'] = {p: {int(w): v for w, v in ws.items()} for p, ws in d['weeks'].items()}
    return d


def season_stats(weeks):
    """pid -> (mean FP/g over played games, games played)."""
    out = {}
    for p, ws in weeks.items():
        g = [s for v in ws.values() for _, s in v if s is not None]
        if g:
            out[p] = (sum(g) / len(g), len(g))
    return out


# ---- DP: continuation values with the board's normal/CV model -------------
def draws(ppg):
    cv = min(0.6, max(0.2, rb.CV_A + rb.CV_B * math.log(max(ppg, 1))))
    return [max(0.0, ppg * (1 + cv * z)) for z in rb.Z_GRID]


@lru_cache(maxsize=None)
def _draws(ppg):
    return tuple(draws(ppg))


@lru_cache(maxsize=None)
def seq_value(ppgs, q=0.0):
    """Expected locked score of a slot facing rolls ppgs[0..] in order (optimal stopping,
    last roll counts if never locked). Each roll is a DNP (score 0) with prob q."""
    v = 0.0
    for i, p in enumerate(reversed(ppgs)):
        ds = _draws(p)
        if i == 0:
            v = (1 - q) * sum(ds) / len(ds)
        else:
            v = (1 - q) * sum(max(x, v) for x in ds) / len(ds) + q * v
    return v


def r1(x):
    return round(x * 2) / 2  # 0.5 FP grid keeps the lru_cache small


if __name__ == '__main__':
    lv = rb.lock_values(40.0, 5)
    for k in range(1, 6):
        assert abs(seq_value((40.0,) * k) - lv[k]) < 1e-9, k
    assert seq_value((40.0, 40.0), 0.1) < lv[2]
    d = load()
    ss = season_stats(d['weeks'])
    reg = [p for p, (m, g) in ss.items() if g >= 40 and m >= 25]
    print('players', len(d['weeks']), 'regulars(40g,25fp)', len(reg))
    jok = next(p for p, n in d['names'].items() if n.startswith('Nikola Jok'))
    print('Jokic', ss[jok], d['weeks'][jok][3])
    print('ok')
