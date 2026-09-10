# NFL baseline: first real-data retrospective evaluation

Completed September 10, 2026. Research-only; no NFL operational forecast or trade
was created. Local API health was `ok` and trading mode remained `paper`.

## Collection and coverage

The updated BALLDONTLIE credential succeeded after recreating the backend to load
the updated environment. The existing localhost collector ingested bounded windows
covering September–January of seasons 2018–2025. It collected 2,220 source events:
2,127 eligible regular-season finals, 92 excluded postseason events, and one
excluded canceled event. Postseason coverage was incidental and is not complete.

| Season | Eligible final games | Teams | Weeks |
|---|---:|---:|---|
| 2018 | 256 | 32 | 1–17 |
| 2019 | 256 | 32 | 1–17 |
| 2020 | 256 | 32 | 1–17 |
| 2021 | 272 | 32 | 1–18 |
| 2022 | 271 | 32 | 1–18 |
| 2023 | 272 | 32 | 1–18 |
| 2024 | 272 | 32 | 1–18 |
| 2025 | 272 | 32 | 1–18 |

These counts are consistent with the schedule sizes and the canceled 2022
Bills–Bengals game. Counts alone are not an independent game-by-game source audit;
the automated coverage flag correctly remains unverified. Official references:
[NFL schedule expansion](https://www.nfl.com/news/nfl-plans-to-expand-regular-season-to-17-games-per-team-in-2021),
[canceled game](https://www.nfl.com/schedules/2022/by-team/cincinnati-bengals).

One transient provider-availability failure stopped the January 3–31, 2021 window
after the adapter's three attempts. The manual resume date remained January 3;
one explicit retry succeeded. No authentication errors recurred. No failed window
was skipped and no scores were invented.

## Fixed-policy evaluation

Model: `nfl-research-elo-payout-v1`. No parameter changes or tuning were made.
Each week is predicted before its results update ratings. Test-period state
updates use earlier test weeks under the same fixed policy, not future results.
The target is expected ordinary-game payout with ties=0.5, not win probability.
Lower mean squared payout error is better.

| Split | Games | Elo | Constant 0.5 | Expanding home-payout mean |
|---|---:|---:|---:|---:|
| Development 2018–2022 | 1,311 | 0.22980134 | 0.24866514 | 0.24789833 |
| Validation 2023–2024 | 544 | 0.22842024 | 0.25000000 | 0.24823533 |
| Test 2025 | 272 | 0.22756990 | 0.24908088 | 0.24774639 |

The model beats both simple benchmarks on every split in this sample. No
significance, market-edge, or profitability claim follows. Calibration is imperfect:
the validation 0.6–0.7 prediction bin averaged 0.6369 expected versus 0.7802 observed
payout over 91 games. The corresponding test bin averaged 0.6424 versus 0.7381
over 42 games. Do not tune parameters against the now-observed test results.

## Reproducible artifact

`inputs-YYYY.json` preserves every exact typed normalized input used by the pure
evaluator, including source IDs, teams, scores, week, kickoff, and observation time.
`evaluation.json` preserves full configuration, split metrics, calibration bins,
coverage, warnings, and input fingerprint. These files are sufficient to replay the
calculation independently of later database corrections; they are not a copy of
every raw provider field. Recompute with `evaluate_games` after loading each input
through `NflResearchGame.model_validate`. An offline replay was performed and the
entire report excluding per-game predictions exactly equaled `evaluation.json`.

Input fingerprint:
`9c70fcc1ee9089a3851794764e915eeca2fa3b1c7cfb533a0ba76a0cab320b0b`

Local source-selection fingerprint (including excluded source snapshots):
`7a66029a164a9374a5fb5c43f408bc00585584003d117b93c2ac271df886a36b`

## Remaining work

Independently audit source coverage and historical timestamps, define promotion
criteria before prospective testing, and implement immutable operational NFL
forecast/payout integration and fractional exchange settlement before any NFL paper
execution. Real-time information availability is not established by retrospective
latest-result snapshots. Live trading remains out of scope.
