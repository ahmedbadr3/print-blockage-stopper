import { useState, useRef, useEffect } from "react";
import { useHistory, useLogs } from "../hooks/usePrinters";
import { formatDate } from "../lib/utils";
import { CheckCircle, XCircle, Download, Terminal, BarChart3 } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { cn } from "../lib/utils";

export default function History() {
  const { data: history } = useHistory();
  const { data: logs } = useLogs();
  const [tab, setTab] = useState<"history" | "logs">("history");
  const [filter, setFilter] = useState<"all" | "success" | "error">("all");
  const logsEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (tab === "logs") logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs, tab]);

  // Chart data: group by day
  const chartData = (() => {
    if (!history) return [];
    const days: Record<string, { date: string; success: number; error: number }> = {};
    history.forEach((h) => {
      const day = new Date(h.timestamp).toLocaleDateString("en-US", { month: "short", day: "numeric" });
      if (!days[day]) days[day] = { date: day, success: 0, error: 0 };
      days[day][h.result]++;
    });
    return Object.values(days).reverse().slice(-14);
  })();

  const filteredHistory = history?.filter((h) => filter === "all" || h.result === filter) || [];

  const handleExport = () => {
    if (!history) return;
    const csv = ["Printer,Date,Result,Message", ...history.map((h) =>
      `"${h.printer_name}","${h.timestamp}","${h.result}","${h.message || ""}"`
    )].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "print-history.csv";
    a.click();
  };

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold text-foreground">History & Logs</h1>
        <div className="flex gap-2">
          <button
            onClick={() => setTab("history")}
            className={cn(
              "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
              tab === "history" ? "bg-primary/10 text-primary" : "text-muted-foreground hover:text-foreground"
            )}
          >
            <BarChart3 className="h-4 w-4" />
            History
          </button>
          <button
            onClick={() => setTab("logs")}
            className={cn(
              "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
              tab === "logs" ? "bg-primary/10 text-primary" : "text-muted-foreground hover:text-foreground"
            )}
          >
            <Terminal className="h-4 w-4" />
            Logs
          </button>
        </div>
      </div>

      {tab === "history" ? (
        <div className="space-y-6">
          {/* Chart */}
          <div className="rounded-lg border border-border bg-card p-4">
            <h3 className="mb-3 text-sm font-medium text-card-foreground">Print Activity (Last 14 Days)</h3>
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                <XAxis dataKey="date" tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} />
                <YAxis tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "hsl(var(--card))",
                    border: "1px solid hsl(var(--border))",
                    borderRadius: "6px",
                    fontSize: "12px",
                  }}
                />
                <Bar dataKey="success" fill="hsl(var(--success))" radius={[2, 2, 0, 0]} />
                <Bar dataKey="error" fill="hsl(var(--destructive))" radius={[2, 2, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* Filters + Export */}
          <div className="flex items-center justify-between">
            <div className="flex gap-2">
              {(["all", "success", "error"] as const).map((f) => (
                <button
                  key={f}
                  onClick={() => setFilter(f)}
                  className={cn(
                    "rounded-md px-3 py-1.5 text-xs font-medium capitalize transition-colors",
                    filter === f ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground hover:text-foreground"
                  )}
                >
                  {f}
                </button>
              ))}
            </div>
            <button onClick={handleExport} className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground">
              <Download className="h-3.5 w-3.5" />
              Export CSV
            </button>
          </div>

          {/* Table */}
          <div className="overflow-hidden rounded-lg border border-border">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-muted/50">
                  <th className="px-4 py-2.5 text-left font-medium text-muted-foreground">Printer</th>
                  <th className="px-4 py-2.5 text-left font-medium text-muted-foreground">Date</th>
                  <th className="px-4 py-2.5 text-left font-medium text-muted-foreground">Result</th>
                  <th className="px-4 py-2.5 text-left font-medium text-muted-foreground">Message</th>
                </tr>
              </thead>
              <tbody>
                {filteredHistory.map((h) => (
                  <tr key={h.id} className="border-b border-border last:border-0">
                    <td className="px-4 py-2.5 text-foreground">{h.printer_name}</td>
                    <td className="px-4 py-2.5 font-mono text-xs text-muted-foreground">{formatDate(h.timestamp)}</td>
                    <td className="px-4 py-2.5">
                      {h.result === "success" ? (
                        <span className="flex items-center gap-1 text-success"><CheckCircle className="h-3.5 w-3.5" /> Success</span>
                      ) : (
                        <span className="flex items-center gap-1 text-destructive"><XCircle className="h-3.5 w-3.5" /> Error</span>
                      )}
                    </td>
                    <td className="px-4 py-2.5 text-muted-foreground">{h.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        /* Log viewer */
        <div className="rounded-lg border border-border bg-card overflow-hidden">
          <div className="flex items-center gap-2 border-b border-border bg-muted/30 px-4 py-2">
            <Terminal className="h-4 w-4 text-primary" />
            <span className="font-mono text-xs text-muted-foreground">system.log</span>
          </div>
          <div className="max-h-[60vh] overflow-y-auto p-4 font-mono text-xs leading-relaxed">
            {logs?.map((line, i) => (
              <div
                key={i}
                className={cn(
                  "py-0.5",
                  line.includes("ERROR") && "text-destructive",
                  line.includes("WARN") && "text-warning",
                  line.includes("OK") && "text-success",
                  !line.includes("ERROR") && !line.includes("WARN") && !line.includes("OK") && "text-muted-foreground"
                )}
              >
                {line}
              </div>
            ))}
            <div ref={logsEndRef} />
          </div>
        </div>
      )}
    </div>
  );
}
