import { useEffect, useState } from "react";
import { fetchMeta, fetchPlan, fetchPlayers, fetchRules, fetchSquad, fetchWeek } from "./api";
import type { Meta, Plan, Players, Rules, Squad, Week } from "./contract/types";
import { Header } from "./components/Header";
import { SquadPitch } from "./components/SquadPitch";
import { Bench } from "./components/Bench";
import { WeekPanel } from "./components/WeekPanel";
import { PlanPanel } from "./components/PlanPanel";
import { PlayerTable } from "./components/PlayerTable";
import "./App.css";

interface LoadedData {
  meta: Meta;
  rules: Rules;
  players: Players;
  squad: Squad;
  week: Week | null;
  plan: Plan | null;
}

export function App() {
  const [data, setData] = useState<LoadedData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetchMeta(),
      fetchRules(),
      fetchPlayers(),
      fetchSquad(),
      fetchWeek(),
      fetchPlan(),
    ])
      .then(([meta, rules, players, squad, week, plan]) => {
        if (!cancelled) setData({ meta, rules, players, squad, week, plan });
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return (
      <div className="app-error" role="alert">
        Could not load published data: {error}
      </div>
    );
  }

  if (!data) {
    return <div className="app-loading">Loading…</div>;
  }

  return (
    <div className="app">
      <Header meta={data.meta} />
      <main>
        {data.week && <WeekPanel week={data.week} />}
        {data.plan && <PlanPanel plan={data.plan} />}
        <SquadPitch squad={data.squad} rules={data.rules} />
        <Bench squad={data.squad} />
        <PlayerTable players={data.players.players} />
      </main>
    </div>
  );
}
