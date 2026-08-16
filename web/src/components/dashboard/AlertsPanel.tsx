import type { Week } from "../../contract/types";

type Alert = NonNullable<Week["alerts"]>[number];

const ACTIONABLE: Alert["severity"][] = ["urgent", "warning"];

/** Urgent first, then warning, then whatever order the pipeline emitted within a severity. */
const SEVERITY_RANK: Record<Alert["severity"], number> = {
  urgent: 0,
  warning: 1,
  info: 2,
};

export type AlertTone = "actionable" | "informational";

/**
 * Alerts, split by whether they change what you do before this deadline.
 *
 * Attention is the scarce resource on this page. An availability alert changes the squad; a price
 * nudge changes nothing this week and only matters over a run of them. Putting both in one list at
 * the top means neither is read by November, so the actionable ones sit above the recommendation
 * and the informational ones sit below the squad — present, findable, and not competing with the
 * decision.
 *
 * Severity is styled from the existing danger and warning tokens rather than from new colours.
 * Colour is never the only carrier: each alert also names its severity and its category in text,
 * which is what makes it legible to a screen reader and in the accessibility pass of E6-S9.
 */
export function AlertsPanel({
  alerts,
  tone,
}: {
  alerts: Alert[] | undefined;
  tone: AlertTone;
}) {
  const wanted = (alerts ?? []).filter((alert) =>
    tone === "actionable"
      ? ACTIONABLE.includes(alert.severity)
      : !ACTIONABLE.includes(alert.severity),
  );
  if (wanted.length === 0) return null;

  const ordered = [...wanted].sort(
    (a, b) => SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity],
  );
  const headingId = `dash-alerts-${tone}-heading`;

  return (
    <section
      className={`dash-alerts dash-alerts-${tone}`}
      aria-labelledby={headingId}
      // Actionable alerts are announced when they appear; price notes are not worth interrupting for.
      role={tone === "actionable" ? "alert" : undefined}
      data-testid={`dashboard-alerts-${tone}`}
    >
      <h2 id={headingId} className="dash-alerts-heading">
        {tone === "actionable" ? "Needs your attention" : "Worth knowing"}
      </h2>
      <ul className="dash-alert-list">
        {ordered.map((alert, index) => (
          <li
            key={`${alert.category}-${alert.player_id ?? index}-${index}`}
            className={`dash-alert dash-alert-${alert.severity}`}
            data-testid={`dashboard-alert-${alert.severity}`}
          >
            <span className="dash-alert-tags">
              <span className="dash-alert-severity">{alert.severity}</span>
              <span className="dash-alert-category">{alert.category}</span>
            </span>
            <span className="dash-alert-message">{alert.message}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
