import { Printer as PrinterType } from "../../types/printer";
import { Play, Pause, Zap, Settings, Clock, Wifi, WifiOff, AlertTriangle, Loader2 } from "lucide-react";
import { cn, formatCountdown, cronToHuman } from "../../lib/utils";
import InkLevelBar from "./InkLevelBar";
import { usePrintNow, useToggleSchedule } from "../../hooks/usePrinters";
import { useState, useEffect } from "react";

interface Props {
  printer: PrinterType;
  onEdit: (printer: PrinterType) => void;
}

export default function PrinterCard({ printer, onEdit }: Props) {
  const printNow = usePrintNow();
  const toggleSchedule = useToggleSchedule();
  const [countdown, setCountdown] = useState(
    printer.next_print ? formatCountdown(printer.next_print) : "—"
  );

  useEffect(() => {
    if (!printer.next_print || printer.paused) return;
    const interval = setInterval(() => {
      setCountdown(formatCountdown(printer.next_print!));
    }, 60000);
    return () => clearInterval(interval);
  }, [printer.next_print, printer.paused]);

  const statusConfig = {
    ok: { color: "text-success", glow: "glow-success", icon: Wifi, label: "Online" },
    error: { color: "text-destructive", glow: "glow-destructive", icon: AlertTriangle, label: "Error" },
    printing: { color: "text-primary", glow: "glow-primary", icon: Loader2, label: "Printing" },
    unknown: { color: "text-muted-foreground", glow: "", icon: WifiOff, label: "Unknown" },
  };

  const status = statusConfig[printer.status];
  const StatusIcon = status.icon;

  return (
    <div
      className={cn(
        "group relative rounded-lg border border-border bg-card p-4 transition-all hover:border-primary/30",
        printer.status === "printing" && "glow-primary",
        printer.status === "error" && "border-destructive/30"
      )}
    >
      {/* Header */}
      <div className="mb-3 flex items-start justify-between">
        <div className="min-w-0 flex-1">
          <h3 className="truncate font-medium text-card-foreground">{printer.name}</h3>
          <p className="font-mono text-xs text-muted-foreground">{printer.ip}:{printer.port}</p>
          {printer.model && (
            <p className="mt-0.5 truncate text-xs text-muted-foreground">{printer.model}</p>
          )}
        </div>
        <div className={cn("flex items-center gap-1.5 rounded-full px-2 py-1 text-xs font-medium", status.color)}>
          <StatusIcon className={cn("h-3 w-3", printer.status === "printing" && "animate-spin")} />
          <span>{status.label}</span>
        </div>
      </div>

      {/* Schedule info */}
      <div className="mb-3 flex items-center gap-4 text-xs text-muted-foreground">
        <div className="flex items-center gap-1">
          <Clock className="h-3 w-3" />
          <span>{cronToHuman(printer.schedule)}</span>
        </div>
        {printer.next_print && !printer.paused && (
          <div className="font-mono text-primary">Next: {countdown}</div>
        )}
        {printer.paused && (
          <span className="rounded bg-warning/10 px-1.5 py-0.5 font-medium text-warning">PAUSED</span>
        )}
      </div>

      {/* Ink levels */}
      {printer.ink_levels && printer.ink_levels.length > 0 && (
        <div className="mb-3">
          <InkLevelBar levels={printer.ink_levels} />
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center gap-2 border-t border-border pt-3">
        <button
          onClick={() => printNow.mutate(printer.id)}
          disabled={printNow.isPending || printer.status === "printing"}
          className="flex items-center gap-1.5 rounded-md bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary transition-colors hover:bg-primary/20 disabled:opacity-50"
        >
          <Zap className="h-3 w-3" />
          Print Now
        </button>
        <button
          onClick={() => toggleSchedule.mutate(printer.id)}
          className={cn(
            "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
            printer.paused
              ? "bg-success/10 text-success hover:bg-success/20"
              : "bg-warning/10 text-warning hover:bg-warning/20"
          )}
        >
          {printer.paused ? <Play className="h-3 w-3" /> : <Pause className="h-3 w-3" />}
          {printer.paused ? "Resume" : "Pause"}
        </button>
        <button
          onClick={() => onEdit(printer)}
          className="ml-auto rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
        >
          <Settings className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}
