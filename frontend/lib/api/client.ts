import type { AppConfig } from "@/lib/config";
import type {
  BaseForecastResponse,
  ForecastPerformanceResponse,
  HealthResponse,
  MarketResponse,
  NflPilotMonitoringDecisionResponse,
  NflPilotAlertResponse,
  NflPilotDispositionEventResponse,
  NflPilotPositionResponse,
  NflPilotLedgerResponse,
  NflPilotRecommendationAuditResponse,
  NflPilotRecommendationAuditSummaryResponse,
  NflPilotRecommendationAuditVerificationResponse,
  NflPilotAuditVerificationHistoryResponse,
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
  readonly nflAttention: LoadState<readonly NflPilotMonitoringDecisionResponse[]>;
  readonly nflAlerts: LoadState<readonly NflPilotAlertResponse[]>;
  readonly nflDispositions: LoadState<readonly NflPilotDispositionEventResponse[]>;
  readonly nflPilotPositions: LoadState<readonly NflPilotPositionResponse[]>;
  readonly nflPilotLedger: LoadState<NflPilotLedgerResponse | null>;
  readonly nflRecommendationAudit: LoadState<readonly NflPilotRecommendationAuditResponse[]>;
  readonly nflRecommendationAuditSummary: LoadState<NflPilotRecommendationAuditSummaryResponse | null>;
  readonly pilotAuditScenarioId: string | null;
  readonly pilotAuditRecommendation: NflPilotRecommendationAuditResponse["recommendation"] | null;
  readonly pilotAuditOffset: number;
  readonly pilotAuditHasNext: boolean;
}

export interface DashboardFilters {
  readonly pilotAuditScenarioId?: string;
  readonly pilotAuditRecommendation?: NflPilotRecommendationAuditResponse["recommendation"];
  readonly pilotAuditOffset?: number;
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
const auditPageSize = 8;

export async function fetchNflPilotRecommendationAuditDetail(
  config: Readonly<AppConfig>,
  scenarioId: string,
  decisionId: string,
  fetcher: Fetcher = fetch,
): Promise<LoadState<NflPilotRecommendationAuditResponse | null>> {
  return load<NflPilotRecommendationAuditResponse | null>(
    config.backendApiUrl,
    `/nfl-pilot-monitor/audit/${encodeURIComponent(decisionId)}?scenario_id=${encodeURIComponent(scenarioId)}`,
    null,
    (value: unknown): value is NflPilotRecommendationAuditResponse => isObject(value),
    fetcher,
    true,
  );
}

export async function verifyNflPilotRecommendationAuditExport(
  config: Readonly<AppConfig>,
  scenarioId: string,
  fingerprint: string,
  fetcher: Fetcher = fetch,
): Promise<LoadState<NflPilotRecommendationAuditVerificationResponse | null>> {
  return load<NflPilotRecommendationAuditVerificationResponse | null>(
    config.backendApiUrl,
    `/nfl-pilot-monitor/audit/verify?scenario_id=${encodeURIComponent(scenarioId)}&fingerprint=${encodeURIComponent(fingerprint)}&limit=100&offset=0`,
    null,
    (value: unknown): value is NflPilotRecommendationAuditVerificationResponse => isObject(value),
    fetcher,
    true,
  );
}

export async function fetchNflPilotAuditVerificationHistory(
  config: Readonly<AppConfig>,
  scenarioId: string,
  offset = 0,
  fetcher: Fetcher = fetch,
): Promise<LoadState<readonly NflPilotAuditVerificationHistoryResponse[]>> {
  return load<NflPilotAuditVerificationHistoryResponse[]>(
    config.backendApiUrl,
    `/nfl-pilot-monitor/audit/verification-history?scenario_id=${encodeURIComponent(scenarioId)}&limit=9&offset=${offset}`,
    [],
    isArray<NflPilotAuditVerificationHistoryResponse>,
    fetcher,
  );
}

export async function fetchDashboardData(
  config: Readonly<AppConfig>,
  fetcher: Fetcher = fetch,
  filters: Readonly<DashboardFilters> = {},
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
    nflAttention,
    nflAlerts,
    nflDispositions,
    nflPilotPositions,
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
      load<NflPilotMonitoringDecisionResponse[]>(
        config.backendApiUrl,
        "/nfl-pilot-monitor/attention?limit=8",
        [],
        isArray<NflPilotMonitoringDecisionResponse>,
        fetcher,
      ),
      load<NflPilotAlertResponse[]>(
        config.backendApiUrl,
        "/nfl-pilot-alerts?limit=8",
        [],
        isArray<NflPilotAlertResponse>,
        fetcher,
      ),
      load<NflPilotDispositionEventResponse[]>(
        config.backendApiUrl,
        "/nfl-pilot-dispositions?limit=8&offset=0",
        [],
        isArray<NflPilotDispositionEventResponse>,
        fetcher,
      ),
      load<NflPilotPositionResponse[]>(
        config.backendApiUrl,
        "/nfl-pilot-positions?limit=8&offset=0",
        [],
        isArray<NflPilotPositionResponse>,
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
  let nflPilotLedger: LoadState<NflPilotLedgerResponse | null> = availableEmpty(null);
  let nflRecommendationAudit: LoadState<readonly NflPilotRecommendationAuditResponse[]> = availableEmpty([]);
  let nflRecommendationAuditSummary: LoadState<NflPilotRecommendationAuditSummaryResponse | null> = availableEmpty(null);
  let pilotAuditHasNext = false;
  const pilotAuditOffset = filters.pilotAuditOffset ?? 0;

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

  const pilotScenarioId = filters.pilotAuditScenarioId ?? nflPilotPositions.data[0]?.scenario_id;
  if (pilotScenarioId !== undefined) {
    const scenarioId = encodeURIComponent(pilotScenarioId);
    const recommendationQuery = filters.pilotAuditRecommendation === undefined
      ? ""
      : `&recommendation=${encodeURIComponent(filters.pilotAuditRecommendation)}`;
    const [ledger, audit, summary] = await Promise.all([
      load<NflPilotLedgerResponse | null>(
        config.backendApiUrl,
        `/nfl-pilot-scenarios/${scenarioId}/ledger`,
        null,
        (value: unknown): value is NflPilotLedgerResponse => isObject(value),
        fetcher,
      ),
      load<NflPilotRecommendationAuditResponse[]>(
        config.backendApiUrl,
        `/nfl-pilot-monitor/audit?scenario_id=${scenarioId}&limit=${auditPageSize + 1}&offset=${pilotAuditOffset}${recommendationQuery}`,
        [],
        isArray<NflPilotRecommendationAuditResponse>,
        fetcher,
      ),
      load<NflPilotRecommendationAuditSummaryResponse | null>(
        config.backendApiUrl,
        `/nfl-pilot-monitor/audit/summary?scenario_id=${scenarioId}`,
        null,
        (value: unknown): value is NflPilotRecommendationAuditSummaryResponse => isObject(value),
        fetcher,
      ),
    ]);
    nflPilotLedger = ledger;
    nflRecommendationAuditSummary = summary;
    pilotAuditHasNext = audit.ok && audit.data.length > auditPageSize;
    nflRecommendationAudit = { ...audit, data: audit.data.slice(0, auditPageSize) };
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
    nflAttention,
    nflAlerts,
    nflDispositions,
    nflPilotPositions,
    nflPilotLedger,
    nflRecommendationAudit,
    nflRecommendationAuditSummary,
    pilotAuditScenarioId: pilotScenarioId ?? null,
    pilotAuditRecommendation: filters.pilotAuditRecommendation ?? null,
    pilotAuditOffset,
    pilotAuditHasNext,
  };
}
