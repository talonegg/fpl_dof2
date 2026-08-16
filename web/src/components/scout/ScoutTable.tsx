/**
 * The scout table (E6-S2, FR-27) — the searchable, filterable, sortable view over every player.
 *
 * Three things here are load-bearing rather than decorative:
 *
 * - **Virtualisation** (`@tanstack/react-virtual`). ~700 players across up to eighteen columns is
 *   more cells than a browser will lay out inside the NFR-04 budget, so only the rows in view are
 *   in the DOM. The epic states this as mandatory and DL-36 records why the library rather than a
 *   hand-rolled window.
 * - **Uncertainty on every forecast** (Invariant 6, DP-09). An expected-points mean never renders
 *   without its band, and the cell's tooltip spells the range out in words, because a ±0.9 skims
 *   past in a dense table in a way "plausibly 2.4 to 6.0" does not.
 * - **Two layouts, not one shrunk.** Below `PHONE_QUERY` the rows become cards. A dense grid at
 *   390px is a horizontal scrollbar with a name column bolted to it, which is not the same view
 *   made small — it is a worse view.
 *
 * Selection for comparison travels to `/compare` in the URL; see `data/comparison.ts`.
 */

import { useCallback, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { Player } from "../../contract/types";
import {
  COMPARE_MAX,
  COMPARE_MIN,
  useComparisonSelection,
} from "../../data/comparison";
import { Decomposition } from "../Decomposition";
import { ScoutControls } from "./ScoutControls";
import {
  DEFAULT_VISIBLE_COLUMNS,
  PHONE_COLUMNS,
  orderColumns,
  type ScoutColumn,
} from "./columns";
import {
  DEFAULT_SORT,
  EMPTY_FILTERS,
  clubsIn,
  filterPlayers,
  nextSort,
  priceBounds,
  sortPlayers,
  type ScoutFilters,
  type ScoutSort,
} from "./filters";
import { useScoutPresets, type ScoutPreset } from "./presets";
import { PHONE_QUERY, useMediaQuery } from "./useMediaQuery";
import "./scout.css";

/**
 * Virtualiser geometry. DP-06: named, not scattered as literals.
 *
 * The row heights match `scout.css` and must be changed with it — the virtualiser positions rows
 * itself, so a stylesheet that disagrees produces overlap rather than a layout bug you can see.
 * The overscan is how many rows are kept rendered beyond the viewport: enough that a flick does not
 * show blank space, few enough that it is not a second screenful of work per frame.
 */
const ROW_HEIGHT_PX = 38;
const CARD_HEIGHT_PX = 92;
const OVERSCAN_ROWS = 10;

interface ScoutTableProps {
  players: Player[];
}

export function ScoutTable({ players }: ScoutTableProps) {
  const isPhone = useMediaQuery(PHONE_QUERY);

  const [filters, setFilters] = useState<ScoutFilters>(EMPTY_FILTERS);
  const [sort, setSort] = useState<ScoutSort>(DEFAULT_SORT);
  const [chosenColumns, setChosenColumns] = useState<string[]>(DEFAULT_VISIBLE_COLUMNS);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const presets = useScoutPresets();
  const comparison = useComparisonSelection();

  const clubs = useMemo(() => clubsIn(players), [players]);
  const priceRange = useMemo(() => priceBounds(players), [players]);

  const rows = useMemo(
    () => sortPlayers(filterPlayers(players, filters), sort),
    [players, filters, sort],
  );

  // The phone layout picks its own fields; the picker only governs the wide one.
  const columns = useMemo(
    () => orderColumns(isPhone ? PHONE_COLUMNS : chosenColumns),
    [isPhone, chosenColumns],
  );

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const rowHeight = isPhone ? CARD_HEIGHT_PX : ROW_HEIGHT_PX;
  const virtualiser = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => rowHeight,
    overscan: OVERSCAN_ROWS,
    getItemKey: (index) => rows[index]?.id ?? index,
  });

  const applyPreset = useCallback((preset: ScoutPreset) => {
    setFilters(preset.filters);
    setChosenColumns(preset.columns);
    setSort(preset.sort);
  }, []);

  const expanded = expandedId === null ? null : (rows.find((p) => p.id === expandedId) ?? null);

  // A grid template rather than a `<table>`: the rows are absolutely positioned by the virtualiser,
  // which a table's own layout algorithm would fight. ARIA roles keep it a table to a screen reader.
  const template = `2.4rem ${columns.map((column) => column.width).join(" ")}`;

  return (
    <section className="scout" data-testid="player-table">
      <ScoutControls
        filters={filters}
        onFiltersChange={setFilters}
        onResetFilters={() => setFilters(EMPTY_FILTERS)}
        clubs={clubs}
        priceRange={priceRange}
        visibleColumns={chosenColumns}
        onVisibleColumnsChange={setChosenColumns}
        showColumnPicker={!isPhone}
        sort={sort}
        onSortChange={setSort}
        showSortSelect={isPhone}
        presets={presets}
        onApplyPreset={applyPreset}
      />

      <CompareBar comparison={comparison} players={players} />

      <div
        className={`scout-scroll${isPhone ? " scout-scroll-cards" : ""}`}
        ref={scrollRef}
        data-testid="scout-scroll"
        role="table"
        aria-label="Premier League players"
        aria-rowcount={rows.length}
      >
        {!isPhone && (
          <div className="scout-head" role="row" style={{ gridTemplateColumns: template }}>
            <span className="scout-cell scout-cell-select" role="columnheader">
              <span className="visually-hidden">Compare</span>
            </span>
            {columns.map((column) => (
              <HeaderCell
                key={column.key}
                column={column}
                sort={sort}
                onSort={() => setSort((current) => nextSort(current, column.key))}
              />
            ))}
          </div>
        )}

        <div className="scout-body" style={{ height: `${virtualiser.getTotalSize()}px` }}>
          {virtualiser.getVirtualItems().map((item) => {
            const player = rows[item.index];
            if (!player) return null;
            const selected = comparison.isSelected(player.id);
            const shared = {
              player,
              selected,
              canAdd: comparison.canAdd,
              onToggleCompare: () => comparison.toggle(player.id),
              expanded: expandedId === player.id,
              onExpand: () =>
                setExpandedId((current) => (current === player.id ? null : player.id)),
              offset: item.start,
              height: item.size,
            };
            return isPhone ? (
              <ScoutCardRow key={item.key} {...shared} columns={columns} />
            ) : (
              <ScoutGridRow key={item.key} {...shared} columns={columns} template={template} />
            );
          })}
        </div>
      </div>

      <p className="scout-count" data-testid="scout-count">
        Showing {rows.length} of {players.length} players
        {rows.length === 0 && " — no player matches these filters"}
      </p>

      {expanded && <Decomposition player={expanded} />}
    </section>
  );
}

function HeaderCell({
  column,
  sort,
  onSort,
}: {
  column: ScoutColumn;
  sort: ScoutSort;
  onSort: () => void;
}) {
  const active = sort.key === column.key;
  return (
    <span
      className={`scout-cell scout-cell-head${column.numeric ? " scout-cell-numeric" : ""}`}
      role="columnheader"
      aria-sort={active ? (sort.direction === "asc" ? "ascending" : "descending") : "none"}
    >
      <button
        type="button"
        className={`sort-header${active ? " active" : ""}`}
        onClick={onSort}
        title={column.description}
        data-testid={`sort-${column.key}`}
      >
        {column.label}
        {active && <span className="sort-arrow">{sort.direction === "asc" ? " ▲" : " ▼"}</span>}
      </button>
    </span>
  );
}

interface RowProps {
  player: Player;
  selected: boolean;
  canAdd: boolean;
  onToggleCompare: () => void;
  expanded: boolean;
  onExpand: () => void;
  offset: number;
  height: number;
  columns: ScoutColumn[];
}

/** The virtualiser positions every row; both layouts share this wrapper style. */
function rowStyle(offset: number, height: number) {
  return {
    position: "absolute" as const,
    top: 0,
    left: 0,
    width: "100%",
    height: `${height}px`,
    transform: `translateY(${offset}px)`,
  };
}

function CompareCheckbox({
  player,
  selected,
  canAdd,
  onToggleCompare,
}: Pick<RowProps, "player" | "selected" | "canAdd" | "onToggleCompare">) {
  return (
    <input
      type="checkbox"
      checked={selected}
      // Full means full: disabling says so before the click, rather than dropping it silently.
      disabled={!selected && !canAdd}
      onChange={onToggleCompare}
      onClick={(event) => event.stopPropagation()}
      aria-label={`Compare ${player.name}`}
      data-testid={`compare-${player.id}`}
    />
  );
}

function ScoutGridRow({
  player,
  selected,
  canAdd,
  onToggleCompare,
  expanded,
  onExpand,
  offset,
  height,
  columns,
  template,
}: RowProps & { template: string }) {
  return (
    <div
      className={`scout-row${expanded ? " selected" : ""}`}
      role="row"
      tabIndex={0}
      data-testid="player-row"
      style={{ ...rowStyle(offset, height), gridTemplateColumns: template }}
      onClick={onExpand}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onExpand();
        }
      }}
    >
      <span className="scout-cell scout-cell-select" role="cell">
        <CompareCheckbox
          player={player}
          selected={selected}
          canAdd={canAdd}
          onToggleCompare={onToggleCompare}
        />
      </span>
      {columns.map((column) => (
        <span
          key={column.key}
          className={`scout-cell${column.numeric ? " scout-cell-numeric" : ""}`}
          role="cell"
          title={column.cellTitle?.(player)}
        >
          {column.render(player)}
        </span>
      ))}
    </div>
  );
}

/**
 * The phone row: a card, not a squeezed table row.
 *
 * The fields come from the same column definitions, so a formatting change lands in both layouts
 * at once and neither can drift into showing a bare mean.
 */
function ScoutCardRow({
  player,
  selected,
  canAdd,
  onToggleCompare,
  expanded,
  onExpand,
  offset,
  height,
  columns,
}: RowProps) {
  const [, ...rest] = columns;
  return (
    <div
      className={`scout-card${expanded ? " selected" : ""}`}
      role="row"
      tabIndex={0}
      data-testid="player-row"
      style={rowStyle(offset, height)}
      onClick={onExpand}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onExpand();
        }
      }}
    >
      <div className="scout-card-head">
        <span className="scout-card-name" role="cell">
          {player.name}
        </span>
        <span className={`confidence-badge confidence-${player.confidence}`}>
          {player.confidence}
        </span>
        <CompareCheckbox
          player={player}
          selected={selected}
          canAdd={canAdd}
          onToggleCompare={onToggleCompare}
        />
      </div>
      <div className="scout-card-fields">
        {rest.map((column) => (
          <span key={column.key} className="scout-card-field" role="cell">
            <span className="scout-card-label">{column.label}</span>
            <span className="scout-card-value" title={column.cellTitle?.(player)}>
              {column.render(player)}
            </span>
          </span>
        ))}
      </div>
    </div>
  );
}

/**
 * The comparison tray.
 *
 * Always says how many more are needed, because a link that silently does nothing until a hidden
 * threshold is met is the interaction people give up on.
 */
function CompareBar({
  comparison,
  players,
}: {
  comparison: ReturnType<typeof useComparisonSelection>;
  players: Player[];
}) {
  if (comparison.ids.length === 0) return null;

  const chosen = comparison.ids
    .map((id) => players.find((player) => player.id === id))
    .filter((player): player is Player => player !== undefined);

  return (
    <div className="scout-compare-bar" data-testid="scout-compare-bar">
      <span className="scout-compare-label">
        Comparing {chosen.length} of up to {COMPARE_MAX}:
      </span>
      <span className="scout-compare-names">
        {chosen.map((player) => (
          <button
            key={player.id}
            type="button"
            className="scout-compare-chip"
            onClick={() => comparison.toggle(player.id)}
            aria-label={`Remove ${player.name} from the comparison`}
            data-testid={`scout-compare-chip-${player.id}`}
          >
            {player.name} ×
          </button>
        ))}
      </span>
      {comparison.comparable ? (
        <Link className="scout-compare-go" to={comparison.href} data-testid="scout-compare-go">
          Compare
        </Link>
      ) : (
        <span className="scout-compare-hint" data-testid="scout-compare-hint">
          Pick {COMPARE_MIN - comparison.ids.length} more to compare
        </span>
      )}
      <button
        type="button"
        className="scout-toggle"
        onClick={comparison.clear}
        data-testid="scout-compare-clear"
      >
        Clear
      </button>
    </div>
  );
}
