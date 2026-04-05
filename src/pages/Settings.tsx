import { useState } from "react";
import { Webhook, Mail, Home, Send, Globe, Server } from "lucide-react";
import { useApi } from "../hooks/usePrinters";
import { useDemo } from "../contexts/DemoContext";
import { toast } from "sonner";
import { cn } from "../lib/utils";

export default function Settings() {
  const api = useApi();
  const { isDemo, apiBaseUrl, setApiBaseUrl } = useDemo();
  const [webhookUrl, setWebhookUrl] = useState("");
  const [smtp, setSmtp] = useState({ host: "", port: 587, user: "", password: "", to: "" });
  const [ha, setHa] = useState({ url: "", token: "" });
  const [apiUrl, setApiUrl] = useState(apiBaseUrl);

  const handleTestNotification = async (type: string) => {
    try {
      await api.testNotification(type);
      toast.success(`${type} notification sent`);
    } catch {
      toast.error(isDemo ? "Notifications are disabled in demo mode" : "Failed to send notification");
    }
  };

  return (
    <div>
      <h1 className="mb-6 text-2xl font-bold text-foreground">Settings</h1>

      <div className="max-w-2xl space-y-6">
        {/* API Connection */}
        <Section icon={<Server className="h-5 w-5 text-primary" />} title="API Connection" description="Connect to your Print Blockage Stopper Docker container">
          <div className="flex gap-2">
            <input
              value={apiUrl}
              onChange={(e) => setApiUrl(e.target.value)}
              placeholder="http://192.168.1.10:8631"
              className="flex-1 rounded-md border border-input bg-background px-3 py-2 font-mono text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
            />
            <button
              onClick={() => { setApiBaseUrl(apiUrl); toast.success(apiUrl ? "API URL saved — switched to live mode" : "Switched to demo mode"); }}
              className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
            >
              {apiUrl ? "Connect" : "Use Demo"}
            </button>
          </div>
          {isDemo && (
            <p className="mt-2 text-xs text-warning">Running in demo mode with mock data</p>
          )}
        </Section>

        {/* Webhook */}
        <Section icon={<Webhook className="h-5 w-5 text-primary" />} title="Webhook" description="Send notifications to a webhook URL on print events">
          <div className="flex gap-2">
            <input
              value={webhookUrl}
              onChange={(e) => setWebhookUrl(e.target.value)}
              placeholder="https://hooks.example.com/print-events"
              className="flex-1 rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
            />
            <button
              onClick={() => handleTestNotification("webhook")}
              className="flex items-center gap-1.5 rounded-md bg-muted px-3 py-2 text-sm text-muted-foreground hover:text-foreground"
            >
              <Send className="h-3.5 w-3.5" />
              Test
            </button>
          </div>
        </Section>

        {/* Email */}
        <Section icon={<Mail className="h-5 w-5 text-primary" />} title="Email (SMTP)" description="Receive email notifications for print events">
          <div className="grid grid-cols-2 gap-3">
            <Input label="SMTP Host" value={smtp.host} onChange={(v) => setSmtp({ ...smtp, host: v })} placeholder="smtp.gmail.com" />
            <Input label="Port" type="number" value={String(smtp.port)} onChange={(v) => setSmtp({ ...smtp, port: Number(v) })} />
            <Input label="Username" value={smtp.user} onChange={(v) => setSmtp({ ...smtp, user: v })} />
            <Input label="Password" type="password" value={smtp.password} onChange={(v) => setSmtp({ ...smtp, password: v })} />
            <div className="col-span-2">
              <Input label="Send To" value={smtp.to} onChange={(v) => setSmtp({ ...smtp, to: v })} placeholder="you@example.com" />
            </div>
          </div>
          <button
            onClick={() => handleTestNotification("email")}
            className="mt-3 flex items-center gap-1.5 rounded-md bg-muted px-3 py-2 text-sm text-muted-foreground hover:text-foreground"
          >
            <Send className="h-3.5 w-3.5" />
            Send Test Email
          </button>
        </Section>

        {/* Home Assistant */}
        <Section icon={<Home className="h-5 w-5 text-primary" />} title="Home Assistant" description="Integrate with Home Assistant for smart home automation">
          <div className="space-y-3">
            <Input label="HA URL" value={ha.url} onChange={(v) => setHa({ ...ha, url: v })} placeholder="http://homeassistant.local:8123" />
            <Input label="Long-Lived Access Token" value={ha.token} onChange={(v) => setHa({ ...ha, token: v })} type="password" />
          </div>
          <button
            onClick={() => handleTestNotification("homeassistant")}
            className="mt-3 flex items-center gap-1.5 rounded-md bg-muted px-3 py-2 text-sm text-muted-foreground hover:text-foreground"
          >
            <Send className="h-3.5 w-3.5" />
            Test Integration
          </button>
        </Section>

        {/* Save */}
        <button
          onClick={() => {
            api.saveSettings({ webhook_url: webhookUrl, smtp_host: smtp.host, smtp_port: smtp.port, smtp_user: smtp.user, smtp_password: smtp.password, smtp_to: smtp.to, ha_url: ha.url, ha_token: ha.token });
            toast.success("Settings saved");
          }}
          className="w-full rounded-md bg-primary py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          Save All Settings
        </button>
      </div>
    </div>
  );
}

function Section({ icon, title, description, children }: { icon: React.ReactNode; title: string; description: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-card p-5">
      <div className="mb-4 flex items-center gap-3">
        {icon}
        <div>
          <h3 className="font-medium text-card-foreground">{title}</h3>
          <p className="text-xs text-muted-foreground">{description}</p>
        </div>
      </div>
      {children}
    </div>
  );
}

function Input({ label, value, onChange, placeholder, type = "text" }: {
  label: string; value: string; onChange: (v: string) => void; placeholder?: string; type?: string;
}) {
  return (
    <div>
      <label className="mb-1 block text-xs font-medium text-muted-foreground">{label}</label>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
      />
    </div>
  );
}
