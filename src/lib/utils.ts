import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatCountdown(targetDate: string): string {
  const diff = new Date(targetDate).getTime() - Date.now();
  if (diff <= 0) return "Now";
  const days = Math.floor(diff / 86400000);
  const hours = Math.floor((diff % 86400000) / 3600000);
  const minutes = Math.floor((diff % 3600000) / 60000);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

export function formatDate(date: string): string {
  return new Date(date).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function cronToHuman(cron: string): string {
  const parts = cron.split(" ");
  if (parts.length !== 5) return cron;
  const [, hour, dayOfMonth, , dayOfWeek] = parts;

  if (dayOfMonth === "*/2") return `Every 2 days at ${hour}:00`;
  if (dayOfMonth === "*/3") return `Every 3 days at ${hour}:00`;
  if (dayOfMonth === "*" && dayOfWeek === "*") return `Daily at ${hour}:00`;
  if (dayOfWeek === "1") return `Weekly (Mon) at ${hour}:00`;
  return cron;
}
