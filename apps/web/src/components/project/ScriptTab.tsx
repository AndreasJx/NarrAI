"use client";

import { Check, Save, X } from "lucide-react";
import { useState } from "react";

import { api, type Overview } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { useAction } from "@/lib/hooks";

import { useSession } from "../Session";
import { useToast } from "../Toast";
import { EmptyState, Panel } from "../ui";

type Props = { overview: Overview; reload: () => void; goTo: (tab: string) => void };

export function ScriptTab({ overview, reload, goTo }: Props) {
  const latest = overview.latest_script;
  if (!latest) {
    return (
      <Panel>
        <EmptyState
          title="Nenhum roteiro gerado"
          action={<button className="secondary-button" onClick={() => goTo("briefing")}>Ir para o briefing</button>}
        >
          Gere o roteiro a partir do briefing.
        </EmptyState>
      </Panel>
    );
  }
  return <ScriptEditor key={latest.id} overview={overview} reload={reload} goTo={goTo} />;
}

function ScriptEditor({ overview, reload, goTo }: Props) {
  const { canEdit } = useSession();
  const toast = useToast();
  const { busy, run } = useAction();
  const latest = overview.latest_script!;
  const pid = overview.project.id;
  const [selectedId, setSelectedId] = useState(latest.id);
  const [content, setContent] = useState(latest.content);
  const [note, setNote] = useState("");
  const selected = overview.scripts.find((script) => script.id === selectedId) ?? latest;
  const isLatest = selected.id === latest.id;
  const approval = overview.approvals.find((item) => item.gate === "script" && item.target_id === latest.id);
  const dirty = content.trim() !== latest.content.trim();

  const saveVersion = () =>
    run("save", async () => {
      try {
        const script = await api.projects.editScript(pid, latest.id, content);
        toast.success(`Versão ${script.version} salva`);
        reload();
      } catch (error) {
        toast.error(error);
      }
    });

  const decide = (approved: boolean) =>
    run(approved ? "approve" : "reject", async () => {
      try {
        await api.projects.approve(pid, "script", latest.id, approved, note);
        toast.success(approved ? "Roteiro aprovado" : "Roteiro devolvido para ajustes");
        reload();
        if (approved) goTo("storyboard");
      } catch (error) {
        toast.error(error);
      }
    });

  return (
    <div className="tab-grid wide-left">
      <Panel
        title={`Roteiro · versão ${selected.version}`}
        description={`Por ${selected.author} em ${formatDateTime(selected.created_at)}. Cada linha vira uma cena.`}
      >
        {isLatest ? (
          <>
            <textarea
              className="script-editor"
              value={content}
              onChange={(event) => setContent(event.target.value)}
              disabled={!canEdit}
              rows={14}
            />
            <div className="form-actions">
              <span className="muted">{content.split("\n").filter((line) => line.trim()).length} cenas · {content.split(/\s+/).filter(Boolean).length} palavras</span>
              {canEdit && (
                <>
                  <button className="secondary-button" disabled={!dirty || busy !== null} onClick={() => setContent(latest.content)}>
                    Descartar
                  </button>
                  <button className="primary-button" disabled={!dirty || busy !== null || content.trim().length < 2} onClick={saveVersion}>
                    <Save size={15} />{busy === "save" ? "Salvando…" : "Salvar como nova versão"}
                  </button>
                </>
              )}
            </div>
          </>
        ) : (
          <pre className="script-view">{selected.content}</pre>
        )}
      </Panel>

      <div className="stack">
        <Panel title="Aprovação editorial" description="A renderização só começa depois que um humano aprova o roteiro.">
          {approval && (
            <div className={`notice ${approval.approved ? "" : "notice-error"}`}>
              {approval.approved ? "Aprovado" : "Reprovado"} por {approval.actor} em {formatDateTime(approval.created_at)}
              {approval.note && <><br />“{approval.note}”</>}
            </div>
          )}
          {canEdit && (
            <div className="form">
              <label>
                Observação (opcional)
                <input value={note} onChange={(event) => setNote(event.target.value)} placeholder="Ex.: conferi as fontes" />
              </label>
              {dirty && <small className="muted">Salve as alterações antes de aprovar.</small>}
              <div className="form-actions">
                <button className="secondary-button" disabled={busy !== null || dirty} onClick={() => decide(false)}>
                  <X size={15} />Reprovar
                </button>
                <button className="primary-button" disabled={busy !== null || dirty} onClick={() => decide(true)}>
                  <Check size={15} />{busy === "approve" ? "Aprovando…" : `Aprovar versão ${latest.version}`}
                </button>
              </div>
            </div>
          )}
        </Panel>

        <Panel title="Versões">
          <ul className="version-list">
            {overview.scripts.map((script) => (
              <li key={script.id}>
                <button className={script.id === selected.id ? "active" : ""} onClick={() => setSelectedId(script.id)}>
                  <strong>v{script.version}</strong>
                  <span>{script.author}</span>
                  <small>{formatDateTime(script.created_at)}</small>
                  {overview.approvals.some((item) => item.gate === "script" && item.target_id === script.id && item.approved) && (
                    <Check size={14} />
                  )}
                </button>
              </li>
            ))}
          </ul>
        </Panel>
      </div>
    </div>
  );
}
