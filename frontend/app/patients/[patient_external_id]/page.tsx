import { getPatientDetail } from "@/lib/api";
import {
  AuditPanel,
  EmptyState,
  ErrorState,
  EvidenceTable,
  PageHeader,
  SectionCard,
  StatusPill,
} from "@/components/ui";

export const dynamic = "force-dynamic";

export default async function PatientDetailPage({
  params,
}: {
  params: Promise<{ patient_external_id: string }>;
}) {
  const { patient_external_id } = await params;
  const result = await getPatientDetail(patient_external_id).catch((error: unknown) => ({ error }));

  if ("error" in result) {
    return <ErrorState title="Patient detail unavailable" message={String(result.error)} />;
  }

  const patient = result;

  return (
    <div className="stack">
      <PageHeader
        title={patient.patient_name}
        description={`${patient.patient_external_id} · Facility ${patient.facility_id}`}
        actions={
          <>
            {patient.routing_decision ? <StatusPill route={patient.routing_decision.route} /> : null}
            {patient.routing_decision ? <span className="chip chip-outline">{patient.routing_decision.recommended_next_action}</span> : null}
          </>
        }
      />

      <div className="patient-layout">
        <div className="patient-main">
          <SectionCard
            title="Routing summary"
            description={patient.explanation ?? "No routing decision available."}
            actions={patient.routing_decision ? <StatusPill route={patient.routing_decision.route} /> : undefined}
          >
            {patient.routing_decision ? (
              <div className="status-strip">
                <div className="status-card">
                  <span>Route</span>
                  <strong>{patient.routing_decision.route}</strong>
                  <em>{patient.routing_decision.coverage_status}</em>
                </div>
                <div className="status-card">
                  <span>Readiness</span>
                  <strong>{Math.round(patient.routing_decision.readiness_score)}%</strong>
                  <em>Secondary confidence indicator</em>
                </div>
                <div className="status-card">
                  <span>Missing fields</span>
                  <strong>{patient.routing_decision.missing_fields.length}</strong>
                  <em>{patient.routing_decision.missing_fields.length ? patient.routing_decision.missing_fields.join(", ") : "None"}</em>
                </div>
                <div className="status-card">
                  <span>Conflicts</span>
                  <strong>{patient.routing_decision.conflicting_fields.length}</strong>
                  <em>{patient.routing_decision.conflicting_fields.length ? patient.routing_decision.conflicting_fields.join(", ") : "None"}</em>
                </div>
              </div>
            ) : (
              <EmptyState title="No routing decision" message="This patient has not been reconciled yet." />
            )}
          </SectionCard>

          <SectionCard title="Primary wound" description="Selected wound and supporting evidence.">
            {patient.primary_wound ? (
              <div className="details-grid">
                <div className="info-block">
                  <h3>{patient.primary_wound.wound_key}</h3>
                  <p className="fineprint">
                    {patient.primary_wound.wound_type ?? "—"} · {patient.primary_wound.location ?? "—"} · {patient.primary_wound.documentation_state ?? "—"}
                  </p>
                </div>
                <div className="info-block">
                  <strong>Measurements</strong>
                  <div className="muted">
                    {formatMeasure(patient.primary_wound.length_cm, patient.primary_wound.width_cm, patient.primary_wound.depth_cm)}
                  </div>
                </div>
                <div className="info-block">
                  <strong>Drainage</strong>
                  <div className="muted">{patient.primary_wound.drainage_amount ?? "—"}</div>
                </div>
                <div className="info-block">
                  <strong>Source</strong>
                  <div className="muted">
                    {patient.primary_wound.primary_source_type ?? "—"} #{patient.primary_wound.primary_source_record_id ?? "—"}
                  </div>
                </div>
              </div>
            ) : (
              <EmptyState title="No primary wound" message="A primary wound was not selected for this patient." />
            )}
          </SectionCard>

          <SectionCard title="Selected evidence" description="Field-by-field evidence used by the routing engine.">
            <EvidenceTable items={patient.selected_field_evidence} />
          </SectionCard>

          <SectionCard title="Conflicts" description="Disagreements remain visible even when a deterministic winner exists.">
            {patient.conflicts.length ? (
              <div className="table-wrap">
                <table className="table table-compact">
                  <thead>
                    <tr>
                      <th>Field</th>
                      <th>Type</th>
                      <th>State</th>
                      <th>Selected value</th>
                      <th>Explanation</th>
                      <th>Record</th>
                    </tr>
                  </thead>
                  <tbody>
                    {patient.conflicts.map((conflict) => (
                      <tr key={`${conflict.wound_key}-${conflict.field_name}-${conflict.conflict_type}`}>
                        <td>{conflict.field_name}</td>
                        <td>{conflict.conflict_type.replace(/_/g, " ")}</td>
                        <td>{conflict.conflict_state.replace(/_/g, " ")}</td>
                        <td>{conflict.selected_value ?? "—"}</td>
                        <td>{conflict.explanation}</td>
                        <td>
                          <details className="inline-details">
                            <summary>View</summary>
                            <div className="inline-details-body">
                              <pre className="raw-json raw-json--inline">{JSON.stringify(conflict, null, 2)}</pre>
                            </div>
                          </details>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <EmptyState title="No conflicts" message="No conflicts were recorded for this patient." />
            )}
          </SectionCard>

          <SectionCard title="Audit trail" description="Raw source records are collapsed by default.">
            <AuditPanel title="Patient record" defaultOpen={false}>
              <pre className="raw-json">{JSON.stringify(patient.audit.patients, null, 2)}</pre>
            </AuditPanel>
            <AuditPanel title="Coverage records">
              <pre className="raw-json">{JSON.stringify(patient.audit.coverage_records, null, 2)}</pre>
            </AuditPanel>
            <AuditPanel title="Diagnoses">
              <pre className="raw-json">{JSON.stringify(patient.audit.diagnoses, null, 2)}</pre>
            </AuditPanel>
            <AuditPanel title="Progress notes">
              <pre className="raw-json">{JSON.stringify(patient.audit.progress_notes, null, 2)}</pre>
            </AuditPanel>
            <AuditPanel title="Assessments">
              <pre className="raw-json">{JSON.stringify(patient.audit.assessments, null, 2)}</pre>
            </AuditPanel>
            <AuditPanel title="Wound candidates">
              <pre className="raw-json">{JSON.stringify(patient.audit.wound_candidates, null, 2)}</pre>
            </AuditPanel>
          </SectionCard>
        </div>

        <aside className="patient-sidebar">
          <SectionCard title="Patient details" description="Demographics and primary coverage.">
              <div className="kv-grid">
                <div className="kv-row">
                  <span>Birth date</span>
                  <strong>{formatDemographicValue(patient.demographics.birth_date)}</strong>
                </div>
                <div className="kv-row">
                  <span>Gender</span>
                  <strong>{formatDemographicValue(patient.demographics.gender)}</strong>
                </div>
                <div className="kv-row">
                  <span>Primary payer</span>
                  <strong>{formatDemographicValue(patient.demographics.primary_payer_code)}</strong>
                </div>
                <div className="kv-row">
                  <span>New admission</span>
                  <strong>{formatDemographicValue(patient.demographics.is_new_admission, { booleanLabels: true })}</strong>
                </div>
              </div>
          </SectionCard>

          <SectionCard title="Coverage" description="Coverage evidence used for Medicare validation.">
            <div className="subtle-grid">
              {patient.coverage_evidence.map((coverage) => (
                <div className="info-block" key={coverage.id}>
                  <h3>
                    {coverage.payer_name ?? "Coverage"} {coverage.is_active_part_b ? "(Active Part B)" : ""}
                  </h3>
                  <p className="fineprint">
                    {coverage.payer_code ?? "—"} · {coverage.payer_type ?? "—"}
                  </p>
                  <p className="fineprint">
                    {coverage.effective_from ?? "—"} to {coverage.effective_to ?? "present"}
                  </p>
                </div>
              ))}
            </div>
          </SectionCard>

          <SectionCard title="Diagnoses" description="Current source diagnoses.">
            <div className="subtle-grid">
              {patient.diagnoses.map((diagnosis) => (
                <div className="info-block" key={diagnosis.id}>
                  <h3>{diagnosis.icd10_code ?? "—"}</h3>
                  <p className="fineprint">{diagnosis.icd10_description ?? "—"}</p>
                  <p className="fineprint">{diagnosis.clinical_status ?? "—"}</p>
                </div>
              ))}
            </div>
          </SectionCard>

          <SectionCard title="Readiness" description="Deterministic routing outcome and next step.">
            {patient.routing_decision ? (
              <div className="kv-grid">
                <div className="kv-row">
                  <span>Recommended action</span>
                  <strong>{patient.routing_decision.recommended_next_action}</strong>
                </div>
                <div className="kv-row">
                  <span>Readiness score</span>
                  <strong>{Math.round(patient.routing_decision.readiness_score)}%</strong>
                </div>
                <div className="kv-row">
                  <span>Coverage status</span>
                  <strong>{patient.routing_decision.coverage_status}</strong>
                </div>
                <div className="kv-row">
                  <span>Reason codes</span>
                  <strong>{patient.routing_decision.routing_reason_codes_json.join(", ") || "—"}</strong>
                </div>
              </div>
            ) : (
              <EmptyState title="No readiness decision" message="This patient has not been routed yet." />
            )}
          </SectionCard>
        </aside>
      </div>
    </div>
  );
}

function formatMeasure(length: number | null, width: number | null, depth: number | null) {
  const parts = [length, width, depth].filter((value): value is number => value !== null).map((value) => value.toFixed(1));
  return parts.length ? `${parts.join(" × ")} cm` : "—";
}

function formatDemographicValue(value: unknown, options?: { booleanLabels?: boolean }) {
  if (value === null || value === undefined || value === "") {
    return "—";
  }
  if (options?.booleanLabels && typeof value === "boolean") {
    return value ? "Yes" : "No";
  }
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}
