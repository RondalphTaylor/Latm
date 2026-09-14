import { Dashboard } from "@/components/dashboard";
import { fetchDashboardData, type DashboardFilters } from "@/lib/api/client";
import { getAppConfig } from "@/lib/config";
import { buildDashboardViewModel } from "@/lib/dashboard/view-model";

export const dynamic = "force-dynamic";

interface PageProps {
  readonly searchParams: Promise<Record<string, string | string[] | undefined>>;
}

const isUuid = (value: string): boolean =>
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);

function auditFilters(params: Record<string, string | string[] | undefined>): DashboardFilters {
  const scenario = typeof params.scenario === "string" && isUuid(params.scenario)
    ? params.scenario
    : undefined;
  const recommendation = params.recommendation;
  const allowedRecommendation = recommendation === "hold" || recommendation === "reduce" || recommendation === "close"
    ? recommendation
    : undefined;
  return { pilotAuditScenarioId: scenario, pilotAuditRecommendation: allowedRecommendation };
}

export default async function HomePage({ searchParams }: PageProps) {
  const config = getAppConfig();
  const data = await fetchDashboardData(config, fetch, auditFilters(await searchParams));
  const viewModel = buildDashboardViewModel(data);

  return <Dashboard data={data} mode={config.tradingMode} viewModel={viewModel} />;
}
