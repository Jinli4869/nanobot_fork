import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useLocation } from "react-router";

import { getRuntimeInspection, getTracePlayback } from "../../lib/api/client";
import { readWorkspaceState } from "../../lib/workspace-state";

export function OperationsWorkspaceRoute() {
  const location = useLocation();
  const workspaceState = readWorkspaceState(location.pathname, location.search);
  const runId = workspaceState.runId;

  const runtimeQuery = useQuery({
    queryKey: ["runtime-overview"],
    queryFn: () => getRuntimeInspection(),
    retry: false,
  });
  const playbackQuery = useQuery({
    queryKey: ["runtime-playback", runId],
    queryFn: () => getTracePlayback(runId as string),
    retry: false,
    enabled: Boolean(runId),
  });

  const steps = playbackQuery.data?.steps ?? [];
  const [activeStepIndex, setActiveStepIndex] = useState(0);

  useEffect(() => {
    setActiveStepIndex(0);
  }, [runId, steps.length]);

  useEffect(() => {
    if (steps.length === 0) {
      return;
    }
    if (activeStepIndex > steps.length - 1) {
      setActiveStepIndex(steps.length - 1);
    }
  }, [activeStepIndex, steps.length]);

  const selectedStep = useMemo(
    () => (steps.length > 0 ? steps[activeStepIndex] : null),
    [activeStepIndex, steps],
  );
  const selectedStepModelOutput = useMemo(
    () => JSON.stringify(selectedStep?.model_output ?? {}, null, 2),
    [selectedStep?.model_output],
  );
  const selectedStepExecution = useMemo(
    () => JSON.stringify(selectedStep?.execution ?? {}, null, 2),
    [selectedStep?.execution],
  );
  const selectedStepStability = useMemo(
    () => JSON.stringify(selectedStep?.stability ?? {}, null, 2),
    [selectedStep?.stability],
  );

  return (
    <div style={{ display: "grid", gap: "16px" }}>
      <div>
        <h2 style={{ margin: "0 0 8px", fontSize: "1.55rem" }}>Operations console</h2>
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
        {[
          ["Linked session", workspaceState.sessionId ?? "No chat session linked yet."],
          ["Selected run", workspaceState.runId ?? "Choose a run once the runtime view is populated."],
          ["Panel", workspaceState.panel ?? "overview"],
          [
            "Runtime status",
            runtimeQuery.data
              ? `${runtimeQuery.data.status} (${runtimeQuery.data.active_runs.length} active runs)`
              : runtimeQuery.isError
                ? "Runtime fetch pending backend connectivity"
                : "Loading runtime overview",
          ],
        ].map(([label, value]) => (
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

      {!runId ? (
        <div style={{ padding: "12px 4px", color: "rgba(35, 41, 32, 0.78)" }}>
          Select a run to inspect per-step playback.
        </div>
      ) : null}
      {runId && playbackQuery.isLoading ? (
        <div style={{ padding: "12px 4px", color: "rgba(35, 41, 32, 0.78)" }}>Loading step playback...</div>
      ) : null}
      {runId && playbackQuery.isError ? (
        <div style={{ padding: "12px 4px", color: "#9f1f24" }}>Failed to load playback data for this run.</div>
      ) : null}
      {runId && playbackQuery.data?.status === "empty" ? (
        <div style={{ padding: "12px 4px", color: "rgba(35, 41, 32, 0.78)" }}>No step playback found in this run.</div>
      ) : null}

      {runId && playbackQuery.data?.status === "ok" ? (
        <section
          style={{
            borderRadius: "18px",
            border: "1px solid rgba(94, 109, 82, 0.14)",
            background: "rgba(251, 252, 250, 0.97)",
            padding: "12px",
            display: "grid",
            gap: "12px",
          }}
        >
          <div
            style={{
              display: "grid",
              gap: "12px",
              gridTemplateColumns: "minmax(220px, 1fr) minmax(360px, 2fr) minmax(220px, 1fr)",
            }}
          >
            <div
              style={{
                border: "1px solid rgba(94, 109, 82, 0.14)",
                borderRadius: "14px",
                background: "rgba(255, 255, 255, 0.75)",
                padding: "10px",
                maxHeight: "56vh",
                overflowY: "auto",
              }}
            >
              <div style={{ fontWeight: 600, marginBottom: "8px" }}>Agent Steps</div>
              {steps.map((step, index) => (
                <button
                  key={`${step.step_index}-${index}`}
                  type="button"
                  onClick={() => setActiveStepIndex(index)}
                  style={{
                    width: "100%",
                    textAlign: "left",
                    borderRadius: "10px",
                    marginBottom: "8px",
                    padding: "8px",
                    border: index === activeStepIndex
                      ? "1px solid rgba(34, 98, 196, 0.5)"
                      : "1px solid rgba(94, 109, 82, 0.18)",
                    background: index === activeStepIndex ? "rgba(34, 98, 196, 0.08)" : "white",
                    cursor: "pointer",
                  }}
                >
                  <div style={{ fontWeight: 600, fontSize: "0.92rem" }}>
                    Step {step.step_index}
                  </div>
                  <div style={{ marginTop: "4px", color: "rgba(35, 41, 32, 0.84)", fontSize: "0.86rem" }}>
                    {step.action_summary || "No summary"}
                  </div>
                </button>
              ))}
            </div>

            <div
              style={{
                border: "1px solid rgba(94, 109, 82, 0.14)",
                borderRadius: "14px",
                background: "rgba(255, 255, 255, 0.75)",
                padding: "10px",
              }}
            >
              <div style={{ fontWeight: 600, marginBottom: "8px" }}>
                Device Screen {selectedStep ? `(Step ${selectedStep.step_index})` : ""}
              </div>
              {selectedStep?.screenshot_url ? (
                <img
                  src={selectedStep.screenshot_url}
                  alt={`Step ${selectedStep.step_index} screenshot`}
                  style={{
                    width: "100%",
                    borderRadius: "10px",
                    border: "1px solid rgba(94, 109, 82, 0.18)",
                    objectFit: "contain",
                    maxHeight: "54vh",
                    background: "#f7f9f6",
                  }}
                />
              ) : (
                <div
                  style={{
                    minHeight: "240px",
                    borderRadius: "10px",
                    border: "1px dashed rgba(94, 109, 82, 0.25)",
                    display: "grid",
                    placeItems: "center",
                    color: "rgba(35, 41, 32, 0.6)",
                  }}
                >
                  Screenshot unavailable for this step.
                </div>
              )}
            </div>

            <div
              style={{
                border: "1px solid rgba(94, 109, 82, 0.14)",
                borderRadius: "14px",
                background: "rgba(255, 255, 255, 0.75)",
                padding: "10px",
                maxHeight: "56vh",
                overflowY: "auto",
              }}
            >
              <div style={{ fontWeight: 600, marginBottom: "8px" }}>Model Output</div>
              <div style={{ fontSize: "0.82rem", textTransform: "uppercase", letterSpacing: "0.08em" }}>Action</div>
              <pre style={{ whiteSpace: "pre-wrap", wordBreak: "break-word", fontSize: "0.8rem" }}>
                {selectedStep?.action_summary ?? "(none)"}
              </pre>

              <div style={{ fontSize: "0.82rem", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                Model Snapshot
              </div>
              <pre style={{ whiteSpace: "pre-wrap", wordBreak: "break-word", fontSize: "0.78rem" }}>
                {selectedStepModelOutput}
              </pre>

              <div style={{ fontSize: "0.82rem", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                Execution
              </div>
              <pre style={{ whiteSpace: "pre-wrap", wordBreak: "break-word", fontSize: "0.78rem" }}>
                {selectedStepExecution}
              </pre>

              <div style={{ fontSize: "0.82rem", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                Stability
              </div>
              <pre style={{ whiteSpace: "pre-wrap", wordBreak: "break-word", fontSize: "0.78rem" }}>
                {selectedStepStability}
              </pre>
            </div>
          </div>

          <div style={{ display: "grid", gap: "8px" }}>
            <div style={{ fontSize: "0.92rem", color: "rgba(35, 41, 32, 0.88)" }}>
              Timeline: step {steps.length ? activeStepIndex + 1 : 0} / {steps.length}
            </div>
            <input
              type="range"
              min={0}
              max={Math.max(0, steps.length - 1)}
              value={Math.min(activeStepIndex, Math.max(0, steps.length - 1))}
              onChange={(event) => setActiveStepIndex(Number(event.currentTarget.value))}
              disabled={steps.length <= 1}
            />
          </div>
        </section>
      ) : null}
    </div>
  );
}
