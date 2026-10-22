import type {
  Fixtures,
  Health,
  History,
  League,
  Log,
  Meta,
  Models,
  ModelsHistory,
  Plan,
  Players,
  Rules,
  Squad,
  Week,
} from "../contract/types";
import type { SeasonReplay } from "../components/history/season";
import { DATA_BASE, MODELS_HISTORY_URL, SEASON_REPLAY_URL, dataStore } from "./store";

export { DATA_BASE, MODELS_HISTORY_URL, SEASON_REPLAY_URL };

export function fetchMeta(): Promise<Meta> {
  return dataStore.get("meta");
}

export function fetchRules(): Promise<Rules> {
  return dataStore.get("rules");
}

export function fetchPlayers(): Promise<Players> {
  return dataStore.get("players");
}

export function fetchSquad(): Promise<Squad> {
  return dataStore.get("squad");
}

export function fetchWeek(): Promise<Week | null> {
  return dataStore.get("week");
}

export function fetchPlan(): Promise<Plan | null> {
  return dataStore.get("plan");
}

export function fetchHistory(): Promise<History | null> {
  return dataStore.get("history");
}

export function fetchFixtures(): Promise<Fixtures | null> {
  return dataStore.get("fixtures");
}

export function fetchLeague(): Promise<League | null> {
  return dataStore.get("league");
}

export function fetchHealth(): Promise<Health | null> {
  return dataStore.get("health");
}

export function fetchLog(): Promise<Log | null> {
  return dataStore.get("log");
}

export function fetchModels(): Promise<Models | null> {
  return dataStore.get("models");
}

export function fetchModelsHistory(): Promise<ModelsHistory | null> {
  return dataStore.get("models_history_2526");
}

export function fetchSeasonReplay(): Promise<SeasonReplay | null> {
  return dataStore.get("models_history_2627_replay");
}

export function resetTrendCaches(): void {
  dataStore.resetTrends();
}
