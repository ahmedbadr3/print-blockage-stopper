import { Printer, PrintHistoryEntry, AppSettings } from "../types/printer";
import { mockPrinters, generateMockHistory, mockLogs } from "./mockData";

let demoState = {
  printers: [...mockPrinters],
  history: generateMockHistory(),
};

export function createApi(baseUrl: string, isDemo: boolean) {
  async function request<T>(path: string, options?: RequestInit): Promise<T> {
    if (isDemo) throw new Error("Demo mode");
    const res = await fetch(`${baseUrl}${path}`, {
      ...options,
      headers: { "Content-Type": "application/json", ...options?.headers },
    });
    if (!res.ok) throw new Error(`API error: ${res.status}`);
    return res.json();
  }

  return {
    async getPrinters(): Promise<Printer[]> {
      if (isDemo) return demoState.printers;
      return request("/api/printers");
    },

    async addPrinter(printer: Partial<Printer>): Promise<void> {
      if (isDemo) {
        const newPrinter: Printer = {
          id: String(Date.now()),
          name: printer.name || "New Printer",
          ip: printer.ip || "0.0.0.0",
          connection: printer.connection || "ipp",
          port: printer.port || 631,
          paper_size: printer.paper_size || "A4",
          schedule: printer.schedule || "0 3 */2 * *",
          skip_hours: printer.skip_hours || 12,
          test_image: printer.test_image || "nozzle-check",
          paused: false,
          status: "unknown",
        };
        demoState.printers = [...demoState.printers, newPrinter];
        return;
      }
      await request("/api/printers/add", { method: "POST", body: JSON.stringify(printer) });
    },

    async updatePrinter(printer: Partial<Printer>): Promise<void> {
      if (isDemo) {
        demoState.printers = demoState.printers.map((p) =>
          p.id === printer.id ? { ...p, ...printer } : p
        );
        return;
      }
      await request("/api/printers/update", { method: "POST", body: JSON.stringify(printer) });
    },

    async removePrinter(id: string): Promise<void> {
      if (isDemo) {
        demoState.printers = demoState.printers.filter((p) => p.id !== id);
        return;
      }
      await request(`/api/printers/remove`, { method: "POST", body: JSON.stringify({ id }) });
    },

    async printNow(id: string): Promise<void> {
      if (isDemo) {
        demoState.printers = demoState.printers.map((p) =>
          p.id === id ? { ...p, status: "printing" as const, last_print: new Date().toISOString(), last_result: "success" as const } : p
        );
        setTimeout(() => {
          demoState.printers = demoState.printers.map((p) =>
            p.id === id ? { ...p, status: "ok" as const } : p
          );
        }, 3000);
        return;
      }
      await request(`/api/print-now/${id}`, { method: "POST" });
    },

    async toggleSchedule(id: string): Promise<void> {
      if (isDemo) {
        demoState.printers = demoState.printers.map((p) =>
          p.id === id ? { ...p, paused: !p.paused } : p
        );
        return;
      }
      await request(`/api/toggle-schedule/${id}`, { method: "POST" });
    },

    async getHistory(): Promise<PrintHistoryEntry[]> {
      if (isDemo) return demoState.history;
      return request("/api/history");
    },

    async getLogs(): Promise<string[]> {
      if (isDemo) return mockLogs;
      const data = await request<{ logs: string[] }>("/api/logs");
      return data.logs;
    },

    async discover(): Promise<Array<{ ip: string; model?: string }>> {
      if (isDemo) {
        return [
          { ip: "192.168.1.55", model: "Canon PIXMA TR8620" },
          { ip: "192.168.1.60", model: "Epson ET-2850" },
        ];
      }
      return request("/api/discover");
    },

    async testConnection(ip: string, connection: string, port: number) {
      if (isDemo) {
        return { reachable: true, model: "Demo Printer Model", ink_levels: [], error: null };
      }
      return request("/api/test-connection", {
        method: "POST",
        body: JSON.stringify({ ip, connection, port }),
      });
    },

    async getPresets(): Promise<string[]> {
      if (isDemo) return ["nozzle-check", "color-bars", "gradient", "photo-test", "alignment"];
      return request("/api/presets");
    },

    async saveSettings(settings: Partial<AppSettings>): Promise<void> {
      if (isDemo) return;
      await request("/api/notifications", { method: "POST", body: JSON.stringify(settings) });
    },

    async testNotification(type: string): Promise<void> {
      if (isDemo) return;
      await request("/api/notifications/test", { method: "POST", body: JSON.stringify({ type }) });
    },
  };
}
