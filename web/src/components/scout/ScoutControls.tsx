/**
 * The scout view's controls: search, facets, the column picker and the saved presets.
 *
 * Everything except search and the position chips lives behind a disclosure. On a phone the table
 * is the point and eight always-open facets would push it off the screen; on a laptop the disclosure
 * costs one click and keeps the same layout, which is cheaper than maintaining two.
 */

import { useState } from "react";
import {
  GROUP_LABELS,
  GROUP_ORDER,
  PINNED_COLUMN,
  SCOUT_COLUMNS,
  type ScoutColumn,
} from "./columns";
import {
  CONFIDENCES,
  POSITIONS,
  activeFilterCount,
  type Confidence,
  type Position,
  type ScoutFilters,
  type ScoutSort,
} from "./filters";
import type { PresetStore, ScoutPreset } from "./presets";

interface ScoutControlsProps {
  filters: ScoutFilters;
  onFiltersChange: (filters: ScoutFilters) => void;
  onResetFilters: () => void;
  clubs: string[];
  priceRange: { min: number; max: number };
  visibleColumns: string[];
  onVisibleColumnsChange: (columns: string[]) => void;
  /** Hidden on a phone, where the card layout picks its own fields. */
  showColumnPicker: boolean;
  sort: ScoutSort;
  onSortChange: (sort: ScoutSort) => void;
  /**
   * Offer sorting as a control rather than as a column header. The card layout has no header to
   * click, and "sort by any column" is the requirement, not "sort by any column on a laptop".
   */
  showSortSelect: boolean;
  presets: PresetStore;
  onApplyPreset: (preset: ScoutPreset) => void;
}

function toggleIn<T>(list: readonly T[], value: T): T[] {
  return list.includes(value) ? list.filter((item) => item !== value) : [...list, value];
}

export function ScoutControls({
  filters,
  onFiltersChange,
  onResetFilters,
  clubs,
  priceRange,
  visibleColumns,
  onVisibleColumnsChange,
  showColumnPicker,
  sort,
  onSortChange,
  showSortSelect,
  presets,
  onApplyPreset,
}: ScoutControlsProps) {
  const [panel, setPanel] = useState<"none" | "filters" | "columns" | "presets">("none");
  const [presetName, setPresetName] = useState("");

  const activeCount = activeFilterCount(filters);

  function set<K extends keyof ScoutFilters>(key: K, value: ScoutFilters[K]) {
    onFiltersChange({ ...filters, [key]: value });
  }

  function togglePanel(next: "filters" | "columns" | "presets") {
    setPanel((current) => (current === next ? "none" : next));
  }

  function toggleColumn(column: ScoutColumn) {
    if (column.key === PINNED_COLUMN) return;
    onVisibleColumnsChange(toggleIn(visibleColumns, column.key));
  }

  function saveCurrentAsPreset() {
    const name = presetName.trim();
    if (name === "") return;
    presets.save({ name, filters, columns: visibleColumns, sort });
    setPresetName("");
  }

  return (
    <div className="scout-controls">
      <div className="scout-controls-primary">
        <input
          type="search"
          className="scout-search"
          placeholder="Search player or club…"
          value={filters.search}
          onChange={(event) => set("search", event.target.value)}
          data-testid="player-search"
          aria-label="Search players by name or club"
        />

        <div className="position-filter-group" role="group" aria-label="Filter by position">
          <button
            type="button"
            className={`position-filter-btn${filters.positions.length === 0 ? " active" : ""}`}
            onClick={() => set("positions", [])}
            aria-pressed={filters.positions.length === 0}
            data-testid="position-filter-ALL"
          >
            All
          </button>
          {POSITIONS.map((position: Position) => {
            const active = filters.positions.includes(position);
            return (
              <button
                key={position}
                type="button"
                className={`position-filter-btn${active ? " active" : ""}`}
                onClick={() => set("positions", toggleIn(filters.positions, position))}
                aria-pressed={active}
                data-testid={`position-filter-${position}`}
              >
                {position}
              </button>
            );
          })}
        </div>

        {showSortSelect && (
          <div className="scout-sort-select">
            <label className="scout-inline-field">
              Sort
              <select
                value={sort.key}
                onChange={(event) => onSortChange({ ...sort, key: event.target.value })}
                data-testid="scout-sort-key"
              >
                {SCOUT_COLUMNS.map((column) => (
                  <option key={column.key} value={column.key}>
                    {column.description}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              className="scout-toggle"
              onClick={() =>
                onSortChange({ ...sort, direction: sort.direction === "asc" ? "desc" : "asc" })
              }
              aria-label={`Sorting ${sort.direction === "asc" ? "ascending" : "descending"}; click to reverse`}
              data-testid="scout-sort-direction"
            >
              {sort.direction === "asc" ? "▲" : "▼"}
            </button>
          </div>
        )}

        <div className="scout-controls-buttons">
          <button
            type="button"
            className={`scout-toggle${panel === "filters" ? " active" : ""}`}
            onClick={() => togglePanel("filters")}
            aria-expanded={panel === "filters"}
            data-testid="scout-filters-toggle"
          >
            Filters{activeCount > 0 ? ` (${activeCount})` : ""}
          </button>
          {showColumnPicker && (
            <button
              type="button"
              className={`scout-toggle${panel === "columns" ? " active" : ""}`}
              onClick={() => togglePanel("columns")}
              aria-expanded={panel === "columns"}
              data-testid="scout-columns-toggle"
            >
              Columns ({visibleColumns.length})
            </button>
          )}
          <button
            type="button"
            className={`scout-toggle${panel === "presets" ? " active" : ""}`}
            onClick={() => togglePanel("presets")}
            aria-expanded={panel === "presets"}
            data-testid="scout-presets-toggle"
          >
            Presets{presets.presets.length > 0 ? ` (${presets.presets.length})` : ""}
          </button>
        </div>
      </div>

      {panel === "filters" && (
        <div className="scout-panel" data-testid="scout-filters-panel">
          <fieldset className="scout-fieldset">
            <legend>Price, £m</legend>
            <label className="scout-inline-field">
              From
              <input
                type="number"
                inputMode="decimal"
                step="0.1"
                min={priceRange.min}
                max={priceRange.max}
                value={filters.minPrice ?? ""}
                placeholder={String(priceRange.min)}
                onChange={(event) =>
                  set("minPrice", event.target.value === "" ? null : Number(event.target.value))
                }
                data-testid="scout-price-min"
              />
            </label>
            <label className="scout-inline-field">
              To
              <input
                type="number"
                inputMode="decimal"
                step="0.1"
                min={priceRange.min}
                max={priceRange.max}
                value={filters.maxPrice ?? ""}
                placeholder={String(priceRange.max)}
                onChange={(event) =>
                  set("maxPrice", event.target.value === "" ? null : Number(event.target.value))
                }
                data-testid="scout-price-max"
              />
            </label>
          </fieldset>

          <fieldset className="scout-fieldset">
            <legend>Availability</legend>
            <label className="scout-checkbox">
              <input
                type="checkbox"
                checked={filters.availableOnly}
                onChange={(event) => set("availableOnly", event.target.checked)}
                data-testid="scout-available-only"
              />
              Available players only
            </label>
          </fieldset>

          <fieldset className="scout-fieldset">
            <legend>Forecast confidence</legend>
            <div className="scout-chip-row">
              {CONFIDENCES.map((confidence: Confidence) => {
                const active = filters.confidences.includes(confidence);
                return (
                  <button
                    key={confidence}
                    type="button"
                    className={`position-filter-btn${active ? " active" : ""}`}
                    onClick={() => set("confidences", toggleIn(filters.confidences, confidence))}
                    aria-pressed={active}
                    data-testid={`scout-confidence-${confidence}`}
                  >
                    {confidence}
                  </button>
                );
              })}
            </div>
          </fieldset>

          <fieldset className="scout-fieldset scout-fieldset-wide">
            <legend>Club</legend>
            <div className="scout-chip-row scout-club-row">
              {clubs.map((club) => {
                const active = filters.clubs.includes(club);
                return (
                  <button
                    key={club}
                    type="button"
                    className={`position-filter-btn${active ? " active" : ""}`}
                    onClick={() => set("clubs", toggleIn(filters.clubs, club))}
                    aria-pressed={active}
                    data-testid={`scout-club-${club}`}
                  >
                    {club}
                  </button>
                );
              })}
            </div>
          </fieldset>

          <button
            type="button"
            className="scout-toggle"
            onClick={onResetFilters}
            data-testid="scout-clear-filters"
          >
            Clear all filters
          </button>
        </div>
      )}

      {panel === "columns" && showColumnPicker && (
        <div className="scout-panel" data-testid="scout-columns-panel">
          {GROUP_ORDER.map((group) => (
            <fieldset key={group} className="scout-fieldset scout-fieldset-wide">
              <legend>{GROUP_LABELS[group]}</legend>
              <div className="scout-chip-row">
                {SCOUT_COLUMNS.filter((column) => column.group === group).map((column) => {
                  const visible = visibleColumns.includes(column.key);
                  const pinned = column.key === PINNED_COLUMN;
                  return (
                    <label
                      key={column.key}
                      className={`scout-checkbox${pinned ? " scout-checkbox-pinned" : ""}`}
                      title={column.description}
                    >
                      <input
                        type="checkbox"
                        checked={visible || pinned}
                        disabled={pinned}
                        onChange={() => toggleColumn(column)}
                        data-testid={`scout-column-${column.key}`}
                      />
                      {column.label}
                    </label>
                  );
                })}
              </div>
            </fieldset>
          ))}
        </div>
      )}

      {panel === "presets" && (
        <div className="scout-panel" data-testid="scout-presets-panel">
          <p className="scout-panel-hint">
            A preset stores the filters, the columns and the sort, on this device only. There is no
            account and nothing is sent anywhere.
          </p>
          <div className="scout-preset-save">
            <label className="scout-inline-field">
              Name
              <input
                type="text"
                value={presetName}
                placeholder="Cheap defenders"
                onChange={(event) => setPresetName(event.target.value)}
                data-testid="scout-preset-name"
              />
            </label>
            <button
              type="button"
              className="scout-toggle"
              onClick={saveCurrentAsPreset}
              disabled={presetName.trim() === ""}
              data-testid="scout-preset-save"
            >
              Save current view
            </button>
          </div>
          {presets.presets.length === 0 ? (
            <p className="scout-panel-hint">No saved presets yet.</p>
          ) : (
            <ul className="scout-preset-list" data-testid="scout-preset-list">
              {presets.presets.map((preset) => (
                <li key={preset.name} className="scout-preset-item">
                  <button
                    type="button"
                    className="scout-preset-apply"
                    onClick={() => onApplyPreset(preset)}
                    data-testid={`scout-preset-apply-${preset.name}`}
                  >
                    {preset.name}
                  </button>
                  <button
                    type="button"
                    className="scout-preset-delete"
                    onClick={() => presets.remove(preset.name)}
                    aria-label={`Delete preset ${preset.name}`}
                    data-testid={`scout-preset-delete-${preset.name}`}
                  >
                    Delete
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
