"use client";

import { ChevronRight, CirclePlay, Clock3, Plus, ShieldCheck, Sparkles, WandSparkles } from "lucide-react";
import Link from "next/link";

import { useOpenComposer } from "@/components/AppShell";
import { ProjectCard } from "@/components/ProjectCard";
import { useSession } from "@/components/Session";
import { EmptyState, ErrorNotice, Loading, ProgressBar, Workflow } from "@/components/ui";
import { api } from "@/lib/api";
import { compactNumber, formatDateTime, statusInfo } from "@/lib/format";
import { useInterval, useResource } from "@/lib/hooks";
import { workflow } from "@/lib/workflow";

export default function DashboardPage() {
  const openComposer = useOpenComposer();
  const { me, canEdit } = useSession();
  const dashboard = useResource(api.dashboard, `dashboard:${me.organization.id}`);
  const active = dashboard.data?.active_render;
  const rendering = active && ["queued", "processing"].includes(active.render.status);
  useInterval(dashboard.reload, rendering ? 3000 : null);

  return (
    <>
      <section className="hero">
        <div>
          <p className="eyebrow"><WandSparkles size={14} /> ESTÚDIO INTELIGENTE</p>
          <h1>Transforme ideias em<br /><em>histórias que explicam.</em></h1>
          <p className="hero-copy">Da pesquisa à publicação, com você no controle de cada decisão.</p>
        </div>
        {canEdit && (
          <button className="primary-button" onClick={openComposer}><Plus size={18} />Criar novo vídeo</button>
        )}
      </section>

      {dashboard.error && <ErrorNotice error={dashboard.error} onRetry={dashboard.reload} />}
      {dashboard.loading && <Loading />}

      {dashboard.data && (
        <>
          {active ? (
            <section className="workflow-card">
              <div className="card-heading">
                <div>
                  <span className="live-dot" />
                  <strong>{rendering ? "Em produção" : "Último render"}</strong>
                  <small>{active.project.name}</small>
                </div>
                <Link className="text-button" href={`/projects/${active.project.id}`}>Abrir projeto <ChevronRight size={16} /></Link>
              </div>
              <Workflow
                steps={workflow({
                  hasBrief: true,
                  hasScript: true,
                  scriptApproved: true,
                  renderStatus: active.render.status,
                  publishApproved: ["approved", "publishing", "published"].includes(active.project.status),
                  published: active.project.status === "published",
                })}
              />
              <div className="render-status">
                <div className="render-preview"><CirclePlay size={24} /></div>
                <div className="render-copy">
                  <strong>
                    {rendering ? "Compondo cenas, narração e legendas" : `Render ${statusInfo(active.render.status).label.toLowerCase()}`}
                  </strong>
                  <span>
                    {active.scenes} cenas · iniciado {formatDateTime(active.render.started_at ?? active.render.created_at)}
                  </span>
                </div>
                <div className="render-progress">
                  <ProgressBar value={active.render.progress} />
                  <span>{active.render.progress}%</span>
                </div>
                <div className="estimate"><Clock3 size={15} /> {statusInfo(active.render.status).label}</div>
              </div>
            </section>
          ) : (
            <section className="workflow-card">
              <EmptyState
                title="Nenhum vídeo em produção"
                action={canEdit && <button className="secondary-button" onClick={openComposer}><Plus size={16} />Criar o primeiro vídeo</button>}
              >
                Crie um briefing para gerar pesquisa e roteiro. Depois de aprovar o roteiro, a narração e o vídeo são produzidos aqui.
              </EmptyState>
            </section>
          )}

          <section className="stat-grid">
            <div className="stat"><span>Projetos</span><strong>{dashboard.data.project_count}</strong></div>
            <div className="stat"><span>Em revisão</span><strong>{dashboard.data.status_counts.review ?? 0}</strong></div>
            <div className="stat"><span>Publicados</span><strong>{compactNumber(dashboard.data.published_count)}</strong></div>
            <div className="stat"><span>Canais conectados</span><strong>{dashboard.data.connected_channels}</strong></div>
          </section>

          <section id="projetos" className="section-block">
            <div className="section-title">
              <div>
                <h2>Projetos recentes</h2>
                <p>Continue de onde parou ou acompanhe o desempenho.</p>
              </div>
              <Link className="text-button" href="/projects">Ver todos <ChevronRight size={16} /></Link>
            </div>
            {dashboard.data.projects.length ? (
              <div className="project-grid">
                {dashboard.data.projects.map((project) => <ProjectCard key={project.id} project={project} />)}
              </div>
            ) : (
              <EmptyState title="Sem projetos ainda">Seus vídeos aparecerão aqui.</EmptyState>
            )}
          </section>

          <section className="insight-card">
            <div className="insight-icon"><Sparkles /></div>
            <div>
              <span className="eyebrow">INSIGHT MAIS RECENTE</span>
              <h3>
                {dashboard.data.latest_insight?.text ??
                  "Publique e registre métricas para receber recomendações baseadas nos seus vídeos."}
              </h3>
              <p>
                {dashboard.data.latest_insight
                  ? `Gerado em ${formatDateTime(dashboard.data.latest_insight.created_at)}`
                  : "Os insights usam visualizações e interações das publicações."}
              </p>
            </div>
            <Link
              className="secondary-button"
              href={
                dashboard.data.latest_insight
                  ? `/projects/${dashboard.data.latest_insight.project_id}?tab=desempenho`
                  : "/performance"
              }
            >
              {dashboard.data.latest_insight ? "Criar experimento" : "Ver desempenho"}
            </Link>
          </section>
        </>
      )}

      <footer><ShieldCheck size={15} /> Nenhum conteúdo é publicado sem sua aprovação.</footer>
    </>
  );
}
