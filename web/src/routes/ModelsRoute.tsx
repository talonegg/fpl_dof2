import { useDataState } from "../data/DataProvider";
import { ModelDiffView } from "../components/models/ModelDiffView";

/** Champion vs challenger, side by side. Reads both weeks regardless of the toggle. */
export function ModelsRoute() {
  const { state } = useDataState();
  if (state.status !== "ready") return null;
  const { week, challenger, players } = state.data;
  return <ModelDiffView champion={week} challenger={challenger} players={players} />;
}
