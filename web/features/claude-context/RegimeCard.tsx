import { Card } from "@/components/ui/Card";
import { Disclosure } from "@/components/ui/Disclosure";
import { StatusWord } from "@/components/ui/StatusWord";
import { FigureLines } from "./FigureLines";
import { cutSentence, etLabel, leveragedLines, percent, regimeLine } from "./format";
import type { ClaudeContext, IndexRegime, RegimeLimit } from "./types";

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

function IndexBlock({ ix, limit }: { ix: IndexRegime; limit: RegimeLimit | undefined }) {
  return (
    // From 640px both indices share three grid rows (heading, line, figures), so the perforations
    // and figures line up even when one index's line wraps and the other's does not.
    <div role="group" aria-label={`${ix.index} regime`} className="min-w-0 sm:row-span-3 sm:grid sm:grid-rows-subgrid">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-[1.0625rem] font-bold">{ix.index}</h3>
        <StatusWord tone={ix.effective === "normal" ? "neutral" : "flag"}>{cap(ix.effective)}</StatusWord>
      </div>
      <p className="mt-1 text-[0.8125rem] text-muted">{regimeLine(ix)}</p>
      {limit ? (
        <FigureLines
          label={`${ix.index} limits on new puts`}
          rows={[
            { label: "Budget", value: `${percent(limit.budget_pct)} of normal` },
            { label: "Per trade", value: `${percent(limit.per_trade_pct)} of normal` },
            { label: "New puts a day", value: limit.max_new_per_day === null ? "No limit" : String(limit.max_new_per_day) },
            { label: "Guaranteed lots a day", value: String(limit.floor_new_per_day) },
          ]}
        />
      ) : (
        <p className="mt-3 text-[0.8125rem] text-muted">
          Limits <span className="hatch mx-0.5 px-1.5 text-unknown">n/a</span> The limits could not be read from the config.
        </p>
      )}
    </div>
  );
}

/** Regime and limits: what the system thinks the market is and what that does to new puts. */
export function RegimeCard({ ctx }: { ctx: ClaudeContext }) {
  const limits = ctx.limits ?? [];
  const lines = leveragedLines(ctx.leveraged ?? []);
  return (
    <Card aria-labelledby="regime-title">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3">
        <h2 id="regime-title" className="text-[1.0625rem] font-bold">
          Regime and limits
        </h2>
        {ctx.regime && <span className="text-[0.8125rem] text-muted">Recorded {etLabel(ctx.regime.as_of)}</span>}
      </div>
      <p className="mt-1 text-[0.8125rem] text-muted">
        How much new cash-secured put risk the system takes, given what it thinks the market is doing.
      </p>

      {!ctx.regime_enabled && (
        <p className="mt-3 flex flex-wrap items-center gap-2 text-sm">
          <StatusWord tone="flag">Off in config</StatusWord>
          <span>The regime limits are switched off in risk_limits.yaml, so none of the limits below is applied.</span>
        </p>
      )}
      {ctx.suspended_today && (
        <p className="mt-3 flex flex-wrap items-center gap-2 text-sm">
          <StatusWord tone="flag">Suspended today</StatusWord>
          <span>/regime off was sent. The regime limits below are not applied today.</span>
        </p>
      )}
      {ctx.claude_cut_breaker_tripped_today && (
        // The day's circuit breaker: Claude zeroed most of the day's auto puts, so cuts are recorded
        // but not applied until tomorrow. The one state here that changes what happens today besides
        // /regime off, so it is a flag word in the same stack (a state is a word), whatever the cut
        // mode below says and whether or not a regime is recorded. Self-contained: the sentence
        // names Claude's size cuts, which the card explains lower down.
        <p className="mt-3 flex flex-wrap items-center gap-2 text-sm">
          <StatusWord tone="flag">Cuts paused today</StatusWord>
          <span>The circuit breaker tripped, so Claude&apos;s size cuts are recorded but not applied until tomorrow.</span>
        </p>
      )}

      {ctx.regime ? (
        <>
          <div className="mt-4 grid gap-5 sm:grid-cols-2 sm:gap-x-6 sm:gap-y-0">
            {[ctx.regime.spy, ctx.regime.qqq].map((ix) => (
              <IndexBlock key={ix.index} ix={ix} limit={limits.find((l) => l.index === ix.index)} />
            ))}
          </div>
        </>
      ) : (
        <p className="mt-4 text-sm">
          <span className="hatch px-1.5 text-unknown">n/a</span> No regime recorded yet. The trading service writes one on
          its first scan.
        </p>
      )}

      <div className="mt-4 border-t border-border pt-3">
        <h3 className="text-xs font-semibold tracking-[0.04em] text-muted">Leveraged ETFs trade smaller still</h3>
        {ctx.leveraged_enabled ? (
          lines.length > 0 && (
            <ul className="mt-1 grid gap-1 text-sm">
              {lines.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
          )
        ) : (
          <p className="mt-1 text-sm">Leveraged-ETF ceilings are switched off.</p>
        )}
        <p className="mt-2 text-sm">{cutSentence(ctx.claude_cut_mode, ctx.account_mode, ctx.claude_cut_breaker_tripped_today)}</p>
        <p className="mt-1 text-[0.8125rem] text-muted">
          Claude can lower the size of a put the system opens on its own. It can never raise it.
        </p>
      </div>

      <div className="mt-3">
        <Disclosure summary={<span className="text-sm font-semibold">What the limits mean</span>} tone="plain">
          <ul className="grid gap-1.5 text-sm text-muted">
            <li>Budget: how much of the normal capital allowance for new puts is open in this regime.</li>
            <li>Per trade: the largest single order, against its normal size.</li>
            <li>New puts a day: the most the system opens in one day.</li>
            <li>Guaranteed lots a day: lots that a full book cannot block, so one gets through each day.</li>
          </ul>
        </Disclosure>
      </div>
    </Card>
  );
}
