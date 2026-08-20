import { Dashboard } from "@/components/dashboard";
import { fetchDashboardData } from "@/lib/api/client";
import { getAppConfig } from "@/lib/config";
import { buildDashboardViewModel } from "@/lib/dashboard/view-model";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  const config = getAppConfig();
  const data = await fetchDashboardData(config);
  const viewModel = buildDashboardViewModel(data);

  return <Dashboard data={data} mode={config.tradingMode} viewModel={viewModel} />;
}
