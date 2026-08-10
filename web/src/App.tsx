import { useEffect, useState } from "react";
import { fetchMeta, fetchPlayers, fetchRules, fetchSquad } from "./api";
import type { Meta, Players, Rules, Squad } from "./contract/types";
import { Header } from "./components/Header";
import { SquadPitch } from "./components/SquadPitch";
import { Bench } from "./components/Bench";
import { PlayerTable } from "./components/PlayerTable";
import "./App.css";

interface LoadedData {
  meta: Meta;
  rules: Rules;
  players: Players;
  squad: Squad;
}

export function App() {
  const [data, setData] = useState<LoadedData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([fetchMeta(), fetchRules(), fetchPlayers(), fetchSquad()])
      .then(([meta, rules, players, squad]) => {
        if (!cancelled) setData({ meta, rules, players, squad });
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
        <SquadPitch squad={data.squad} rules={data.rules} />
        <Bench squad={data.squad} />
        <PlayerTable players={data.players.players} />
      </main>
    </div>
  );
}
