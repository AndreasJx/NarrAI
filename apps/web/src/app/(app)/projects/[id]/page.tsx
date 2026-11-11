"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { use } from "react";

import { AutopilotBanner } from "@/components/autopilot/AutopilotBanner";
import { BriefTab } from "@/components/project/BriefTab";
import { HistoryTab } from "@/components/project/HistoryTab";
import { PerformanceTab } from "@/components/project/PerformanceTab";
import { PublishTab } from "@/components/project/PublishTab";
import { RenderTab } from "@/components/project/RenderTab";
import { ScriptTab } from "@/components/project/ScriptTab";
import { StoryboardTab } from "@/components/project/StoryboardTab";
import { ErrorNotice, Loading, StatusBadge, Workflow } from "@/components/ui";
import { api, type Overview } from "@/lib/api";
import { money } from "@/lib/format";
import { useInterval, useResource } from "@/lib/hooks";
import { overviewWorkflow, publishApproved, scriptApproved } from "@/lib/workflow";

const TABS = [
  { id: "briefing", label: "Briefing" },
  { id: "roteiro", label: "Roteiro" },
  { id: "storyboard", label: "Storyboard" },
  { id: "render", label: "Render e prévia" },
  { id: "publicacao", label: "Publicação" },
  { id: "desempenho", label: "Desempenho" },
  { id: "historico", label: "Histórico" },
];

function defaultTab(overview: Overview): string {
  if (!overview.brief) return "briefing";
  if (!overview.latest_script || !scriptApproved(overview)) return "roteiro";
  if (!overview.latest_render) return "storyboard";
  if (overview.latest_render.status !== "completed" || !publishApproved(overview)) return "render";
  if (!overview.publications.length) return "publicacao";
  return "desempenho";
}

export default function ProjectPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ tab?: string; connected?: string }>;
}) {
  const { id } = use(params);
  const { tab: requestedTab, connected } = use(searchParams);
  const router = useRouter();
  const projectId = Number(id);
  const overview = useResource(() => api.projects.overview(projectId), `overview:${projectId}`);
  const data = overview.data;
  const rendering = data?.latest_render && ["queued", "processing"].includes(data.latest_render.status);
  const scheduled = data?.publications.some((item) => item.status === "scheduled");
  useInterval(overview.reload, rendering ? 2000 : scheduled ? 15000 : null);

  if (overview.error && !data) {
    return (
      <>
        <Link className="back-link" href="/projects"><ArrowLeft size={15} />Projetos</Link>
        <ErrorNotice error={overview.error} onRetry={overview.reload} />
      </>
    );
  }
  if (!data) return <Loading label="Carregando projeto" />;

  const tab = TABS.some((item) => item.id === requestedTab) ? requestedTab! : defaultTab(data);
  const goTo = (next: string) => router.replace(`/projects/${projectId}?tab=${next}`, { scroll: false });
  const props = { overview: data, reload: overview.reload, goTo };
  const budgetUsed = data.project.budget_cents ? Math.round((data.project.spent_cents / data.project.budget_cents) * 100) : 0;

  return (
    <>
      <Link className="back-link" href="/projects"><ArrowLeft size={15} />Projetos</Link>
      <section className="page-head">
        <div>
          <p className="eyebrow">PROJETO #{data.project.id}</p>
          <h1 className="page-title">{data.project.name}</h1>
          <div className="meta-row">
            <StatusBadge status={data.project.status} />
            <span>Orçamento: {money(data.project.spent_cents)} de {money(data.project.budget_cents)} ({budgetUsed}%)</span>
          </div>
        </div>
      </section>

      <AutopilotBanner project={data.project} reload={overview.reload} />

      <section className="workflow-card">
        <Workflow steps={overviewWorkflow(data)} />
      </section>

      <nav className="tabs" aria-label="Etapas do projeto">
        {TABS.map((item) => (
          <button key={item.id} className={item.id === tab ? "active" : ""} onClick={() => goTo(item.id)}>
            {item.label}
          </button>
        ))}
      </nav>

      <div className="tab-content">
        {tab === "briefing" && <BriefTab key={data.brief?.id ?? "new"} {...props} />}
        {tab === "roteiro" && <ScriptTab {...props} />}
        {tab === "storyboard" && <StoryboardTab {...props} />}
        {tab === "render" && <RenderTab {...props} />}
        {tab === "publicacao" && <PublishTab {...props} connected={connected} />}
        {tab === "desempenho" && <PerformanceTab overview={data} />}
        {tab === "historico" && <HistoryTab projectId={projectId} />}
      </div>
    </>
  );
}
