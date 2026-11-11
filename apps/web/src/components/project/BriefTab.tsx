"use client";

import { BookOpen, RefreshCw, Save, WandSparkles } from "lucide-react";
import { useState, type FormEvent } from "react";

import { api, type Dossier, type Language, type Overview } from "@/lib/api";
import { formatDateTime, LANGUAGE_LABEL } from "@/lib/format";
import { useAction, useInterval, useResource } from "@/lib/hooks";

import { useSession } from "../Session";
import { useToast } from "../Toast";
import { EmptyState, Panel } from "../ui";

type Props = { overview: Overview; reload: () => void; goTo: (tab: string) => void };

function DossierView({ dossier }: { dossier: Dossier }) {
  return (
    <div className="dossier">
      <p className="dossier-summary">{dossier.summary}</p>
      <small className="muted">
        Dossiê por {dossier.provider} · {dossier.facts.length} fatos · {dossier.video_moments.length} trechos de vídeo ·{" "}
        {formatDateTime(dossier.created_at)}
      </small>
      {dossier.facts.length > 0 && (
        <details open>
          <summary>Fatos com fonte</summary>
          <ol className="fact-list">
            {dossier.facts.slice(0, 12).map((fact) => (
              <li key={fact.id}>
                {fact.text}
                {fact.source_url && (
                  <> <a href={fact.source_url} target="_blank" rel="noreferrer">fonte</a></>
                )}
              </li>
            ))}
          </ol>
        </details>
      )}
      {dossier.hooks.length > 0 && (
        <details>
          <summary>Ganchos sugeridos</summary>
          <ul className="fact-list">{dossier.hooks.map((hook) => <li key={hook}>{hook}</li>)}</ul>
        </details>
      )}
      {dossier.video_moments.length > 0 && (
        <details>
          <summary>Trechos de vídeos para clipes</summary>
          <ul className="fact-list">
            {dossier.video_moments.map((moment) => (
              <li key={`${moment.video_id}-${moment.start}`}>
                <a href={`${moment.url}&t=${moment.start}s`} target="_blank" rel="noreferrer">{moment.title}</a> · {moment.start}s–{moment.end}s ·{" "}
                {moment.description}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

export function BriefTab({ overview, reload, goTo }: Props) {
  const { canEdit } = useSession();
  const toast = useToast();
  const { busy, run } = useAction();
  const brief = overview.brief;
  const pid = overview.project.id;
  const [form, setForm] = useState({
    topic: brief?.topic ?? "",
    audience: brief?.audience ?? "Pessoas curiosas, de 18 a 35 anos",
    objective: brief?.objective ?? "Explicar de forma clara e gerar retenção",
    duration: Number(brief?.constraints?.duration_seconds ?? 60),
    tone: String(brief?.constraints?.tone ?? "didático e próximo"),
    language: (brief?.language ?? overview.project.language ?? "pt-BR") as Language,
  });
  const [waitingFrom, setWaitingFrom] = useState<number | null>(null);
  const researching = waitingFrom !== null && overview.sources.length <= waitingFrom;
  useInterval(reload, researching ? 4000 : null);
  const dossier = useResource(() => api.projects.dossier(pid), `dossier:${pid}:${overview.sources.length}`);
  const set = (key: keyof typeof form) => (event: { target: { value: string } }) =>
    setForm((current) => ({ ...current, [key]: key === "duration" ? Number(event.target.value) : event.target.value }));

  async function save(event: FormEvent) {
    event.preventDefault();
    await run("save", async () => {
      try {
        await api.projects.saveBrief(pid, {
          topic: form.topic,
          audience: form.audience,
          objective: form.objective,
          language: form.language,
          constraints: { ...(brief?.constraints ?? {}), tone: form.tone, duration_seconds: form.duration },
        });
        toast.success("Briefing salvo");
        reload();
      } catch (error) {
        toast.error(error);
      }
    });
  }

  const generate = (name: "research" | "script") =>
    run(name, async () => {
      try {
        if (name === "research") {
          const job = await api.projects.researchJob(pid);
          if (job.queued) {
            setWaitingFrom(overview.sources.length);
            toast.success("Pesquisa iniciada: artigos e vídeos estão sendo analisados");
          } else {
            toast.success("Pesquisa gerada");
          }
        } else {
          await api.projects.generateScript(pid);
          toast.success("Nova versão de roteiro gerada");
          goTo("roteiro");
        }
        reload();
      } catch (error) {
        toast.error(error);
      }
    });

  return (
    <div className="tab-grid">
      <Panel title="Briefing" description="O ponto de partida da pesquisa e do roteiro.">
        <form className="form" onSubmit={save}>
          <label>
            Tema
            <textarea required minLength={2} value={form.topic} onChange={set("topic")} disabled={!canEdit} />
          </label>
          <label>
            Público
            <input required value={form.audience} onChange={set("audience")} disabled={!canEdit} />
          </label>
          <label>
            Objetivo
            <input required value={form.objective} onChange={set("objective")} disabled={!canEdit} />
          </label>
          <div className="form-row">
            <label>
              Duração alvo
              <select value={form.duration} onChange={set("duration")} disabled={!canEdit}>
                <option value={30}>30 segundos</option>
                <option value={60}>60 segundos</option>
                <option value={90}>90 segundos</option>
                <option value={180}>3 minutos</option>
              </select>
            </label>
            <label>
              Tom
              <input value={form.tone} onChange={set("tone")} disabled={!canEdit} />
            </label>
          </div>
          <label>
            Idioma do vídeo
            <select value={form.language} onChange={set("language")} disabled={!canEdit}>
              {Object.entries(LANGUAGE_LABEL).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
            <small>Define o idioma do roteiro, das legendas e a voz usada na narração.</small>
          </label>
          {canEdit && (
            <div className="form-actions">
              <button className="secondary-button" disabled={busy !== null}>
                <Save size={15} />{busy === "save" ? "Salvando…" : "Salvar briefing"}
              </button>
              <button
                type="button"
                className="primary-button"
                disabled={busy !== null || !brief}
                onClick={() => generate("script")}
              >
                <WandSparkles size={15} />{busy === "script" ? "Gerando…" : overview.latest_script ? "Gerar nova versão do roteiro" : "Gerar roteiro"}
              </button>
            </div>
          )}
        </form>
      </Panel>

      <Panel
        title="Pesquisa e fontes"
        description="Revise e complemente antes de aprovar o roteiro."
        actions={
          canEdit && (
            <button className="secondary-button small" disabled={busy !== null || !brief || researching} onClick={() => generate("research")}>
              <RefreshCw size={14} />{busy === "research" || researching ? "Pesquisando…" : "Pesquisar artigos e vídeos"}
            </button>
          )
        }
      >
        {dossier.data && <DossierView dossier={dossier.data} />}
        {overview.sources.length ? (
          <ul className="source-list">
            {overview.sources.map((source) => (
              <li key={source.id}>
                <BookOpen size={16} />
                <div>
                  <strong>{source.title}</strong>
                  <p>{source.summary}</p>
                  <small>
                    {source.provider} · {formatDateTime(source.created_at)}
                    {source.url && (
                      <> · <a href={source.url} target="_blank" rel="noreferrer">abrir</a></>
                    )}
                  </small>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState title="Nenhuma fonte ainda">
            {brief ? "Gere uma pesquisa para contextualizar o roteiro." : "Salve o briefing para habilitar a pesquisa."}
          </EmptyState>
        )}
      </Panel>
    </div>
  );
}
