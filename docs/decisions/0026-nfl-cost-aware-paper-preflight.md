# Decision 0026: NFL cost-aware paper preflight

## Scope

This release adds a pure, deterministic NFL paper-entry preflight. It accepts one
already-audited directional expected payout, direct ask, raw edge, and caller-supplied
capital cap. It applies configured absolute price slippage and a flat estimated fee,
rounding execution price and per-contract unit cost upward to six decimal places and
money costs upward to cents. It selects the greatest whole-contract quantity whose
all-in simulated cost fits the cap.

The pure calculator has no side effects. Its paper-mode API wrapper persists a
separate immutable review only after revalidating the source shadow and latest quote;
the record is not an order, position-size proposal, risk authorization, trade, or
portfolio action.

## Safety boundary

Every result sets `risk_decision=reject` and `execution_enabled=false`, including a
cost-qualified result. The reason is `nfl_pilot_not_approved`. This preserves the
existing research-only NFL match guard and requires the separately reviewed pilot
cohort and explicit approval before any future entry integration can exist.

The preflight intentionally does not reuse NBA `position_size_proposals`,
`risk_decisions`, executions, portfolios, or positions. Those records carry NBA
probability and opportunity lineage that NFL expected payouts must not impersonate.

## Verification

Focused tests cover upward slippage and fee rounding, whole-contract affordability,
raw-edge consistency, adjusted-edge calculation, and the unconditional execution
block. Integration work remains a later, explicitly approved step: persist a
separate immutable NFL review record, bind it to a reviewed pilot cohort, and add
isolated entry-to-settlement tests without enabling real-money trading.
