"use client";

import { Bot, Check, Lightbulb, Play, RefreshCw, RotateCcw, Sparkles, X, Zap } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { AutopilotSettingsForm } from "@/components/autopilot/SettingsForm";
import { useSession } from "@/components/Session";
import { useToast } from "@/components/Toast";
import { EmptyState, ErrorNotice, Loading, Panel, StatusBadge } from "@/components/ui";
import { api, type AITestReport, type AutopilotOverview, type Language } from "@/lib/api";
import { formatDateTime, LANGUAGE_LABEL, money, STAGE_LABEL } from "@/lib/format";
import { useAction, useInterval, useResource } from "@/lib/hooks";

const TABS = [
  { id: "painel", label: "Painel" },
  { id: "excecoes", label: "Exceções" },
  { id: "temas", label: "Temas" },
  { id: "playbook", label: "Playbook" },
  { id: "configuracoes", label: "Configurações" },
];

const INTEGRATION_LABEL: Record<string, string> = {
  ai: "Azure OpenAI",
  transcription: "Transcrição",
  articles: "Busca de artigos (Tavily)",
  youtube: "YouTube Data API",
  pexels: "Pexels",
  pixabay: "Pixabay",
  open_media: "Wikimedia + Openverse",
  fair_use_clips: "Clipes curtos (yt-dlp)",
  queue: "Fila do worker",
  youtube_login: "Login do YouTube",
  tiktok_login: "Login do TikTok",
  live_publish: "Publicação real",
};

function RetentionChart({ points }: { points: [number, number][] }) {
  if (points.length < 2) return <p className="muted">Sem curvas de retenção ainda. Elas chegam do YouTube Analytics ou podem ser registradas na aba Desempenho do projeto.</p>;
  const width = 320;
  const height = 120;
  const path = points.map(([x, y]) => `${(x * width).toFixed(1)},${(height - Math.min(1, y) * height).toFixed(1)}`).join(" ");
  return (
    <svg className="retention-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Curva média de retenção">
      <polyline points={`0,${height} ${path} ${width},${height}`} className="area" />
      <polyline points={path} className="line" />
    </svg>
  );
}

function Dashboard({ data, reload }: { data: AutopilotOverview; reload: () => void }) {
  const { canEdit, isOwner } = useSession();
  const toast = useToast();
  const router = useRouter();
  const { busy, run } = useAction();
  const [topic, setTopic] = useState("");
  const [language, setLanguage] = useState<Language>("pt-BR");
  const [aiTest, setAiTest] = useState<AITestReport | null>(null);

  const testAI = () =>
    run("test", async () => {
      try {
        setAiTest(await api.autopilot.testAI());
      } catch (error) {
        toast.error(error);
      }
    });

  const start = (event: FormEvent) => {
    event.preventDefault();
    run("start", async () => {
      try {
        const project = await api.autopilot.start({ topic: topic.trim() || undefined, language });
        toast.success(`Piloto automático iniciado: ${project.name}`);
        router.push(`/projects/${project.id}`);
      } catch (error) {
        toast.error(error);
      }
    });
  };

  return (
    <div className="stack">
      <section className="stat-grid">
        <div className="stat"><span>Vídeos produzidos sozinho</span><strong>{data.produced}</strong></div>
        <div className="stat"><span>Publicados</span><strong>{data.published}</strong></div>
        <div className="stat"><span>Aprovação automática</span><strong>{Math.round(data.auto_approval_rate * 100)}%</strong></div>
        <div className="stat"><span>Aguardando você</span><strong>{data.inbox_count}</strong></div>
      </section>

      <div className="tab-grid wide-left">
        {canEdit && (
          <Panel title="Novo vídeo no piloto automático" description="Deixe o tema vazio para a IA escolher o melhor tema sugerido.">
            <form className="form" onSubmit={start}>
              <label>
                Tema (opcional)
                <input value={topic} onChange={(event) => setTopic(event.target.value)} placeholder="Ex.: Destiny 1" />
              </label>
              <label>
                Idioma
                <select value={language} onChange={(event) => setLanguage(event.target.value as Language)}>
                  {Object.entries(LANGUAGE_LABEL).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
              </label>
              <div className="form-actions">
                <button className="primary-button" disabled={busy !== null}><Play size={15} />{busy ? "Iniciando…" : "Produzir sozinho"}</button>
              </div>
            </form>
          </Panel>
        )}
        <Panel
          title="Integrações"
          description="Sem uma chave, a etapa usa a alternativa local."
          actions={
            isOwner && (
              <button className="secondary-button small" disabled={busy !== null || !data.integrations.ai} onClick={testAI}>
                <Zap size={14} />{busy === "test" ? "Testando…" : "Testar IA"}
              </button>
            )
          }
        >
          <ul className="integration-list">
            {Object.entries(data.integrations).map(([key, on]) => (
              <li key={key}><span className={`dot ${on ? "ok" : ""}`} />{INTEGRATION_LABEL[key] ?? key}</li>
            ))}
          </ul>
          {aiTest && (
            <div className={`notice ${aiTest.ok ? "" : "notice-error"} ai-test`}>
              {aiTest.ok ? (
                <>
                  <strong>{aiTest.deployment} respondeu em {(aiTest.latency_ms / 1000).toFixed(1)}s</strong> (configuração: {aiTest.source}).{" "}
                  JSON ok · visão {aiTest.vision ? `ok (cor: ${aiTest.vision_answer})` : `falhou: ${aiTest.vision_error ?? "sem resposta"}`}
                </>
              ) : (
                <><strong>Falha em {aiTest.endpoint}:</strong> {aiTest.error}</>
              )}
            </div>
          )}
        </Panel>
      </div>

      {data.in_flight.length > 0 && (
        <Panel title="Em produção agora" actions={<button className="icon-button" onClick={reload} aria-label="Atualizar"><RefreshCw size={14} /></button>}>
          <ul className="insight-list">
            {data.in_flight.map((project) => (
              <li key={project.id}>
                <p><Link href={`/projects/${project.id}`}>{project.name}</Link></p>
                <small>{STAGE_LABEL[project.autopilot_stage ?? ""] ?? project.autopilot_stage} · {LANGUAGE_LABEL[project.language]}</small>
              </li>
            ))}
          </ul>
        </Panel>
      )}

      <div className="tab-grid">
        <Panel title="Etapas" description="Tempo, custo e notas médias de cada etapa automática.">
          <table className="table compact">
            <thead><tr><th>Etapa</th><th>Execuções</th><th>Tempo</th><th>Custo</th><th>Nota</th><th>Bloqueios</th></tr></thead>
            <tbody>
              {data.stage_stats.map((stat) => (
                <tr key={stat.stage}>
                  <td>{STAGE_LABEL[stat.stage] ?? stat.stage}</td>
                  <td>{stat.runs}</td>
                  <td>{stat.avg_seconds}s</td>
                  <td>{money(Math.round(stat.avg_cost_cents))}</td>
                  <td>{stat.avg_score ?? "—"}</td>
                  <td>{stat.blocked + stat.failed}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
        <Panel title="Retenção média" description={`${data.retention_samples} vídeo(s) com curva medida.`}>
          <RetentionChart points={data.retention_curve} />
          {data.rules.length > 0 && (
            <ul className="fact-list">{data.rules.slice(0, 4).map((rule) => <li key={rule.id}>{rule.text}</li>)}</ul>
          )}
        </Panel>
      </div>

      <Panel title="Atividade recente">
        {data.recent_runs.length ? (
          <table className="table compact">
            <thead><tr><th>Quando</th><th>Projeto</th><th>Etapa</th><th>Status</th><th>Nota</th><th>Tempo</th></tr></thead>
            <tbody>
              {data.recent_runs.map((item) => (
                <tr key={item.id}>
                  <td>{formatDateTime(item.started_at)}</td>
                  <td><Link href={`/projects/${item.project_id}`}>#{item.project_id}</Link></td>
                  <td>{STAGE_LABEL[item.stage] ?? item.stage}</td>
                  <td><StatusBadge status={item.status === "blocked" ? "failed" : item.status} /></td>
                  <td>{item.score ?? "—"}</td>
                  <td>{(item.duration_ms / 1000).toFixed(1)}s</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <EmptyState title="Nada produzido ainda">Inicie um vídeo acima ou ative a produção na cadência em Configurações.</EmptyState>
        )}
      </Panel>
    </div>
  );
}

function Inbox() {
  const { canEdit } = useSession();
  const toast = useToast();
  const { busy, run } = useAction();
  const inbox = useResource(api.autopilot.inbox, "autopilot:inbox");

  const resume = (projectId: number, approve: boolean) =>
    run(`${projectId}-${approve}`, async () => {
      try {
        await api.autopilot.resume(projectId, approve);
        toast.success(approve ? "Aprovado: produção retomada" : "Etapa reenviada");
        inbox.reload();
      } catch (error) {
        toast.error(error);
      }
    });

  if (inbox.error) return <ErrorNotice error={inbox.error} onRetry={inbox.reload} />;
  if (inbox.loading) return <Loading />;
  return (
    <Panel title="Caixa de exceções" description="Só chegam aqui vídeos que um portão de qualidade reprovou ou que falharam.">
      {inbox.data?.length ? (
        <ul className="inbox-list">
          {inbox.data.map((item) => (
            <li key={item.project.id}>
              <div>
                <strong><Link href={`/projects/${item.project.id}`}>{item.project.name}</Link></strong>
                <small>{STAGE_LABEL[item.stage] ?? item.stage} · {formatDateTime(item.blocked_at)}</small>
                <p>{item.reason}</p>
              </div>
              {canEdit && (
                <div className="row-actions">
                  {["script_gate", "render_gate"].includes(item.stage) && (
                    <button className="primary-button small" disabled={busy !== null} onClick={() => resume(item.project.id, true)}>
                      <Check size={14} />Aprovar
                    </button>
                  )}
                  <button className="secondary-button small" disabled={busy !== null} onClick={() => resume(item.project.id, false)}>
                    <RotateCcw size={14} />Tentar de novo
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState title="Nenhuma exceção">Tudo que o piloto automático produziu passou nos portões de qualidade.</EmptyState>
      )}
    </Panel>
  );
}

function Topics() {
  const { canEdit } = useSession();
  const toast = useToast();
  const router = useRouter();
  const { busy, run } = useAction();
  const topics = useResource(() => api.autopilot.topics(), "autopilot:topics");

  const act = (name: string, task: () => Promise<unknown>, message: string, after?: (value: unknown) => void) =>
    run(name, async () => {
      try {
        const value = await task();
        toast.success(message);
        topics.reload();
        after?.(value);
      } catch (error) {
        toast.error(error);
      }
    });

  return (
    <Panel
      title="Pauta sugerida"
      description="Temas propostos a partir do nicho, de vídeos populares e do desempenho do próprio canal."
      actions={
        canEdit && (
          <button className="secondary-button small" disabled={busy !== null} onClick={() => act("plan", api.autopilot.planTopics, "Novos temas sugeridos")}>
            <Lightbulb size={14} />{busy === "plan" ? "Pensando…" : "Sugerir temas"}
          </button>
        )
      }
    >
      {topics.error && <ErrorNotice error={topics.error} onRetry={topics.reload} />}
      {topics.loading && <Loading />}
      {topics.data?.length ? (
        <ul className="inbox-list">
          {topics.data.map((topic) => (
            <li key={topic.id}>
              <div>
                <strong>{topic.topic}</strong>
                <small>Potencial {Math.round(topic.predicted_score)} · {String(topic.source.provider ?? "")}</small>
                {topic.angle && <p>{topic.angle}</p>}
                {topic.reason && <p className="muted">{topic.reason}</p>}
              </div>
              {canEdit && (
                <div className="row-actions">
                  <button
                    className="primary-button small"
                    disabled={busy !== null}
                    onClick={() =>
                      act(`use-${topic.id}`, () => api.autopilot.useTopic(topic.id), "Produção iniciada", (project) =>
                        router.push(`/projects/${(project as { id: number }).id}`),
                      )
                    }
                  >
                    <Sparkles size={14} />Produzir
                  </button>
                  <button className="icon-button" aria-label="Descartar tema" disabled={busy !== null} onClick={() => act(`rm-${topic.id}`, () => api.autopilot.rejectTopic(topic.id), "Tema descartado")}>
                    <X size={14} />
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      ) : (
        !topics.loading && <EmptyState title="Sem temas na fila">Defina o nicho em Configurações e peça sugestões.</EmptyState>
      )}
    </Panel>
  );
}

function Playbook() {
  const { canEdit } = useSession();
  const toast = useToast();
  const { busy, run } = useAction();
  const rules = useResource(api.autopilot.playbook, "autopilot:playbook");
  const refresh = () =>
    run("refresh", async () => {
      try {
        await api.autopilot.refreshPlaybook();
        toast.success("Playbook recalculado com as métricas atuais");
        rules.reload();
      } catch (error) {
        toast.error(error);
      }
    });
  return (
    <Panel
      title="Playbook aprendido"
      description="Regras extraídas das métricas reais. Elas entram nos prompts de tema e roteiro e ajustam o ritmo da edição."
      actions={canEdit && <button className="secondary-button small" disabled={busy !== null} onClick={refresh}><RefreshCw size={14} />Recalcular</button>}
    >
      {rules.loading && <Loading />}
      {rules.data?.length ? (
        <ul className="insight-list">
          {rules.data.map((rule) => (
            <li key={rule.id}>
              <p>{rule.text}</p>
              <small>{rule.key} · confiança {Math.round(rule.confidence * 100)}% · {String(rule.evidence.samples ?? 0)} vídeos · {formatDateTime(rule.created_at)}</small>
            </li>
          ))}
        </ul>
      ) : (
        !rules.loading && <EmptyState title="Ainda aprendendo">São necessários pelo menos 2 vídeos publicados com métricas para gerar as primeiras regras.</EmptyState>
      )}
    </Panel>
  );
}

function SettingsTab() {
  const settings = useResource(api.autopilot.settings, "autopilot:settings");
  if (settings.error) return <ErrorNotice error={settings.error} onRetry={settings.reload} />;
  if (!settings.data) return <Loading />;
  return (
    <Panel title="Configurações do piloto automático">
      <AutopilotSettingsForm initial={settings.data} onSaved={(value) => settings.mutate(value)} />
    </Panel>
  );
}

export default function AutopilotPage() {
  const [tab, setTab] = useState("painel");
  const overview = useResource(api.autopilot.overview, "autopilot:overview");
  const busy = Boolean(overview.data?.in_flight.length);
  useInterval(overview.reload, tab === "painel" && busy ? 5000 : null);

  return (
    <>
      <section className="page-head">
        <div>
          <p className="eyebrow"><Bot size={14} /> AUTOMAÇÃO</p>
          <h1 className="page-title">Piloto automático</h1>
          <p className="hero-copy">Pesquisa, roteiro, mídia, edição, revisão e publicação sem intervenção: você só decide as exceções.</p>
        </div>
        {overview.data && <StatusBadge status={overview.data.enabled ? "approved" : "draft"} />}
      </section>
      <nav className="tabs" aria-label="Seções do piloto automático">
        {TABS.map((item) => (
          <button key={item.id} className={item.id === tab ? "active" : ""} onClick={() => setTab(item.id)}>
            {item.label}
            {item.id === "excecoes" && overview.data?.inbox_count ? <span className="tab-count">{overview.data.inbox_count}</span> : null}
          </button>
        ))}
      </nav>
      {tab === "painel" && (
        <>
          {overview.error && <ErrorNotice error={overview.error} onRetry={overview.reload} />}
          {overview.loading && <Loading />}
          {overview.data && <Dashboard data={overview.data} reload={overview.reload} />}
        </>
      )}
      {tab === "excecoes" && <Inbox />}
      {tab === "temas" && <Topics />}
      {tab === "playbook" && <Playbook />}
      {tab === "configuracoes" && <SettingsTab />}
    </>
  );
}
