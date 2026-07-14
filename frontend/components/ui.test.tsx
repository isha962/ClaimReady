import { render, screen } from "@testing-library/react";

import { ConflictPill, MetricCard, StatusPill } from "@/components/ui";
import { QueueTable } from "@/components/queue-table";

describe("ui components", () => {
  it("renders status pills with consistent labels", () => {
    render(<StatusPill route="flag_for_review" />);
    expect(screen.getByText("Review")).toBeInTheDocument();
  });

  it("renders metric cards", () => {
    render(<MetricCard label="Auto accept" value={3} note="Latest run" />);
    expect(screen.getByText("Auto accept")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
  });

  it("renders queue rows", () => {
    render(
      <QueueTable
        items={[
          {
            patient_internal_id: 1,
            patient_external_id: "FA-001",
            patient_name: "Agnes Dunbar",
            facility_id: 101,
            facility_label: "Facility 101",
            route: "auto_accept",
            readiness_score: 92.4,
            active_part_b: true,
            primary_wound_summary: {
              wound_key: "patient:1:wound:1",
              wound_type: "pressure_ulcer",
              pressure_ulcer_stage: "3",
              location: "Sacrum",
              length_cm: 3.4,
              width_cm: 2.1,
              depth_cm: 0.5,
              drainage_amount: "moderate",
              documentation_state: "active",
              is_primary_wound: true,
            },
            missing_fields: [],
            conflicting_fields: [],
            recommended_next_action: "Proceed to auto-accept.",
            conflict_count: 0,
          },
        ]}
        sortBy="readiness_score"
        sortOrder="desc"
        buildSortHref={(sortBy) => `/queue?sort_by=${sortBy}`}
      />
    );
    expect(screen.getByText("Agnes Dunbar")).toBeInTheDocument();
    expect(screen.getByText("Auto accept")).toBeInTheDocument();
    expect(screen.getByText("92%")).toBeInTheDocument();
    expect(screen.getByText("Proceed to auto-accept.")).toBeInTheDocument();
  });

  it("renders conflict pills", () => {
    render(<ConflictPill state="unresolved_material" />);
    expect(screen.getByText("Unresolved")).toBeInTheDocument();
  });
});
