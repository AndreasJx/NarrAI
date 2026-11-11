"use client";

import { BookOpen, Search } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { useSession } from "@/components/Session";
import { EmptyState, ErrorNotice, Loading, Panel } from "@/components/ui";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { useResource } from "@/lib/hooks";

export default function SourcesPage() {
  const { me } = useSession();
  const sources = useResource(api.sources, `sources:${me.organization.id}`);
  const [query, setQuery] = useState("");
  const term = query.trim().toLowerCase();
  const filtered = (sources.data ?? []).filter(
    (source) => !term || source.title.toLowerCase().includes(term) || source.summary.toLowerCase().includes(term),
  );

  return (
    <>
      <section className="page-head">
        <div>
          <p className="eyebrow">BIBLIOTECA</p>
          <h1 className="page-title">Fontes</h1>
          <p className="hero-copy">Pesquisas e referências usadas nos roteiros da organização.</p>
        </div>
      </section>
      <div className="toolbar">
        <span className="muted">{filtered.length} fontes</span>
        <label className="search">
          <Search size={15} />
          <input placeholder="Buscar nas fontes" value={query} onChange={(event) => setQuery(event.target.value)} />
        </label>
      </div>
      {sources.error && <ErrorNotice error={sources.error} onRetry={sources.reload} />}
      {sources.loading && <Loading />}
      {sources.data && (
        <Panel>
          {filtered.length ? (
            <ul className="source-list">
              {filtered.map((source) => (
                <li key={source.id}>
                  <BookOpen size={16} />
                  <div>
                    <strong>{source.title}</strong>
                    <p>{source.summary}</p>
                    <small>
                      <Link href={`/projects/${source.project_id}?tab=briefing`}>Projeto #{source.project_id}</Link> · {source.provider} ·{" "}
                      {formatDateTime(source.created_at)}
                      {source.url && (
                        <> · <a href={source.url} target="_blank" rel="noreferrer">abrir referência</a></>
                      )}
                    </small>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState title="Nenhuma fonte encontrada">As pesquisas geradas nos projetos aparecem aqui.</EmptyState>
          )}
        </Panel>
      )}
    </>
  );
}
