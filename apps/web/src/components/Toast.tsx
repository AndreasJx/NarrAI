"use client";

import { CircleAlert, CircleCheck, X } from "lucide-react";
import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

import { errorMessage } from "@/lib/api";

type Toast = { id: number; message: string; tone: "success" | "error" };
type ToastValue = { success: (message: string) => void; error: (error: unknown) => void };

const ToastContext = createContext<ToastValue | null>(null);
let nextId = 1;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const dismiss = useCallback((id: number) => setToasts((items) => items.filter((item) => item.id !== id)), []);
  const push = useCallback(
    (message: string, tone: Toast["tone"]) => {
      const id = nextId++;
      setToasts((items) => [...items.slice(-3), { id, message, tone }]);
      setTimeout(() => dismiss(id), tone === "error" ? 8000 : 4000);
    },
    [dismiss],
  );
  const [value] = useState<ToastValue>(() => ({
    success: (message) => push(message, "success"),
    error: (error) => push(errorMessage(error), "error"),
  }));

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toast-stack" role="status" aria-live="polite">
        {toasts.map((toast) => (
          <div key={toast.id} className={`toast toast-${toast.tone}`}>
            {toast.tone === "success" ? <CircleCheck size={17} /> : <CircleAlert size={17} />}
            <span>{toast.message}</span>
            <button onClick={() => dismiss(toast.id)} aria-label="Fechar"><X size={15} /></button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastValue {
  const value = useContext(ToastContext);
  if (!value) throw new Error("useToast must be used inside ToastProvider");
  return value;
}
