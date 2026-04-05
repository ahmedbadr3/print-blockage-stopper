import { useState } from "react";
import { Plus, Zap } from "lucide-react";
import { usePrinters, usePrintNow } from "../hooks/usePrinters";
import PrinterCard from "../components/dashboard/PrinterCard";
import AddPrinterDialog from "../components/dialogs/AddPrinterDialog";
import EditPrinterDialog from "../components/dialogs/EditPrinterDialog";
import { Printer } from "../types/printer";

export default function Dashboard() {
  const { data: printers, isLoading } = usePrinters();
  const [addOpen, setAddOpen] = useState(false);
  const [editPrinter, setEditPrinter] = useState<Printer | null>(null);

  return (
    <div>
      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Printers</h1>
          <p className="text-sm text-muted-foreground">Manage your automated self-test schedules</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setAddOpen(true)}
            className="flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
          >
            <Plus className="h-4 w-4" />
            Add Printer
          </button>
        </div>
      </div>

      {/* Grid */}
      {isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-52 animate-pulse rounded-lg border border-border bg-card" />
          ))}
        </div>
      ) : printers && printers.length > 0 ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {printers.map((printer) => (
            <PrinterCard key={printer.id} printer={printer} onEdit={setEditPrinter} />
          ))}
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border py-16">
          <Zap className="mb-3 h-10 w-10 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">No printers configured</p>
          <button
            onClick={() => setAddOpen(true)}
            className="mt-3 text-sm font-medium text-primary hover:underline"
          >
            Add your first printer
          </button>
        </div>
      )}

      <AddPrinterDialog open={addOpen} onClose={() => setAddOpen(false)} />
      <EditPrinterDialog printer={editPrinter} onClose={() => setEditPrinter(null)} />
    </div>
  );
}
