import { getPatients } from "@/lib/api";
import { EmptyState, ErrorState, PageHeader, SectionCard } from "@/components/ui";
import { QueueTable } from "@/components/queue-table";

export const dynamic = "force-dynamic";

type SearchParams = Record<string, string | string[] | undefined>;

export default async function BillerQueuePage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const params = await searchParams;
  const filters = {
    facility_id: params.facility_id,
    route: params.route,
    wound_type: params.wound_type,
    missing_field: params.missing_field,
    conflict_status: params.conflict_status,
    minimum_readiness_score: params.minimum_readiness_score,
    search: params.search,
    page: params.page ?? "1",
    page_size: params.page_size ?? "25",
    sort_by: params.sort_by ?? "readiness_score",
    sort_order: params.sort_order ?? "desc",
  };

  const result = await getPatients(filters).catch((error: unknown) => ({ error }));

  if ("error" in result) {
    return <ErrorState title="Queue unavailable" message={String(result.error)} />;
  }

  const activeFilters = Object.entries(filters).filter(([, value]) => value && value !== "1" && value !== "25" && value !== "readiness_score" && value !== "desc");
  const sortBy =
    filters.sort_by === "patient_name" || filters.sort_by === "facility_id" || filters.sort_by === "route" || filters.sort_by === "readiness_score"
      ? filters.sort_by
      : "readiness_score";
  const sortOrder = String(filters.sort_order) === "asc" ? "asc" : "desc";
  const baseHref = (overrides: Record<string, string>) => {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(filters)) {
      if (value && key !== "sort_by" && key !== "sort_order" && key !== "page") {
        params.set(key, String(value));
      }
    }
    for (const [key, value] of Object.entries(overrides)) {
      if (value) {
        params.set(key, value);
      } else {
        params.delete(key);
      }
    }
    return `/queue?${params.toString()}`;
  };

  return (
    <div className="stack">
      <PageHeader
        eyebrow="Biller operations"
        title="Work Queue"
        description="Scan patients by route, missing documentation, and readiness. Open a patient to review the evidence trail."
        actions={
          <>
            <a className="button button-secondary" href="/queue">
              Clear filters
            </a>
            <a className="button button-primary" href="/api/export/patients.csv">
              Export CSV
            </a>
          </>
        }
      />

      <SectionCard
        title="Filters"
        description="Narrow the queue by facility, route, wound type, missing field, conflict status, or readiness."
        actions={<span className="fineprint">{activeFilters.length ? `${activeFilters.length} active filter${activeFilters.length === 1 ? "" : "s"}` : "No active filters"}</span>}
      >
        <form className="controls controls--dense" method="get">
          <input name="search" placeholder="Search patient ID or name" defaultValue={String(filters.search ?? "")} />
          <input name="facility_id" placeholder="Facility ID" defaultValue={String(filters.facility_id ?? "")} />
          <select name="route" defaultValue={String(filters.route ?? "")}>
            <option value="">All routes</option>
            <option value="auto_accept">Auto accept</option>
            <option value="flag_for_review">Review</option>
            <option value="reject">Reject</option>
          </select>
          <input name="wound_type" placeholder="Wound type" defaultValue={String(filters.wound_type ?? "")} />
          <input name="missing_field" placeholder="Missing field" defaultValue={String(filters.missing_field ?? "")} />
          <input name="conflict_status" placeholder="Conflict status" defaultValue={String(filters.conflict_status ?? "")} />
          <input name="minimum_readiness_score" placeholder="Minimum readiness" defaultValue={String(filters.minimum_readiness_score ?? "")} />
          <button type="submit">Apply filters</button>
        </form>
        <div className="chip-list chip-list--wrap">
          {activeFilters.length ? (
            activeFilters.map(([key, value]) => (
              <a className="chip chip-outline" key={key} href={baseHref({ [key]: "" })}>
                {key.replace(/_/g, " ")}: {value}
              </a>
            ))
          ) : (
            <span className="chip chip-muted">Queue shown in default order</span>
          )}
        </div>
      </SectionCard>

      {result.items.length ? (
        <SectionCard
          title={`Patients (${result.pagination.total})`}
          description="Current-state routing rows only. Sorted for rapid review."
          actions={
            <div className="table-toolbar">
              <a className="toolbar-link" href={baseHref({ sort_by: "patient_name", sort_order: "asc" })}>
                Patient
              </a>
              <a className="toolbar-link" href={baseHref({ sort_by: "facility_id", sort_order: "asc" })}>
                Facility
              </a>
              <a className="toolbar-link" href={baseHref({ sort_by: "route", sort_order: "asc" })}>
                Route
              </a>
              <a className="toolbar-link" href={baseHref({ sort_by: "readiness_score", sort_order: "desc" })}>
                Readiness
              </a>
            </div>
          }
        >
          <QueueTable
            items={result.items}
            sortBy={sortBy}
            sortOrder={sortOrder}
            buildSortHref={(sortBy) =>
              baseHref({
                sort_by: sortBy,
                sort_order: sortBy === filters.sort_by && sortOrder === "asc" ? "desc" : "asc",
              })
            }
          />
        </SectionCard>
      ) : (
        <EmptyState title="No matching patients" message="Try broadening the search or clearing filters." />
      )}

      <SectionCard title="Queue signal" description="This view is optimized for rapid scanning of documentation gaps and routing decisions.">
        <div className="status-strip">
          <div className="status-card">
            <span>Sort</span>
            <strong>{String(filters.sort_by ?? "readiness_score").replace(/_/g, " ")}</strong>
          </div>
          <div className="status-card">
            <span>Order</span>
            <strong>{String(filters.sort_order ?? "desc").toUpperCase()}</strong>
          </div>
          <div className="status-card">
            <span>Search</span>
            <strong>{filters.search ? String(filters.search) : "None"}</strong>
          </div>
          <div className="status-card">
            <span>Facility</span>
            <strong>{filters.facility_id ? String(filters.facility_id) : "All"}</strong>
          </div>
        </div>
      </SectionCard>
    </div>
  );
}
