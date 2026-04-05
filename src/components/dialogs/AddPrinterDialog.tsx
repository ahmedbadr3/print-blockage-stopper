import { useState } from "react";
import { X, Search, Loader2, Plus, Wifi } from "lucide-react";
import { useAddPrinter, useApi } from "../../hooks/usePrinters";
import { cn } from "../../lib/utils";

interface Props {
  open: boolean;
  onClose: () => void;
}

const SCHEDULE_PRESETS = [
  { label: "Daily", value: "0 3 * * *" },
  { label: "Every 2 days", value: "0 3 */2 * *" },
  { label: "Every 3 days", value: "0 3 */3 * *" },
  { label: "Weekly", value: "0 3 * * 1" },
];

export default function AddPrinterDialog({ open, onClose }: Props) {
  const addPrinter = useAddPrinter();
  const api = useApi();
  const [form, setForm] = useState({
    name: "",
    ip: "",
    connection: "ipp" as "ipp" | "socket",
    port: 631,
    paper_size: "A4",
    schedule: "0 3 */2 * *",
    skip_hours: 12,
    test_image: "nozzle-check",
  });
  const [discovering, setDiscovering] = useState(false);
  const [discovered, setDiscovered] = useState<Array<{ ip: string; model?: string }>>([]);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<string | null>(null);

  if (!open) return null;

  const handleDiscover = async () => {
    setDiscovering(true);
    try {
      const results = await api.discover();
      setDiscovered(results);
    } catch {
      setDiscovered([]);
    }
    setDiscovering(false);
  };

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await api.testConnection(form.ip, form.connection, form.port) as { reachable: boolean; model?: string; error?: string };
      setTestResult(result.reachable ? `✓ Connected — ${result.model || "Unknown model"}` : `✗ ${result.error}`);
    } catch {
      setTestResult("✗ Connection failed");
    }
    setTesting(false);
  };

  const handleSubmit = () => {
    addPrinter.mutate(form);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm">
      <div className="w-full max-w-lg rounded-lg border border-border bg-card p-6 shadow-2xl">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-card-foreground">Add Printer</h2>
          <button onClick={onClose} className="rounded-md p-1 text-muted-foreground hover:text-foreground">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="space-y-4">
          {/* Discovery */}
          <div>
            <button
              onClick={handleDiscover}
              disabled={discovering}
              className="flex w-full items-center justify-center gap-2 rounded-md border border-dashed border-border py-2.5 text-sm text-muted-foreground transition-colors hover:border-primary hover:text-primary"
            >
              {discovering ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
              {discovering ? "Scanning network..." : "Discover Printers"}
            </button>
            {discovered.length > 0 && (
              <div className="mt-2 space-y-1">
                {discovered.map((d) => (
                  <button
                    key={d.ip}
                    onClick={() => setForm({ ...form, ip: d.ip, name: d.model || `Printer ${d.ip}` })}
                    className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm hover:bg-accent"
                  >
                    <Wifi className="h-3.5 w-3.5 text-success" />
                    <span className="font-mono">{d.ip}</span>
                    {d.model && <span className="text-muted-foreground">— {d.model}</span>}
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="col-span-2">
              <label className="mb-1 block text-xs font-medium text-muted-foreground">Name</label>
              <input
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                placeholder="My Printer"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">IP Address</label>
              <input
                value={form.ip}
                onChange={(e) => setForm({ ...form, ip: e.target.value })}
                className="w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                placeholder="192.168.1.50"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">Connection</label>
              <div className="flex gap-2">
                {(["ipp", "socket"] as const).map((type) => (
                  <button
                    key={type}
                    onClick={() => setForm({ ...form, connection: type, port: type === "ipp" ? 631 : 9100 })}
                    className={cn(
                      "flex-1 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                      form.connection === type
                        ? "bg-primary/10 text-primary"
                        : "bg-muted text-muted-foreground hover:text-foreground"
                    )}
                  >
                    {type.toUpperCase()}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">Port</label>
              <input
                type="number"
                value={form.port}
                onChange={(e) => setForm({ ...form, port: Number(e.target.value) })}
                className="w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">Paper Size</label>
              <select
                value={form.paper_size}
                onChange={(e) => setForm({ ...form, paper_size: e.target.value })}
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
              >
                {["A4", "A3", "A3+", "Letter", "Legal", "4x6"].map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Schedule */}
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">Schedule</label>
            <div className="flex flex-wrap gap-2">
              {SCHEDULE_PRESETS.map((p) => (
                <button
                  key={p.value}
                  onClick={() => setForm({ ...form, schedule: p.value })}
                  className={cn(
                    "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                    form.schedule === p.value
                      ? "bg-primary/10 text-primary"
                      : "bg-muted text-muted-foreground hover:text-foreground"
                  )}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          {/* Test connection */}
          <button
            onClick={handleTest}
            disabled={!form.ip || testing}
            className="flex items-center gap-2 text-sm text-primary hover:underline disabled:opacity-50"
          >
            {testing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Wifi className="h-3.5 w-3.5" />}
            Test Connection
          </button>
          {testResult && (
            <p className={cn("text-xs font-mono", testResult.startsWith("✓") ? "text-success" : "text-destructive")}>
              {testResult}
            </p>
          )}

          {/* Submit */}
          <div className="flex justify-end gap-3 pt-2">
            <button onClick={onClose} className="rounded-md px-4 py-2 text-sm text-muted-foreground hover:text-foreground">
              Cancel
            </button>
            <button
              onClick={handleSubmit}
              disabled={!form.name || !form.ip}
              className="flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              <Plus className="h-4 w-4" />
              Add Printer
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
