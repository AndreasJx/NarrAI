"use client";

import { ExternalLink, Link2, Play, RefreshCw, Send, Unplug, X } from "lucide-react";
import { useState, type FormEvent } from "react";

import { api, type Connection, type Overview, type Platform } from "@/lib/api";
import { formatDateTime, newKey, PLATFORM_LABEL } from "@/lib/format";
import { useAction, useResource } from "@/lib/hooks";
import { publishApproved } from "@/lib/workflow";

import { useSession } from "../Session";
import { useToast } from "../Toast";
import { EmptyState, Panel, StatusBadge } from "../ui";

type Props = { overview: Overview; reload: () => void; goTo: (tab: string) => void; connected?: string };

export function PublishTab({ overview, reload, goTo, connected }: Props) {
  const { canEdit } = useSession();
  const toast = useToast();
  const { busy, run } = useAction();
  const platforms = useResource(api.channels.platforms, "platforms");
  const pid = overview.project.id;
  const render = overview.latest_render;
  const rendered = render?.status === "completed";
  const approved = publishApproved(overview);
  const active = overview.connections.filter((item) => item.enabled);

  const action = (name: string, task: () => Promise<unknown>, message: string) =>
    run(name, async () => {
      try {
        await task();
        toast.success(message);
        reload();
      } catch (error) {
        toast.error(error);
      }
    });

  const connectOAuth = (platform: string) =>
    run(`oauth-${platform}`, async () => {
      try {
        const { authorization_url } = await api.channels.authorize(platform, pid);
        window.location.assign(authorization_url);
      } catch (error) {
        toast.error(error);
      }
    });

  return (
    <div className="stack">
      {connected && <div className="notice">Canal {PLATFORM_LABEL[connected] ?? connected} conectado via OAuth.</div>}
      <div className="tab-grid">
        <Panel title="Canais" description="Conecte via OAuth para publicar de verdade ou use o modo simulado para testar o fluxo.">
          {platforms.data?.map((platform) => (
            <ChannelRow
              key={platform.id}
              platform={platform}
              connections={active.filter((item) => item.platform === platform.id)}
              canEdit={canEdit}
              busy={busy}
              onOAuth={() => connectOAuth(platform.id)}
              onSimulated={() =>
                action(
                  `sim-${platform.id}`,
                  () => api.channels.create(pid, platform.id, `${platform.id}-simulado-${active.length + 1}`),
                  "Canal simulado conectado",
                )
              }
              onDisable={(connection) => action(`off-${connection.id}`, () => api.channels.disable(connection.id), "Canal desconectado")}
            />
          ))}
        </Panel>

        <Panel title="Publicar">
          <ul className="checklist">
            <li className={rendered ? "ok" : ""}>Render concluído {!rendered && <button className="text-button" onClick={() => goTo("render")}>ir para render</button>}</li>
            <li className={approved ? "ok" : ""}>Publicação aprovada por um humano</li>
            <li className={active.length ? "ok" : ""}>Canal conectado</li>
          </ul>
          {rendered && approved && active.length > 0 && canEdit ? (
            <PublishForm overview={overview} connections={active} platforms={platforms.data ?? []} onDone={reload} />
          ) : (
            <p className="muted">Conclua os itens acima para liberar a publicação.</p>
          )}
        </Panel>
      </div>

      <Panel title="Publicações">
        {overview.publications.length ? (
          <table className="table">
            <thead>
              <tr><th>Título</th><th>Canal</th><th>Status</th><th>Quando</th><th /></tr>
            </thead>
            <tbody>
              {overview.publications.map((publication) => {
                const connection = overview.connections.find((item) => item.id === publication.connection_id);
                return (
                  <tr key={publication.id}>
                    <td>
                      <strong>{publication.title}</strong>
                      {publication.error && <small className="error-text">{publication.error}</small>}
                    </td>
                    <td>
                      {PLATFORM_LABEL[connection?.platform ?? ""] ?? connection?.platform}
                      <small>{publication.simulated ? "simulada" : "real"}</small>
                    </td>
                    <td><StatusBadge status={publication.status} /></td>
                    <td>{formatDateTime(publication.published_at ?? publication.scheduled_at ?? publication.created_at)}</td>
                    <td className="row-actions">
                      {publication.url && (
                        <a className="icon-button" href={publication.url} target="_blank" rel="noreferrer" aria-label="Abrir publicação">
                          <ExternalLink size={14} />
                        </a>
                      )}
                      {canEdit && ["scheduled", "failed"].includes(publication.status) && (
                        <button
                          className="icon-button"
                          disabled={busy !== null}
                          aria-label="Publicar agora"
                          onClick={() => action(`run-${publication.id}`, () => api.publications.run(publication.id), "Publicação executada")}
                        >
                          <Play size={14} />
                        </button>
                      )}
                      {canEdit && publication.status === "scheduled" && (
                        <button
                          className="icon-button"
                          disabled={busy !== null}
                          aria-label="Cancelar agendamento"
                          onClick={() => action(`cancel-${publication.id}`, () => api.publications.cancel(publication.id), "Agendamento cancelado")}
                        >
                          <X size={14} />
                        </button>
                      )}
                      {canEdit && !publication.simulated && publication.status === "processing" && (
                        <button
                          className="icon-button"
                          disabled={busy !== null}
                          aria-label="Consultar status"
                          onClick={() => action(`rec-${publication.id}`, () => api.publications.reconcile(publication.id), "Status atualizado")}
                        >
                          <RefreshCw size={14} />
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          <EmptyState title="Nenhuma publicação">As publicações e agendamentos deste projeto aparecem aqui.</EmptyState>
        )}
      </Panel>
    </div>
  );
}

function ChannelRow({
  platform,
  connections,
  canEdit,
  busy,
  onOAuth,
  onSimulated,
  onDisable,
}: {
  platform: Platform;
  connections: Connection[];
  canEdit: boolean;
  busy: string | null;
  onOAuth: () => void;
  onSimulated: () => void;
  onDisable: (connection: Connection) => void;
}) {
  return (
    <div className="channel-row">
      <div className="channel-head">
        <strong>{platform.label}</strong>
        {canEdit && (
          <div className="channel-actions">
            {platform.id !== "local" && (
              <button
                className="secondary-button small"
                disabled={!platform.oauth_configured || busy !== null}
                title={platform.oauth_configured ? undefined : "Defina as credenciais OAuth no .env da API"}
                onClick={onOAuth}
              >
                <Link2 size={14} />OAuth
              </button>
            )}
            <button className="secondary-button small" disabled={busy !== null} onClick={onSimulated}>
              {platform.id === "local" ? "Ativar" : "Simulado"}
            </button>
          </div>
        )}
      </div>
      {connections.map((connection) => (
        <div className="channel-connection" key={connection.id}>
          <span className={`dot ${connection.authorized ? "ok" : ""}`} />
          <span>{connection.external_account_id}</span>
          <small>{connection.authorized ? "OAuth autorizado" : "simulado"}</small>
          {canEdit && (
            <button className="icon-button" onClick={() => onDisable(connection)} aria-label="Desconectar">
              <Unplug size={13} />
            </button>
          )}
        </div>
      ))}
    </div>
  );
}

function PublishForm({
  overview,
  connections,
  platforms,
  onDone,
}: {
  overview: Overview;
  connections: Connection[];
  platforms: Platform[];
  onDone: () => void;
}) {
  const toast = useToast();
  const { busy, run } = useAction();
  const [connectionId, setConnectionId] = useState(connections[0].id);
  const [title, setTitle] = useState(overview.project.name);
  const [description, setDescription] = useState(overview.brief?.objective ?? "");
  const [live, setLive] = useState(false);
  const [schedule, setSchedule] = useState("");
  const connection = connections.find((item) => item.id === connectionId) ?? connections[0];
  const platform = platforms.find((item) => item.id === connection.platform);
  const liveAllowed = Boolean(platform?.live_enabled && connection.authorized);

  async function submit(event: FormEvent) {
    event.preventDefault();
    await run("publish", async () => {
      try {
        const publication = await api.publications.create(overview.project.id, {
          render_id: overview.latest_render!.id,
          connection_id: connection.id,
          title,
          description,
          idempotency_key: newKey("publish"),
          live: live && liveAllowed,
          scheduled_at: schedule ? new Date(schedule).toISOString() : null,
        });
        toast.success(publication.status === "scheduled" ? "Publicação agendada" : "Publicação enviada");
        setSchedule("");
        onDone();
      } catch (error) {
        toast.error(error);
      }
    });
  }

  return (
    <form className="form" onSubmit={submit}>
      <label>
        Canal
        <select value={connection.id} onChange={(event) => setConnectionId(Number(event.target.value))}>
          {connections.map((item) => (
            <option key={item.id} value={item.id}>
              {PLATFORM_LABEL[item.platform]} · {item.external_account_id}
            </option>
          ))}
        </select>
      </label>
      <label>
        Título
        <input required maxLength={300} value={title} onChange={(event) => setTitle(event.target.value)} />
      </label>
      <label>
        Descrição
        <textarea rows={3} value={description} onChange={(event) => setDescription(event.target.value)} />
      </label>
      <label>
        Agendar para (opcional)
        <input type="datetime-local" value={schedule} onChange={(event) => setSchedule(event.target.value)} />
      </label>
      <label className="checkbox">
        <input type="checkbox" checked={live && liveAllowed} disabled={!liveAllowed} onChange={(event) => setLive(event.target.checked)} />
        Publicar de verdade na plataforma
        {!liveAllowed && (
          <small>
            {connection.authorized ? "Publicação real desativada (ALLOW_LIVE_PUBLISH=false)." : "Requer canal conectado via OAuth."}
          </small>
        )}
      </label>
      <button className="primary-button" disabled={busy !== null || !title.trim()}>
        <Send size={15} />{busy ? "Enviando…" : schedule ? "Agendar" : live && liveAllowed ? "Publicar agora" : "Publicar (simulado)"}
      </button>
    </form>
  );
}
