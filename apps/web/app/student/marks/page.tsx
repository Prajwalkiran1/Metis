"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Legend,
  Line,
  LineChart,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { api, ApiError } from "@/lib/api";
import {
  Badge,
  Button,
  Card,
  ErrorText,
  Loading,
  Table,
  Td,
  Th,
} from "@/components/ui";

type AssessmentType = "cie1" | "cie2" | "cie3" | "see" | "assignment" | "lab";

type AssessmentSummary = {
  id: string;
  course_offering_id: string;
  course_code: string;
  course_title: string;
  type: AssessmentType;
  name: string;
  max_marks: string;
  weight_percent: string | null;
  scheduled_date: string | null;
  state: "draft" | "open" | "locked";
};

type MarkOut = {
  id: string;
  marks_obtained: string | null;
  is_absent: boolean;
  state: "entered" | "locked";
};

type StudentMarkItem = {
  assessment: AssessmentSummary;
  mark: MarkOut | null;
  class_mean: number | null;
  class_stddev: number | null;
};

type StudentMarksHistory = {
  student_user_id: string;
  items: StudentMarkItem[];
};

type GradeRule = {
  assessment_type: AssessmentType;
  weight_percent: string;
  passing_threshold_percent: string;
};

type GradeRuleSet = {
  course_offering_id: string;
  rules: GradeRule[];
};

function pct(item: StudentMarkItem): number | null {
  if (!item.mark || item.mark.is_absent || item.mark.marks_obtained === null) {
    return null;
  }
  const n = Number(item.mark.marks_obtained);
  const max = Number(item.assessment.max_marks);
  if (!Number.isFinite(n) || !Number.isFinite(max) || max === 0) return null;
  return (n / max) * 100;
}

export default function StudentMarksPage() {
  const [history, setHistory] = useState<StudentMarksHistory | null>(null);
  const [rulesByOffering, setRulesByOffering] = useState<Record<string, GradeRuleSet>>({});
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const me = await api<{ id: string }>("/users/me");
        const h = await api<StudentMarksHistory>(`/marks/${me.id}/history`);
        setHistory(h);

        // Pull grade rules for each unique offering so we can project grades.
        const offeringIds = Array.from(
          new Set(h.items.map((it) => it.assessment.course_offering_id)),
        );
        const fetched = await Promise.all(
          offeringIds.map((oid) =>
            api<GradeRuleSet>("/grade-rules", { query: { course_offering_id: oid } }).catch(
              () => null,
            ),
          ),
        );
        const map: Record<string, GradeRuleSet> = {};
        for (const r of fetched) if (r) map[r.course_offering_id] = r;
        setRulesByOffering(map);
      } catch (e) {
        setErr(e instanceof ApiError ? e.message : "failed to load marks");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  // Group items by course offering for the radar chart + per-subject projection.
  const bySubject = useMemo(() => {
    const m: Record<
      string,
      { code: string; title: string; items: StudentMarkItem[] }
    > = {};
    for (const it of history?.items ?? []) {
      const k = it.assessment.course_offering_id;
      if (!m[k]) {
        m[k] = { code: it.assessment.course_code, title: it.assessment.course_title, items: [] };
      }
      m[k].items.push(it);
    }
    return m;
  }, [history]);

  // Radar chart data: one axis per subject; value = avg marks %.
  const radarData = useMemo(() => {
    return Object.entries(bySubject).map(([_oid, v]) => {
      const ps = v.items.map(pct).filter((x): x is number => x !== null);
      const avg = ps.length ? ps.reduce((a, b) => a + b, 0) / ps.length : 0;
      return { subject: v.code, percent: Math.round(avg * 100) / 100 };
    });
  }, [bySubject]);

  // Trend line data: chronological list per subject.
  const trendData = useMemo(() => {
    if (!history) return [] as { date: string; [subject: string]: number | string }[];
    const allDates = Array.from(
      new Set(
        history.items
          .filter((it) => it.assessment.scheduled_date)
          .map((it) => it.assessment.scheduled_date as string),
      ),
    ).sort();
    return allDates.map((d) => {
      const row: { date: string; [s: string]: number | string } = { date: d };
      for (const [_oid, v] of Object.entries(bySubject)) {
        const onDate = v.items.find((it) => it.assessment.scheduled_date === d);
        if (onDate) {
          const p = pct(onDate);
          if (p !== null) row[v.code] = Math.round(p * 100) / 100;
        }
      }
      return row;
    });
  }, [bySubject, history]);

  // Per-subject grade projection: required SEE % to hit a 50 / 70 / 90 cutoff.
  const projection = useMemo(() => {
    const out: { subject: string; current_total: number; need_see_for_pass: number | null; need_see_for_distinction: number | null }[] = [];
    for (const [oid, v] of Object.entries(bySubject)) {
      const rs = rulesByOffering[oid]?.rules ?? [];
      let earned = 0;
      let entered_weight = 0;
      let see_weight = 0;
      for (const it of v.items) {
        const rule = rs.find((r) => r.assessment_type === it.assessment.type);
        const w = rule ? Number(rule.weight_percent) : 0;
        if (it.assessment.type === "see") {
          see_weight = w;
          continue;
        }
        const p = pct(it);
        if (p !== null && w > 0) {
          earned += (p / 100) * w;
          entered_weight += w;
        }
      }
      const need_see_pass = see_weight > 0
        ? Math.max(0, Math.min(100, ((40 - earned) / see_weight) * 100))
        : null;
      const need_see_dist = see_weight > 0
        ? Math.max(0, Math.min(100, ((75 - earned) / see_weight) * 100))
        : null;
      out.push({
        subject: v.code,
        current_total: Math.round(earned * 100) / 100,
        need_see_for_pass: need_see_pass !== null ? Math.round(need_see_pass) : null,
        need_see_for_distinction: need_see_dist !== null ? Math.round(need_see_dist) : null,
      });
    }
    return out;
  }, [bySubject, rulesByOffering]);

  // Rank approximation: percentile based on (self - mean) / stddev across assessments where stddev exists.
  const rankSummary = useMemo(() => {
    if (!history) return null;
    let count = 0;
    let above = 0;
    for (const it of history.items) {
      if (it.class_mean === null || !it.mark || it.mark.is_absent || it.mark.marks_obtained === null) {
        continue;
      }
      const me = Number(it.mark.marks_obtained);
      if (me >= it.class_mean) above += 1;
      count += 1;
    }
    if (!count) return null;
    return { percentile: Math.round((above / count) * 100), comparisons: count };
  }, [history]);

  const downloadPdf = async () => {
    // Lazy-load to keep initial bundle smaller.
    const [{ jsPDF }, autoTableMod] = await Promise.all([
      import("jspdf"),
      import("jspdf-autotable"),
    ]);
    const autoTable = (autoTableMod as { default: typeof autoTableMod.default }).default;
    if (!history) return;
    const doc = new jsPDF();
    doc.setFontSize(14);
    doc.text("Metis — Marks Report", 14, 18);
    doc.setFontSize(10);
    doc.text(new Date().toLocaleString(), 14, 26);
    const body = history.items.map((it) => [
      it.assessment.course_code,
      it.assessment.type.toUpperCase(),
      it.assessment.name,
      it.assessment.scheduled_date ?? "",
      it.mark?.is_absent
        ? "absent"
        : it.mark?.marks_obtained
          ? `${it.mark.marks_obtained} / ${it.assessment.max_marks}`
          : "—",
      it.class_mean !== null ? it.class_mean.toFixed(2) : "—",
    ]);
    autoTable(doc, {
      startY: 32,
      head: [["Course", "Type", "Name", "Date", "Marks", "Class avg"]],
      body,
      styles: { fontSize: 9 },
    });
    doc.save(`marks-${new Date().toISOString().slice(0, 10)}.pdf`);
  };

  if (loading) return <Loading />;
  if (err) return <ErrorText>{err}</ErrorText>;
  if (!history) return <p>No marks yet.</p>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-zinc-900">My marks</h1>
        <Button type="button" variant="secondary" onClick={downloadPdf}>
          Download PDF
        </Button>
      </div>

      {rankSummary ? (
        <p className="text-sm text-zinc-700">
          You scored at or above the class average on{" "}
          <span className="font-medium">{rankSummary.percentile}%</span> of the{" "}
          {rankSummary.comparisons} assessment(s) with class statistics available.
        </p>
      ) : null}

      <Card className="overflow-hidden">
        <Table>
          <thead>
            <tr>
              <Th>Course</Th>
              <Th>Type</Th>
              <Th>Name</Th>
              <Th>Date</Th>
              <Th>Marks</Th>
              <Th>Class avg</Th>
              <Th>State</Th>
            </tr>
          </thead>
          <tbody>
            {history.items.map((it) => (
              <tr key={it.assessment.id}>
                <Td className="text-xs">{it.assessment.course_code}</Td>
                <Td>{it.assessment.type.toUpperCase()}</Td>
                <Td>{it.assessment.name}</Td>
                <Td className="text-xs">{it.assessment.scheduled_date ?? "—"}</Td>
                <Td>
                  {it.mark === null ? (
                    <span className="text-xs text-zinc-400">not entered</span>
                  ) : it.mark.is_absent ? (
                    <Badge tone="amber">absent</Badge>
                  ) : (
                    <span>
                      {it.mark.marks_obtained} <span className="text-xs text-zinc-500">/ {it.assessment.max_marks}</span>
                    </span>
                  )}
                </Td>
                <Td>
                  {it.class_mean !== null
                    ? <span className="text-xs">{it.class_mean.toFixed(2)}</span>
                    : "—"}
                </Td>
                <Td>
                  {it.assessment.state === "locked" ? (
                    <Badge tone="red">locked</Badge>
                  ) : (
                    <Badge tone="green">{it.assessment.state}</Badge>
                  )}
                </Td>
              </tr>
            ))}
            {history.items.length === 0 ? (
              <tr>
                <Td colSpan={7} className="text-center text-sm text-zinc-500">
                  No assessments yet.
                </Td>
              </tr>
            ) : null}
          </tbody>
        </Table>
      </Card>

      {radarData.length > 1 ? (
        <Card className="p-4">
          <h2 className="mb-2 text-sm font-medium text-zinc-900">Subject radar</h2>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <RadarChart data={radarData}>
                <PolarGrid />
                <PolarAngleAxis dataKey="subject" />
                <PolarRadiusAxis domain={[0, 100]} />
                <Radar
                  dataKey="percent"
                  name="Average %"
                  stroke="#18181b"
                  fill="#18181b"
                  fillOpacity={0.2}
                />
                <Tooltip />
              </RadarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      ) : null}

      {trendData.length > 0 ? (
        <Card className="p-4">
          <h2 className="mb-2 text-sm font-medium text-zinc-900">Trend by subject</h2>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={trendData}>
                <XAxis dataKey="date" />
                <YAxis domain={[0, 100]} />
                <Tooltip />
                <Legend />
                {Object.values(bySubject).map((v, i) => (
                  <Line
                    key={v.code}
                    type="monotone"
                    dataKey={v.code}
                    stroke={["#18181b", "#3b82f6", "#16a34a", "#dc2626", "#a855f7", "#f59e0b"][i % 6]}
                    connectNulls
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>
      ) : null}

      {projection.length > 0 ? (
        <Card className="p-4">
          <h2 className="mb-2 text-sm font-medium text-zinc-900">Grade projection</h2>
          <p className="mb-2 text-xs text-zinc-500">
            Based on current weighted total per subject and the offering's grade rules. SEE weight required for pass (≥40) and distinction (≥75).
          </p>
          <Table>
            <thead>
              <tr>
                <Th>Subject</Th>
                <Th>Current</Th>
                <Th>Need in SEE for pass</Th>
                <Th>Need in SEE for distinction</Th>
              </tr>
            </thead>
            <tbody>
              {projection.map((p) => (
                <tr key={p.subject}>
                  <Td>{p.subject}</Td>
                  <Td>{p.current_total} / 100</Td>
                  <Td>
                    {p.need_see_for_pass !== null
                      ? `${p.need_see_for_pass}%`
                      : "—"}
                  </Td>
                  <Td>
                    {p.need_see_for_distinction !== null
                      ? `${p.need_see_for_distinction}%`
                      : "—"}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      ) : null}
    </div>
  );
}
