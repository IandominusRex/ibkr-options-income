import { Card } from "@/components/ui/Card";
import { Disclosure } from "@/components/ui/Disclosure";
import { StatusWord } from "@/components/ui/StatusWord";
import { FigureLines } from "./FigureLines";
import { etLabel, percent, shortDay, signedPercent } from "./format";
import type { ClaudeContext, MarketPicture } from "./types";

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

function Stories({ picture }: { picture: MarketPicture }) {
  const stories = picture.stories ?? [];
  return (
    <div className="mt-4">
      <h3 className="text-xs font-semibold tracking-[0.04em] text-muted">Stories</h3>
      {stories.length === 0 ? (
        <p className="mt-1 text-sm">No stories are being tracked.</p>
      ) : (
        <ul className="mt-1">
          {stories.map((s) => (
            <li key={s.id} className="border-t border-border py-3 first:border-t-0">
              <p className="break-words text-sm">
                <span className="font-bold">{s.title}</span> <span className="text-[0.8125rem] text-muted">since {shortDay(s.started_on)}</span>
              </p>
              {s.description && (
                <p className="mt-1 break-words text-sm">
                  <span className="mr-1.5 text-xs font-semibold tracking-[0.04em] text-muted">Claude&apos;s description</span>
                  {s.description}
                </p>
              )}
              {(s.evidence ?? []).length > 0 && (
                <p className="tabular mt-1 font-mono text-[0.8125rem] text-muted">Evidence: {(s.evidence ?? []).join(", ")}</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Numbers({ picture }: { picture: MarketPicture }) {
  const facts = picture.facts ?? [];
  const events = picture.events ?? [];
  const sv = picture.seasonality;
  return (
    <div className="grid gap-4">
      {facts.length > 0 && (
        <FigureLines
          label="Numbers Python computed"
          rows={facts.map((f, i) => ({
            label: (
              <>
                <span className="mr-2 text-muted">F{i + 1}</span>
                {f.label}
              </>
            ),
            value: f.value,
          }))}
        />
      )}
      {sv && (
        <p className="flex flex-wrap items-center gap-2 text-sm">
          <StatusWord>Weak signal</StatusWord>
          <span>
            SPY averaged {signedPercent(sv.avg_return_pct)} in {MONTH_NAMES[sv.month - 1]} ({sv.years}-year average), up in{" "}
            {percent(sv.up_share * 100)} of those years.
          </span>
        </p>
      )}
      {events.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold tracking-[0.04em] text-muted">Coming up</h3>
          <ul className="mt-1 grid gap-1 text-sm">
            {events.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        </div>
      )}
      {facts.length === 0 && !sv && events.length === 0 && <p className="text-sm">No numbers in this picture.</p>}
    </div>
  );
}

/** The picture Claude reads: the stories first, the numbers and the calendar behind a disclosure. */
export function PictureCard({ ctx }: { ctx: ClaudeContext }) {
  const picture = ctx.picture ?? null;
  return (
    <Card aria-labelledby="picture-title">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3">
        <h2 id="picture-title" className="text-[1.0625rem] font-bold">
          Market picture
        </h2>
        {picture && <span className="text-[0.8125rem] text-muted">Rebuilt {etLabel(picture.built_at)}</span>}
      </div>
      {!ctx.available ? (
        <p className="mt-2 text-sm">The news service has not written anything yet, so there is no picture.</p>
      ) : !picture ? (
        <p className="mt-2 text-sm">No picture has been built yet.</p>
      ) : (
        <>
          <p className="mt-1 text-[0.8125rem] text-muted">
            Every Claude call reads this, as plain text. Python wrote the numbers; Claude wrote the descriptions.
          </p>
          {picture.stale && (
            <p className="mt-3 flex flex-wrap items-center gap-2 text-sm">
              <StatusWord tone="flag">Stale</StatusWord>
              <span>
                Stale since {etLabel(picture.built_at)}. Claude&apos;s step failed on the last rebuild, so treat the stories as
                out of date.
              </span>
            </p>
          )}
          {(picture.regimes ?? []).length > 0 && (
            <p className="mt-2 text-[0.8125rem] text-muted">
              Regimes in this picture: {(picture.regimes ?? []).map((r) => `${r.index} ${r.effective}`).join(", ")}.
              {picture.regime_source === "news" && " The regimes were estimated by the news service; the trading service has not recorded one."}
            </p>
          )}
          <Stories picture={picture} />
          <div className="mt-2">
            <Disclosure summary={<span className="text-sm font-semibold">The numbers and what is coming</span>} tone="plain">
              <Numbers picture={picture} />
            </Disclosure>
          </div>
        </>
      )}
    </Card>
  );
}
