import type { AppConfig } from "@/lib/config";
import type {
  BaseForecastResponse,
  ForecastPerformanceResponse,
  HealthResponse,
  MarketResponse,
  MlbApprovedDatasetReadinessResponse,
  MlbBackfillBatchResponse,
  MlbBackfillCheckpointResponse,
  OpportunityResponse,
  PaperPositionResponse,
  PaperTradeResponse,
  PortfolioResponse,
  PositionEventResponse,
  SportsEventResponse,
  TradingPerformanceResponse,
} from "@/lib/api/contracts";

export interface LoadState<T> {
  readonly data: T;
  readonly ok: boolean;
  readonly error: string | null;
}

export interface DashboardData {
  readonly loadedAt: string;
  readonly health: LoadState<HealthResponse | null>;
  readonly markets: LoadState<readonly MarketResponse[]>;
  readonly events: LoadState<readonly SportsEventResponse[]>;
  readonly forecasts: LoadState<readonly BaseForecastResponse[]>;
  readonly opportunities: LoadState<readonly OpportunityResponse[]>;
  readonly portfolios: LoadState<readonly PortfolioResponse[]>;
  readonly positions: LoadState<readonly PaperPositionResponse[]>;
  readonly trades: LoadState<readonly PaperTradeResponse[]>;
  readonly positionEvents: LoadState<readonly PositionEventResponse[]>;
  readonly forecastPerformance: LoadState<ForecastPerformanceResponse | null>;
  readonly tradingPerformance: LoadState<TradingPerformanceResponse | null>;
  readonly mlbReadiness: LoadState<MlbApprovedDatasetReadinessResponse | null>;
  readonly mlbBackfillCheckpoint: LoadState<MlbBackfillCheckpointResponse | null>;
  readonly mlbBackfillBatches: LoadState<readonly MlbBackfillBatchResponse[]>;
}

type Validator<T> = (value: unknown) => value is T;
type Fetcher = typeof fetch;

const isObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const isArray = <T>(value: unknown): value is T[] => Array.isArray(value);

async function load<T>(
  baseUrl: string,
  path: string,
  fallback: T,
  validator: Validator<T>,
  fetcher: Fetcher,
  notFoundIsEmpty = false,
): Promise<LoadState<T>> {
  try {
    const response = await fetcher(`${baseUrl}${path}`, {
      cache: "no-store",
      headers: { accept: "application/json" },
      signal: AbortSignal.timeout(5000),
    });

    if (response.status === 404 && notFoundIsEmpty) {
      return { data: fallback, ok: true, error: null };
    }
    if (!response.ok) {
      return {
        data: fallback,
        ok: false,
        error: `${path} returned HTTP ${response.status}`,
      };
    }

    const value: unknown = await response.json();
    if (!validator(value)) {
      return { data: fallback, ok: false, error: `${path} returned an unexpected payload` };
    }

    return { data: value, ok: true, error: null };
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : "request failed";
    return { data: fallback, ok: false, error: `${path}: ${message}` };
  }
}

const availableEmpty = <T>(data: T): LoadState<T> => ({ data, ok: true, error: null });

export async function fetchDashboardData(
  config: Readonly<AppConfig>,
  fetcher: Fetcher = fetch,
): Promise<DashboardData> {
  const [
    health,
    markets,
    events,
    forecasts,
    opportunities,
    portfolios,
    forecastPerformance,
    mlbReadiness,
    mlbBackfillCheckpoint,
    mlbBackfillBatches,
  ] =
    await Promise.all([
      load<HealthResponse | null>(
        config.backendApiUrl,
        "/health/ready",
        null,
        (value: unknown): value is HealthResponse => isObject(value),
        fetcher,
      ),
      load<MarketResponse[]>(
        config.backendApiUrl,
        "/markets?nba_only=true&limit=8&offset=0",
        [],
        isArray<MarketResponse>,
        fetcher,
      ),
      load<SportsEventResponse[]>(
        config.backendApiUrl,
        "/events?limit=24&offset=0",
        [],
        isArray<SportsEventResponse>,
        fetcher,
      ),
      load<BaseForecastResponse[]>(
        config.backendApiUrl,
        "/forecasts?latest_only=true&purpose=operational&limit=8&offset=0",
        [],
        isArray<BaseForecastResponse>,
        fetcher,
      ),
      load<OpportunityResponse[]>(
        config.backendApiUrl,
        "/opportunities?latest_only=true&current_only=true&limit=8&offset=0",
        [],
        isArray<OpportunityResponse>,
        fetcher,
      ),
      load<PortfolioResponse[]>(
        config.backendApiUrl,
        "/portfolios?limit=10&offset=0",
        [],
        isArray<PortfolioResponse>,
        fetcher,
      ),
      load<ForecastPerformanceResponse | null>(
        config.backendApiUrl,
        "/forecast-performance?purpose=operational",
        null,
        (value: unknown): value is ForecastPerformanceResponse => isObject(value),
        fetcher,
      ),
      load<MlbApprovedDatasetReadinessResponse | null>(
        config.backendApiUrl,
        "/mlb-approved-dataset-readiness",
        null,
        (value: unknown): value is MlbApprovedDatasetReadinessResponse => isObject(value),
        fetcher,
      ),
      load<MlbBackfillCheckpointResponse | null>(
        config.backendApiUrl,
        "/mlb-research-backfill-workflow",
        null,
        (value: unknown): value is MlbBackfillCheckpointResponse => isObject(value),
        fetcher,
        true,
      ),
      load<MlbBackfillBatchResponse[]>(
        config.backendApiUrl,
        "/mlb-research-backfill-workflow/batches?limit=1&offset=0",
        [],
        isArray<MlbBackfillBatchResponse>,
        fetcher,
      ),
    ]);

  const primaryPortfolio =
    portfolios.data.find((portfolio: PortfolioResponse): boolean => portfolio.is_active) ??
    portfolios.data[0];

  let positions: LoadState<readonly PaperPositionResponse[]> = availableEmpty([]);
  let trades: LoadState<readonly PaperTradeResponse[]> = availableEmpty([]);
  let positionEvents: LoadState<readonly PositionEventResponse[]> = availableEmpty([]);
  let tradingPerformance: LoadState<TradingPerformanceResponse | null> = availableEmpty(null);

  if (primaryPortfolio !== undefined) {
    const portfolioId = encodeURIComponent(primaryPortfolio.id);
    [positions, trades, positionEvents, tradingPerformance] = await Promise.all([
      load<PaperPositionResponse[]>(
        config.backendApiUrl,
        `/positions?portfolio_id=${portfolioId}&limit=8&offset=0`,
        [],
        isArray<PaperPositionResponse>,
        fetcher,
      ),
      load<PaperTradeResponse[]>(
        config.backendApiUrl,
        `/trades?portfolio_id=${portfolioId}&limit=8&offset=0`,
        [],
        isArray<PaperTradeResponse>,
        fetcher,
      ),
      load<PositionEventResponse[]>(
        config.backendApiUrl,
        `/position-events?portfolio_id=${portfolioId}&limit=8&offset=0`,
        [],
        isArray<PositionEventResponse>,
        fetcher,
      ),
      load<TradingPerformanceResponse | null>(
        config.backendApiUrl,
        `/portfolios/${portfolioId}/performance`,
        null,
        (value: unknown): value is TradingPerformanceResponse => isObject(value),
        fetcher,
      ),
    ]);
  }

  return {
    loadedAt: new Date().toISOString(),
    health,
    markets,
    events,
    forecasts,
    opportunities,
    portfolios,
    positions,
    trades,
    positionEvents,
    forecastPerformance,
    tradingPerformance,
    mlbReadiness,
    mlbBackfillCheckpoint,
    mlbBackfillBatches,
  };
}
