"use client";

import { Check, Clapperboard, Download, RotateCcw, X } from "lucide-react";
import { useState } from "react";

import { api, type Overview, type Render } from "@/lib/api";
import { formatDateTime, newKey, statusInfo } from "@/lib/format";
import { useAction, useResource } from "@/lib/hooks";
import { publishApproved, scriptApproved } from "@/lib/workflow";

import { useSession } from "../Session";
import { useToast } from "../Toast";
import { EmptyState, Panel, ProgressBar, StatusBadge } from "../ui";

type Props = { overview: Overview; reload: () => void; goTo: (tab: string) => void };

export function VideoPlayer({ render }: { render: Render }) {
  const preview = useResource(() => api.renders.preview(render.id), `preview:${render.id}:${render.finished_at}`);
  if (preview.error) return <div className="notice notice-error">{preview.error.message}</div>;
  if (!preview.data) return <div className="phone-frame loading" />;
  if (preview.data.kind !== "video") {
    return (
      <div className="notice">
        O worker não encontrou o FFmpeg e gerou apenas um manifesto da renderização.{" "}
        <a href={preview.data.url} target="_blank" rel="noreferrer">Ver manifesto</a>
      </div>
    );
  }
  return (
    <div className="player">
      <video className="phone-frame" src={preview.data.url} controls playsInline preload="metadata" />
      <a className="text-button" href={preview.data.url} download={`narra-render-${render.id}.mp4`} target="_blank" rel="noreferrer">
        <Download size={14} />Baixar MP4
      </a>
    </div>
  );
}

export function RenderTab({ overview, reload, goTo }: Props) {
  const { canEdit, me } = useSession();
  const toast = useToast();
  const { busy, run } = useAction();
  const [note, setNote] = useState("");
  const pid = overview.project.id;
  const script = overview.latest_script;
  const render = overview.latest_render;
  const ready = scriptApproved(overview);
  const active = render && ["queued", "processing"].includes(render.status);
  const outdated = render && script && render.script_version_id !== script.id;
  const publishApproval = render && overview.approvals.find((item) => item.gate === "publish" && item.target_id === render.id);

  const start = () =>
    run("render", async () => {
      try {
        await api.renders.create(pid, script!.id, newKey("render"));
        toast.success("Renderização iniciada");
        reload();
      } catch (error) {
        toast.error(error);
      }
    });

  const retry = () =>
    run("retry", async () => {
      try {
        await api.renders.retry(render!.id);
        toast.success("Render reenviado para a fila");
        reload();
      } catch (error) {
        toast.error(error);
      }
    });

  const decide = (approved: boolean) =>
    run(approved ? "approve" : "reject", async () => {
      try {
        await api.projects.approve(pid, "publish", render!.id, approved, note);
        toast.success(approved ? "Publicação aprovada" : "Prévia reprovada");
        reload();
        if (approved) goTo("publicacao");
      } catch (error) {
        toast.error(error);
      }
    });

  if (!script || (!ready && !render)) {
    return (
      <Panel>
        <EmptyState title="Aprove o roteiro primeiro" action={<button className="secondary-button" onClick={() => goTo("roteiro")}>Revisar roteiro</button>}>
          A narração e o vídeo só são produzidos a partir de uma versão aprovada do roteiro.
        </EmptyState>
      </Panel>
    );
  }

  return (
    <div className="tab-grid wide-left">
      <Panel
        title="Renderização"
        description={`Narração Kokoro com a voz ${me.organization.voice}, vídeo vertical 1080×1920 com legendas.`}
        actions={
          canEdit &&
          !active && (
            <button
              className="primary-button small"
              disabled={busy !== null || !ready}
              title={ready ? undefined : `Aprove a versão ${script.version} do roteiro para renderizar`}
              onClick={start}
            >
              <Clapperboard size={14} />{busy === "render" ? "Enviando…" : render ? "Renderizar novamente" : "Renderizar vídeo"}
            </button>
          )
        }
      >
        {!render && <EmptyState title="Nenhum render ainda">Clique em “Renderizar vídeo” para produzir a prévia.</EmptyState>}
        {render && (
          <div className="render-detail">
            <div className="render-line">
              <StatusBadge status={render.status} />
              <span className="muted">
                Render #{render.id} · roteiro v{overview.scripts.find((item) => item.id === render.script_version_id)?.version ?? "?"} ·
                tentativa {render.attempts || 1} · {formatDateTime(render.created_at)}
              </span>
            </div>
            {(active || render.status === "failed") && (
              <div className="render-progress-row">
                <ProgressBar value={render.progress} />
                <span>{render.progress}%</span>
              </div>
            )}
            {active && <p className="muted">{render.status === "queued" ? "Aguardando o worker…" : "Sintetizando narração e compondo cenas…"}</p>}
            {render.error && <div className={`notice ${render.status === "failed" ? "notice-error" : ""}`}>{render.error}</div>}
            {render.status === "failed" && canEdit && (
              <button className="secondary-button small" disabled={busy !== null} onClick={retry}>
                <RotateCcw size={14} />Tentar novamente
              </button>
            )}
            {outdated && render.status === "completed" && (
              <div className="notice">Este render usa uma versão anterior do roteiro. Renderize novamente para refletir a versão {script.version}.</div>
            )}
            {render.status === "completed" && <VideoPlayer render={render} />}
          </div>
        )}
      </Panel>

      <Panel title="Aprovação da prévia" description="Assista à prévia completa antes de liberar a publicação.">
        {!render || render.status !== "completed" ? (
          <p className="muted">Disponível quando o render for concluído.</p>
        ) : (
          <>
            {publishApproval && (
              <div className={`notice ${publishApproval.approved ? "" : "notice-error"}`}>
                {publishApproval.approved ? "Aprovado" : "Reprovado"} por {publishApproval.actor} em {formatDateTime(publishApproval.created_at)}
              </div>
            )}
            {canEdit && (
              <div className="form">
                <label>
                  Observação (opcional)
                  <input value={note} onChange={(event) => setNote(event.target.value)} />
                </label>
                <div className="form-actions">
                  <button className="secondary-button" disabled={busy !== null} onClick={() => decide(false)}>
                    <X size={15} />Reprovar
                  </button>
                  <button className="primary-button" disabled={busy !== null} onClick={() => decide(true)}>
                    <Check size={15} />{publishApproved(overview) ? "Aprovado" : "Aprovar publicação"}
                  </button>
                </div>
              </div>
            )}
          </>
        )}
        <p className="muted small-print">Status do projeto: {statusInfo(overview.project.status).label}</p>
      </Panel>
    </div>
  );
}
