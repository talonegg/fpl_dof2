import { useTheme } from "../theme/ThemeProvider";

const LABELS: Record<string, { icon: string; text: string }> = {
  light: { icon: "☀", text: "Light" },
  dark: { icon: "☾", text: "Dark" },
  system: { icon: "◐", text: "System" },
};

/**
 * Cycles light → dark → system. "System" is shown as its own state rather than hidden, so a reader
 * who has overridden the theme can always get back to following the operating system.
 */
export function ThemeToggle() {
  const { preference, resolved, cyclePreference } = useTheme();
  const label = LABELS[preference];

  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={cyclePreference}
      data-testid="theme-toggle"
      data-preference={preference}
      data-resolved={resolved}
      title={`Theme: ${label.text}${preference === "system" ? ` (currently ${resolved})` : ""}`}
      aria-label={`Theme: ${label.text}. Change theme.`}
    >
      <span aria-hidden="true">{label.icon}</span>
      <span className="theme-toggle-text">{label.text}</span>
    </button>
  );
}
