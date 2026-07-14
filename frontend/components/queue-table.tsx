import Link from "next/link";

import { StatusPill } from "@/components/ui";
import type { PatientListItem } from "@/lib/types";

type QueueSortKey = "patient_name" | "facility_id" | "route" | "readiness_score";

export function QueueTable({
  items,
  sortBy,
  sortOrder,
  buildSortHref,
}: {
  items: PatientListItem[];
  sortBy: QueueSortKey;
  sortOrder: "asc" | "desc";
  buildSortHref: (sortBy: QueueSortKey) => string;
}) {
  return (
    <div className="table-wrap">
      <table className="table table-compact">
        <thead>
          <tr>
            <SortableHeader label="Patient" active={sortBy === "patient_name"} sortOrder={sortOrder} href={buildSortHref("patient_name")} />
            <SortableHeader label="Facility" active={sortBy === "facility_id"} sortOrder={sortOrder} href={buildSortHref("facility_id")} />
            <SortableHeader label="Route" active={sortBy === "route"} sortOrder={sortOrder} href={buildSortHref("route")} />
            <SortableHeader label="Readiness" active={sortBy === "readiness_score"} sortOrder={sortOrder} href={buildSortHref("readiness_score")} />
            <th>Wound</th>
            <th>Location</th>
            <th>Measurements</th>
            <th>Part B</th>
            <th>Gaps</th>
            <th>Unresolved conflicts</th>
            <th>Next action</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.patient_external_id}>
              <td>
                <div className="table-cell-stack">
                  <Link className="strong-link" href={`/patients/${encodeURIComponent(item.patient_external_id)}`}>
                    {item.patient_name}
                  </Link>
                  <span className="muted">{item.patient_external_id}</span>
                </div>
              </td>
              <td>{item.facility_label}</td>
              <td>
                <StatusPill route={item.route} />
              </td>
              <td>
                <strong>{Math.round(item.readiness_score)}%</strong>
              </td>
              <td>{item.primary_wound_summary?.wound_type ?? "—"}</td>
              <td>{item.primary_wound_summary?.location ?? "—"}</td>
              <td>{formatMeasurement(item)}</td>
              <td>
                <span className={item.active_part_b ? "chip" : "chip chip-muted"}>{item.active_part_b ? "Active" : "Inactive"}</span>
              </td>
              <td>
                {item.missing_fields.length ? (
                  <div className="chip-list">
                    {item.missing_fields.map((field) => (
                      <span className="chip chip-muted" key={`${item.patient_external_id}-${field}`}>
                        {field}
                      </span>
                    ))}
                  </div>
                ) : (
                  "—"
                )}
              </td>
              <td>{item.conflict_count ? <span className="chip chip-outline">{item.conflict_count}</span> : "—"}</td>
              <td className="table-row-strong">{item.recommended_next_action}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SortableHeader({
  label,
  href,
  active,
  sortOrder,
}: {
  label: string;
  href: string;
  active: boolean;
  sortOrder: "asc" | "desc";
}) {
  return (
    <th>
      <Link className={active ? "strong-link" : ""} href={href}>
        {label}
        {active ? <span className="compact-note"> {sortOrder === "asc" ? "↑" : "↓"}</span> : null}
      </Link>
    </th>
  );
}

function formatMeasurement(item: PatientListItem) {
  const wound = item.primary_wound_summary;
  if (!wound) {
    return "—";
  }
  const values = [wound.length_cm, wound.width_cm, wound.depth_cm].filter((value): value is number => value !== null);
  return values.length ? `${values.map((value) => Number(value).toFixed(1)).join(" × ")} cm` : "—";
}
