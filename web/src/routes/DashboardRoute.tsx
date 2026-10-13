import { latestModelGameweek, useData, useDataState, useModel } from "../data/DataProvider";
import { hasFullWeek } from "../data/model";
import { Dashboard } from "../components/dashboard/Dashboard";
import { ModelAdviceCard } from "../components/models/ModelAdviceCard";

/**
 * The dashboard (E6-S6, FR-26) — the product's front page. Composition lives in
 * `components/dashboard/Dashboard.tsx`; this route only supplies the published data.
 *
 * Choosing a comparison model without a full week (engine, A, A+odds) adds its advice card above
 * the champion's recommendation; the champion's live advice stays on the page underneath it.
 */
export function DashboardRoute() {
  const { meta, rules, squad, week, plan } = useData();
  const { state } = useDataState();
  const { effective } = useModel();
  const latest = state.status === "ready" ? latestModelGameweek(state.data) : null;
  const comparison =
    !hasFullWeek(effective) && latest ? <ModelAdviceCard model={effective} gameweek={latest} /> : null;

  return (
    <Dashboard
      meta={meta}
      rules={rules}
      squad={squad}
      week={week}
      plan={plan}
      comparison={comparison}
    />
  );
}
