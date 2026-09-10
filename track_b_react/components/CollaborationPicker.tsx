"use client";

/**
 * Collaboration picker used by every page that operates on one collaboration.
 *
 * Loads the joined list once and reports the selection upward. Pages should not
 * each re-implement this: getting the joined/invited distinction wrong (a NULL
 * local_name means "invitation not yet joined") is an easy mistake.
 */

import { useEffect, useState } from "react";

import { listCollaborations } from "@/lib/facade";
import type { CollaborationSummary } from "@/lib/types";

import { Alert, Spinner } from "./ui";

export function CollaborationPicker({
  value,
  onChange,
  label = "Collaboration",
}: {
  value: string;
  onChange: (name: string, collab: CollaborationSummary | undefined) => void;
  label?: string;
}) {
  const [joined, setJoined] = useState<CollaborationSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const r = await listCollaborations();
      if (cancelled) return;
      if (r.ok) {
        setJoined(r.data.joined);
        // Auto-select when there is exactly one, so the common case is zero clicks.
        if (!value && r.data.joined.length === 1) {
          const only = r.data.joined[0];
          onChange(only.local_name ?? "", only);
        }
      } else {
        setError(r.error.cause);
      }
      setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (loading) return <Spinner label="Loading collaborations…" />;
  if (error) return <Alert kind="err" title="Could not load collaborations">{error}</Alert>;

  if (!joined.length) {
    return (
      <Alert kind="warn" title="No joined collaborations">
        Create one on the <strong>Create</strong> page, or accept an invitation on{" "}
        <strong>Invitations</strong>. If you expected to see one here, it may have been
        created by a different role — DCR privileges are per-role.
      </Alert>
    );
  }

  return (
    <div className="field">
      <label>{label}</label>
      <select
        value={value}
        onChange={(e) => {
          const name = e.target.value;
          onChange(name, joined.find((c) => c.local_name === name));
        }}
      >
        <option value="">Select…</option>
        {joined.map((c) => (
          <option key={c.local_name} value={c.local_name ?? ""}>
            {c.local_name}
            {c.is_owner ? " (owner)" : ""}
          </option>
        ))}
      </select>
    </div>
  );
}
