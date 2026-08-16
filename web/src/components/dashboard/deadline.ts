/**
 * Deadline arithmetic and formatting, kept pure so it can be tested across the transition weeks
 * without a browser (DP-03).
 *
 * The wire carries UTC and nothing else (DL-11). The offset between the UK and the owner's local
 * zone is *not* a constant — the UK leaves BST in late October and Australia enters AEDT in early
 * October, so the gap moves from +9 to +11 within a few weeks. Anything baked in at publish time
 * would be silently wrong for exactly the fortnight nobody is checking, so the conversion happens
 * here, in the browser, from the instant.
 */

/**
 * Render an instant in a named IANA zone.
 *
 * An unknown zone must not blank the deadline. UTC is the wrong zone but a legible one, and a
 * legible wrong answer beats an empty box on the one screen that exists to stop a deadline being
 * missed (DP-15).
 */
export function formatInZone(instant: Date, zone: string): string {
  try {
    return new Intl.DateTimeFormat("en-GB", {
      timeZone: zone,
      weekday: "short",
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
      timeZoneName: "short",
    }).format(instant);
  } catch {
    return `${instant.toISOString().slice(0, 16).replace("T", " ")} UTC`;
  }
}

/** True once the instant is in the past. Takes `now` as an argument rather than reading a clock. */
export function hasPassed(target: Date, now: Date): boolean {
  return target.getTime() - now.getTime() <= 0;
}

/**
 * How long until an instant, as prose.
 *
 * Deliberately coarse: days and hours while there is more than a day to go, hours and minutes
 * inside that, and minutes alone in the last hour. Seconds are never shown — a seconds counter
 * invites refreshing a page rather than making a decision, and this figure is not the one anybody
 * should be cutting fine.
 */
export function timeUntil(target: Date, now: Date): string {
  const seconds = Math.floor((target.getTime() - now.getTime()) / 1000);
  if (seconds <= 0) return "passed";

  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);

  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

/**
 * How much attention the countdown deserves, as a class-name suffix.
 *
 * Under six hours is the band where the answer to "shall I look at this tomorrow" changes, so that
 * is where the styling changes too.
 */
export function urgencyOf(target: Date, now: Date): "passed" | "imminent" | "soon" | "distant" {
  const hours = (target.getTime() - now.getTime()) / 3_600_000;
  if (hours <= 0) return "passed";
  if (hours <= 6) return "imminent";
  if (hours <= 36) return "soon";
  return "distant";
}
