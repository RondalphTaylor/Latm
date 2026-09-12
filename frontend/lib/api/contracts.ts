export type DecimalValue = string;

export interface NflPilotMonitoringDecisionResponse {
  readonly id: string;
  readonly position_id: string;
  readonly recommendation: string;
  readonly reason: string;
  readonly requires_attention: boolean;
  readonly remaining_edge: DecimalValue | null;
  readonly evaluated_at: string;
}

export interface HealthResponse {
  readonly status: string;
}

export interface MarketPriceResponse {
  readonly yes_bid: DecimalValue | null;
  readonly yes_ask: DecimalValue | null;
  readonly no_bid: DecimalValue | null;
  readonly no_ask: DecimalValue | null;
  readonly last_price: DecimalValue | null;
  readonly volume: DecimalValue | null;
  readonly volume_24h: DecimalValue | null;
  readonly open_interest: DecimalValue | null;
  readonly liquidity: DecimalValue | null;
  readonly retrieved_at: string;
}

export interface MarketResponse {
  readonly id: string;
  readonly provider_name: string;
  readonly provider_market_id: string;
  readonly market_type: string;
  readonly title: string;
  readonly subtitle: string | null;
  readonly status: string;
  readonly is_nba: boolean;
  readonly close_time: string | null;
  readonly latest_price: MarketPriceResponse | null;
}

export interface TeamResponse {
  readonly id: string;
  readonly abbreviation: string;
  readonly full_name: string;
}

export interface SportsEventResponse {
  readonly id: string;
  readonly event_date: string;
  readonly scheduled_start_time: string;
  readonly status: string;
  readonly status_detail: string;
  readonly home_team: TeamResponse;
  readonly away_team: TeamResponse;
  readonly home_score: number | null;
  readonly away_score: number | null;
}

export interface ModelVersionResponse {
  readonly id: string;
  readonly model_name: string;
  readonly model_version: string;
  readonly algorithm: string;
}

export interface BaseForecastResponse {
  readonly id: string;
  readonly sports_event_id: string;
  readonly purpose: "operational" | "historical_replay";
  readonly home_win_probability: DecimalValue;
  readonly away_win_probability: DecimalValue;
  readonly generated_at: string;
  readonly model: ModelVersionResponse;
}

export interface OpportunityResponse {
  readonly id: string;
  readonly market_id: string;
  readonly sports_event_id: string;
  readonly base_forecast_id: string;
  readonly direction: "yes" | "no";
  readonly market_probability: DecimalValue;
  readonly model_probability: DecimalValue;
  readonly raw_edge: DecimalValue;
  readonly status: "no_edge" | "watch" | "trade_candidate";
  readonly status_reason: string;
  readonly valid_until: string;
  readonly evaluated_at: string;
  readonly model: ModelVersionResponse;
}

export interface PortfolioSnapshotResponse {
  readonly id: string;
  readonly sequence: number;
  readonly currency: string;
  readonly starting_bankroll: DecimalValue;
  readonly current_bankroll: DecimalValue;
  readonly cash_balance: DecimalValue;
  readonly reserved_capital: DecimalValue;
  readonly committed_capital: DecimalValue;
  readonly available_bankroll: DecimalValue;
  readonly realized_pnl: DecimalValue;
  readonly open_position_value: DecimalValue;
  readonly unrealized_pnl: DecimalValue;
  readonly total_portfolio_value: DecimalValue;
  readonly captured_at: string;
}

export interface PortfolioResponse {
  readonly id: string;
  readonly name: string;
  readonly execution_mode: "paper";
  readonly currency: string;
  readonly starting_bankroll: DecimalValue;
  readonly status: string;
  readonly is_active: boolean;
  readonly latest_snapshot: PortfolioSnapshotResponse;
}

export interface PaperPositionResponse {
  readonly id: string;
  readonly portfolio_id: string;
  readonly market_id: string;
  readonly execution_mode: "paper";
  readonly direction: "yes" | "no";
  readonly status: "open" | "closed" | "settled";
  readonly initial_quantity: number;
  readonly quantity: number;
  readonly disposed_quantity: number;
  readonly average_entry_price: DecimalValue;
  readonly total_cost_basis: DecimalValue;
  readonly mark_price: DecimalValue;
  readonly mark_basis: string;
  readonly market_value: DecimalValue;
  readonly unrealized_pnl: DecimalValue;
  readonly realized_pnl: DecimalValue;
  readonly opened_at: string;
  readonly updated_at: string;
}

export interface PaperTradeResponse {
  readonly id: string;
  readonly portfolio_id: string;
  readonly market_id: string;
  readonly execution_mode: "paper";
  readonly action: "buy";
  readonly direction: "yes" | "no";
  readonly status: "filled" | "rejected";
  readonly reason_code: string;
  readonly executed_quantity: number | null;
  readonly execution_price: DecimalValue | null;
  readonly total_cost: DecimalValue | null;
  readonly adjusted_edge: DecimalValue | null;
  readonly attempted_at: string;
  readonly executed_at: string | null;
}

export interface PositionEventResponse {
  readonly id: string;
  readonly position_id: string;
  readonly portfolio_id: string;
  readonly market_id: string;
  readonly execution_mode: "paper";
  readonly decision: "hold" | "reduce" | "close" | "settle";
  readonly reason_code: string;
  readonly state_changed: boolean;
  readonly action_quantity: number;
  readonly net_proceeds: DecimalValue | null;
  readonly realized_pnl_increment: DecimalValue;
  readonly evaluated_at: string;
  readonly executed_at: string | null;
}

export interface ForecastCalibrationBin {
  readonly index: number;
  readonly lower_bound: DecimalValue;
  readonly upper_bound: DecimalValue;
  readonly upper_bound_inclusive: boolean;
  readonly sample_size: number;
  readonly mean_prediction: DecimalValue | null;
  readonly observed_frequency: DecimalValue | null;
}

export interface ForecastModelPerformance {
  readonly summary: {
    readonly model_version_id: string;
    readonly model_name: string;
    readonly model_version: string;
    readonly sample_size: number;
    readonly mean_brier_score: DecimalValue;
    readonly prediction_accuracy: DecimalValue | null;
    readonly expected_calibration_error: DecimalValue;
    readonly maximum_calibration_error: DecimalValue;
  };
  readonly calibration: {
    readonly sample_size: number;
    readonly bins: readonly ForecastCalibrationBin[];
  };
}

export interface ForecastPerformanceResponse {
  readonly purpose: "operational" | "historical_replay";
  readonly evaluation_count: number;
  readonly unique_event_count: number;
  readonly model_count: number;
  readonly models: readonly ForecastModelPerformance[];
  readonly warnings: readonly string[];
}

export interface SnapshotDrawdown {
  readonly amount: DecimalValue;
  readonly fraction: DecimalValue;
  readonly peak_at: string;
  readonly trough_at: string;
}

export interface TradingPerformanceResponse {
  readonly portfolio_id: string;
  readonly execution_mode: "paper";
  readonly currency: "USD";
  readonly as_of: string;
  readonly calculated_at: string;
  readonly net_total_pnl: DecimalValue;
  readonly realized_pnl: DecimalValue;
  readonly unrealized_pnl: DecimalValue;
  readonly return_on_starting_bankroll: DecimalValue;
  readonly position_count: number;
  readonly open_position_count: number;
  readonly completed_position_count: number;
  readonly winning_position_count: number;
  readonly losing_position_count: number;
  readonly breakeven_position_count: number;
  readonly win_rate: DecimalValue | null;
  readonly average_adjusted_entry_edge: DecimalValue | null;
  readonly average_terminal_return: DecimalValue | null;
  readonly maximum_drawdown: SnapshotDrawdown;
  readonly warnings: readonly string[];
}

export type MlbDatasetSplit = "train" | "validation" | "test" | "prospective_holdout";

export interface MlbApprovedDatasetReadinessResponse {
  readonly policy_name: string;
  readonly policy_version: string;
  readonly policy_fingerprint: string;
  readonly split_policy_fingerprint: string;
  readonly validation_start: string;
  readonly test_start: string;
  readonly prospective_holdout_start: string;
  readonly minimum_split_counts: Readonly<Record<MlbDatasetSplit, number>>;
  readonly eligible_split_counts: Readonly<Record<MlbDatasetSplit, number>>;
  readonly shortfall_by_split: Readonly<Record<MlbDatasetSplit, number>>;
  readonly exploratory_fit_data_ready: boolean;
  readonly prospective_evaluation_data_ready: boolean;
  readonly retrospective_allowed_for_exploratory_splits: true;
  readonly prospective_holdout_requires_operational_pregame: true;
  readonly model_fitting_enabled: false;
  readonly probability_generation_enabled: false;
  readonly automatic_trading_enabled: false;
  readonly blockers: readonly string[];
}

export interface MlbBackfillCheckpointResponse {
  readonly id: string;
  readonly policy_name: string;
  readonly policy_version: string;
  readonly policy_fingerprint: string;
  readonly split_policy_fingerprint: string;
  readonly status: "active" | "complete" | "exhausted";
  readonly regular_season_start: string;
  readonly validation_start_date: string;
  readonly test_start_date: string;
  readonly prospective_holdout_start_date: string;
  readonly train_cursor_date: string;
  readonly train_cursor_offset: number;
  readonly validation_cursor_date: string;
  readonly validation_cursor_offset: number;
  readonly test_cursor_date: string;
  readonly test_cursor_offset: number;
  readonly batch_limit: number;
  readonly version: number;
  readonly batches_completed: number;
  readonly events_examined: number;
  readonly examples_created: number;
  readonly last_run_at: string | null;
  readonly finished_at: string | null;
  readonly state_fingerprint: string;
  readonly research_only: true;
  readonly probability_generated: false;
  readonly automatic_trading_eligible: false;
  readonly created_at: string;
  readonly updated_at: string;
}

export interface MlbBackfillBatchResponse {
  readonly id: string;
  readonly checkpoint_id: string;
  readonly sequence: number;
  readonly split: Exclude<MlbDatasetSplit, "prospective_holdout">;
  readonly window_date: string;
  readonly offset: number;
  readonly batch_limit: number;
  readonly cursor_date_after: string;
  readonly cursor_offset_after: number;
  readonly run_at: string;
  readonly events_refreshed: number;
  readonly examined: number;
  readonly retrospective_vectors_built: number;
  readonly examples_labeled: number;
  readonly examples_created: number;
  readonly result_counts: Readonly<Record<string, number>>;
  readonly input_fingerprint: string;
  readonly result_fingerprint: string;
  readonly research_only: true;
  readonly probability_generated: false;
  readonly automatic_trading_eligible: false;
  readonly created_at: string;
}
