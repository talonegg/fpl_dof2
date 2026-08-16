import { useData } from "../data/DataProvider";
import { Dashboard } from "../components/dashboard/Dashboard";

/**
 * The dashboard (E6-S6, FR-26) — the product's front page. Composition lives in
 * `components/dashboard/Dashboard.tsx`; this route only supplies the published data.
 */
export function DashboardRoute() {
  const { meta, rules, squad, week, plan } = useData();

  return <Dashboard meta={meta} rules={rules} squad={squad} week={week} plan={plan} />;
}
