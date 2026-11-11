"use client";

import type { ReactNode } from "react";

import { AppShell } from "@/components/AppShell";
import { SessionProvider } from "@/components/Session";
import { ToastProvider } from "@/components/Toast";

export default function AuthenticatedLayout({ children }: { children: ReactNode }) {
  return (
    <ToastProvider>
      <SessionProvider>
        <AppShell>{children}</AppShell>
      </SessionProvider>
    </ToastProvider>
  );
}
