import { NavLink, Outlet, useLocation } from "react-router";

import {
  buildChatHref,
  buildOperationsHref,
  readWorkspaceState,
} from "../lib/workspace-state";

const shellStyles = {
  page: {
    minHeight: "100vh",
    background:
      "linear-gradient(180deg, rgb(244 239 231) 0%, rgb(252 249 243) 42%, rgb(242 246 242) 100%)",
    color: "rgb(33 37 34)",
    fontFamily: '"Iowan Old Style", "Palatino Linotype", "Book Antiqua", serif',
  },
  frame: {
    maxWidth: "1080px",
    margin: "0 auto",
    padding: "32px 20px 48px",
  },
  hero: {
    display: "grid",
    gap: "18px",
    padding: "28px",
    borderRadius: "24px",
    background: "rgba(255, 253, 248, 0.9)",
    border: "1px solid rgba(94, 109, 82, 0.18)",
    boxShadow: "0 20px 48px rgba(94, 109, 82, 0.1)",
  },
  eyebrow: {
    fontSize: "0.78rem",
    letterSpacing: "0.18em",
    textTransform: "uppercase" as const,
    color: "rgb(96 111 81)",
    margin: 0,
  },
  title: {
    fontSize: "clamp(2.3rem, 5vw, 4.4rem)",
    lineHeight: 1,
    margin: 0,
  },
  subtitle: {
    margin: 0,
    maxWidth: "62ch",
    fontSize: "1.02rem",
    lineHeight: 1.6,
    color: "rgb(72 79 74)",
  },
  nav: {
    display: "flex",
    flexWrap: "wrap" as const,
    gap: "12px",
    marginTop: "6px",
  },
  navLink: {
    padding: "12px 18px",
    borderRadius: "999px",
    textDecoration: "none",
    border: "1px solid rgba(94, 109, 82, 0.25)",
    color: "inherit",
    background: "rgba(255, 255, 255, 0.72)",
    fontSize: "0.98rem",
  },
  activeNavLink: {
    background: "rgb(55 76 61)",
    color: "rgb(251 248 241)",
    border: "1px solid rgb(55 76 61)",
  },
  contextRow: {
    display: "flex",
    flexWrap: "wrap" as const,
    gap: "10px",
  },
  badge: {
    display: "inline-flex",
    alignItems: "center",
    gap: "8px",
    padding: "9px 12px",
    borderRadius: "999px",
    background: "rgba(232, 240, 232, 0.9)",
    border: "1px solid rgba(94, 109, 82, 0.18)",
    fontSize: "0.9rem",
  },
  section: {
    marginTop: "22px",
    padding: "28px",
    borderRadius: "24px",
    background: "rgba(255, 255, 255, 0.72)",
    border: "1px solid rgba(94, 109, 82, 0.12)",
  },
};

export function WorkspaceShell() {
  const location = useLocation();
  const workspaceState = readWorkspaceState(location.pathname, location.search);

  const chatHref = buildChatHref(workspaceState);
  const operationsHref = buildOperationsHref(workspaceState);

  return (
    <main style={shellStyles.page}>
      <div style={shellStyles.frame}>
        <section style={shellStyles.hero}>
          <p style={shellStyles.eyebrow}>Nanobot Workspace</p>
          <h1 style={shellStyles.title}>One browser workspace for chat and operations.</h1>
          <p style={shellStyles.subtitle}>
            Phase 20 starts by turning the backend contracts from Phases 17-19 into a single
            route-backed app shell. The active session and selected run stay visible in the URL so
            navigation does not reset the operator&apos;s context.
          </p>
          <nav aria-label="Workspace views" style={shellStyles.nav}>
            <WorkspaceNavLink label="Chat" to={chatHref} />
            <WorkspaceNavLink label="Operations" to={operationsHref} />
          </nav>
          <div style={shellStyles.contextRow}>
            <ContextBadge label="Session" value={workspaceState.sessionId ?? "Not selected"} />
            <ContextBadge label="Run" value={workspaceState.runId ?? "Not selected"} />
            <ContextBadge label="Panel" value={workspaceState.panel ?? "overview"} />
          </div>
        </section>
        <section style={shellStyles.section}>
          <Outlet />
        </section>
      </div>
    </main>
  );
}

function WorkspaceNavLink({ label, to }: { label: string; to: string }) {
  return (
    <NavLink
      to={to}
      style={({ isActive }) => ({
        ...shellStyles.navLink,
        ...(isActive ? shellStyles.activeNavLink : null),
      })}
    >
      {label}
    </NavLink>
  );
}

function ContextBadge({ label, value }: { label: string; value: string }) {
  return (
    <span style={shellStyles.badge}>
      <strong>{label}:</strong> {value}
    </span>
  );
}
