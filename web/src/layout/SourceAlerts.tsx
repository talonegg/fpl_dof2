import type { PublishedData } from "../data/published";
import { modelLabel } from "../data/registry";
import { formatLocalDateTime } from "../format";
import "./sourceAlerts.css";

/** Names joined for a sentence: "A", "A and B", "A, B and C". */
const names = (list: string[]) =>
  list.length < 2 ? list.join("") : `${list.slice(0, -1).join(", ")} and ${list[list.length - 1]}`;

/**
 * ORC-07: a strategy waiting for a source, and a source that has just arrived, on every route.
 *
 * Both are read from published files only (Invariant 8): the offline banner from `models.json`'s
 * latest gameweek, while it is the one being advised and its deadline is ahead; the arrival from a
 * strategy's week file, which carries `arrived` for the one run its source refreshed it in.
 */
export function SourceAlerts({ data, now = Date.now() }: { data: PublishedData; now?: number }) {
  const gameweeks = data.models?.gameweeks ?? [];
  const latest = gameweeks[gameweeks.length - 1];
  const open = (id: string) => {
    const deadline = (data.weeks[id] ?? data.week)?.deadline;
    if (!deadline) return true;
    return deadline.gameweek === (latest?.gameweek ?? deadline.gameweek) && Date.parse(deadline.deadline_utc) > now;
  };
  const offline = Object.entries(latest?.availability ?? {}).filter(
    ([id, a]) => !a.available && (a.sources?.length ?? 0) > 0 && open(id),
  );
  const arrived = Object.entries(data.weeks).filter(([id, w]) => w.arrived && open(id));
  if (offline.length === 0 && arrived.length === 0) return null;
  return (
    <>
      {offline.map(([id, a]) => (
        <p key={id} className="source-alert" role="alert" data-testid={`source-offline-${id}`}>
          <strong>{modelLabel(data.registry, id)} has no advice for GW{latest?.gameweek} yet.</strong>{" "}
          It is waiting for {names(a.sources ?? [])}
          {a.since ? `, missing since ${formatLocalDateTime(a.since)}` : ""}.{" "}
          {a.next_check
            ? `Next checked at ${formatLocalDateTime(a.next_check)}, if GitHub runs that check.`
            : "No further check is due before the deadline."}
        </p>
      ))}
      {arrived.map(([id, w]) => (
        <p key={id} className="source-alert source-arrived" role="status" data-testid={`source-arrived-${id}`}>
          <strong>{names(w.arrived?.sources ?? [])} arrived</strong> at{" "}
          {formatLocalDateTime(w.arrived?.at ?? "")}, and {modelLabel(data.registry, id)} was refreshed with
          it.
        </p>
      ))}
    </>
  );
}
