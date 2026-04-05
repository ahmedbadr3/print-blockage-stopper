import { useState, useEffect } from "react";
import { X, Trash2, Save } from "lucide-react";
import { Printer } from "../../types/printer";
import { useUpdatePrinter, useRemovePrinter } from "../../hooks/usePrinters";
import { cn } from "../../lib/utils";

const SCHEDULE_PRESETS = [
  { label: "Daily", value: "0 3 * * *" },
  { label: "Every 2 days", value: "0 3 */2 * *" },
  { label: "Every 3 days", value: "0 3 */3 * *" },
  { label: "Weekly", value: "0 3 * * 1" },
];

interface Props {
  printer: Printer | null;
  onClose: () => void;
}

export default function EditPrinterDialog({ printer, onClose }: Props) {
  const updatePrinter = useUpdatePrinter();
  const removePrinter = useRemovePrinter();
  const [form, setForm] = useState(printer);
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => {
    setForm(printer);
    setConfirmDelete(false);
  }, [printer]);

  if (!printer || !form) return null;

  const handleSave = () => {
    updatePrinter.mutate(form);
    onClose();
  };

  const handleDelete = () => {
    if (!confirmDelete) {
      setConfirmDelete(true);
      return;
    }
    removePrinter.mutate(printer.id);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-background/80 backdrop-blur-sm">
      <div className="w-full max-w-lg rounded-lg border border-border bg-card p-6 shadow-2xl">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-card-foreground">Edit Printer</h2>
          <button onClick={onClose} className="rounded-md p-1 text-muted-foreground hover:text-foreground">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div className="col-span-2">
              <label className="mb-1 block text-xs font-medium text-muted-foreground">Name</label>
              <input
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">IP Address</label>
              <input
                value={form.ip}
                onChange={(e) => setForm({ ...form, ip: e.target.value })}
                className="w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
              />
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
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">Skip Hours</label>
              <input
                type="number"
                value={form.skip_hours}
                onChange={(e) => setForm({ ...form, skip_hours: Number(e.target.value) })}
                className="w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-sm text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
              />
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
            <input
              value={form.schedule}
              onChange={(e) => setForm({ ...form, schedule: e.target.value })}
              className="mt-2 w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
              placeholder="Custom cron expression"
            />
          </div>

          {/* Actions */}
          <div className="flex items-center justify-between border-t border-border pt-4">
            <button
              onClick={handleDelete}
              className={cn(
                "flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                confirmDelete
                  ? "bg-destructive text-destructive-foreground"
                  : "text-destructive hover:bg-destructive/10"
              )}
            >
              <Trash2 className="h-4 w-4" />
              {confirmDelete ? "Confirm Delete" : "Delete"}
            </button>
            <div className="flex gap-3">
              <button onClick={onClose} className="rounded-md px-4 py-2 text-sm text-muted-foreground hover:text-foreground">
                Cancel
              </button>
              <button
                onClick={handleSave}
                className="flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
              >
                <Save className="h-4 w-4" />
                Save
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
