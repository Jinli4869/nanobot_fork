import {
  Outlet,
  createBrowserRouter,
  createMemoryRouter,
  useLocation,
} from "react-router";

import { WorkspaceShell } from "./shell";
import { readWorkspaceState } from "../lib/workspace-state";

export function createWorkspaceRouter() {
  return createBrowserRouter(buildWorkspaceRoutes());
}

export function createWorkspaceMemoryRouter(initialEntries: string[]) {
  return createMemoryRouter(buildWorkspaceRoutes(), { initialEntries });
}

function buildWorkspaceRoutes() {
  return [
    {
      path: "/",
      element: <WorkspaceShell />,
      children: [
        {
          index: true,
          element: <ChatWorkspaceRoute />,
        },
        {
          path: "chat",
          element: <ChatWorkspaceRoute />,
        },
        {
          path: "chat/:sessionId",
          element: <ChatWorkspaceRoute />,
        },
        {
          path: "operations",
          element: <OperationsWorkspaceRoute />,
        },
      ],
    },
  ];
}

function ChatWorkspaceRoute() {
  const location = useLocation();
  const workspaceState = readWorkspaceState(location.pathname, location.search);

  return (
    <WorkspacePanel
      title="Chat workspace"
      description="Session-backed chat routing is wired first so browser navigation stays stable before live API hooks arrive."
      details={[
        ["Active session", workspaceState.sessionId ?? "Start or resume a session to lock browser context."],
        ["Return path", workspaceState.runId ? `Linked to run ${workspaceState.runId}` : "No linked run selected."],
      ]}
      footer={`Current route: ${location.pathname}${location.search}`}
    />
  );
}

function OperationsWorkspaceRoute() {
  const location = useLocation();
  const workspaceState = readWorkspaceState(location.pathname, location.search);

  return (
    <WorkspacePanel
      title="Operations console"
      description="Operations keeps the selected run and diagnostics panel in search params so the shell can round-trip back to chat without losing context."
      details={[
        ["Linked session", workspaceState.sessionId ?? "No chat session linked yet."],
        ["Selected run", workspaceState.runId ?? "Choose a run once runtime endpoints are wired."],
        ["Panel", workspaceState.panel ?? "overview"],
      ]}
      footer={`Current route: ${location.pathname}${location.search}`}
    />
  );
}

function WorkspacePanel({
  title,
  description,
  details,
  footer,
}: {
  title: string;
  description: string;
  details: Array<[string, string]>;
  footer: string;
}) {
  return (
    <div style={{ display: "grid", gap: "16px" }}>
      <div>
        <h2 style={{ margin: "0 0 8px", fontSize: "1.55rem" }}>{title}</h2>
        <p style={{ margin: 0, lineHeight: 1.6 }}>{description}</p>
      </div>
      <dl
        style={{
          display: "grid",
          gap: "12px",
          margin: 0,
          padding: 0,
          gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
        }}
      >
        {details.map(([label, value]) => (
          <div
            key={label}
            style={{
              padding: "16px",
              borderRadius: "18px",
              background: "rgba(246, 248, 245, 0.95)",
              border: "1px solid rgba(94, 109, 82, 0.14)",
            }}
          >
            <dt style={{ fontSize: "0.82rem", textTransform: "uppercase", letterSpacing: "0.08em" }}>
              {label}
            </dt>
            <dd style={{ margin: "8px 0 0", lineHeight: 1.5 }}>{value}</dd>
          </div>
        ))}
      </dl>
      <p data-testid="route-debug" style={{ margin: 0, color: "rgb(82 91 84)" }}>
        {footer}
      </p>
      <Outlet />
    </div>
  );
}
