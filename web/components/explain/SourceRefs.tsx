import type { SourceRef } from "./types";

/**
 * "Under the hood" - the bridge from the simplified explanation back to the real modules
 * and the exhaustive reference docs, for anyone who wants to go past the plain-English
 * version. Deliberately plain (a labelled list, not a diagram) - this is the one place on
 * each panel that is allowed to look like documentation rather than an explainer.
 */
export function SourceRefs({ files }: { files: SourceRef[] }) {
  if (files.length === 0) return null;

  return (
    <div className="mt-6 rounded-md border border-border bg-surface px-4 py-3">
      <h3 className="mb-2 font-mono text-xs uppercase tracking-wide text-muted">
        Under the hood
      </h3>
      <ul className="flex flex-col gap-1">
        {files.map((f) => (
          <li key={f.path} className="text-xs">
            <code className="font-mono text-content">{f.path}</code>
            <span className="text-muted"> &mdash; {f.note}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
