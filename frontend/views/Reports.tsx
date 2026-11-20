"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Card,
  CardContent,
  CircularProgress,
  Typography,
} from "@mui/material";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { AgentStream } from "@/components/AgentStream";
import { apiFetch } from "@/lib/api";

type Completions = {
  total_completions: number;
  unique_learners: number;
  by_object: { object_id: string; completions: number }[];
};

export default function ReportsPage() {
  const {
    data: summary,
    error,
    isLoading,
  } = useQuery({
    queryKey: ["reports", "completions"],
    queryFn: () => apiFetch<Completions>("/v1/reports/completions"),
  });

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-semibold">Reports</h1>

      <section className="space-y-3">
        <h2 className="font-medium">Completion summary</h2>
        {error && <Alert severity="error">{error.message}</Alert>}
        {isLoading && <CircularProgress aria-label="Loading report" />}
        {summary && (
          <>
            <div className="flex gap-6 text-sm">
              <p>
                <span className="text-2xl font-semibold">
                  {summary.total_completions}
                </span>{" "}
                completions
              </p>
              <p>
                <span className="text-2xl font-semibold">
                  {summary.unique_learners}
                </span>{" "}
                learners
              </p>
            </div>
            <Card variant="outlined">
              <CardContent>
                <Typography component="h3" variant="h6">
                  Learning completions by object
                </Typography>
                <Typography variant="body2">
                  Based on persisted xAPI completion statements; downloads are
                  excluded.
                </Typography>
                {summary.by_object.length ? (
                  <div style={{ width: "100%", height: 300 }}>
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={summary.by_object} accessibilityLayer>
                        <CartesianGrid strokeDasharray="3 3" />
                        <XAxis dataKey="object_id" hide />
                        <YAxis allowDecimals={false} />
                        <Tooltip />
                        <Bar dataKey="completions" fill="#1762c4" />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                ) : (
                  <Typography sx={{ py: 3 }}>
                    No completion events yet.
                  </Typography>
                )}
              </CardContent>
            </Card>
            <table className="w-full text-left text-sm">
              <thead className="text-[var(--muted)]">
                <tr>
                  <th className="py-1">Learning object</th>
                  <th className="py-1 text-right">Completions</th>
                </tr>
              </thead>
              <tbody>
                {summary.by_object.map((row) => (
                  <tr
                    key={row.object_id}
                    className="border-t border-[var(--border)]"
                  >
                    <td className="py-1 break-all">{row.object_id}</td>
                    <td className="py-1 text-right">{row.completions}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="font-medium">Ask a question</h2>
        <p className="text-sm text-[var(--muted)]">
          Try: &quot;How many completions do we have?&quot; or &quot;Completions
          by object&quot;.
        </p>
        <AgentStream
          endpoint="/v1/agents/ask"
          buildBody={(question) => ({ question })}
          placeholder="Ask about completions"
        />
      </section>
    </div>
  );
}
