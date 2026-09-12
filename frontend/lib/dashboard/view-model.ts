import type {
  ForecastCalibrationBin,
  ForecastModelPerformance,
  MarketResponse,
  MlbBackfillBatchResponse,
  MlbBackfillCheckpointResponse,
  MlbDatasetSplit,
  PaperPositionResponse,
  PortfolioResponse,
  TradingPerformanceResponse,
} from "@/lib/api/contracts";
import type { DashboardData, LoadState } from "@/lib/api/client";

export interface MarketRow {
  readonly id: string;
  readonly title: string;
  readonly provider: string;
  readonly status: string;
  readonly yesBid: string | null;
  readonly yesAsk: string | null;
  readonly noBid: string | null;
  readonly noAsk: string | null;
  readonly volume: string | null;
  readonly liquidity: string | null;
  readonly pricedAt: string | null;
}

export interface ForecastRow {
  readonly id: string;
  readonly matchup: string;
  readonly model: string;
  readonly homeProbability: string;
  readonly marketProbability: string | null;
  readonly edge: string | null;
  readonly generatedAt: string;
}

export interface OpportunityRow {
  readonly id: string;
  readonly marketTitle: string;
  readonly matchup: string;
  readonly direction: string;
  readonly modelProbability: string;
  readonly marketProbability: string;
  readonly edge: string;
  readonly status: string;
  readonly validUntil: string;
}

export interface PositionRow {
  readonly id: string;
  readonly marketTitle: string;
  readonly direction: string;
  readonly status: string;
  readonly quantity: number;
  readonly entryPrice: string;
  readonly markPrice: string;
  readonly markBasis: string;
  readonly marketValue: string;
  readonly unrealizedPnl: string;
  readonly realizedPnl: string;
  readonly updatedAt: string;
}

export interface ActivityRow {
  readonly id: string;
  readonly kind: "entry" | "monitoring";
  readonly action: string;
  readonly result: string;
  readonly marketTitle: string;
  readonly quantity: number | null;
  readonly amount: string | null;
  readonly pnl: string | null;
  readonly occurredAt: string;
}

export interface MlbReadinessRow {
  readonly split: MlbDatasetSplit;
  readonly label: string;
  readonly eligible: number;
  readonly minimum: number;
  readonly shortfall: number;
  readonly provenance: "retrospective permitted" | "operational pregame only";
}

export interface DashboardViewModel {
  readonly primaryPortfolio: PortfolioResponse | null;
  readonly performance: TradingPerformanceResponse | null;
  readonly degradedSections: readonly string[];
  readonly marketRows: readonly MarketRow[];
  readonly forecastRows: readonly ForecastRow[];
  readonly opportunityRows: readonly OpportunityRow[];
  readonly positionRows: readonly PositionRow[];
  readonly activityRows: readonly ActivityRow[];
  readonly modelPerformance: readonly ForecastModelPerformance[];
  readonly calibrationBins: readonly ForecastCalibrationBin[];
  readonly mlbReadinessRows: readonly MlbReadinessRow[];
  readonly mlbCheckpoint: MlbBackfillCheckpointResponse | null;
  readonly mlbLatestBatch: MlbBackfillBatchResponse | null;
  readonly nflAttention: DashboardData["nflAttention"]["data"];
}

function markFailure<T>(state: LoadState<T>, label: string, failures: string[]): void {
  if (!state.ok) {
    failures.push(label);
  }
}

function matchupLabel(
  eventId: string,
  events: ReadonlyMap<string, DashboardData["events"]["data"][number]>,
): string {
  const event = events.get(eventId);
  return event === undefined
    ? `Event ${eventId.slice(0, 8)}`
    : `${event.away_team.abbreviation} at ${event.home_team.abbreviation}`;
}

function marketLabel(marketId: string, markets: ReadonlyMap<string, MarketResponse>): string {
  return markets.get(marketId)?.title ?? `Market ${marketId.slice(0, 8)}`;
}

function primaryPortfolio(portfolios: readonly PortfolioResponse[]): PortfolioResponse | null {
  return portfolios.find((portfolio: PortfolioResponse): boolean => portfolio.is_active) ??
    portfolios[0] ??
    null;
}

function positionRow(
  position: PaperPositionResponse,
  markets: ReadonlyMap<string, MarketResponse>,
): PositionRow {
  return {
    id: position.id,
    marketTitle: marketLabel(position.market_id, markets),
    direction: position.direction,
    status: position.status,
    quantity: position.quantity,
    entryPrice: position.average_entry_price,
    markPrice: position.mark_price,
    markBasis: position.mark_basis,
    marketValue: position.market_value,
    unrealizedPnl: position.unrealized_pnl,
    realizedPnl: position.realized_pnl,
    updatedAt: position.updated_at,
  };
}

export function buildDashboardViewModel(data: DashboardData): DashboardViewModel {
  const failures: string[] = [];
  markFailure(data.health, "API readiness", failures);
  markFailure(data.markets, "markets", failures);
  markFailure(data.events, "sports events", failures);
  markFailure(data.forecasts, "forecasts", failures);
  markFailure(data.opportunities, "opportunities", failures);
  markFailure(data.portfolios, "portfolios", failures);
  markFailure(data.positions, "positions", failures);
  markFailure(data.trades, "trade history", failures);
  markFailure(data.positionEvents, "position activity", failures);
  markFailure(data.forecastPerformance, "forecast performance", failures);
  markFailure(data.tradingPerformance, "portfolio performance", failures);
  markFailure(data.mlbReadiness, "MLB dataset readiness", failures);
  markFailure(data.mlbBackfillCheckpoint, "MLB backfill checkpoint", failures);
  markFailure(data.mlbBackfillBatches, "MLB backfill history", failures);
  markFailure(data.nflAttention, "NFL pilot attention", failures);

  const markets = new Map(
    data.markets.data.map((market: MarketResponse): readonly [string, MarketResponse] => [
      market.id,
      market,
    ]),
  );
  const events = new Map(
    data.events.data.map((event): readonly [string, typeof event] => [event.id, event]),
  );
  const opportunitiesByForecast = new Map(
    data.opportunities.data.map((opportunity) => [opportunity.base_forecast_id, opportunity]),
  );

  const marketRows = data.markets.data.map(
    (market: MarketResponse): MarketRow => ({
      id: market.id,
      title: market.title,
      provider: market.provider_name,
      status: market.status,
      yesBid: market.latest_price?.yes_bid ?? null,
      yesAsk: market.latest_price?.yes_ask ?? null,
      noBid: market.latest_price?.no_bid ?? null,
      noAsk: market.latest_price?.no_ask ?? null,
      volume: market.latest_price?.volume ?? null,
      liquidity: market.latest_price?.liquidity ?? null,
      pricedAt: market.latest_price?.retrieved_at ?? null,
    }),
  );

  const forecastRows = data.forecasts.data.map((forecast): ForecastRow => {
    const opportunity = opportunitiesByForecast.get(forecast.id);
    return {
      id: forecast.id,
      matchup: matchupLabel(forecast.sports_event_id, events),
      model: `${forecast.model.model_name} · ${forecast.model.model_version}`,
      homeProbability: forecast.home_win_probability,
      marketProbability: opportunity?.market_probability ?? null,
      edge: opportunity?.raw_edge ?? null,
      generatedAt: forecast.generated_at,
    };
  });

  const opportunityRows = data.opportunities.data.map(
    (opportunity): OpportunityRow => ({
      id: opportunity.id,
      marketTitle: marketLabel(opportunity.market_id, markets),
      matchup: matchupLabel(opportunity.sports_event_id, events),
      direction: opportunity.direction,
      modelProbability: opportunity.model_probability,
      marketProbability: opportunity.market_probability,
      edge: opportunity.raw_edge,
      status: opportunity.status,
      validUntil: opportunity.valid_until,
    }),
  );

  const activityRows: ActivityRow[] = [
    ...data.trades.data.map(
      (trade): ActivityRow => ({
        id: trade.id,
        kind: "entry",
        action: `${trade.action} ${trade.direction}`,
        result: trade.status,
        marketTitle: marketLabel(trade.market_id, markets),
        quantity: trade.executed_quantity,
        amount: trade.total_cost,
        pnl: null,
        occurredAt: trade.executed_at ?? trade.attempted_at,
      }),
    ),
    ...data.positionEvents.data.map(
      (event): ActivityRow => ({
        id: event.id,
        kind: "monitoring",
        action: event.decision,
        result: event.reason_code,
        marketTitle: marketLabel(event.market_id, markets),
        quantity: event.action_quantity,
        amount: event.net_proceeds,
        pnl: event.realized_pnl_increment,
        occurredAt: event.executed_at ?? event.evaluated_at,
      }),
    ),
  ].sort(
    (left: ActivityRow, right: ActivityRow): number =>
      Date.parse(right.occurredAt) - Date.parse(left.occurredAt),
  );

  const modelPerformance = data.forecastPerformance.data?.models ?? [];
  const readiness = data.mlbReadiness.data;
  const splitOrder: readonly MlbDatasetSplit[] = [
    "train",
    "validation",
    "test",
    "prospective_holdout",
  ];
  const mlbReadinessRows = readiness === null
    ? []
    : splitOrder.map(
        (split): MlbReadinessRow => ({
          split,
          label: split === "prospective_holdout" ? "Prospective holdout" : split,
          eligible: readiness.eligible_split_counts[split],
          minimum: readiness.minimum_split_counts[split],
          shortfall: readiness.shortfall_by_split[split],
          provenance:
            split === "prospective_holdout"
              ? "operational pregame only"
              : "retrospective permitted",
        }),
      );

  return {
    primaryPortfolio: primaryPortfolio(data.portfolios.data),
    performance: data.tradingPerformance.data,
    degradedSections: failures,
    marketRows,
    forecastRows,
    opportunityRows,
    positionRows: data.positions.data.map((position) => positionRow(position, markets)),
    activityRows: activityRows.slice(0, 8),
    modelPerformance,
    calibrationBins: modelPerformance[0]?.calibration.bins ?? [],
    mlbReadinessRows,
    mlbCheckpoint: data.mlbBackfillCheckpoint.data,
    mlbLatestBatch: data.mlbBackfillBatches.data[0] ?? null,
    nflAttention: data.nflAttention.data,
  };
}
