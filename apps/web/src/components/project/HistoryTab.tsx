"use client";

import { api } from "@/lib/api";
import { formatDateTime, statusInfo } from "@/lib/format";
import { useResource } from "@/lib/hooks";

import { ErrorNotice, Loading, Panel } from "../ui";

const ACTIONS: Record<string, string> = {
  "project.created": "Projeto criado",
  "project.updated": "Projeto atualizado",
  "project.status_changed": "Status alterado",
  "brief.saved": "Briefing salvo",
  "research.generated": "Pesquisa gerada",
  "script.generated": "Roteiro gerado",
  "script.edited": "Roteiro editado",
  "storyboard.generated": "Storyboard gerado",
  "scene.updated": "Cena atualizada",
  "approval.set": "Aprovação registrada",
  "upload.requested": "Upload iniciado",
  "upload.completed": "Upload concluído",
  "upload.rejected": "Upload rejeitado",
  "asset.deleted": "Mídia removida",
  "render.queued": "Render enfileirado",
  "render.retried": "Render reenviado",
  "render.completed": "Render concluído",
  "render.failed": "Render falhou",
  "connection.created": "Canal conectado",
  "connection.disabled": "Canal desconectado",
  "oauth.connected": "OAuth autorizado",
  "publication.requested": "Publicação solicitada",
  "publication.completed": "Publicação concluída",
  "publication.failed": "Publicação falhou",
  "publication.cancelled": "Agendamento cancelado",
  "publication.reconciled": "Status da publicação atualizado",
  "metrics.captured": "Métricas registradas",
  "insight.generated": "Insight gerado",
  "experiment.created": "Experimento criado",
};

function describe(action: string, payload: Record<string, unknown>): string {
  if (action === "project.status_changed") {
    return `${statusInfo(String(payload.previous)).label} → ${statusInfo(String(payload.current)).label}${payload.reason ? ` (${payload.reason})` : ""}`;
  }
  if (action === "approval.set") return `${payload.gate}: ${payload.approved ? "aprovado" : "reprovado"}`;
  if (typeof payload.cost_cents === "number" && payload.cost_cents) return `custo R$ ${(payload.cost_cents / 100).toFixed(2)}`;
  if (payload.error) return String(payload.error);
  return "";
}

export function HistoryTab({ projectId }: { projectId: number }) {
  const audit = useResource(() => api.projects.audit(projectId), `audit:${projectId}`);
  return (
    <Panel title="Histórico de auditoria" description="Toda ação registra quem fez, quando e o que mudou.">
      {audit.error && <ErrorNotice error={audit.error} onRetry={audit.reload} />}
      {audit.loading && <Loading />}
      {audit.data && (
        <ol className="timeline">
          {audit.data.map((event) => (
            <li key={event.id}>
              <strong>{ACTIONS[event.action] ?? event.action}</strong>
              <span>{describe(event.action, event.payload)}</span>
              <small>{event.actor} · {formatDateTime(event.created_at)}</small>
            </li>
          ))}
        </ol>
      )}
    </Panel>
  );
}
