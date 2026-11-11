"use client";

import { Plus, Search } from "lucide-react";
import { use, useState } from "react";

import { useOpenComposer } from "@/components/AppShell";
import { ProjectCard } from "@/components/ProjectCard";
import { useSession } from "@/components/Session";
import { EmptyState, ErrorNotice, Loading } from "@/components/ui";
import { api } from "@/lib/api";
import { STATUS } from "@/lib/format";
import { useResource } from "@/lib/hooks";

const FILTERS = ["", "draft", "review", "processing", "approved", "published", "failed"];

export default function ProjectsPage({ searchParams }: { searchParams: Promise<{ oauth_error?: string }> }) {
  const { oauth_error: oauthError } = use(searchParams);
  const { me, canEdit } = useSession();
  const openComposer = useOpenComposer();
  const [status, setStatus] = useState("");
  const [query, setQuery] = useState("");
  const projects = useResource(
    () => api.projects.list({ status, q: query.trim() }),
    `projects:${me.organization.id}:${status}:${query.trim()}`,
  );

  return (
    <>
      <section className="page-head">
        <div>
          <p className="eyebrow">BIBLIOTECA</p>
          <h1 className="page-title">Projetos</h1>
          <p className="hero-copy">Todos os vídeos da organização {me.organization.name}.</p>
        </div>
        {canEdit && <button className="primary-button" onClick={openComposer}><Plus size={18} />Criar novo vídeo</button>}
      </section>

      {oauthError && <div className="notice notice-error">Conexão do canal não concluída: {oauthError}</div>}

      <div className="toolbar">
        <div className="chips">
          {FILTERS.map((item) => (
            <button key={item || "all"} className={`chip ${status === item ? "active" : ""}`} onClick={() => setStatus(item)}>
              {item ? STATUS[item].label : "Todos"}
            </button>
          ))}
        </div>
        <label className="search">
          <Search size={15} />
          <input placeholder="Buscar por nome" value={query} onChange={(event) => setQuery(event.target.value)} />
        </label>
      </div>

      {projects.error && <ErrorNotice error={projects.error} onRetry={projects.reload} />}
      {projects.loading && !projects.data && <Loading />}
      {projects.data &&
        (projects.data.length ? (
          <div className="project-grid">
            {projects.data.map((project) => <ProjectCard key={project.id} project={project} />)}
          </div>
        ) : (
          <EmptyState title="Nenhum projeto encontrado">
            {status || query ? "Ajuste os filtros para ver outros projetos." : "Crie o primeiro vídeo para começar."}
          </EmptyState>
        ))}
    </>
  );
}
