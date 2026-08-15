import { getAppConfig, type TradingMode } from "@/lib/config";

export const dynamic = "force-dynamic";

const tradingModeLabels: Record<TradingMode, string> = {
  paper: "Paper trading",
};

export default function HomePage() {
  const config = getAppConfig();

  return (
    <main className="status-shell">
      <section className="status-card" aria-labelledby="status-title">
        <p className="eyebrow">LATM</p>
        <h1 id="status-title">Application is running</h1>
        <p className="summary">
          The Phase 7 MVP is online with auditable NBA research, paper portfolio accounting,
          advisory position sizing, and deterministic risk decisions in its safe default mode.
        </p>

        <dl className="status-list">
          <div>
            <dt>Application status</dt>
            <dd>
              <span className="status-dot" aria-hidden="true" />
              Online
            </dd>
          </div>
          <div>
            <dt>Trading mode</dt>
            <dd>{tradingModeLabels[config.tradingMode]}</dd>
          </div>
          <div>
            <dt>Base model</dt>
            <dd>NBA Elo V1</dd>
          </div>
          <div>
            <dt>Opportunity strategy</dt>
            <dd>Directional raw edge V1</dd>
          </div>
          <div>
            <dt>Default paper bankroll</dt>
            <dd>$1,000</dd>
          </div>
          <div>
            <dt>Position sizing</dt>
            <dd>Raw-edge bands V1</dd>
          </div>
          <div>
            <dt>Risk policy</dt>
            <dd>Deterministic MVP V1</dd>
          </div>
        </dl>

        <p className="safety-note">No order execution is enabled.</p>
      </section>
    </main>
  );
}
