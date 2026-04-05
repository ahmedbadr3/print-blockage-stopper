export interface InkLevel {
  name: string;
  level: number;
  color: string;
}

export interface Printer {
  id: string;
  name: string;
  ip: string;
  connection: "ipp" | "socket";
  port: number;
  paper_size: string;
  schedule: string;
  skip_hours: number;
  test_image: string;
  paused: boolean;
  status: "ok" | "error" | "unknown" | "printing";
  model?: string;
  ink_levels?: InkLevel[];
  last_print?: string;
  last_result?: "success" | "error";
  next_print?: string;
}

export interface PrintHistoryEntry {
  id: string;
  printer_id: string;
  printer_name: string;
  timestamp: string;
  result: "success" | "error";
  message?: string;
}

export interface AppSettings {
  webhook_url: string;
  smtp_host: string;
  smtp_port: number;
  smtp_user: string;
  smtp_password: string;
  smtp_to: string;
  ha_url: string;
  ha_token: string;
}
