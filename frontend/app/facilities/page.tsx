import { getFacilities } from "@/lib/api";
import { EmptyState, ErrorState, PageHeader, SectionCard } from "@/components/ui";

export const dynamic = "force-dynamic";

export default async function FacilitiesPage() {
  const result = await getFacilities().catch((error: unknown) => ({ error }));

  if ("error" in result) {
    return <ErrorState title="Facility intelligence unavailable" message={String(result.error)} />;
  }

  return (
    <div className="stack">
      <PageHeader
        eyebrow="Operations"
        title="Facility Intelligence"
        description="Compare route mix, documentation gaps, and wound composition across facilities."
      />

      {result.items.length ? (
        <>
          <SectionCard title="Facility comparison" description="Current route mix and documentation gaps by facility.">
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
                  {result.items.map((facility) => {
                    const autoAcceptCount = Math.round(facility.auto_accept_rate * facility.patient_count);
                    const reviewCount = Math.round(facility.review_rate * facility.patient_count);
                    const rejectCount = Math.round(facility.reject_rate * facility.patient_count);
                    return (
                      <tr key={facility.facility_id}>
                        <td>
                          <div className="table-cell-stack">
                            <strong>{facility.facility_label}</strong>
                            <span className="muted">Operational route mix</span>
                          </div>
                        </td>
                        <td>{facility.patient_count}</td>
                        <td>{autoAcceptCount} · {Math.round(facility.auto_accept_rate * 100)}%</td>
                        <td>{reviewCount} · {Math.round(facility.review_rate * 100)}%</td>
                        <td>{rejectCount} · {Math.round(facility.reject_rate * 100)}%</td>
                        <td>{facility.most_common_missing_fields.length ? facility.most_common_missing_fields.join(", ") : "—"}</td>
                        <td>{facility.conflict_count}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </SectionCard>

          <div className="grid columns-2">
            <SectionCard title="Route distribution" description="Auto accept, review, and reject mix by facility.">
              <div className="table-wrap">
                <table className="table table-compact">
                  <thead>
                    <tr>
                      <th>Facility</th>
                      <th>Auto accept</th>
                      <th>Review</th>
                      <th>Reject</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.items.map((facility) => (
                      <tr key={facility.facility_id}>
                        <td>{facility.facility_label}</td>
                        <td>{Math.round(facility.auto_accept_rate * facility.patient_count)} · {Math.round(facility.auto_accept_rate * 100)}%</td>
                        <td>{Math.round(facility.review_rate * facility.patient_count)} · {Math.round(facility.review_rate * 100)}%</td>
                        <td>{Math.round(facility.reject_rate * facility.patient_count)} · {Math.round(facility.reject_rate * 100)}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </SectionCard>

            <SectionCard title="Documentation gaps" description="Most common documentation gap by facility.">
              <div className="table-wrap">
                <table className="table table-compact">
                  <thead>
                    <tr>
                      <th>Facility</th>
                      <th>Documentation gap</th>
                      <th>Unresolved conflicts</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.items.map((facility) => (
                      <tr key={facility.facility_id}>
                        <td>{facility.facility_label}</td>
                        <td>{facility.most_common_missing_fields.length ? facility.most_common_missing_fields.join(", ") : "—"}</td>
                        <td>{facility.conflict_count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </SectionCard>

            <SectionCard title="Wound type mix" description="Top reconciled wound types by facility.">
              <div className="table-wrap">
                <table className="table table-compact">
                  <thead>
                    <tr>
                      <th>Facility</th>
                      <th>Wound type</th>
                      <th>Count</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.items.flatMap((facility) =>
                      facility.wound_type_distribution.length
                        ? facility.wound_type_distribution.map((item) => (
                            <tr key={`${facility.facility_id}-${item.wound_type}`}>
                              <td>{facility.facility_label}</td>
                              <td>{item.wound_type}</td>
                              <td>{item.count}</td>
                            </tr>
                          ))
                        : [
                            <tr key={`${facility.facility_id}-none`}>
                              <td>{facility.facility_label}</td>
                              <td colSpan={2}>No wound mix available</td>
                            </tr>,
                          ],
                    )}
                  </tbody>
                </table>
              </div>
            </SectionCard>
          </div>
        </>
      ) : (
        <EmptyState title="No facility metrics" message="Run reconciliation to populate facility intelligence." />
      )}
    </div>
  );
}
