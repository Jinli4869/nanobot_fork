import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RouterProvider } from "react-router";

import { AppProviders } from "./providers";
import { createWorkspaceMemoryRouter } from "./router";

describe("WorkspaceShell", () => {
  it("keeps the active session visible when navigating between chat and operations", async () => {
    const router = createWorkspaceMemoryRouter([
      "/chat/session-123?runId=run-9&panel=trace",
    ]);

    render(
      <AppProviders>
        <RouterProvider router={router} />
      </AppProviders>,
    );

    screen.getByText("Session:");
    screen.getAllByText("session-123");
    screen.getAllByText("run-9");
    screen.getByText(/Current route: \/chat\/session-123\?runId=run-9&panel=trace/);

    fireEvent.click(screen.getByRole("link", { name: "Operations" }));

    screen.getByText("Operations console");
    screen.getAllByText("session-123");
    screen.getAllByText("run-9");
    screen.getByText(/Current route: \/operations\?sessionId=session-123&runId=run-9&panel=trace/);

    fireEvent.click(screen.getByRole("link", { name: "Chat" }));

    screen.getByText("Chat workspace");
    screen.getAllByText("session-123");
    screen.getByText(/Current route: \/chat\/session-123\?runId=run-9&panel=trace/);
  });
});
