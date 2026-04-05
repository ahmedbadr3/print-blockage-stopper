import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useDemo } from "../contexts/DemoContext";
import { createApi } from "../services/api";
import { Printer } from "../types/printer";
import { toast } from "sonner";

export function useApi() {
  const { isDemo, apiBaseUrl } = useDemo();
  return createApi(apiBaseUrl, isDemo);
}

export function usePrinters() {
  const api = useApi();
  return useQuery({
    queryKey: ["printers"],
    queryFn: () => api.getPrinters(),
  });
}

export function usePrintNow() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.printNow(id),
    onSuccess: () => {
      toast.success("Print job sent");
      qc.invalidateQueries({ queryKey: ["printers"] });
    },
    onError: () => toast.error("Failed to send print job"),
  });
}

export function useToggleSchedule() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.toggleSchedule(id),
    onSuccess: () => {
      toast.success("Schedule updated");
      qc.invalidateQueries({ queryKey: ["printers"] });
    },
  });
}

export function useAddPrinter() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (printer: Partial<Printer>) => api.addPrinter(printer),
    onSuccess: () => {
      toast.success("Printer added");
      qc.invalidateQueries({ queryKey: ["printers"] });
    },
    onError: () => toast.error("Failed to add printer"),
  });
}

export function useUpdatePrinter() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (printer: Partial<Printer>) => api.updatePrinter(printer),
    onSuccess: () => {
      toast.success("Printer updated");
      qc.invalidateQueries({ queryKey: ["printers"] });
    },
    onError: () => toast.error("Failed to update printer"),
  });
}

export function useRemovePrinter() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.removePrinter(id),
    onSuccess: () => {
      toast.success("Printer removed");
      qc.invalidateQueries({ queryKey: ["printers"] });
    },
    onError: () => toast.error("Failed to remove printer"),
  });
}

export function useHistory() {
  const api = useApi();
  return useQuery({
    queryKey: ["history"],
    queryFn: () => api.getHistory(),
  });
}

export function useLogs() {
  const api = useApi();
  return useQuery({
    queryKey: ["logs"],
    queryFn: () => api.getLogs(),
    refetchInterval: 10000,
  });
}
