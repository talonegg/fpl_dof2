# FPL API — annotated response shapes

Supporting reference for the [`fpl-api` skill](../SKILL.md). Load when writing a parser for a
specific endpoint. These are illustrative shapes based on long-stable, widely-documented community
knowledge of the API — **verify against a live response and lock in the exact shape via a recorded
contract test before relying on this for parsing code.** Field sets have drifted over past seasons
and will drift again.

## `bootstrap-static/` (abridged)

```jsonc
{
  "events": [
    { "id": 1, "name": "Gameweek 1", "deadline_time": "2026-08-21T17:30:00Z",
      "finished": false, "is_current": false, "is_next": true }
    // ... one per gameweek
  ],
  "teams": [
    { "id": 1, "name": "Arsenal", "short_name": "ARS",
      "strength": 4, "strength_overall_home": 1250, "strength_overall_away": 1300 }
    // ... 20 teams
  ],
  "element_types": [
    { "id": 1, "singular_name": "Goalkeeper", "plural_name": "Goalkeepers" }
    // GK / DEF / MID / FWD
  ],
  "elements": [
    {
      "id": 1, "first_name": "...", "second_name": "...", "web_name": "...",
      "team": 1, "element_type": 3,
      "now_cost": 105,                 // tenths of £m -> £10.5m
      "cost_change_start": 5,          // tenths of £m since season start
      "selected_by_percent": "34.2",
      "status": "a",                   // a / d / i / s / u ...
      "chance_of_playing_next_round": 100,
      "chance_of_playing_this_round": 100,
      "form": "5.2", "points_per_game": "4.8", "total_points": 42,
      "minutes": 720, "goals_scored": 3, "assists": 4,
      "clean_sheets": 2, "goals_conceded": 8,
      "yellow_cards": 1, "red_cards": 0,
      "bonus": 6, "bps": 210,
      "expected_goals": "2.1", "expected_assists": "1.8"   // FPL's own xG/xA, if exposed
    }
    // ... ~700 players
  ],
  "game_settings": {
    // some rule parameters exposed here — check at implementation time, do not assume completeness
  }
}
```

## `fixtures/` (abridged, one entry)

```jsonc
{
  "id": 1, "event": 1,
  "team_h": 1, "team_a": 5,
  "team_h_difficulty": 3, "team_a_difficulty": 3,
  "kickoff_time": "2026-08-21T19:00:00Z",
  "finished": false,
  "team_h_score": null, "team_a_score": null,
  "stats": []   // populated post-match: goals, assists, cards, bps, etc. per side
}
```

## `event/{gw}/live/` (abridged, one player)

```jsonc
{
  "elements": [
    {
      "id": 1,
      "stats": {
        "minutes": 90, "goals_scored": 1, "assists": 0,
        "clean_sheets": 0, "goals_conceded": 1,
        "saves": 0, "bonus": 3, "bps": 45,
        "defensive_contribution": 1,     // whether the DefCon threshold was hit this match
        "total_points": 9
      },
      "explain": [
        { "fixture": 1, "stats": [ { "identifier": "goals_scored", "points": 4, "value": 1 } ] }
      ]
    }
  ]
}
```

`explain` is the per-action points breakdown FPL itself computed — extremely useful as ground truth
for the rules-engine conformance test (`fpl-rules` skill, and Design §10).

## `entry/{team_id}/event/{gw}/picks/` (abridged)

```jsonc
{
  "picks": [
    { "element": 1, "position": 1, "multiplier": 2, "is_captain": true, "is_vice_captain": false }
    // 15 entries, position 1-11 = starting XI, 12-15 = bench, multiplier 2 = captain
  ],
  "entry_history": {
    "event": 5, "points": 68, "total_points": 310,
    "bank": 3, "value": 1005,           // tenths of £m
    "event_transfers": 1, "event_transfers_cost": 0,
    "points_on_bench": 4
  },
  "active_chip": null   // "wildcard" / "freehit" / "3xc" / "bboost" if played this gameweek
}
```

**Remember:** this endpoint is only reliable for gameweeks that have already had their deadline pass
— see the visibility gap in `SKILL.md`.

## `entry/{team_id}/transfers/` (abridged, one entry)

```jsonc
{
  "element_in": 15, "element_in_cost": 80,
  "element_out": 3, "element_out_cost": 75,
  "entry": 1234567, "event": 4,
  "time": "2026-09-10T14:22:01Z"
}
```

Full history, unpaginated, oldest first. This is what makes pre-deadline squad reconstruction
possible (see the visibility-gap procedure in `SKILL.md`).
