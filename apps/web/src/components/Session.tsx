"use client";

import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, type ReactNode } from "react";

import { ApiError, api, type Me } from "@/lib/api";
import { useResource } from "@/lib/hooks";

type SessionValue = {
  me: Me;
  canEdit: boolean;
  isOwner: boolean;
  refresh: () => void;
  replace: (me: Me) => void;
  logout: () => Promise<void>;
};

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const session = useResource(api.auth.me, "me");

  useEffect(() => {
    if (session.error instanceof ApiError && session.error.status === 401) {
      api.auth.logout().finally(() => router.replace(`/login?next=${encodeURIComponent(pathname)}`));
    }
  }, [session.error, router, pathname]);

  if (!session.data) {
    return (
      <div className="screen-center">
        {session.error && !(session.error instanceof ApiError && session.error.status === 401) ? (
          <div className="empty-state">
            <strong>Não foi possível carregar sua sessão</strong>
            <p>{session.error.message}</p>
            <button className="secondary-button" onClick={session.reload}>Tentar novamente</button>
          </div>
        ) : (
          <div className="spinner" aria-label="Carregando" />
        )}
      </div>
    );
  }

  const me = session.data;
  const value: SessionValue = {
    me,
    canEdit: me.role !== "viewer",
    isOwner: me.role === "owner",
    refresh: session.reload,
    replace: session.mutate,
    logout: async () => {
      await api.auth.logout();
      router.replace("/login");
    },
  };
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside SessionProvider");
  return value;
}
