"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useState, type FormEvent } from "react";

import { api, errorMessage } from "@/lib/api";

export default function LoginPage({ searchParams }: { searchParams: Promise<{ next?: string }> }) {
  const { next } = use(searchParams);
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.auth.login(email, password);
      router.replace(next && next.startsWith("/") && !next.startsWith("//") ? next : "/");
      router.refresh();
    } catch (failure) {
      setError(errorMessage(failure));
      setBusy(false);
    }
  }

  return (
    <form className="auth-card" onSubmit={submit}>
      <p className="eyebrow">BEM-VINDO DE VOLTA</p>
      <h2>Entrar no Narra</h2>
      <label>
        E-mail
        <input type="email" autoComplete="email" required value={email} onChange={(event) => setEmail(event.target.value)} />
      </label>
      <label>
        Senha
        <input
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
      </label>
      {error && <div className="notice notice-error">{error}</div>}
      <button className="primary-button full" disabled={busy}>{busy ? "Entrando…" : "Entrar"}</button>
      <p className="auth-switch">Ainda não tem conta? <Link href="/signup">Criar conta</Link></p>
    </form>
  );
}
