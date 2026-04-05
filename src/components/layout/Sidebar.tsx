import { NavLink, useLocation } from "react-router-dom";
import { Printer, History, Settings, LayoutDashboard, ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";
import { cn } from "../../lib/utils";

const navItems = [
  { to: "/", icon: LayoutDashboard, label: "Dashboard" },
  { to: "/history", icon: History, label: "History & Logs" },
  { to: "/settings", icon: Settings, label: "Settings" },
];

export default function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);
  const location = useLocation();

  return (
    <aside
      className={cn(
        "flex flex-col border-r border-border bg-card transition-all duration-300",
        collapsed ? "w-16" : "w-60"
      )}
    >
      {/* Logo */}
      <div className="flex h-14 items-center gap-3 border-b border-border px-4">
        <Printer className="h-6 w-6 shrink-0 text-primary" />
        {!collapsed && (
          <span className="font-mono text-sm font-bold tracking-tight text-foreground truncate">
            PBS Dashboard
          </span>
        )}
      </div>

      {/* Nav */}
      <nav className="flex-1 space-y-1 px-2 py-4">
        {navItems.map((item) => {
          const active = location.pathname === item.to;
          return (
            <NavLink
              key={item.to}
              to={item.to}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2.5 text-sm font-medium transition-colors",
                active
                  ? "bg-primary/10 text-primary glow-primary"
                  : "text-muted-foreground hover:bg-accent hover:text-foreground"
              )}
            >
              <item.icon className="h-4 w-4 shrink-0" />
              {!collapsed && <span>{item.label}</span>}
            </NavLink>
          );
        })}
      </nav>

      {/* Collapse toggle */}
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="flex h-10 items-center justify-center border-t border-border text-muted-foreground hover:text-foreground transition-colors"
      >
        {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
      </button>
    </aside>
  );
}
