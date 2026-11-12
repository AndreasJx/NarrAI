"use client";

import { Copy, ExternalLink, Link2, Save, Trash2, Unplug } from "lucide-react";
import { useState, type FormEvent } from "react";

import { api, type ChannelAccount, type PlatformCredential } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { useAction, useResource } from "@/lib/hooks";

import { useSession } from "../Session";
import { useToast } from "../Toast";
import { ErrorNotice, Loading, Panel } from "../ui";

const SOURCE_LABEL: Record<PlatformCredential["source"], string> = {
  organization: "App da organização",
  env: "Usando o .env do servidor",
  none: "Não configurado",
};
const SOURCE_BADGE: Record<PlatformCredential["source"], string> = {
  organization: "badge-green",
  env: "badge-blue",
  none: "badge-neutral",
};

export function PlatformsPanel({ organizationId }: { organizationId: number }) {
  const credentials = useResource(api.channels.credentials, `platform-credentials:${organizationId}`);
  const accounts = useResource(api.channels.accounts, `channel-accounts:${organizationId}`);

  return (
    <Panel
      title="Plataformas de publicação"
      description="Cadastre aqui o app OAuth de cada plataforma e conecte os canais uma única vez: todos os projetos e o piloto automático passam a usá-los, sem editar o .env."
    >
      {credentials.error && <ErrorNotice error={credentials.error} onRetry={credentials.reload} />}
      {accounts.error && <ErrorNotice error={accounts.error} onRetry={accounts.reload} />}
      {credentials.data ? (
        credentials.data.map((credential) => (
          <PlatformRow
            key={credential.platform}
            credential={credential}
            accounts={(accounts.data ?? []).filter((item) => item.platform === credential.platform)}
            onSaved={() => {
              credentials.reload();
              accounts.reload();
            }}
          />
        ))
      ) : (
        <Loading />
      )}
    </Panel>
  );
}

function PlatformRow({
  credential,
  accounts,
  onSaved,
}: {
  credential: PlatformCredential;
  accounts: ChannelAccount[];
  onSaved: () => void;
}) {
  const { isOwner, canEdit } = useSession();
  const toast = useToast();
  const { busy, run } = useAction();
  const ownApp = credential.source === "organization";
  const [form, setForm] = useState({
    clientId: ownApp ? credential.client_id : "",
    secret: "",
    live: credential.live_enabled,
  });

  const action = (name: string, task: () => Promise<unknown>, message: string) =>
    run(name, async () => {
      try {
        await task();
        toast.success(message);
        onSaved();
      } catch (error) {
        toast.error(error);
      }
    });

  const save = (event: FormEvent) => {
    event.preventDefault();
    action(
      "save",
      async () => {
        await api.channels.saveCredentials(credential.platform, {
          client_id: form.clientId.trim(),
          client_secret: form.secret.trim() || undefined,
          live_enabled: form.live,
        });
        setForm((current) => ({ ...current, secret: "" }));
      },
      `${credential.label}: credenciais salvas`,
    );
  };

  const connect = () =>
    run("connect", async () => {
      try {
        const { authorization_url } = await api.channels.authorize(credential.platform);
        window.location.assign(authorization_url);
      } catch (error) {
        toast.error(error);
      }
    });

  const copyRedirect = async () => {
    try {
      await navigator.clipboard.writeText(credential.redirect_uri);
      toast.success("URI de redirecionamento copiada");
    } catch {
      toast.error(new Error("Não foi possível copiar; selecione o texto manualmente."));
    }
  };

  return (
    <div className="channel-row">
      <div className="channel-head">
        <strong>{credential.label}</strong>
        <span className={`badge ${SOURCE_BADGE[credential.source]}`}><i />{SOURCE_LABEL[credential.source]}</span>
      </div>

      <dl className="details" style={{ marginTop: 10 }}>
        <dt>URI de retorno</dt>
        <dd>
          <code>{credential.redirect_uri}</code>
          <button type="button" className="text-button" onClick={copyRedirect}><Copy size={12} />copiar</button>
          <a className="text-button" href={credential.console_url} target="_blank" rel="noreferrer">
            <ExternalLink size={12} />abrir console
          </a>
        </dd>
        {credential.source !== "none" && (
          <>
            <dt>Client ID</dt>
            <dd>{credential.client_id}</dd>
          </>
        )}
        <dt>Publicação real</dt>
        <dd>
          {credential.live_forced_by_env
            ? "Liberada para todas as plataformas (ALLOW_LIVE_PUBLISH=true no servidor)"
            : credential.live_enabled
              ? "Liberada"
              : "Somente simulada"}
        </dd>
      </dl>

      {isOwner && (
        <form className="form" onSubmit={save} style={{ marginTop: 12 }}>
          <div className="form-row">
            <label>
              Client ID
              <input
                required
                value={form.clientId}
                onChange={(event) => setForm({ ...form, clientId: event.target.value })}
              />
            </label>
            <label>
              Client secret
              <input
                type="password"
                autoComplete="new-password"
                value={form.secret}
                placeholder={ownApp ? "Salvo e criptografado; preencha só para trocar" : ""}
                onChange={(event) => setForm({ ...form, secret: event.target.value })}
              />
            </label>
          </div>
          <label className="checkbox">
            <input type="checkbox" checked={form.live} onChange={(event) => setForm({ ...form, live: event.target.checked })} />
            Permitir publicação real nesta plataforma
            <small>Sem isso, as publicações ficam no modo simulado, mesmo com o canal conectado.</small>
          </label>
          <div className="form-actions">
            {ownApp && (
              <button
                type="button"
                className="secondary-button small"
                disabled={busy !== null}
                onClick={() => action("remove", () => api.channels.removeCredentials(credential.platform), "Credenciais removidas")}
              >
                <Trash2 size={14} />Remover app
              </button>
            )}
            <button className="primary-button" disabled={busy !== null || !form.clientId.trim()}>
              <Save size={15} />{busy === "save" ? "Salvando…" : "Salvar"}
            </button>
          </div>
        </form>
      )}

      <div style={{ marginTop: 12 }}>
        {accounts.map((account) => (
          <div className="channel-connection" key={account.id}>
            <span className={`dot ${account.authorized ? "ok" : ""}`} />
            <span>
              <strong>{account.display_name || account.external_account_id}</strong>
              {account.display_name && <small> · {account.external_account_id}</small>}
            </span>
            <small>
              {account.projects} {account.projects === 1 ? "projeto" : "projetos"}
              {account.can_refresh ? " · renovação automática" : account.expires_at ? ` · expira ${formatDateTime(account.expires_at)}` : ""}
            </small>
            {isOwner && (
              <button
                className="icon-button"
                aria-label={`Desconectar ${account.display_name || account.external_account_id}`}
                disabled={busy !== null}
                onClick={() => action(`off-${account.id}`, () => api.channels.disconnectAccount(account.id), "Conta desconectada")}
              >
                <Unplug size={13} />
              </button>
            )}
          </div>
        ))}
        {canEdit && (
          <button
            type="button"
            className="secondary-button small"
            style={{ marginTop: 8 }}
            disabled={credential.source === "none" || busy !== null}
            title={credential.source === "none" ? "Cadastre o app OAuth acima primeiro" : undefined}
            onClick={connect}
          >
            <Link2 size={14} />{accounts.length ? "Conectar outra conta" : "Conectar conta"}
          </button>
        )}
      </div>
    </div>
  );
}
