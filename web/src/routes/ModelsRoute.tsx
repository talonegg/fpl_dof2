import { useDataState } from "../data/DataProvider";
import { ModelDiffView } from "../components/models/ModelDiffView";
import { ModelsSeasonView } from "../components/models/ModelsSeasonView";

/** All models: season to date across the five frozen models, then champion vs challenger in full. */
export function ModelsRoute() {
  const { state } = useDataState();
  if (state.status !== "ready") return null;
  const { week, challenger, players, models } = state.data;
  return (
    <>
      <ModelsSeasonView models={models} />
      <ModelDiffView champion={week} challenger={challenger} players={players} />
    </>
  );
}
