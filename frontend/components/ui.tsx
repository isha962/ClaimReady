"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import type { Route, SelectedFieldEvidenceItem } from "@/lib/types";

const NAV_ITEMS = [
  { href: "/", label: "Command Center" },
  { href: "/queue", label: "Work Queue" },
  { href: "/facilities", label: "Facilities" },
  { href: "/pipeline-health", label: "Pipeline Health" },
] as const;

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand-block">
          <Link className="brand-mark" href="/">
            ClaimReady
          </Link>
          <p className="brand-subtitle">Billing operations</p>
        </div>
        <nav className="app-nav" aria-label="Primary">
          {NAV_ITEMS.map((item) => {
            const active = item.href === "/" ? pathname === "/" : pathname?.startsWith(item.href);
            return (
              <Link key={item.href} className={active ? "app-nav-link active" : "app-nav-link"} href={item.href} aria-current={active ? "page" : undefined}>
                {item.label}
              </Link>
            );
          })}
        </nav>
      </header>
      <main className="main-content">{children}</main>
    </div>
  );
}

export function PageHeader({
  title,
  description,
  actions,
  eyebrow,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
  eyebrow?: string;
}) {
  return (
    <header className="page-header">
      <div className="page-header-copy">
        {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
        <h2>{title}</h2>
        {description ? <p className="page-description">{description}</p> : null}
      </div>
      {actions ? <div className="page-actions">{actions}</div> : null}
    </header>
  );
}

export function SectionCard({
  title,
  description,
  actions,
  children,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="section-card">
      <div className="section-header">
        <div>
          <h3>{title}</h3>
          {description ? <p>{description}</p> : null}
        </div>
        {actions ? <div className="section-actions">{actions}</div> : null}
      </div>
      {children}
    </section>
  );
}

export function MetricCard({
  label,
  value,
  note,
}: {
  label: string;
  value: string | number;
  note?: string;
}) {
  return (
    <div className="metric-card">
      <span>{label}</span>
      <strong>{value}</strong>
      {note ? <em>{note}</em> : null}
    </div>
  );
}

export function StatusPill({ route }: { route: Route }) {
  const labelMap = {
    auto_accept: "Auto accept",
    flag_for_review: "Review",
    reject: "Reject",
  } as const;
  return <span className={`status-badge route-${route}`}>{labelMap[route]}</span>;
}

export function ConflictPill({ state }: { state: string }) {
  const className =
    state === "unresolved_material" ? "status-badge conflict conflict-unresolved" : state === "resolved" ? "status-badge conflict conflict-resolved" : "status-badge conflict conflict-historical";
  const labelMap: Record<string, string> = {
    unresolved_material: "Unresolved",
    resolved: "Resolved",
    historical: "Historical",
  };
  return <span className={className}>{labelMap[state] ?? state.replace(/_/g, " ")}</span>;
}

export function EvidenceTable({ items }: { items: SelectedFieldEvidenceItem[] }) {
  if (!items.length) {
    return <EmptyState title="No selected evidence" message="Evidence will appear here after reconciliation." />;
  }

  return (
    <div className="table-wrap">
      <table className="table table-compact evidence-table">
        <thead>
          <tr>
            <th>Field</th>
            <th>Selected value</th>
            <th>Source</th>
            <th>Date</th>
            <th>Confidence</th>
            <th>State</th>
            <th>Evidence</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={`${item.candidate_key}-${item.field_name}-${item.synced_at ?? "no-sync-time"}`}>
              <td>
                <div className="table-cell-stack">
                  <strong>{item.field_name}</strong>
                  <span className="muted">{item.value_type}</span>
                </div>
              </td>
              <td>{item.selected_value ?? "—"}</td>
              <td>
                <div className="table-cell-stack">
                  <span>{item.source_type}</span>
                  <span className="muted">{item.source_record_id}</span>
                </div>
              </td>
              <td>{formatDateTime(item.source_date)}</td>
              <td>{item.confidence.toFixed(2)}</td>
              <td>
                <ConflictPill state={item.conflict_status} />
              </td>
              <td>
                <details className="inline-details">
                  <summary>View source</summary>
                  <div className="inline-details-body">
                    <p className="fineprint">Source excerpt</p>
                    <pre className="raw-json raw-json--inline">{item.source_excerpt ?? "—"}</pre>
                    <p className="fineprint">Alternative values</p>
                    <pre className="raw-json raw-json--inline">{JSON.stringify(item.alternative_values_json, null, 2)}</pre>
                  </div>
                </details>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function AuditPanel({
  title,
  children,
  defaultOpen = false,
}: {
  title: string;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  return (
    <details className="audit-panel" open={defaultOpen}>
      <summary>{title}</summary>
      <div className="audit-panel-body">{children}</div>
    </details>
  );
}

export function LoadingState({ title }: { title: string }) {
  return (
    <div className="state-surface state-loading">
      <h3>{title}</h3>
      <p>Loading current view.</p>
    </div>
  );
}

export function ErrorState({ title, message }: { title: string; message: string }) {
  return (
    <div className="state-surface state-error">
      <h3>{title}</h3>
      <p>{message}</p>
    </div>
  );
}

export function EmptyState({ title, message }: { title: string; message: string }) {
  return (
    <div className="state-surface">
      <h3>{title}</h3>
      <p>{message}</p>
    </div>
  );
}

function formatDateTime(value: string | null | undefined) {
  if (!value) {
    return "—";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parsed);
}
