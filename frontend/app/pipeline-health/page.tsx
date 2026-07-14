import { getPipelineHealth } from "@/lib/api";
import { EmptyState, ErrorState, PageHeader, SectionCard } from "@/components/ui";

export const dynamic = "force-dynamic";

export default async function PipelineHealthPage() {
  const result = await getPipelineHealth().catch((error: unknown) => ({ error }));

  if ("error" in result) {
    return <ErrorState title="Pipeline health unavailable" message={String(result.error)} />;
  }

  return (
    <div className="stack">
      <PageHeader eyebrow="Operations" title="Pipeline Health" description="Latest sync and reconciliation runs, endpoint failures, and record counts." />

      <div className="grid columns-2">
        <SectionCard title="Latest sync run">
          {result.latest_sync_run ? (
            <div className="kv-grid">
              <div className="kv-row">
                <span>Status</span>
                <strong>{result.latest_sync_run.status}</strong>
              </div>
              <div className="kv-row">
                <span>Started</span>
                <strong>{formatDate(result.latest_sync_run.started_at)}</strong>
              </div>
              <div className="kv-row">
                <span>Finished</span>
                <strong>{formatDate(result.latest_sync_run.finished_at)}</strong>
              </div>
              <div className="kv-row">
                <span>Requests</span>
                <strong>{result.latest_sync_run.request_count}</strong>
              </div>
              <div className="kv-row">
                <span>Retries</span>
                <strong>{result.latest_sync_run.retry_count}</strong>
              </div>
              <div className="kv-row">
                <span>429s</span>
                <strong>{result.latest_sync_run.rate_limited_count}</strong>
              </div>
              <div className="kv-row">
                <span>Failures</span>
                <strong>{result.latest_sync_run.failure_count}</strong>
              </div>
              <div className="kv-row">
                <span>Latency</span>
                <strong>{result.latest_sync_run.total_latency_ms} ms</strong>
              </div>
            </div>
          ) : (
            <EmptyState title="No sync history" message="Sync data will appear after the ingestion pipeline runs." />
          )}
        </SectionCard>

        <SectionCard title="Latest reconciliation run">
          {result.latest_reconciliation_run ? (
            <div className="kv-grid">
              <div className="kv-row">
                <span>Status</span>
                <strong>{result.latest_reconciliation_run.status}</strong>
              </div>
              <div className="kv-row">
                <span>Started</span>
                <strong>{formatDate(result.latest_reconciliation_run.started_at)}</strong>
              </div>
              <div className="kv-row">
                <span>Finished</span>
                <strong>{formatDate(result.latest_reconciliation_run.finished_at)}</strong>
              </div>
              <div className="kv-row">
                <span>Patients evaluated</span>
                <strong>{result.latest_reconciliation_run.patients_evaluated}</strong>
              </div>
              <div className="kv-row">
                <span>Wounds reconciled</span>
                <strong>{result.latest_reconciliation_run.wounds_reconciled}</strong>
              </div>
              <div className="kv-row">
                <span>Resolved conflicts</span>
                <strong>{result.latest_reconciliation_run.resolved_conflicts}</strong>
              </div>
              <div className="kv-row">
                <span>Unresolved conflicts</span>
                <strong>{result.latest_reconciliation_run.unresolved_conflicts}</strong>
              </div>
              <div className="kv-row">
                <span>Evaluation date</span>
                <strong>{result.latest_reconciliation_run.evaluation_date ?? "—"}</strong>
              </div>
            </div>
          ) : (
            <EmptyState title="No reconciliation history" message="Reconciliation data will appear after the backend processes candidates." />
          )}
        </SectionCard>
      </div>

      <SectionCard title="Endpoint failures" description="Grouped by URL and status code.">
        {result.endpoint_failures.length ? (
          <div className="table-wrap">
            <table className="table table-compact">
              <thead>
                <tr>
                  <th>Endpoint</th>
                  <th>Status</th>
                  <th>Count</th>
                </tr>
              </thead>
              <tbody>
                {result.endpoint_failures.map((failure) => (
                  <tr key={`${failure.url}-${failure.status_code}`}>
                    <td>{failure.url}</td>
                    <td>{failure.status_code ?? "network"}</td>
                    <td>{failure.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState title="No endpoint failures" message="The latest sync did not record any failed requests." />
        )}
      </SectionCard>
    </div>
  );
}

function formatDate(value: string | null) {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}
