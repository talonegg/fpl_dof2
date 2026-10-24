import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { BOTTOM_SECTIONS, MORE_SECTIONS, SECTIONS, sectionOf, slug } from "../routes/nav";
import type { NavSection } from "../routes/nav";

function SectionLink({ section, prefix }: { section: NavSection; prefix: string }) {
  return (
    <NavLink
      to={section.path}
      end={section.path === "/"}
      className={({ isActive }) => `app-nav-link${isActive ? " active" : ""}`}
      data-testid={`${prefix}-${slug(section.label)}`}
    >
      <span className="app-nav-link-full">{section.label}</span>
      <span className="app-nav-link-short">{section.shortLabel}</span>
    </NavLink>
  );
}

/** Wide screens: all eight sections in §1 order. Hidden by CSS on narrow screens, where `BottomBar` takes over. */
export function TopNav() {
  return (
    <nav className="app-nav" aria-label="Main">
      <ul className="app-nav-links">
        {SECTIONS.map((section) => (
          <li key={section.path}>
            <SectionLink section={section} prefix="nav" />
          </li>
        ))}
      </ul>
    </nav>
  );
}

/**
 * Narrow screens (§5 Q3): five sections in a bottom bar and the rest behind "More", a disclosure
 * button. Opening it moves focus to the first entry; Escape closes it and returns focus to the button;
 * following a link closes it.
 */
export function BottomBar() {
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLUListElement>(null);
  const item = useRef<HTMLLIElement>(null);
  const { pathname } = useLocation();
  const inMore = MORE_SECTIONS.some((s) => s === sectionOf(pathname));

  useEffect(() => setOpen(false), [pathname]);
  // A tap anywhere outside the More item closes the menu.
  useEffect(() => {
    if (!open) return;
    const away = (event: MouseEvent) => {
      if (!(event.target instanceof Node) || !item.current?.contains(event.target)) setOpen(false);
    };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open]);
  useEffect(() => {
    if (open) menu.current?.querySelector("a")?.focus();
  }, [open]);

  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key === "Escape" && open) {
      setOpen(false);
      button.current?.focus();
    }
  };

  return (
    <nav className="app-bottombar" aria-label="Sections" data-testid="bottom-bar" onKeyDown={onKeyDown}>
      <ul className="app-bottombar-links">
        {BOTTOM_SECTIONS.map((section) => (
          <li key={section.path}>
            <SectionLink section={section} prefix="bottom" />
          </li>
        ))}
        <li className="app-more" ref={item}>
          <button
            ref={button}
            type="button"
            className={`app-nav-link app-more-button${inMore ? " active" : ""}`}
            aria-expanded={open}
            aria-controls="app-more-menu"
            onClick={() => setOpen((o) => !o)}
            data-testid="bottom-more"
          >
            More
          </button>
          <ul id="app-more-menu" ref={menu} className="app-more-menu" hidden={!open} data-testid="bottom-more-menu">
            {MORE_SECTIONS.map((section) => (
              <li key={section.path}>
                <SectionLink section={section} prefix="more" />
              </li>
            ))}
          </ul>
        </li>
      </ul>
    </nav>
  );
}

/** The current section's sub-views, as links: each tab is a route. Nothing for a single-view section. */
export function SectionTabs() {
  const section = sectionOf(useLocation().pathname);
  if (!section || section.tabs.length === 0) return null;
  return (
    <nav className="section-tabs" aria-label={`${section.label} views`} data-testid="section-tabs">
      {section.tabs.map((tab) => (
        <NavLink
          key={tab.path}
          to={tab.path}
          end
          className={({ isActive }) => `section-tab${isActive ? " active" : ""}`}
          data-testid={`tab-${slug(tab.path.slice(1))}`}
        >
          {tab.label}
        </NavLink>
      ))}
    </nav>
  );
}
