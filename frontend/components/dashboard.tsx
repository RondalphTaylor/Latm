import type { ReactNode } from "react";
import Link from "next/link";

import type { DashboardData } from "@/lib/api/client";
import type { TradingPerformanceResponse } from "@/lib/api/contracts";
import type { TradingMode } from "@/lib/config";
import type { DashboardViewModel } from "@/lib/dashboard/view-model";
import {
  decimalSign,
  formatCompactNumber,
  formatMoney,
  formatPrice,
  formatProbability,
  formatSignedMoney,
  formatSignedPercent,
  formatTimestamp,
  humanize,
} from "@/lib/format";

interface DashboardProps {
  readonly data: DashboardData;
  readonly mode: TradingMode;
  readonly viewModel: DashboardViewModel;
}

interface SectionProps {
  readonly id: string;
  readonly eyebrow: string;
  readonly title: string;
  readonly description: string;
  readonly note?: string;
  readonly children: ReactNode;
}

interface EmptyStateProps {
  readonly title: string;
  readonly children: ReactNode;
}

interface MetricProps {
  readonly label: string;
  readonly value: string;
  readonly detail: string;
  readonly tone?: "positive" | "negative" | "flat";
}

function Section({ id, eyebrow, title, description, note, children }: SectionProps) {
  return (
    <section className="dashboard-section" id={id} aria-labelledby={`${id}-title`}>
      <div className="section-heading">
        <div>
          <p className="eyebrow">{eyebrow}</p>
          <h2 id={`${id}-title`}>{title}</h2>
          <p>{description}</p>
        </div>
        {note === undefined ? null : <span className="section-note">{note}</span>}
      </div>
      {children}
    </section>
  );
}

function EmptyState({ title, children }: EmptyStateProps) {
  return (
    <div className="empty-state">
      <span className="empty-state-mark" aria-hidden="true">···</span>
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}

function Metric({ label, value, detail, tone = "flat" }: MetricProps) {
  return (
    <article className="metric-card">
      <p>{label}</p>
      <strong className={`metric-value tone-${tone}`}>{value}</strong>
      <span>{detail}</span>
    </article>
  );
}

function auditHref(scenarioId: string, recommendation: string | null, offset = 0): string {
  const params = new URLSearchParams({ scenario: scenarioId });
  if (recommendation !== null) {
    params.set("recommendation", recommendation);
  }
  if (offset > 0) {
    params.set("offset", String(offset));
  }
  return `/?${params.toString()}#pilot-audit`;
}

function auditDetailHref(
  scenarioId: string,
  decisionId: string,
  recommendation: string | null,
  offset: number,
): string {
  const params = new URLSearchParams({ scenario: scenarioId });
  if (recommendation !== null) {
    params.set("recommendation", recommendation);
  }
  if (offset > 0) {
    params.set("offset", String(offset));
  }
  return `/audit/${encodeURIComponent(decisionId)}?${params.toString()}`;
}

function auditExportHref(
  scenarioId: string,
  recommendation: string | null,
  format: "csv" | "json",
): string {
  const params = new URLSearchParams({ scenario: scenarioId, format });
  if (recommendation !== null) {
    params.set("recommendation", recommendation);
  }
  return `/audit-export?${params.toString()}`;
}

function TableRegion({ label, children }: { readonly label: string; readonly children: ReactNode }) {
  return (
    <div className="table-region" role="region" aria-label={label} tabIndex={0}>
      {children}
    </div>
  );
}

function StatusPill({ value }: { readonly value: string }) {
  const className = value === "trade_candidate" || value === "open" ? "pill-accent" : "";
  return <span className={`status-pill ${className}`}>{humanize(value)}</span>;
}

function PerformanceMetrics({ performance }: { readonly performance: TradingPerformanceResponse }) {
  return (
    <div className="metric-grid performance-metrics">
      <Metric
        label="Total P&L"
        value={formatSignedMoney(performance.net_total_pnl)}
        detail="Realized + current marked equity"
        tone={decimalSign(performance.net_total_pnl)}
      />
      <Metric
        label="Return"
        value={formatSignedPercent(performance.return_on_starting_bankroll)}
        detail="Unannualized on starting bankroll"
        tone={decimalSign(performance.return_on_starting_bankroll)}
      />
      <Metric
        label="Win rate"
        value={formatProbability(performance.win_rate)}
        detail={`${performance.winning_position_count}W · ${performance.losing_position_count}L · ${performance.breakeven_position_count} flat`}
      />
      <Metric
        label="Max drawdown"
        value={formatSignedPercent(`-${performance.maximum_drawdown.fraction}`)}
        detail="Snapshot-sequence sampled"
        tone={performance.maximum_drawdown.amount === "0.00" ? "flat" : "negative"}
      />
    </div>
  );
}

export function Dashboard({ data, mode, viewModel }: DashboardProps) {
  const { primaryPortfolio, performance, mlbCheckpoint, mlbLatestBatch } = viewModel;
  const snapshot = primaryPortfolio?.latest_snapshot;
  const isReady = data.health.ok && data.health.data?.status === "ready";
  const primaryModel = viewModel.modelPerformance[0];
  const selectedAuditScenarioId = data.pilotAuditScenarioId;
  const auditScenarioIds = Array.from(
    new Set([
      ...(selectedAuditScenarioId === null ? [] : [selectedAuditScenarioId]),
      ...data.nflPilotPositions.data.map((position) => position.scenario_id),
    ]),
  );

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to dashboard</a>

      <header className="topbar">
        <a className="brand" href="#overview" aria-label="LATM dashboard home">
          <span className="brand-mark" aria-hidden="true">L</span>
          <span>
            <strong>LATM</strong>
            <small>Research desk</small>
          </span>
        </a>

        <nav className="section-nav" aria-label="Dashboard sections">
          <a href="#positions">Positions</a>
          <a href="#attention">Attention</a>
          <a href="#pilot-history">Pilot history</a>
          <a href="#pilot-positions">Pilot exposure</a>
          <a href="#pilot-ledger">Pilot ledger</a>
          <a href="#pilot-audit">Pilot audit</a>
          <a href="#forecasts">Forecasts</a>
          <a href="#opportunities">Edges</a>
          <a href="#markets">Markets</a>
          <a href="#mlb-research">MLB research</a>
          <a href="#performance">Performance</a>
        </nav>

        <div className="topbar-actions">
          <span className="paper-badge" aria-label="Trading mode: paper, simulated only">
            <span aria-hidden="true" />
            {mode} / simulated
          </span>
          <Link className="refresh-link" href="/">Refresh</Link>
        </div>
      </header>

      <main id="main-content">
        <section className="hero" id="overview" aria-labelledby="overview-title">
          <div className="hero-copy">
            <p className="eyebrow">NBA prediction-market intelligence</p>
            <h1 id="overview-title">The paper desk, at a glance.</h1>
            <p>
              Research signals, exposure, and evaluation live in one auditable view. Every
              number below is read from the backend; this dashboard cannot place an order.
            </p>
            <div className="hero-status-line">
              <span className={`connection-status ${isReady ? "is-ready" : "is-degraded"}`}>
                <span aria-hidden="true" />
                {isReady ? "API ready" : "API degraded"}
              </span>
              <span>
                Refreshed <time dateTime={data.loadedAt}>{formatTimestamp(data.loadedAt)}</time>
              </span>
            </div>
          </div>

          <aside className="safety-panel" aria-label="Paper trading safety status">
            <div>
              <p>Execution boundary</p>
              <strong>Simulation only</strong>
            </div>
            <dl>
              <div><dt>Live orders</dt><dd>Not implemented</dd></div>
              <div><dt>Portfolio</dt><dd>{primaryPortfolio?.name ?? "Not created"}</dd></div>
              <div><dt>Model</dt><dd>{primaryModel?.summary.model_version ?? "Awaiting samples"}</dd></div>
              <div>
                <dt>Data quality</dt>
                <dd>
                  {viewModel.degradedSections.length === 0
                    ? "All reads available"
                    : `${viewModel.degradedSections.length} reads unavailable`}
                </dd>
              </div>
            </dl>
          </aside>
        </section>

        {viewModel.degradedSections.length === 0 ? null : (
          <aside className="degraded-banner" role="status">
            <strong>Partial data view</strong>
            <span>
              Unavailable now: {viewModel.degradedSections.join(", ")}. Healthy sections remain
              usable and missing values are never shown as zero.
            </span>
          </aside>
        )}

        {snapshot === undefined ? (
          <EmptyState title="No paper portfolio yet">
            Create a portfolio through the backend workflow to populate bankroll, exposure, and
            performance. Research data remains available below.
          </EmptyState>
        ) : (
          <div className="metric-grid overview-metrics" aria-label="Portfolio overview">
            <Metric
              label="Portfolio value"
              value={formatMoney(snapshot.total_portfolio_value, snapshot.currency)}
              detail={`Ledger snapshot ${snapshot.sequence}`}
            />
            <Metric
              label="Available bankroll"
              value={formatMoney(snapshot.available_bankroll, snapshot.currency)}
              detail={`${formatMoney(snapshot.committed_capital, snapshot.currency)} committed`}
            />
            <Metric
              label="Realized P&L"
              value={formatSignedMoney(snapshot.realized_pnl, snapshot.currency)}
              detail="Closed and settled exposure"
              tone={decimalSign(snapshot.realized_pnl)}
            />
            <Metric
              label="Unrealized P&L"
              value={formatSignedMoney(snapshot.unrealized_pnl, snapshot.currency)}
              detail="Stored paper marks, not live exits"
              tone={decimalSign(snapshot.unrealized_pnl)}
            />
          </div>
        )}

        <Section
          id="pilot-ledger"
          eyebrow="NFL pilot"
          title="Paper pilot ledger"
          description="Scenario-level simulated balances derived from the isolated pilot ledger. These figures are not a provider account balance."
          note="Read-only scenario summary"
        >
          {!data.nflPilotLedger.ok ? (
            <EmptyState title="Pilot ledger is unavailable">{data.nflPilotLedger.error}</EmptyState>
          ) : data.nflPilotLedger.data === null ? (
            <EmptyState title="No pilot ledger yet">A pilot ledger appears once an isolated pilot position is available.</EmptyState>
          ) : (
            <div className="metric-grid overview-metrics" aria-label="NFL pilot paper ledger">
              <Metric label="Current bankroll" value={formatMoney(data.nflPilotLedger.data.current_bankroll)} detail="Starting bankroll plus realized P&amp;L" />
              <Metric label="Available bankroll" value={formatMoney(data.nflPilotLedger.data.available_bankroll)} detail={`${formatMoney(data.nflPilotLedger.data.committed_capital)} committed`} />
              <Metric label="Realized P&amp;L" value={formatSignedMoney(data.nflPilotLedger.data.realized_pnl)} detail="Recorded simulated exits and settlements" tone={decimalSign(data.nflPilotLedger.data.realized_pnl)} />
              <Metric label="Position status" value={`${data.nflPilotLedger.data.open_positions} open`} detail={`${data.nflPilotLedger.data.settled_positions} completed`} />
            </div>
          )}
        </Section>

        <Section
          id="pilot-audit"
          eyebrow="NFL pilot"
          title="Recommendation audit"
          description="Immutable monitoring recommendations with the exact quote and forecast lineage used at evaluation. A linked disposition is a recorded paper outcome, never a live order."
          note={data.pilotAuditRecommendation === null ? "Latest 8 decisions" : `${humanize(data.pilotAuditRecommendation)} decisions · latest 8`}
        >
          {selectedAuditScenarioId === null ? null : (
            <div className="workflow-copy audit-filters">
              <p>Decision: {([null, "hold", "reduce", "close"] as const).map((recommendation) => (
                <Link
                  className={recommendation === data.pilotAuditRecommendation ? "filter-link filter-link-active" : "filter-link"}
                  href={auditHref(selectedAuditScenarioId, recommendation)}
                  key={recommendation ?? "all"}
                >
                  {recommendation === null ? "All" : humanize(recommendation)}
                </Link>
              ))}</p>
              {auditScenarioIds.length < 2 ? null : <p>Scenario: {auditScenarioIds.map((scenarioId) => (
                <Link
                  className={scenarioId === selectedAuditScenarioId ? "filter-link filter-link-active" : "filter-link"}
                  href={auditHref(scenarioId, data.pilotAuditRecommendation)}
                  key={scenarioId}
                >
                  {scenarioId.slice(0, 8)}
                </Link>
              ))}</p>}
              {!data.nflRecommendationAuditSummary.ok || data.nflRecommendationAuditSummary.data === null ? null : <p>Scenario totals: {data.nflRecommendationAuditSummary.data.total} decisions · {data.nflRecommendationAuditSummary.data.hold} hold · {data.nflRecommendationAuditSummary.data.reduce} reduce · {data.nflRecommendationAuditSummary.data.close} close · {data.nflRecommendationAuditSummary.data.attention_required} attention</p>}
              <p>Export first 100 matching immutable rows: <a className="filter-link" href={auditExportHref(selectedAuditScenarioId, data.pilotAuditRecommendation, "csv")}>CSV</a><a className="filter-link" href={auditExportHref(selectedAuditScenarioId, data.pilotAuditRecommendation, "json")}>JSON</a></p>
            </div>
          )}
          {!data.nflRecommendationAudit.ok ? (
            <EmptyState title="Recommendation audit is unavailable">{data.nflRecommendationAudit.error}</EmptyState>
          ) : data.nflRecommendationAudit.data.length === 0 ? (
            <EmptyState title="No pilot recommendations">Monitoring decisions will appear here once a pilot position is evaluated.</EmptyState>
          ) : (
            <TableRegion label="NFL pilot recommendation audit">
              <table>
                <caption>Latest immutable pilot recommendation evidence</caption>
                <thead>
                  <tr>
                    <th scope="col">Decision</th><th scope="col">Position</th><th scope="col">Quote</th>
                    <th scope="col">Forecast</th><th scope="col" className="numeric">Edge</th><th scope="col">Disposition</th>
                  </tr>
                </thead>
                <tbody>
                  {data.nflRecommendationAudit.data.map((item) => (
                    <tr key={item.decision_id}>
                      <td><StatusPill value={item.recommendation} /><small><Link href={auditDetailHref(selectedAuditScenarioId as string, item.decision_id, data.pilotAuditRecommendation, data.pilotAuditOffset)}>View detail</Link> · {humanize(item.reason)} · {formatTimestamp(item.evaluated_at)}</small></td>
                      <td><strong>{item.position_id.slice(0, 8)}</strong><small>{item.requires_attention ? "Attention required" : "Routine monitoring"}</small></td>
                      <td><StatusPill value={item.quote_status ?? "missing"} /><small>{item.quote_age_seconds === null ? "No quote audit" : `${item.quote_age_seconds}s old`}</small></td>
                      <td><StatusPill value={item.forecast_valid_at_decision === true ? "valid" : item.forecast_valid_at_decision === false ? "stale" : "missing"} /><small>{item.forecast_valid_until === null ? "No forecast" : `Valid until ${formatTimestamp(item.forecast_valid_until)}`}</small></td>
                      <td className={`numeric tone-${decimalSign(item.remaining_edge)}`}>{formatSignedPercent(item.remaining_edge)}</td>
                      <td>{item.disposition_action === null ? "Not disposed" : `${humanize(item.disposition_action)} · ${formatTimestamp(item.disposition_recorded_at)}`}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableRegion>
          )}
          {selectedAuditScenarioId === null ? null : (
            <nav className="audit-pagination" aria-label="Recommendation audit pages">
              {data.pilotAuditOffset === 0 ? <span>Previous</span> : <Link href={auditHref(selectedAuditScenarioId, data.pilotAuditRecommendation, Math.max(0, data.pilotAuditOffset - 8))}>Previous</Link>}
              <span>{data.nflRecommendationAudit.data.length === 0 ? "No rows" : `Rows ${data.pilotAuditOffset + 1}–${data.pilotAuditOffset + data.nflRecommendationAudit.data.length}`}</span>
              {data.pilotAuditHasNext ? <Link href={auditHref(selectedAuditScenarioId, data.pilotAuditRecommendation, data.pilotAuditOffset + 8)}>Next</Link> : <span>Next</span>}
            </nav>
          )}
        </Section>

        <Section
          id="attention"
          eyebrow="NFL pilot"
          title="Attention feed"
          description="Paper-only monitoring recommendations that require review. No action is taken from this dashboard."
          note="Latest 8 flagged recommendations"
        >
          {!data.nflAttention.ok ? (
            <EmptyState title="Attention feed is unavailable">{data.nflAttention.error}</EmptyState>
          ) : viewModel.nflAttention.length === 0 ? (
            <EmptyState title="No NFL pilot attention items">Fresh, qualifying pilot inputs will appear here only when review is needed.</EmptyState>
          ) : (
            <><div className="activity-list">
              {viewModel.nflAttention.map((item) => (
                <article key={item.id}>
                  <span className="activity-icon activity-monitoring" aria-hidden="true">!</span>
                  <div><div className="activity-title"><strong>{humanize(item.recommendation)}</strong><StatusPill value={item.reason} /></div><p>Position {item.position_id.slice(0, 8)}</p><small>{formatTimestamp(item.evaluated_at)}</small></div>
                  <div className="activity-values"><strong>{formatSignedPercent(item.remaining_edge)}</strong><span>Recommendation only</span></div>
                </article>
              ))}
            </div>{data.nflAlerts.ok && data.nflAlerts.data.length > 0 ? <p className="workflow-copy">Alert journal: {data.nflAlerts.data.map((alert) => alert.message).join(" · ")}</p> : null}</>
          )}
        </Section>

        <Section
          id="pilot-positions"
          eyebrow="NFL pilot"
          title="Paper pilot position detail"
          description="Current paper-ledger exposure with original, remaining, and disposed contracts. Linked exits are immutable history, not executable instructions."
          note="Latest 8 isolated pilot positions"
        >
          {!data.nflPilotPositions.ok ? (
            <EmptyState title="Pilot positions are unavailable">{data.nflPilotPositions.error}</EmptyState>
          ) : data.nflPilotPositions.data.length === 0 ? (
            <EmptyState title="No NFL pilot positions">A simulated entry becomes visible here once it has a pilot-ledger projection.</EmptyState>
          ) : (
            <TableRegion label="NFL pilot paper position detail">
              <table>
                <caption>Current isolated NFL pilot ledger projections</caption>
                <thead>
                  <tr>
                    <th scope="col">Position</th><th scope="col">Side</th><th scope="col">Status</th>
                    <th scope="col" className="numeric">Original</th><th scope="col" className="numeric">Remaining</th>
                    <th scope="col" className="numeric">Disposed</th><th scope="col" className="numeric">Cost left</th>
                    <th scope="col" className="numeric">Realized</th><th scope="col">History</th>
                  </tr>
                </thead>
                <tbody>
                  {data.nflPilotPositions.data.map((position) => {
                    const linked = data.nflDispositions.data.filter(
                      (disposition) => disposition.position_id === position.id,
                    );
                    return (
                      <tr key={position.id}>
                        <td><strong>{position.id.slice(0, 8)}</strong><small>Updated {formatTimestamp(position.updated_at)}</small></td>
                        <td className="uppercase">{position.direction}</td>
                        <td><StatusPill value={position.status} /></td>
                        <td className="numeric">{position.quantity}</td>
                        <td className="numeric">{position.remaining_quantity}</td>
                        <td className="numeric">{position.disposed_quantity}</td>
                        <td className="numeric">{formatMoney(position.remaining_cost_basis)}</td>
                        <td className={`numeric tone-${decimalSign(position.realized_pnl)}`}>{formatSignedMoney(position.realized_pnl)}</td>
                        <td>{linked.length === 0 ? "No visible exits" : `${linked.length} linked exit${linked.length === 1 ? "" : "s"}`}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </TableRegion>
          )}
        </Section>

        <Section
          id="pilot-history"
          eyebrow="NFL pilot"
          title="Paper disposition history"
          description="Immutable simulated reductions and closes. This view is observational and cannot submit an order."
          note="Latest 8 simulated exits"
        >
          {!data.nflDispositions.ok ? (
            <EmptyState title="Pilot disposition history is unavailable">{data.nflDispositions.error}</EmptyState>
          ) : data.nflDispositions.data.length === 0 ? (
            <EmptyState title="No NFL pilot dispositions">A revalidated paper reduce or close will appear here after it is recorded.</EmptyState>
          ) : (
            <TableRegion label="NFL pilot paper disposition history">
              <table>
                <caption>Latest immutable simulated NFL exits</caption>
                <thead>
                  <tr>
                    <th scope="col">Action</th><th scope="col">Position</th><th scope="col" className="numeric">Qty</th>
                    <th scope="col" className="numeric">Bid</th><th scope="col" className="numeric">Proceeds</th>
                    <th scope="col" className="numeric">Realized</th><th scope="col">Recorded</th>
                  </tr>
                </thead>
                <tbody>
                  {data.nflDispositions.data.map((item) => (
                    <tr key={item.id}>
                      <td><StatusPill value={item.action} /></td>
                      <td><strong>{item.position_id.slice(0, 8)}</strong><small>Paper only</small></td>
                      <td className="numeric">{item.quantity}</td>
                      <td className="numeric">{formatPrice(item.execution_price)}</td>
                      <td className="numeric">{formatMoney(item.gross_proceeds)}</td>
                      <td className={`numeric tone-${decimalSign(item.realized_pnl_increment)}`}>
                        {formatSignedMoney(item.realized_pnl_increment)}
                      </td>
                      <td>{formatTimestamp(item.recorded_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableRegion>
          )}
        </Section>

        <Section
          id="positions"
          eyebrow="Exposure"
          title="Paper positions"
          description="Current projections with their stored mark basis and audit timestamp."
          note="Latest 8 for the primary portfolio"
        >
          {!data.positions.ok ? (
            <EmptyState title="Positions are unavailable">{data.positions.error}</EmptyState>
          ) : viewModel.positionRows.length === 0 ? (
            <EmptyState title="No paper positions">
              Filled paper entries will appear here with cost basis and marked P&L.
            </EmptyState>
          ) : (
            <TableRegion label="Paper positions table">
              <table>
                <caption>Latest paper position projections</caption>
                <thead>
                  <tr>
                    <th scope="col">Market</th><th scope="col">Side</th><th scope="col">Status</th>
                    <th scope="col" className="numeric">Qty</th><th scope="col" className="numeric">Entry</th>
                    <th scope="col" className="numeric">Mark</th><th scope="col" className="numeric">Value</th>
                    <th scope="col" className="numeric">Unrealized</th>
                  </tr>
                </thead>
                <tbody>
                  {viewModel.positionRows.map((position) => (
                    <tr key={position.id}>
                      <td>
                        <strong>{position.marketTitle}</strong>
                        <small>Mark: {humanize(position.markBasis)} · {formatTimestamp(position.updatedAt)}</small>
                      </td>
                      <td className="uppercase">{position.direction}</td>
                      <td><StatusPill value={position.status} /></td>
                      <td className="numeric">{position.quantity}</td>
                      <td className="numeric">{formatPrice(position.entryPrice)}</td>
                      <td className="numeric">{formatPrice(position.markPrice)}</td>
                      <td className="numeric">{formatMoney(position.marketValue)}</td>
                      <td className={`numeric tone-${decimalSign(position.unrealizedPnl)}`}>
                        {formatSignedMoney(position.unrealizedPnl)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableRegion>
          )}
        </Section>

        <Section
          id="forecasts"
          eyebrow="Model desk"
          title="Forecasts"
          description="Latest operational forecasts joined to normalized games and current market comparisons."
          note="Latest 8 operational forecasts"
        >
          {!data.forecasts.ok ? (
            <EmptyState title="Forecasts are unavailable">{data.forecasts.error}</EmptyState>
          ) : viewModel.forecastRows.length === 0 ? (
            <EmptyState title="No operational forecasts">
              Forecast rows will appear after normalized NBA events have enough pregame history.
            </EmptyState>
          ) : (
            <div className="card-grid">
              {viewModel.forecastRows.map((forecast) => (
                <article className="forecast-card" key={forecast.id}>
                  <div className="card-topline">
                    <span>{forecast.matchup}</span><span>{formatTimestamp(forecast.generatedAt)}</span>
                  </div>
                  <h3>{formatProbability(forecast.homeProbability)} home win</h3>
                  <p>{forecast.model}</p>
                  <dl className="compact-stats">
                    <div><dt>Market</dt><dd>{formatProbability(forecast.marketProbability)}</dd></div>
                    <div>
                      <dt>Raw edge</dt>
                      <dd className={`tone-${decimalSign(forecast.edge)}`}>{formatSignedPercent(forecast.edge)}</dd>
                    </div>
                  </dl>
                </article>
              ))}
            </div>
          )}
        </Section>

        <Section
          id="opportunities"
          eyebrow="Mispricing radar"
          title="Current opportunities"
          description="Direct, same-side market probabilities compared with the active operational model."
          note="Latest 8 current classifications"
        >
          {!data.opportunities.ok ? (
            <EmptyState title="Opportunities are unavailable">{data.opportunities.error}</EmptyState>
          ) : viewModel.opportunityRows.length === 0 ? (
            <EmptyState title="No current opportunities">
              No fresh matched market currently clears the configured watch threshold.
            </EmptyState>
          ) : (
            <TableRegion label="Current opportunities table">
              <table>
                <caption>Latest current market opportunity classifications</caption>
                <thead>
                  <tr>
                    <th scope="col">Market</th><th scope="col">Side</th>
                    <th scope="col" className="numeric">Market</th><th scope="col" className="numeric">Model</th>
                    <th scope="col" className="numeric">Edge</th><th scope="col">Classification</th>
                  </tr>
                </thead>
                <tbody>
                  {viewModel.opportunityRows.map((opportunity) => (
                    <tr key={opportunity.id}>
                      <td><strong>{opportunity.marketTitle}</strong><small>{opportunity.matchup}</small></td>
                      <td className="uppercase">{opportunity.direction}</td>
                      <td className="numeric">{formatProbability(opportunity.marketProbability)}</td>
                      <td className="numeric">{formatProbability(opportunity.modelProbability)}</td>
                      <td className={`numeric tone-${decimalSign(opportunity.edge)}`}>{formatSignedPercent(opportunity.edge)}</td>
                      <td><StatusPill value={opportunity.status} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableRegion>
          )}
        </Section>

        <Section
          id="markets"
          eyebrow="Market tape"
          title="NBA market records"
          description="Provider-normalized binary quotes. Missing liquidity is shown as unavailable, never zero."
          note="Latest 8 NBA records"
        >
          {!data.markets.ok ? (
            <EmptyState title="Markets are unavailable">{data.markets.error}</EmptyState>
          ) : viewModel.marketRows.length === 0 ? (
            <EmptyState title="No NBA markets ingested">
              Run the read-only ingestion workflow to populate normalized market records.
            </EmptyState>
          ) : (
            <TableRegion label="NBA market records table">
              <table>
                <caption>Latest normalized NBA prediction market records</caption>
                <thead>
                  <tr>
                    <th scope="col">Market</th><th scope="col">Status</th>
                    <th scope="col" className="numeric">YES bid / ask</th><th scope="col" className="numeric">NO bid / ask</th>
                    <th scope="col" className="numeric">Volume</th><th scope="col" className="numeric">Liquidity</th>
                  </tr>
                </thead>
                <tbody>
                  {viewModel.marketRows.map((market) => (
                    <tr key={market.id}>
                      <td><strong>{market.title}</strong><small>{market.provider} · priced {formatTimestamp(market.pricedAt)}</small></td>
                      <td><StatusPill value={market.status} /></td>
                      <td className="numeric">{formatPrice(market.yesBid)} / {formatPrice(market.yesAsk)}</td>
                      <td className="numeric">{formatPrice(market.noBid)} / {formatPrice(market.noAsk)}</td>
                      <td className="numeric">{formatCompactNumber(market.volume)}</td>
                      <td className="numeric">{formatCompactNumber(market.liquidity)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableRegion>
          )}
        </Section>

        <Section
          id="mlb-research"
          eyebrow="Offseason research"
          title="MLB dataset readiness"
          description="Checkpointed historical collection and prospective pregame evidence, kept outside every probability and trading path."
          note="Read-only automation observability"
        >
          {!data.mlbReadiness.ok || data.mlbReadiness.data === null ? (
            <EmptyState title="MLB readiness is unavailable">
              {data.mlbReadiness.error ?? "The approved dataset policy could not be loaded."}
            </EmptyState>
          ) : (
            <div className="mlb-research-stack">
              <div className="mlb-readiness-grid" aria-label="MLB dataset split readiness">
                {viewModel.mlbReadinessRows.map((row) => (
                  <article className="mlb-readiness-card" key={row.split}>
                    <div className="performance-title-row">
                      <div>
                        <p>{row.provenance}</p>
                        <h3>{humanize(row.label)}</h3>
                      </div>
                      <StatusPill value={row.shortfall === 0 ? "ready" : "collecting"} />
                    </div>
                    <strong className="mlb-readiness-count">
                      {row.eligible}<span> / {row.minimum}</span>
                    </strong>
                    <meter
                      min={0}
                      max={row.minimum}
                      value={Math.min(row.eligible, row.minimum)}
                      aria-label={`${row.label} readiness: ${row.eligible} of ${row.minimum}`}
                    />
                    <small>{row.shortfall === 0 ? "Threshold met" : `${row.shortfall} games short`}</small>
                  </article>
                ))}
              </div>

              <div className="mlb-workflow-grid">
                <article className="performance-panel">
                  <div className="performance-title-row">
                    <div>
                      <p>Historical workflow</p>
                      <h3>{mlbCheckpoint === null ? "Not started" : humanize(mlbCheckpoint.status)}</h3>
                    </div>
                    <span className="status-pill pill-accent">Research only</span>
                  </div>
                  {mlbCheckpoint === null ? (
                    <p className="workflow-copy">
                      The first scheduled run will create the durable cursor. No historical batch has been consumed.
                    </p>
                  ) : (
                    <dl className="scorecard-grid">
                      <div><dt>Batches</dt><dd>{mlbCheckpoint.batches_completed}</dd></div>
                      <div><dt>Examples created</dt><dd>{mlbCheckpoint.examples_created}</dd></div>
                      <div><dt>Test cursor</dt><dd>{mlbCheckpoint.test_cursor_date} · {mlbCheckpoint.test_cursor_offset}</dd></div>
                      <div><dt>Validation cursor</dt><dd>{mlbCheckpoint.validation_cursor_date} · {mlbCheckpoint.validation_cursor_offset}</dd></div>
                      <div><dt>Train cursor</dt><dd>{mlbCheckpoint.train_cursor_date} · {mlbCheckpoint.train_cursor_offset}</dd></div>
                      <div><dt>Last run</dt><dd>{formatTimestamp(mlbCheckpoint.last_run_at)}</dd></div>
                    </dl>
                  )}
                </article>

                <article className="performance-panel">
                  <div className="performance-title-row">
                    <div>
                      <p>Latest immutable batch</p>
                      <h3>{mlbLatestBatch === null ? "Awaiting first batch" : `Batch ${mlbLatestBatch.sequence}`}</h3>
                    </div>
                    {mlbLatestBatch === null ? null : <StatusPill value={mlbLatestBatch.split} />}
                  </div>
                  {mlbLatestBatch === null ? (
                    <p className="workflow-copy">
                      Batch provenance and terminal reasons will appear after the checkpoint advances.
                    </p>
                  ) : (
                    <>
                      <dl className="scorecard-grid">
                        <div><dt>Window</dt><dd>{mlbLatestBatch.window_date}</dd></div>
                        <div><dt>Examined</dt><dd>{mlbLatestBatch.examined}</dd></div>
                        <div><dt>Vectors</dt><dd>{mlbLatestBatch.retrospective_vectors_built}</dd></div>
                        <div><dt>Examples</dt><dd>{mlbLatestBatch.examples_created}</dd></div>
                      </dl>
                      <ul className="warning-list mlb-result-list">
                        {Object.entries(mlbLatestBatch.result_counts)
                          .filter(([, count]) => count > 0)
                          .sort(([left], [right]) => left.localeCompare(right))
                          .map(([reason, count]) => (
                            <li key={reason}>{humanize(reason)}: {count}</li>
                          ))}
                      </ul>
                    </>
                  )}
                </article>
              </div>

              <p className="mlb-safety-note">
                Model fitting: disabled · Probability generation: disabled · Automatic trading: disabled
              </p>
            </div>
          )}
        </Section>

        <Section
          id="activity"
          eyebrow="Audit trail"
          title="Recent paper activity"
          description="Entry attempts and position-monitoring events, ordered by their recorded timestamps."
          note="Latest 8 combined events"
        >
          {!data.trades.ok && !data.positionEvents.ok ? (
            <EmptyState title="Activity is unavailable">Trade and position-event reads both failed. No activity is being inferred.</EmptyState>
          ) : viewModel.activityRows.length === 0 ? (
            <EmptyState title="No paper activity">Filled entries, rejected attempts, holds, reductions, closes, and settlements will appear here.</EmptyState>
          ) : (
            <div className="activity-list">
              {viewModel.activityRows.map((activity) => (
                <article key={activity.id}>
                  <span className={`activity-icon activity-${activity.kind}`} aria-hidden="true">{activity.kind === "entry" ? "E" : "M"}</span>
                  <div>
                    <div className="activity-title"><strong>{humanize(activity.action)}</strong><StatusPill value={activity.result} /></div>
                    <p>{activity.marketTitle}</p>
                    <small>{formatTimestamp(activity.occurredAt)}{activity.quantity === null ? "" : ` · ${activity.quantity} contracts`}</small>
                  </div>
                  <div className="activity-values">
                    <strong>{formatMoney(activity.amount)}</strong>
                    {activity.pnl === null ? null : <span className={`tone-${decimalSign(activity.pnl)}`}>{formatSignedMoney(activity.pnl)} realized</span>}
                  </div>
                </article>
              ))}
            </div>
          )}
        </Section>

        <Section
          id="performance"
          eyebrow="Evaluation"
          title="Performance & calibration"
          description="Authoritative paper-ledger results and current operational forecast reliability."
          note="No retrospective samples mixed in"
        >
          <div className="performance-stack">
            {performance === null ? (
              <EmptyState title="Trading performance is not available">
                {data.tradingPerformance.error ?? "A paper portfolio with a reconciled ledger is required before trading metrics exist."}
              </EmptyState>
            ) : (
              <div className="performance-panel">
                <div className="performance-title-row">
                  <div><h3>Paper strategy</h3><p>As of <time dateTime={performance.as_of}>{formatTimestamp(performance.as_of)}</time></p></div>
                  <span className="status-pill">{performance.completed_position_count} completed</span>
                </div>
                <PerformanceMetrics performance={performance} />
                {performance.warnings.length === 0 ? null : (
                  <ul className="warning-list">{performance.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
                )}
              </div>
            )}

            {viewModel.modelPerformance.length === 0 ? (
              <EmptyState title="No evaluated operational forecasts">Calibration remains unavailable—not zero or perfect—until completed forecast samples are materialized.</EmptyState>
            ) : (
              <div className="calibration-layout">
                <div className="performance-panel model-scorecard">
                  <p className="eyebrow">Active scorecard</p>
                  <h3>{primaryModel?.summary.model_name} · {primaryModel?.summary.model_version}</h3>
                  <dl className="scorecard-grid">
                    <div><dt>Samples</dt><dd>{primaryModel?.summary.sample_size}</dd></div>
                    <div><dt>Brier</dt><dd>{primaryModel?.summary.mean_brier_score}</dd></div>
                    <div><dt>Accuracy</dt><dd>{formatProbability(primaryModel?.summary.prediction_accuracy)}</dd></div>
                    <div><dt>ECE</dt><dd>{formatProbability(primaryModel?.summary.expected_calibration_error)}</dd></div>
                  </dl>
                </div>
                <div className="performance-panel calibration-panel">
                  <div className="performance-title-row"><div><h3>Reliability bins</h3><p>Prediction confidence versus observed frequency</p></div></div>
                  <div className="calibration-list">
                    {viewModel.calibrationBins.map((bin) => (
                      <div className="calibration-row" key={bin.index}>
                        <span>{formatProbability(bin.lower_bound)}–{formatProbability(bin.upper_bound)}</span>
                        <meter min="0" max="1" value={bin.observed_frequency ?? "0"} aria-label={`Observed frequency in calibration bin ${bin.index + 1}`} />
                        <strong>{bin.sample_size === 0 ? "No samples" : `${formatProbability(bin.observed_frequency)} · n=${bin.sample_size}`}</strong>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>
        </Section>
      </main>

      <footer>
        <div><strong>LATM</strong><span>Auditable prediction-market research</span></div>
        <p>Paper fills are simulated locally. Live execution is outside the MVP.</p>
      </footer>
    </div>
  );
}
