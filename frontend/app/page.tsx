import Link from "next/link";

import { getFacilities, getPipelineHealth, getSummary } from "@/lib/api";
import { EmptyState, ErrorState, MetricCard, PageHeader, SectionCard } from "@/components/ui";

export const dynamic = "force-dynamic";

export default async function CommandCenterPage() {
  const [summaryResult, facilitiesResult, pipelineResult] = await Promise.allSettled([getSummary(), getFacilities(), getPipelineHealth()]);

  const summary = summaryResult.status === "fulfilled" ? summaryResult.value : null;
  const facilities = facilitiesResult.status === "fulfilled" ? facilitiesResult.value.items : null;
  const pipeline = pipelineResult.status === "fulfilled" ? pipelineResult.value : null;

  return (
    <div className="stack">
      <PageHeader
        title="Command Center"
        description="Current billing readiness across all facilities."
        actions={
          <Link className="button button-secondary" href="/queue">
            Open work queue
          </Link>
        }
      />

      {summary ? (
        <>
          <div className="grid metrics">
            <MetricCard label="Total patients" value={summary.total_patients} />
            <MetricCard label="Active Part B" value={summary.active_medicare_part_b_count} />
            <MetricCard label="Auto accept" value={summary.auto_accept_count} />
            <MetricCard label="Review" value={summary.flag_for_review_count} />
            <MetricCard label="Reject" value={summary.reject_count} />
            <MetricCard
              label="Claim-ready rate"
              value={`${Math.round(summary.claim_ready_rate * 100)}%`}
              note={summary.most_common_missing_field ? `Most common documentation gap: ${summary.most_common_missing_field}` : "No common documentation gap"}
            />
          </div>

          <SectionCard title="Latest pipeline status" description="Most recent sync, reconciliation, and data quality signals.">
            <div className="status-strip">
              <div className="status-card">
                <span>Latest sync</span>
                <strong>{summary.latest_sync_time ? formatTimestamp(summary.latest_sync_time) : "No sync run"}</strong>
                <em>{pipeline?.latest_sync_run ? `${pipeline.latest_sync_run.status} run ${pipeline.latest_sync_run.id}` : "No sync history"}</em>
              </div>
              <div className="status-card">
                <span>Latest reconciliation</span>
                <strong>{summary.latest_reconciliation_time ? formatTimestamp(summary.latest_reconciliation_time) : "No reconciliation run"}</strong>
                <em>{pipeline?.latest_reconciliation_run ? `${pipeline.latest_reconciliation_run.status} run ${pipeline.latest_reconciliation_run.id}` : "No reconciliation history"}</em>
              </div>
              <div className="status-card">
                <span>Unresolved conflicts</span>
                <strong>{summary.unresolved_conflict_count}</strong>
                <em>Route decisions remain deterministic</em>
              </div>
            </div>
          </SectionCard>
        </>
      ) : (
        <ErrorState title="Summary unavailable" message={summaryResult.status === "rejected" ? String(summaryResult.reason) : "Unable to load summary metrics."} />
      )}

      <div className="grid columns-2">
        <SectionCard title="Facility comparison" description="Route mix and documentation gaps by facility.">
          {facilities ? (
            <div className="table-wrap">
              <table className="table table-compact">
                <thead>
                  <tr>
                    <th>Facility</th>
                    <th>Patients</th>
                    <th>Auto accept</th>
                    <th>Review</th>
                    <th>Reject</th>
                    <th>Documentation gap</th>
                    <th>Unresolved conflicts</th>
                  </tr>
                </thead>
                <tbody>
                  {facilities.map((facility) => {
                    const autoAcceptCount = Math.round(facility.auto_accept_rate * facility.patient_count);
                    const reviewCount = Math.round(facility.review_rate * facility.patient_count);
                    const rejectCount = Math.round(facility.reject_rate * facility.patient_count);
                    return (
                      <tr key={facility.facility_id}>
                        <td>
                          <div className="table-cell-stack">
                            <strong>{facility.facility_label}</strong>
                            <span className="muted">Wound mix available below</span>
                          </div>
                        </td>
                        <td>{facility.patient_count}</td>
                        <td>
                          <div className="table-cell-stack">
                            <strong>{autoAcceptCount}</strong>
                            <span className="muted">{Math.round(facility.auto_accept_rate * 100)}%</span>
                          </div>
                        </td>
                        <td>
                          <div className="table-cell-stack">
                            <strong>{reviewCount}</strong>
                            <span className="muted">{Math.round(facility.review_rate * 100)}%</span>
                          </div>
                        </td>
                        <td>
                          <div className="table-cell-stack">
                            <strong>{rejectCount}</strong>
                            <span className="muted">{Math.round(facility.reject_rate * 100)}%</span>
                          </div>
                        </td>
                        <td>{facility.most_common_missing_fields.length ? facility.most_common_missing_fields.join(", ") : "—"}</td>
                        <td>{facility.conflict_count}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState title="No facility data" message="Facility-level metrics appear once reconciliation has current-state rows to summarize." />
          )}
        </SectionCard>

        <SectionCard title="Operational snapshot" description="A compact look at the current workflow.">
          {pipeline ? (
            <div className="subtle-grid">
              <div className="info-block">
                <h3>Latest sync run</h3>
                <div className="details-grid">
                  <div>
                    <strong>{pipeline.latest_sync_run ? pipeline.latest_sync_run.status : "—"}</strong>
                    <div className="muted">Status</div>
                  </div>
                  <div>
                    <strong>{pipeline.latest_sync_run?.request_count ?? 0}</strong>
                    <div className="muted">Requests</div>
                  </div>
                  <div>
                    <strong>{pipeline.latest_sync_run?.retry_count ?? 0}</strong>
                    <div className="muted">Retries</div>
                  </div>
                  <div>
                    <strong>{pipeline.latest_sync_run?.failure_count ?? 0}</strong>
                    <div className="muted">Failures</div>
                  </div>
                </div>
              </div>
              <div className="info-block">
                <h3>Latest reconciliation run</h3>
                <div className="details-grid">
                  <div>
                    <strong>{pipeline.latest_reconciliation_run ? pipeline.latest_reconciliation_run.status : "—"}</strong>
                    <div className="muted">Status</div>
                  </div>
                  <div>
                    <strong>{pipeline.latest_reconciliation_run?.evaluation_date ?? "—"}</strong>
                    <div className="muted">Evaluation date</div>
                  </div>
                  <div>
                    <strong>{pipeline.latest_reconciliation_run?.patients_evaluated ?? 0}</strong>
                    <div className="muted">Patients evaluated</div>
                  </div>
                  <div>
                    <strong>{pipeline.latest_reconciliation_run?.wounds_reconciled ?? 0}</strong>
                    <div className="muted">Wounds reconciled</div>
                  </div>
                  <div>
                    <strong>{pipeline.latest_reconciliation_run?.resolved_conflicts ?? 0}</strong>
                    <div className="muted">Resolved conflicts</div>
                  </div>
                  <div>
                    <strong>{pipeline.latest_reconciliation_run?.unresolved_conflicts ?? 0}</strong>
                    <div className="muted">Unresolved conflicts</div>
                  </div>
                </div>
              </div>
              <div className="info-block">
                <h3>Counts</h3>
                <div className="kv-grid">
                  <div className="kv-row">
                    <span>Patients ingested</span>
                    <strong>{pipeline.records_ingested.patients}</strong>
                  </div>
                  <div className="kv-row">
                    <span>Extraction candidates</span>
                    <strong>{pipeline.extraction_candidate_count}</strong>
                  </div>
                  <div className="kv-row">
                    <span>Endpoint failures</span>
                    <strong>{pipeline.endpoint_failures.length}</strong>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <ErrorState title="Pipeline status unavailable" message={pipelineResult.status === "rejected" ? String(pipelineResult.reason) : "Unable to load pipeline health."} />
          )}
        </SectionCard>
      </div>
    </div>
  );
}

function formatTimestamp(value: string) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parsed);
}
