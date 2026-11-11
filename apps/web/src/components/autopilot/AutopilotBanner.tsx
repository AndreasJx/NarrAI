"use client";

import { Bot, Check, Pause, Play, RotateCcw } from "lucide-react";

import { api, type Project } from "@/lib/api";
import { STAGE_LABEL, STAGE_ORDER } from "@/lib/format";
import { useAction, useInterval } from "@/lib/hooks";

import { useSession } from "../Session";
import { useToast } from "../Toast";

const TERMINAL = new Set(["done", "needs_review", "failed", "stopped"]);

export function AutopilotBanner({ project, reload }: { project: Project; reload: () => void }) {
  const { canEdit } = useSession();
  const toast = useToast();
  const { busy, run } = useAction();
  const stage = project.autopilot_stage ?? "";
  const active = project.autopilot && !TERMINAL.has(stage);
  useInterval(reload, active ? 4000 : null);

  const act = (name: string, task: () => Promise<unknown>, message: string) =>
    run(name, async () => {
      try {
        await task();
        toast.success(message);
        reload();
      } catch (error) {
        toast.error(error);
      }
    });

  if (!project.autopilot) {
    if (!canEdit) return null;
    return (
      <div className="autopilot-banner off">
        <Bot size={18} />
        <div>
          <strong>Piloto automático desligado</strong>
          <small>Ative para a IA concluir as etapas restantes sozinha, parando apenas se um portão de qualidade reprovar.</small>
        </div>
        <button className="secondary-button small" disabled={busy !== null} onClick={() => act("enable", () => api.autopilot.enable(project.id), "Piloto automático ativado")}>
          <Play size={14} />Ativar
        </button>
      </div>
    );
  }

  const blockedStage = stage === "needs_review" ? (project.autopilot_reason?.match(/^\[(\w+)\]/)?.[1] ?? "") : "";
  const reached = STAGE_ORDER.indexOf((blockedStage || stage) as (typeof STAGE_ORDER)[number]);
  const canApprove = blockedStage === "script_gate" || blockedStage === "render_gate";

  return (
    <div className={`autopilot-banner ${stage === "needs_review" ? "blocked" : stage === "done" ? "done" : "running"}`}>
      <Bot size={18} />
      <div className="autopilot-body">
        <strong>
          Piloto automático · {STAGE_LABEL[stage] ?? stage}
          {active && <span className="pulse" aria-hidden />}
        </strong>
        <ol className="stage-dots">
          {STAGE_ORDER.map((item, index) => (
            <li
              key={item}
              className={
                stage === "done" || index < reached ? "done" : index === reached ? (blockedStage ? "blocked" : "active") : ""
              }
            >
              {STAGE_LABEL[item]}
            </li>
          ))}
        </ol>
        {stage === "needs_review" && project.autopilot_reason && <small className="error-text">{project.autopilot_reason}</small>}
      </div>
      {canEdit && (
        <div className="panel-actions">
          {stage === "needs_review" && canApprove && (
            <button className="primary-button small" disabled={busy !== null} onClick={() => act("approve", () => api.autopilot.resume(project.id, true), "Aprovado: o piloto automático continua")}>
              <Check size={14} />Aprovar e continuar
            </button>
          )}
          {stage === "needs_review" && (
            <button className="secondary-button small" disabled={busy !== null} onClick={() => act("retry", () => api.autopilot.resume(project.id, false), "Etapa reenviada")}>
              <RotateCcw size={14} />Tentar de novo
            </button>
          )}
          {active && (
            <button className="secondary-button small" disabled={busy !== null} onClick={() => act("stop", () => api.autopilot.stop(project.id), "Piloto automático pausado")}>
              <Pause size={14} />Pausar
            </button>
          )}
        </div>
      )}
    </div>
  );
}
