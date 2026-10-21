# 2026-27 NBA schedule by Sleeper fantasy week

> Archived research. Rankings, injury claims, simulations, and pick advice below are historical. Use the [current league rules](../../prep-notes.md#league-rules) and a fresh `./draft.py` run for decisions. OUT players use a bench spot in this league. Old season-total scores and survival percentages are retired.

Source: Sleeper schedule API `api.sleeper.com/schedule/nba/regular/2026` (1,200 games, 80/team; 2 games/team TBD after NBA Cup group stage, all in the Dec 4-11 gap = weeks 7-8). Weeks are Mon-Sun.

League settings (Sleeper API): playoff_week_start=21, playoff_teams=6, one week per round -> **playoffs = weeks 21, 22, 23** (Mar 8-14, Mar 15-21, Mar 22-28 2027). Seeds 1-2 get a bye in week 21. Regular season = weeks 1-20 (trade deadline week 18). Weeks 24-25 (Mar 29-Apr 11) are not played.

League average games per week: w1 2.87, w2 3.27, w3 3.60, w4 3.40, w5 3.40, w6 3.20, w7 1.93, w8 0.93, w9 3.67, w10 3.53, w11 3.47, w12 3.60, w13 3.47, w14 3.47, w15 3.60, w16 3.60, w17 3.53, w18 2.00, w19 2.13, w20 3.27, w21 3.53, w22 3.47, w23 3.60

## (b) Playoff schedule ranking (weeks 21-23)

Sort: total playoff games, then week 23 (final), then weeks 22+23 (semis+final; top seeds skip week 21), then fewer back-to-backs.

| Rank | Team | W21 | W22 | W23 | Total | W22+23 | B2B in playoffs | Games on light nights (<=6 NBA games) |
|---|---|---|---|---|---|---|---|---|
| 1 | DAL | 4 | 4 | 4 | 12 | 8 | 1 | 3 |
| 2 | PHX | 4 | 4 | 4 | 12 | 8 | 2 | 4 |
| 3 | MEM | 4 | 4 | 4 | 12 | 8 | 3 | 1 |
| 4 | ORL | 3 | 4 | 4 | 11 | 8 | 2 | 2 |
| 5 | PHI | 3 | 4 | 4 | 11 | 8 | 2 | 3 |
| 6 | TOR | 3 | 4 | 4 | 11 | 8 | 2 | 4 |
| 7 | CHA | 4 | 3 | 4 | 11 | 7 | 1 | 1 |
| 8 | DET | 4 | 3 | 4 | 11 | 7 | 2 | 0 |
| 9 | LAC | 4 | 3 | 4 | 11 | 7 | 2 | 1 |
| 10 | OKC | 4 | 3 | 4 | 11 | 7 | 2 | 3 |
| 11 | BOS | 4 | 3 | 4 | 11 | 7 | 3 | 2 |
| 12 | GSW | 4 | 3 | 4 | 11 | 7 | 3 | 2 |
| 13 | SAC | 4 | 4 | 3 | 11 | 7 | 1 | 2 |
| 14 | ATL | 4 | 4 | 3 | 11 | 7 | 2 | 2 |
| 15 | DEN | 4 | 4 | 3 | 11 | 7 | 2 | 1 |
| 16 | NOP | 4 | 4 | 3 | 11 | 7 | 2 | 4 |
| 17 | CHI | 3 | 3 | 4 | 10 | 7 | 1 | 1 |
| 18 | WAS | 3 | 3 | 4 | 10 | 7 | 1 | 0 |
| 19 | HOU | 3 | 3 | 4 | 10 | 7 | 2 | 1 |
| 20 | MIL | 3 | 3 | 4 | 10 | 7 | 2 | 2 |
| 21 | UTA | 3 | 3 | 4 | 10 | 7 | 2 | 2 |
| 22 | NYK | 3 | 3 | 4 | 10 | 7 | 3 | 2 |
| 23 | MIN | 4 | 2 | 4 | 10 | 6 | 1 | 1 |
| 24 | BKN | 3 | 4 | 3 | 10 | 7 | 1 | 2 |
| 25 | IND | 3 | 4 | 3 | 10 | 7 | 2 | 1 |
| 26 | LAL | 3 | 4 | 3 | 10 | 7 | 2 | 3 |
| 27 | SAS | 3 | 4 | 3 | 10 | 7 | 2 | 1 |
| 28 | POR | 3 | 4 | 3 | 10 | 7 | 3 | 3 |
| 29 | MIA | 4 | 3 | 3 | 10 | 6 | 0 | 3 |
| 30 | CLE | 4 | 3 | 2 | 9 | 5 | 1 | 1 |

## (a) Regular-season evenness (weeks 1-20)

SD = std dev of (team games - league avg) per week; lower = steadier weekly output. 4-gm wks = weeks with 4+ games. <=2 wks excludes the short weeks 7, 8, 18, 19 (everyone is light). Sort: regular-season games desc, then SD asc.

| Rank | Team | Games w1-20 | SD | 4+ gm wks | <=2 gm wks | B2B w1-20 |
|---|---|---|---|---|---|---|
| 1 | CLE | 63 | 0.45 | 9 | 1 | 11 |
| 2 | LAL | 63 | 0.49 | 9 | 0 | 9 |
| 3 | WAS | 63 | 0.52 | 9 | 1 | 10 |
| 4 | UTA | 63 | 0.54 | 9 | 1 | 8 |
| 5 | HOU | 63 | 0.57 | 9 | 1 | 7 |
| 6 | NOP | 63 | 0.60 | 10 | 2 | 9 |
| 7 | PHI | 63 | 0.61 | 9 | 1 | 8 |
| 8 | POR | 63 | 0.67 | 9 | 2 | 11 |
| 9 | MIA | 62 | 0.36 | 7 | 0 | 8 |
| 10 | TOR | 62 | 0.39 | 7 | 0 | 9 |
| 11 | OKC | 62 | 0.41 | 7 | 0 | 7 |
| 12 | MIL | 62 | 0.45 | 7 | 0 | 10 |
| 13 | ORL | 62 | 0.45 | 8 | 0 | 10 |
| 14 | NYK | 62 | 0.48 | 6 | 0 | 8 |
| 15 | IND | 62 | 0.50 | 6 | 0 | 7 |
| 16 | ATL | 62 | 0.52 | 7 | 1 | 10 |
| 17 | CHI | 62 | 0.52 | 6 | 0 | 11 |
| 18 | BOS | 62 | 0.56 | 9 | 2 | 8 |
| 19 | BKN | 62 | 0.57 | 9 | 1 | 9 |
| 20 | SAS | 62 | 0.58 | 7 | 1 | 8 |
| 21 | MIN | 62 | 0.64 | 9 | 2 | 6 |
| 22 | DET | 61 | 0.37 | 6 | 0 | 9 |
| 23 | LAC | 61 | 0.45 | 6 | 0 | 7 |
| 24 | SAC | 61 | 0.49 | 6 | 0 | 9 |
| 25 | GSW | 61 | 0.57 | 8 | 0 | 9 |
| 26 | MEM | 61 | 0.59 | 6 | 1 | 7 |
| 27 | CHA | 61 | 0.60 | 7 | 2 | 10 |
| 28 | DEN | 61 | 0.60 | 7 | 1 | 6 |
| 29 | PHX | 61 | 0.62 | 9 | 3 | 7 |
| 30 | DAL | 60 | 0.60 | 7 | 2 | 11 |

## Games per team per week (weeks 1-23; B2B count in parentheses when >0)

| Team | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 | 16 | 17 | 18 | 19 | 20 | 21 | 22 | 23 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ATL | 3(1) | 4(1) | 4(1) | 3 | 3 | 2 | 2 | 1 | 4(1) | 3(1) | 3 | 4(1) | 3 | 4(1) | 3 | 4 | 4 | 2(1) | 3(1) | 3(1) | 4(1) | 4(1) | 3 |
| BKN | 3(1) | 3 | 4(1) | 2 | 3 | 4(1) | 2 | 1 | 4 | 4(1) | 3 | 4(1) | 4(1) | 3(1) | 4 | 3 | 4(1) | 1 | 2 | 4(1) | 3 | 4(1) | 3 |
| BOS | 2 | 4(1) | 4 | 3(1) | 4(1) | 3 | 2 | 1 | 4 | 2 | 4(1) | 3 | 3 | 4(1) | 4 | 4(1) | 4(1) | 2(1) | 2 | 3 | 4(1) | 3 | 4(2) |
| CHA | 3(1) | 4(1) | 3 | 3 | 2 | 3 | 2 | 1 | 4(1) | 4(1) | 4(1) | 4(1) | 3(1) | 3(1) | 4 | 4(1) | 3 | 2 | 3(1) | 2 | 4(1) | 3 | 4 |
| CHI | 3(1) | 3 | 3 | 3(1) | 4 | 3 | 2 | 1 | 4(1) | 3 | 3(1) | 5(2) | 3 | 3(1) | 4(1) | 3 | 4(1) | 2(1) | 2 | 4(1) | 3 | 3 | 4(1) |
| CLE | 2 | 4(1) | 4(1) | 4(1) | 3 | 3 | 2 | 1 | 4(1) | 3 | 4(1) | 3 | 4(1) | 3 | 4(1) | 4(1) | 4(1) | 2(1) | 2(1) | 3 | 4(1) | 3 | 2 |
| DAL | 3(1) | 3 | 4 | 4(1) | 3(1) | 2 | 2 | 0 | 4(1) | 3(1) | 3(1) | 4(1) | 3 | 4(2) | 4 | 4(1) | 3 | 2 | 3(1) | 2 | 4(1) | 4 | 4 |
| DEN | 2 | 3 | 3 | 3 | 4 | 3 | 2 | 1 | 3 | 4 | 4(1) | 3 | 5(2) | 3 | 4(1) | 4(1) | 4(1) | 1 | 2 | 3 | 4 | 4(1) | 3(1) |
| DET | 3 | 3(1) | 3 | 3 | 4(1) | 3 | 2 | 1 | 4 | 4(2) | 3 | 4(1) | 3 | 3 | 4(1) | 4(1) | 3(1) | 2 | 2 | 3(1) | 4(1) | 3 | 4(1) |
| GSW | 3(1) | 4 | 3 | 3 | 4(1) | 3 | 1 | 1 | 4 | 4(1) | 3 | 3(1) | 4(1) | 4(1) | 3(1) | 4 | 3(1) | 2 | 1 | 4(1) | 4(1) | 3(1) | 4(1) |
| HOU | 3(1) | 4(1) | 3 | 4 | 3 | 3 | 2(1) | 1 | 4 | 2 | 4(1) | 3 | 4(1) | 4 | 4(1) | 3 | 4(1) | 2 | 2 | 4 | 3 | 3(1) | 4(1) |
| IND | 3 | 4 | 3 | 4 | 3 | 3(1) | 2 | 1 | 3(1) | 4(1) | 3 | 4(1) | 4 | 3(1) | 3 | 3 | 4(1) | 3(1) | 2 | 3 | 3 | 4(1) | 3(1) |
| LAC | 3 | 3 | 3 | 3 | 3 | 4 | 2(1) | 1 | 3 | 4(1) | 4(1) | 3 | 3(1) | 4 | 3 | 4(1) | 4(1) | 2(1) | 2 | 3 | 4(1) | 3 | 4(1) |
| LAL | 3 | 4(1) | 4 | 3 | 3(1) | 3 | 2 | 0 | 4(1) | 4 | 4(1) | 3(1) | 4(1) | 4(1) | 4(1) | 3 | 3 | 2 | 2 | 4(1) | 3(1) | 4(1) | 3 |
| MEM | 3 | 3 | 3 | 4(1) | 4(1) | 4 | 2(1) | 1 | 4 | 4(1) | 2 | 4(1) | 3 | 3 | 3 | 3 | 3 | 3(1) | 2(1) | 3 | 4(1) | 4(1) | 4(1) |
| MIA | 3(1) | 3 | 4(1) | 3(1) | 3 | 3 | 2 | 1 | 4 | 4 | 3 | 4(1) | 4(1) | 3(1) | 3 | 4(1) | 4 | 2 | 2 | 3(1) | 4 | 3 | 3 |
| MIL | 3(1) | 3 | 4 | 4(1) | 3(1) | 4(1) | 2 | 1 | 4 | 3 | 4(1) | 3 | 4(1) | 3(1) | 3 | 3 | 4(1) | 2(1) | 2 | 3(1) | 3(1) | 3 | 4(1) |
| MIN | 3 | 4(1) | 4 | 2 | 4(1) | 4 | 2(1) | 1 | 3 | 4 | 4(1) | 3(1) | 3 | 4 | 4 | 4(1) | 2 | 2 | 2 | 3 | 4(1) | 2 | 4 |
| NOP | 3(1) | 3(1) | 4 | 4(1) | 4(1) | 3 | 2 | 1 | 4 | 3 | 4(1) | 4 | 2 | 2 | 4(1) | 4(1) | 4 | 2(1) | 2 | 4(1) | 4(1) | 4(1) | 3 |
| NYK | 3 | 3(1) | 3 | 4(1) | 4(1) | 3 | 2(1) | 1 | 3 | 4 | 3(1) | 3 | 4(1) | 4 | 3 | 4(1) | 3 | 2 | 3(1) | 3 | 3(1) | 3(1) | 4(1) |
| OKC | 3 | 3 | 4(1) | 4(1) | 3 | 3 | 2 | 1 | 3 | 4(1) | 4(1) | 3(1) | 3 | 4 | 4(1) | 4(1) | 3 | 2 | 2 | 3 | 4 | 3(1) | 4(1) |
| ORL | 3 | 3 | 3 | 3(1) | 4 | 3(1) | 1 | 1 | 4(1) | 4(1) | 4(1) | 4(1) | 4(1) | 3 | 4(1) | 3 | 4(1) | 2 | 2 | 3(1) | 3(1) | 4(1) | 4 |
| PHI | 4(1) | 3(1) | 4 | 3 | 3 | 4(1) | 2(1) | 1 | 2 | 4 | 3(1) | 4 | 3 | 4(1) | 4(1) | 4 | 3 | 2 | 2 | 4(1) | 3 | 4(1) | 4(1) |
| PHX | 2 | 2 | 4(1) | 4(1) | 3 | 4 | 2(1) | 1 | 4 | 3 | 4(1) | 4(1) | 2 | 4 | 4(1) | 3(1) | 4 | 2 | 2 | 3 | 4(1) | 4 | 4(1) |
| POR | 2 | 3 | 4(1) | 3(1) | 4(1) | 4 | 2 | 1 | 3 | 4(1) | 2 | 4(1) | 4(1) | 4(1) | 3(1) | 3 | 5(2) | 2 | 2 | 4(1) | 3(1) | 4(1) | 3(1) |
| SAC | 3 | 3 | 4 | 3 | 3(1) | 3 | 2 | 1 | 3 | 3 | 4(1) | 4(1) | 4(1) | 3(1) | 4(1) | 3(1) | 4(1) | 1 | 3(1) | 3 | 4 | 4(1) | 3 |
| SAS | 3(1) | 3(1) | 4(1) | 4 | 3 | 4 | 2 | 1 | 4(1) | 4 | 4(1) | 3 | 2 | 3 | 3(1) | 4(1) | 3 | 3(1) | 2 | 3 | 3 | 4(1) | 3(1) |
| TOR | 3 | 3 | 3 | 4(1) | 3(1) | 3 | 2 | 1 | 4 | 3(1) | 4 | 4(1) | 4(1) | 3(1) | 4 | 4(1) | 3 | 2(1) | 2 | 3(1) | 3 | 4(1) | 4(1) |
| UTA | 3 | 3 | 4 | 4(1) | 4(1) | 3 | 2 | 1 | 4 | 3(1) | 3(1) | 4 | 4(1) | 4(1) | 3 | 4(1) | 2 | 2 | 2 | 4(1) | 3 | 3(1) | 4(1) |
| WAS | 3(1) | 3 | 4(1) | 4(1) | 4 | 2 | 2 | 1 | 4 | 4(2) | 3 | 3(1) | 4(1) | 4(1) | 3 | 3 | 4(1) | 2 | 2 | 4(1) | 3 | 3 | 4(1) |

## How to use it (draft tiebreaker)

- Playoff edge: the range is 9 to 12 games over weeks 21-23. DAL, PHX and MEM play 12 (4-4-4). ORL, PHI and TOR play 11 but have 4-4 in weeks 22-23, so they're as good as the top three if you earn a bye. CLE is clearly worst (9; 3-2 in the semis and final). MIA and MIN are next worst (6 games in weeks 22-23).
- Size: a 4-game week against a 3-game week is +1 game, about +33% for that player in that matchup. A 40 fpts/game player is worth about +40 in that week. That's real, but it only counts if you make the playoffs. Use it only between players ranked within about a round of each other.
- Regular season: totals over weeks 1-20 run 60 to 63 (a gap of about 5%), and every team's week-to-week SD is 0.36-0.67. Don't use evenness as a tiebreaker. It's noise next to player quality.
- Caveats: (1) Weeks 7-8 will add about 2 games per team once the NBA Cup knockout and TBD games are scheduled. That doesn't affect the playoff weeks. (2) This assumes Sleeper matchup week = the schedule's `week` field (Mon-Sun calendar weeks, no merged All-Star week). That fits Sleeper's API and last season's leaguemate league (playoff_week_start 22 on the same 25-week calendar), but I haven't checked it against the in-app matchup calendar. (3) Back-to-backs: stars sometimes rest on the 2nd night, so a 4-game week with 2 B2Bs (e.g. BOS week 23) is worth a bit less than 4.
