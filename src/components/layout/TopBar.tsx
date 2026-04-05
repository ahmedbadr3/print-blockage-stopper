import { Sun, Moon, Radio, Wifi, WifiOff } from "lucide-react";
import { useTheme } from "../../contexts/ThemeContext";
import { useDemo } from "../../contexts/DemoContext";
import { usePrinters } from "../../hooks/usePrinters";

export default function TopBar() {
  const { theme, toggleTheme } = useTheme();
  const { isDemo } = useDemo();
  const { data: printers } = usePrinters();

  const total = printers?.length || 0;
  const active = printers?.filter((p) => !p.paused && p.status !== "error").length || 0;
  const errors = printers?.filter((p) => p.status === "error").length || 0;

  return (
    <header className="flex h-14 items-center justify-between border-b border-border bg-card px-4 md:px-6">
      <div className="flex items-center gap-4">
        {/* Status badges */}
        <div className="hidden items-center gap-3 sm:flex">
          <StatusBadge icon={<Radio className="h-3.5 w-3.5" />} label="Total" value={total} />
          <StatusBadge icon={<Wifi className="h-3.5 w-3.5" />} label="Active" value={active} variant="success" />
          {errors > 0 && (
            <StatusBadge icon={<WifiOff className="h-3.5 w-3.5" />} label="Errors" value={errors} variant="error" />
          )}
        </div>
      </div>

      <div className="flex items-center gap-3">
        {/* Demo indicator */}
        {isDemo && (
          <span className="rounded-full bg-warning/10 px-2.5 py-1 font-mono text-xs font-medium text-warning">
            DEMO
          </span>
        )}

        {/* Theme toggle */}
        <button
          onClick={toggleTheme}
          className="rounded-md p-2 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          aria-label="Toggle theme"
        >
          {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </button>
      </div>
    </header>
  );
}

function StatusBadge({
  icon,
  label,
  value,
  variant = "default",
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  variant?: "default" | "success" | "error";
}) {
  const colors = {
    default: "text-muted-foreground",
    success: "text-success",
    error: "text-destructive",
  };

  return (
    <div className={`flex items-center gap-1.5 text-xs font-medium ${colors[variant]}`}>
      {icon}
      <span className="hidden md:inline">{label}:</span>
      <span className="font-mono">{value}</span>
    </div>
  );
}
