import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useLocation } from "react-router";

import { getChatSession } from "../../lib/api/client";
import { connectChatEvents, type ChatEvent } from "../../lib/chat-events";
import { readWorkspaceState } from "../../lib/workspace-state";

export function ChatWorkspaceRoute() {
  const location = useLocation();
  const workspaceState = readWorkspaceState(location.pathname, location.search);
  const [latestEvent, setLatestEvent] = useState<ChatEvent | null>(null);

  const sessionQuery = useQuery({
    queryKey: ["chat-session", workspaceState.sessionId],
    queryFn: () => getChatSession(workspaceState.sessionId!),
    enabled: Boolean(workspaceState.sessionId),
    retry: false,
  });

  useEffect(() => {
    if (!workspaceState.sessionId) {
      return () => undefined;
    }

    return connectChatEvents(workspaceState.sessionId, setLatestEvent);
  }, [workspaceState.sessionId]);

  return (
    <WorkspaceRouteCard
      title="Chat workspace"
      description="Session-backed chat now reads through the typed frontend client and keeps the SSE transport ready for the next phase of live message wiring."
      sections={[
        ["Active session", workspaceState.sessionId ?? "Start or resume a browser session to lock chat context."],
        [
          "Transcript status",
          sessionQuery.data
            ? `${sessionQuery.data.messages.length} messages loaded`
            : sessionQuery.isError
              ? "Session fetch pending backend connectivity"
              : workspaceState.sessionId
                ? "Loading current transcript"
                : "No session selected yet",
        ],
        [
          "Latest event",
          latestEvent
            ? `${latestEvent.type} (${latestEvent.run_id ?? "no run id"})`
            : "Waiting for EventSource activity",
        ],
      ]}
      footer={`Current route: ${location.pathname}${location.search}`}
    />
  );
}

function WorkspaceRouteCard({
  title,
  description,
  sections,
  footer,
}: {
  title: string;
  description: string;
  sections: Array<[string, string]>;
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
        {sections.map(([label, value]) => (
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
    </div>
  );
}
