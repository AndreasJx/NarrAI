"use client";

import Link from "next/link";

import { useSession } from "@/components/Session";
import { EmptyState, ErrorNotice, Loading, Panel, StatusBadge } from "@/components/ui";
import { api, type Project, type ProjectMetrics } from "@/lib/api";
import { compactNumber } from "@/lib/format";
import { useResource } from "@/lib/hooks";

type Row = { project: Project; metrics: ProjectMetrics };

async function loadPerformance(): Promise<Row[]> {
  const projects = await api.projects.list();
  const published = projects.filter((project) => ["published", "publishing"].includes(project.status));
  return Promise.all(published.map(async (project) => ({ project, metrics: await api.projects.metrics(project.id) })));
}

export default function PerformancePage() {
  const { me } = useSession();
  const rows = useResource(loadPerformance, `performance:${me.organization.id}`);
  const totals = (rows.data ?? []).reduce(
    (sum, row) => ({
      views: sum.views + row.metrics.views,
      interactions: sum.interactions + row.metrics.likes + row.metrics.comments + row.metrics.shares,
    }),
    { views: 0, interactions: 0 },
  );

  return (
    <>
      <section className="page-head">
        <div>
          <p className="eyebrow">ANÁLISE</p>
          <h1 className="page-title">Desempenho</h1>
          <p className="hero-copy">Resultados das publicações medidas em todos os projetos.</p>
        </div>
      </section>
      {rows.error && <ErrorNotice error={rows.error} onRetry={rows.reload} />}
      {rows.loading && <Loading />}
      {rows.data && (
        <>
          <section className="stat-grid">
            <div className="stat"><span>Projetos publicados</span><strong>{rows.data.length}</strong></div>
            <div className="stat"><span>Visualizações</span><strong>{compactNumber(totals.views)}</strong></div>
            <div className="stat"><span>Interações</span><strong>{compactNumber(totals.interactions)}</strong></div>
            <div className="stat">
              <span>Engajamento médio</span>
              <strong>{totals.views ? ((totals.interactions / totals.views) * 100).toFixed(1) : "0.0"}%</strong>
            </div>
          </section>
          <Panel title="Por projeto">
            {rows.data.length ? (
              <table className="table">
                <thead><tr><th>Projeto</th><th>Status</th><th>Views</th><th>Curtidas</th><th>Coment.</th><th>Compart.</th><th>Engaj.</th></tr></thead>
                <tbody>
                  {rows.data.map(({ project, metrics }) => (
                    <tr key={project.id}>
                      <td><Link href={`/projects/${project.id}?tab=desempenho`}>{project.name}</Link></td>
                      <td><StatusBadge status={project.status} /></td>
                      <td>{compactNumber(metrics.views)}</td>
                      <td>{compactNumber(metrics.likes)}</td>
                      <td>{compactNumber(metrics.comments)}</td>
                      <td>{compactNumber(metrics.shares)}</td>
                      <td>{(metrics.engagement_rate * 100).toFixed(1)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <EmptyState title="Nenhum projeto publicado">Publique um vídeo e registre métricas para acompanhar o desempenho.</EmptyState>
            )}
          </Panel>
        </>
      )}
    </>
  );
}
