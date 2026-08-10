import { useMemo, useState } from "react";
import type { Player } from "../contract/types";
import { formatPercent, formatPrice, formatXp } from "../format";
import { Decomposition } from "./Decomposition";

interface PlayerTableProps {
  players: Player[];
}

type SortKey =
  | "name"
  | "position"
  | "team"
  | "price"
  | "xp_next"
  | "xp_horizon"
  | "start_probability"
  | "selected_by_percent";

type SortDirection = "asc" | "desc";

const POSITIONS: Array<Player["position"] | "ALL"> = ["ALL", "GKP", "DEF", "MID", "FWD"];

const COLUMNS: { key: SortKey; label: string }[] = [
  { key: "name", label: "Name" },
  { key: "position", label: "Pos" },
  { key: "team", label: "Team" },
  { key: "price", label: "Price" },
  { key: "xp_next", label: "xP next" },
  { key: "xp_horizon", label: "xP horizon" },
  { key: "start_probability", label: "Start %" },
  { key: "selected_by_percent", label: "Selected %" },
];

function sortValue(p: Player, key: SortKey): string | number {
  switch (key) {
    case "name":
      return p.name.toLowerCase();
    case "position":
      return p.position;
    case "team":
      return p.team.toLowerCase();
    case "price":
      return p.price;
    case "xp_next":
      return p.xp_next;
    case "xp_horizon":
      return p.xp_horizon;
    case "start_probability":
      return p.start_probability;
    case "selected_by_percent":
      return p.selected_by_percent ?? -1;
  }
}

export function PlayerTable({ players }: PlayerTableProps) {
  const [search, setSearch] = useState("");
  const [positionFilter, setPositionFilter] = useState<Player["position"] | "ALL">("ALL");
  const [sortKey, setSortKey] = useState<SortKey>("xp_next");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return players.filter((p) => {
      if (positionFilter !== "ALL" && p.position !== positionFilter) return false;
      if (!needle) return true;
      return p.name.toLowerCase().includes(needle) || p.team.toLowerCase().includes(needle);
    });
  }, [players, search, positionFilter]);

  const sorted = useMemo(() => {
    const copy = [...filtered];
    copy.sort((a, b) => {
      const av = sortValue(a, sortKey);
      const bv = sortValue(b, sortKey);
      let cmp: number;
      if (typeof av === "number" && typeof bv === "number") {
        cmp = av - bv;
      } else {
        cmp = String(av).localeCompare(String(bv));
      }
      return sortDirection === "asc" ? cmp : -cmp;
    });
    return copy;
  }, [filtered, sortKey, sortDirection]);

  function handleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDirection((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDirection("desc");
    }
  }

  const selectedPlayer = selectedId !== null ? players.find((p) => p.id === selectedId) ?? null : null;

  return (
    <section data-testid="player-table" className="player-table-section">
      <div className="player-table-controls">
        <input
          type="text"
          placeholder="Search name or club…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          data-testid="player-search"
          aria-label="Search players by name or club"
        />
        <div className="position-filter-group">
          {POSITIONS.map((pos) => (
            <button
              key={pos}
              type="button"
              className={`position-filter-btn${positionFilter === pos ? " active" : ""}`}
              onClick={() => setPositionFilter(pos)}
              data-testid={`position-filter-${pos}`}
            >
              {pos === "ALL" ? "All" : pos}
            </button>
          ))}
        </div>
      </div>

      <div className="player-table-scroll">
        <table>
          <thead>
            <tr>
              {COLUMNS.map((col) => {
                const active = sortKey === col.key;
                return (
                  <th key={col.key}>
                    <button
                      type="button"
                      className={`sort-header${active ? " active" : ""}`}
                      onClick={() => handleSort(col.key)}
                      data-testid={`sort-${col.key}`}
                    >
                      {col.label}
                      {active && <span className="sort-arrow">{sortDirection === "asc" ? " ▲" : " ▼"}</span>}
                    </button>
                  </th>
                );
              })}
              <th>Confidence</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((p) => (
              <tr
                key={p.id}
                className={`player-row${selectedId === p.id ? " selected" : ""}`}
                data-testid="player-row"
                onClick={() => setSelectedId(p.id === selectedId ? null : p.id)}
              >
                <td>{p.name}</td>
                <td>{p.position}</td>
                <td>{p.team}</td>
                <td>{formatPrice(p.price)}</td>
                <td>{formatXp(p.xp_next, p.xp_next_sd)}</td>
                <td>{formatXp(p.xp_horizon, p.xp_horizon_sd)}</td>
                <td>{formatPercent(p.start_probability * 100)}</td>
                <td>{formatPercent(p.selected_by_percent)}</td>
                <td>
                  <span className={`confidence-badge confidence-${p.confidence}`}>{p.confidence}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="player-table-count">
        Showing {sorted.length} of {players.length} players
      </p>

      {selectedPlayer && <Decomposition player={selectedPlayer} />}
    </section>
  );
}
