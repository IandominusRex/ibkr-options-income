"use client";

import { useState } from "react";
import { ClaudePanel } from "./ClaudePanel";
import { DataPanel } from "./DataPanel";
import { ExecutionPanel } from "./ExecutionPanel";
import { GatePanel } from "./GatePanel";
import { IdeasPanel } from "./IdeasPanel";
import { OverviewPanel } from "./OverviewPanel";
import { TAB_META, TAB_ORDER } from "./types";
import type { TabKey } from "./types";
import { WatchingPanel } from "./WatchingPanel";
import { WebLayerPanel } from "./WebLayerPanel";

/**
 * The System Explanation page frame. Plain useState tab switching, same shape as
 * PortfolioShell/PnlShell - no react-query anywhere on this page, because every panel is
 * static content describing how the system works rather than a live view of it. Matches
 * the rest of the app's tab-bar convention (border-b-2 on the active tab) so this console
 * feels like one product rather than a bolted-on docs page.
 */
export function ExplainShell() {
  const [tab, setTab] = useState<TabKey>("overview");

  const panelProps = { onNavigate: setTab };

  return (
    <div className="px-8 py-6">
      <header className="mb-6">
        <h1 className="font-mono text-2xl text-content">System Explanation</h1>
        <p className="mt-1 text-sm text-muted">
          How the whole options-income system actually works, in plain English - one subtab per
          stage, each showing where it sits in the larger pipeline and how it depends on the
          others. Nothing on this page is live data; for that, see Options, Portfolio, and P&amp;L.
        </p>
      </header>

      <nav
        className="mb-6 flex flex-wrap gap-1 border-b border-border"
        aria-label="System Explanation sections"
      >
        {TAB_ORDER.map((key) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            className={
              "border-b-2 px-3 py-2 text-sm transition-colors " +
              (tab === key
                ? "border-focus text-content"
                : "border-transparent text-muted hover:text-content")
            }
            aria-current={tab === key ? "page" : undefined}
          >
            {TAB_META[key].short}
          </button>
        ))}
      </nav>

      {tab === "overview" && <OverviewPanel {...panelProps} />}
      {tab === "data" && <DataPanel {...panelProps} />}
      {tab === "ideas" && <IdeasPanel {...panelProps} />}
      {tab === "gate" && <GatePanel {...panelProps} />}
      {tab === "claude" && <ClaudePanel {...panelProps} />}
      {tab === "execution" && <ExecutionPanel {...panelProps} />}
      {tab === "watching" && <WatchingPanel {...panelProps} />}
      {tab === "web" && <WebLayerPanel {...panelProps} />}
    </div>
  );
}
