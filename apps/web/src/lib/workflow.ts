import type { WorkflowStep } from "@/components/ui";

import type { Overview } from "./api";

type WorkflowInput = {
  hasBrief: boolean;
  hasScript: boolean;
  scriptApproved: boolean;
  renderStatus: string | null;
  publishApproved: boolean;
  published: boolean;
};

export function workflow(input: WorkflowInput): WorkflowStep[] {
  const rendered = input.renderStatus === "completed";
  const rendering = input.renderStatus === "queued" || input.renderStatus === "processing";
  const states: WorkflowStep["state"][] = [
    input.hasBrief ? "done" : "active",
    input.hasScript && input.scriptApproved ? "done" : input.hasBrief ? "active" : "todo",
    rendered ? "done" : input.scriptApproved ? "active" : "todo",
    input.publishApproved && rendered ? "done" : rendered ? "active" : "todo",
    input.published ? "done" : input.publishApproved && rendered ? "active" : "todo",
  ];
  const productionDetail =
    input.renderStatus === "failed" ? "Falhou — tente novamente" : rendering ? "Narração e cenas" : "Voz, cenas e legendas";
  return [
    { label: "Briefing", detail: "Tema e audiência", state: states[0] },
    { label: "Roteiro", detail: input.hasScript && !input.scriptApproved ? "Aguardando revisão" : "Fontes e narrativa", state: states[1] },
    { label: "Produção", detail: productionDetail, state: states[2] },
    { label: "Aprovação", detail: "Revisão humana da prévia", state: states[3] },
    { label: "Publicação", detail: "TikTok e YouTube", state: states[4] },
  ];
}

export function scriptApproved(overview: Overview): boolean {
  const script = overview.latest_script;
  return Boolean(
    script && overview.approvals.some((item) => item.gate === "script" && item.target_id === script.id && item.approved),
  );
}

export function publishApproved(overview: Overview): boolean {
  const render = overview.latest_render;
  return Boolean(
    render && overview.approvals.some((item) => item.gate === "publish" && item.target_id === render.id && item.approved),
  );
}

export function overviewWorkflow(overview: Overview): WorkflowStep[] {
  return workflow({
    hasBrief: Boolean(overview.brief),
    hasScript: Boolean(overview.latest_script),
    scriptApproved: scriptApproved(overview),
    renderStatus: overview.latest_render?.status ?? null,
    publishApproved: publishApproved(overview),
    published: overview.publications.some((item) => item.status === "published"),
  });
}
