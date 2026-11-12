"use client";

import { Save } from "lucide-react";
import { useState, type FormEvent } from "react";

import { api, type AutopilotSettings } from "@/lib/api";
import { LANGUAGE_LABEL, money } from "@/lib/format";
import { useAction } from "@/lib/hooks";

import { useSession } from "../Session";
import { useToast } from "../Toast";

const lines = (value: string) => value.split("\n").map((item) => item.trim()).filter(Boolean);

export function AutopilotSettingsForm({ initial, onSaved }: { initial: AutopilotSettings; onSaved: (value: AutopilotSettings) => void }) {
  const { isOwner } = useSession();
  const toast = useToast();
  const { busy, run } = useAction();
  const [form, setForm] = useState({
    ...initial,
    banned: initial.banned_topics.join("\n"),
    press: initial.press_kit_urls.join("\n"),
    budget: initial.video_budget_cents / 100,
  });
  const set = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) => setForm((current) => ({ ...current, [key]: value }));

  const save = (event: FormEvent) => {
    event.preventDefault();
    run("save", async () => {
      try {
        const saved = await api.autopilot.updateSettings({
          enabled: form.enabled,
          script_threshold: form.script_threshold,
          cadence_hours: form.cadence_hours,
          auto_publish: form.auto_publish,
          live_publish: form.live_publish,
          platform: form.platform,
          language: form.language,
          niche: form.niche,
          audience: form.audience,
          duration_seconds: form.duration_seconds,
          video_budget_cents: Math.round(form.budget * 100),
          banned_topics: lines(form.banned),
          press_kit_urls: lines(form.press),
        });
        toast.success("Piloto automático atualizado");
        onSaved(saved);
      } catch (error) {
        toast.error(error);
      }
    });
  };

  const disabled = !isOwner;
  return (
    <form className="form" onSubmit={save}>
      <label className="checkbox">
        <input type="checkbox" checked={form.enabled} disabled={disabled} onChange={(event) => set("enabled", event.target.checked)} />
        Produzir vídeos sozinho na cadência definida
        <small>O agendador escolhe o melhor tema sugerido, pesquisa, escreve, monta, revisa e publica um vídeo por janela.</small>
      </label>
      <div className="form-row">
        <label>
          Nicho do canal
          <input value={form.niche} disabled={disabled} placeholder="Ex.: história dos videogames" onChange={(event) => set("niche", event.target.value)} />
        </label>
        <label>
          Público
          <input value={form.audience} disabled={disabled} onChange={(event) => set("audience", event.target.value)} />
        </label>
      </div>
      <div className="form-row">
        <label>
          Idioma padrão
          <select value={form.language} disabled={disabled} onChange={(event) => set("language", event.target.value as AutopilotSettings["language"])}>
            {Object.entries(LANGUAGE_LABEL).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <label>
          Duração alvo (s)
          <input type="number" min={15} max={600} value={form.duration_seconds} disabled={disabled} onChange={(event) => set("duration_seconds", Number(event.target.value))} />
        </label>
      </div>
      <div className="form-row">
        <label>
          Um vídeo a cada (horas)
          <input type="number" min={1} max={720} value={form.cadence_hours} disabled={disabled} onChange={(event) => set("cadence_hours", Number(event.target.value))} />
        </label>
        <label>
          Nota mínima do roteiro (0-100)
          <input type="number" min={0} max={100} value={form.script_threshold} disabled={disabled} onChange={(event) => set("script_threshold", Number(event.target.value))} />
          <small>Abaixo disso a IA reescreve uma vez; persistindo, o vídeo vai para a caixa de exceções.</small>
        </label>
      </div>
      <div className="form-row">
        <label>
          Teto por vídeo (R$)
          <input type="number" min={0} step={0.5} value={form.budget} disabled={disabled} onChange={(event) => set("budget", Number(event.target.value))} />
          <small>Atual: {money(initial.video_budget_cents)} por vídeo.</small>
        </label>
        <label>
          Canal de publicação
          <select value={form.platform} disabled={disabled} onChange={(event) => set("platform", event.target.value as AutopilotSettings["platform"])}>
            <option value="local">Simulado (local)</option>
            <option value="youtube">YouTube</option>
            <option value="tiktok">TikTok</option>
          </select>
          <small>YouTube/TikTok usam a conta conectada em Plataformas de publicação.</small>
        </label>
      </div>
      <label className="checkbox">
        <input type="checkbox" checked={form.auto_publish} disabled={disabled} onChange={(event) => set("auto_publish", event.target.checked)} />
        Publicar automaticamente quando o vídeo passar na revisão
      </label>
      <label className="checkbox">
        <input type="checkbox" checked={form.live_publish} disabled={disabled} onChange={(event) => set("live_publish", event.target.checked)} />
        Publicar de verdade (exige conta conectada e publicação real liberada para a plataforma)
      </label>
      <label>
        Temas proibidos (um por linha)
        <textarea rows={3} value={form.banned} disabled={disabled} onChange={(event) => set("banned", event.target.value)} />
      </label>
      <label>
        URLs de press kit oficiais (imagens, uma por linha)
        <textarea rows={3} value={form.press} disabled={disabled} placeholder="https://..." onChange={(event) => set("press", event.target.value)} />
        <small>Material de imprensa liberado pelos detentores dos direitos (ex.: estúdios de games) entra como candidato prioritário.</small>
      </label>
      {isOwner ? (
        <div className="form-actions">
          <button className="primary-button" disabled={busy !== null}><Save size={15} />{busy ? "Salvando…" : "Salvar piloto automático"}</button>
        </div>
      ) : (
        <small className="muted">Somente proprietários alteram o piloto automático.</small>
      )}
    </form>
  );
}
