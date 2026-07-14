export const dynamic = "force-dynamic";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export async function GET() {
  const response = await fetch(new URL("/api/export/patients.csv", API_BASE_URL), {
    cache: "no-store",
  });

  if (!response.ok) {
    const text = await response.text();
    return new Response(text || "Export unavailable", { status: response.status });
  }

  const csv = await response.text();
  return new Response(csv, {
    headers: {
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition": 'attachment; filename="claimready-patients.csv"',
    },
  });
}
