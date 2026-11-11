"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { api, errorMessage } from "@/lib/api";

export default function SignupPage() {
  const router = useRouter();
  const [form, setForm] = useState({ name: "", email: "", password: "", organization_name: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const update = (key: keyof typeof form) => (event: { target: { value: string } }) =>
    setForm((current) => ({ ...current, [key]: event.target.value }));

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.auth.signup(form);
      router.replace("/");
      router.refresh();
    } catch (failure) {
      setError(errorMessage(failure));
      setBusy(false);
    }
  }

  return (
    <form className="auth-card" onSubmit={submit}>
      <p className="eyebrow">COMECE AGORA</p>
      <h2>Criar sua conta</h2>
      <label>
        Seu nome
        <input required autoComplete="name" value={form.name} onChange={update("name")} />
      </label>
      <label>
        E-mail
        <input type="email" required autoComplete="email" value={form.email} onChange={update("email")} />
      </label>
      <label>
        Senha
        <input
          type="password"
          required
          minLength={8}
          autoComplete="new-password"
          value={form.password}
          onChange={update("password")}
        />
        <small>Mínimo de 8 caracteres.</small>
      </label>
      <label>
        Nome do estúdio ou organização
        <input required value={form.organization_name} onChange={update("organization_name")} />
      </label>
      {error && <div className="notice notice-error">{error}</div>}
      <button className="primary-button full" disabled={busy}>{busy ? "Criando…" : "Criar conta"}</button>
      <p className="auth-switch">Já tem conta? <Link href="/login">Entrar</Link></p>
    </form>
  );
}
