"use client";

import { FlaskConical, RefreshCw, Sparkles } from "lucide-react";
import { useState, type FormEvent } from "react";

import { api, type MetricInput, type Overview, type Publication } from "@/lib/api";
import { compactNumber, formatDateTime } from "@/lib/format";
import { useAction, useResource } from "@/lib/hooks";

import { useSession } from "../Session";
import { useToast } from "../Toast";
import { EmptyState, Panel, StatusBadge } from "../ui";

type Props = { overview: Overview };

export function PerformanceTab({ overview }: Props) {
  const { canEdit } = useSession();
  const toast = useToast();
  const { busy, run } = useAction();
  const pid = overview.project.id;
  const metrics = useResource(() => api.projects.metrics(pid), `metrics:${pid}`);
  const insights = useResource(() => api.projects.insights(pid), `insights:${pid}`);
  const experiments = useResource(() => api.projects.experiments(pid), `experiments:${pid}`);
  const [experiment, setExperiment] = useState({ name: "", hypothesis: "", a: "", b: "" });
  const published = overview.publications.filter((item) => ["published", "processing"].includes(item.status));

  const refreshAll = () => {
    metrics.reload();
    insights.reload();
  };

  const generateInsight = () =>
    run("insight", async () => {
      try {
        await api.projects.generateInsight(pid);
        toast.success("Insight gerado");
        insights.reload();
      } catch (error) {
        toast.error(error);
      }
    });

  async function createExperiment(event: FormEvent) {
    event.preventDefault();
    await run("experiment", async () => {
      try {
        await api.projects.createExperiment(pid, {
          name: experiment.name,
          hypothesis: experiment.hypothesis,
          variants: { A: experiment.a, B: experiment.b },
        });
        toast.success("Experimento criado");
        setExperiment({ name: "", hypothesis: "", a: "", b: "" });
        experiments.reload();
      } catch (error) {
        toast.error(error);
      }
    });
  }

  const data = metrics.data;
  return (
    <div className="stack">
      <section className="stat-grid">
        <div className="stat"><span>Visualizações</span><strong>{compactNumber(data?.views ?? 0)}</strong></div>
        <div className="stat"><span>Curtidas</span><strong>{compactNumber(data?.likes ?? 0)}</strong></div>
        <div className="stat"><span>Comentários + compart.</span><strong>{compactNumber((data?.comments ?? 0) + (data?.shares ?? 0))}</strong></div>
        <div className="stat"><span>Engajamento</span><strong>{((data?.engagement_rate ?? 0) * 100).toFixed(1)}%</strong></div>
      </section>

      <Panel title="Métricas por publicação" description="Registre manualmente ou atualize a partir da plataforma (publicações reais).">
        {published.length ? (
          published.map((publication) => (
            <PublicationMetrics key={publication.id} publication={publication} canEdit={canEdit} onSaved={refreshAll} />
          ))
        ) : (
          <EmptyState title="Nada publicado ainda">As métricas ficam disponíveis após a publicação.</EmptyState>
        )}
      </Panel>

      <div className="tab-grid">
        <Panel
          title="Insights"
          actions={
            canEdit && (
              <button className="secondary-button small" disabled={busy !== null} onClick={generateInsight}>
                <Sparkles size={14} />{busy === "insight" ? "Gerando…" : "Gerar insight"}
              </button>
            )
          }
        >
          {insights.data?.length ? (
            <ul className="insight-list">
              {insights.data.map((insight) => (
                <li key={insight.id}>
                  <p>{insight.text}</p>
                  <small>{formatDateTime(insight.created_at)}</small>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">Nenhum insight gerado.</p>
          )}
        </Panel>

        <Panel title="Experimentos" description="Planeje testes A/B para os próximos vídeos.">
          {canEdit && (
            <form className="form" onSubmit={createExperiment}>
              <div className="form-row">
                <label>
                  Nome
                  <input required value={experiment.name} onChange={(event) => setExperiment({ ...experiment, name: event.target.value })} />
                </label>
                <label>
                  Hipótese
                  <input required value={experiment.hypothesis} onChange={(event) => setExperiment({ ...experiment, hypothesis: event.target.value })} />
                </label>
              </div>
              <div className="form-row">
                <label>
                  Variante A
                  <input value={experiment.a} onChange={(event) => setExperiment({ ...experiment, a: event.target.value })} placeholder="Abertura com pergunta" />
                </label>
                <label>
                  Variante B
                  <input value={experiment.b} onChange={(event) => setExperiment({ ...experiment, b: event.target.value })} placeholder="Abertura com dado surpreendente" />
                </label>
              </div>
              <button className="secondary-button" disabled={busy !== null}><FlaskConical size={15} />Criar experimento</button>
            </form>
          )}
          {experiments.data?.length ? (
            <ul className="insight-list">
              {experiments.data.map((item) => (
                <li key={item.id}>
                  <p><strong>{item.name}</strong> — {item.hypothesis}</p>
                  <small>
                    {Object.entries(item.variants).map(([key, value]) => `${key}: ${String(value) || "—"}`).join(" · ")} · <StatusBadge status={item.status} />
                  </small>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">Nenhum experimento criado.</p>
          )}
        </Panel>
      </div>
    </div>
  );
}

function PublicationMetrics({ publication, canEdit, onSaved }: { publication: Publication; canEdit: boolean; onSaved: () => void }) {
  const toast = useToast();
  const { busy, run } = useAction();
  const history = useResource(() => api.publications.metrics(publication.id), `pubmetrics:${publication.id}`);
  const [form, setForm] = useState<MetricInput>({ views: 0, likes: 0, comments: 0, shares: 0, window_hours: 24 });
  const field = (key: keyof MetricInput) => (event: { target: { value: string } }) =>
    setForm((current) => ({ ...current, [key]: Math.max(0, Number(event.target.value) || 0) }));

  const save = (event: FormEvent) => {
    event.preventDefault();
    run("save", async () => {
      try {
        await api.publications.addMetrics(publication.id, form);
        toast.success("Métricas registradas");
        history.reload();
        onSaved();
      } catch (error) {
        toast.error(error);
      }
    });
  };

  const refresh = () =>
    run("refresh", async () => {
      try {
        await api.publications.refreshMetrics(publication.id);
        toast.success("Métricas atualizadas da plataforma");
        history.reload();
        onSaved();
      } catch (error) {
        toast.error(error);
      }
    });

  return (
    <div className="metric-block">
      <div className="metric-head">
        <strong>{publication.title}</strong>
        <small>{publication.simulated ? "simulada" : "real"} · {formatDateTime(publication.published_at ?? publication.created_at)}</small>
        {canEdit && !publication.simulated && (
          <button className="secondary-button small" disabled={busy !== null} onClick={refresh}>
            <RefreshCw size={13} />Atualizar da plataforma
          </button>
        )}
      </div>
      {history.data && history.data.length > 0 && (
        <table className="table compact">
          <thead><tr><th>Janela</th><th>Views</th><th>Curtidas</th><th>Coment.</th><th>Compart.</th></tr></thead>
          <tbody>
            {history.data.map((metric) => (
              <tr key={metric.id}>
                <td>{metric.window_hours}h</td>
                <td>{metric.views}</td>
                <td>{metric.likes}</td>
                <td>{metric.comments}</td>
                <td>{metric.shares}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {canEdit && (
        <form className="metric-form" onSubmit={save}>
          {(["views", "likes", "comments", "shares", "window_hours"] as const).map((key) => (
            <label key={key}>
              {{ views: "Views", likes: "Curtidas", comments: "Coment.", shares: "Compart.", window_hours: "Janela (h)" }[key]}
              <input type="number" min={key === "window_hours" ? 1 : 0} value={form[key]} onChange={field(key)} />
            </label>
          ))}
          <button className="secondary-button small" disabled={busy !== null}>Registrar</button>
        </form>
      )}
      <RetentionBlock publicationId={publication.id} canEdit={canEdit} />
    </div>
  );
}

const ROLE_NAME: Record<string, string> = { hook: "gancho", broll: "apoio", clip: "clipe", reveal: "revelação", scene: "cena" };

function parsePoints(text: string): [number, number][] {
  return text
    .split(/[\s;]+/)
    .map((pair) => pair.split(":").map(Number))
    .filter((pair) => pair.length === 2 && pair.every((value) => Number.isFinite(value)))
    .map(([at, watch]) => [at > 1 ? at / 100 : at, watch > 1 ? watch / 100 : watch] as [number, number]);
}

function RetentionBlock({ publicationId, canEdit }: { publicationId: number; canEdit: boolean }) {
  const toast = useToast();
  const { busy, run } = useAction();
  const curve = useResource(() => api.autopilot.retention(publicationId), `retention:${publicationId}`);
  const [text, setText] = useState("0:100 25:72 50:58 75:47 100:40");

  const save = (event: FormEvent) => {
    event.preventDefault();
    const points = parsePoints(text);
    if (points.length < 2) {
      toast.error(new Error("Informe ao menos dois pontos no formato posição%:audiência%"));
      return;
    }
    run("retention", async () => {
      try {
        await api.autopilot.addRetention(publicationId, points);
        toast.success("Curva registrada e quedas mapeadas para os shots");
        curve.reload();
      } catch (error) {
        toast.error(error);
      }
    });
  };

  return (
    <div className="retention-block">
      {curve.data ? (
        <>
          <small className="muted">Retenção medida em {formatDateTime(curve.data.captured_at)}</small>
          <ul className="fact-list">
            {curve.data.drops.map((drop) => (
              <li key={drop.at}>
                Queda de {Math.round(drop.loss * 100)} p.p. aos {drop.at}s
                {drop.scene ? ` · cena ${drop.scene}, shot ${drop.shot} (${ROLE_NAME[drop.role ?? ""] ?? drop.role ?? "?"})` : ""}
              </li>
            ))}
          </ul>
        </>
      ) : (
        <small className="muted">Sem curva de retenção. Publicações reais no YouTube são coletadas automaticamente todo dia.</small>
      )}
      {canEdit && (
        <form className="retention-form" onSubmit={save}>
          <label>
            Curva manual (posição%:audiência%)
            <input value={text} onChange={(event) => setText(event.target.value)} />
          </label>
          <button className="secondary-button small" disabled={busy !== null}>Registrar curva</button>
        </form>
      )}
    </div>
  );
}
