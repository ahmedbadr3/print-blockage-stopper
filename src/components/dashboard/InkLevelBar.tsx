import { InkLevel } from "../../types/printer";
import { cn } from "../../lib/utils";

export default function InkLevelBar({ levels }: { levels: InkLevel[] }) {
  return (
    <div className="flex gap-1">
      {levels.map((ink, i) => (
        <div key={i} className="group/ink relative flex-1" title={`${ink.name}: ${ink.level}%`}>
          <div className="h-6 rounded-sm bg-muted overflow-hidden">
            <div
              className={cn(
                "h-full rounded-sm transition-all",
                ink.level <= 10 && "animate-pulse-glow"
              )}
              style={{
                height: `${Math.max(ink.level, 2)}%`,
                backgroundColor: ink.color || "hsl(var(--primary))",
                position: "absolute",
                bottom: 0,
                left: 0,
                right: 0,
              }}
            />
          </div>
          {/* Tooltip */}
          <div className="pointer-events-none absolute -top-8 left-1/2 -translate-x-1/2 rounded bg-popover px-1.5 py-0.5 text-[10px] font-mono text-popover-foreground opacity-0 shadow-lg transition-opacity group-hover/ink:opacity-100 whitespace-nowrap z-10">
            {ink.name}: {ink.level}%
          </div>
        </div>
      ))}
    </div>
  );
}
