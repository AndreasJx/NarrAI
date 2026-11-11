"use client";

import { Trash2, UserPlus } from "lucide-react";
import Link from "next/link";
import { useState, type FormEvent } from "react";

import { AutopilotSettingsForm } from "@/components/autopilot/SettingsForm";
import { useSession } from "@/components/Session";
import { useToast } from "@/components/Toast";
import { ErrorNotice, Loading, Panel } from "@/components/ui";
import { api, type Role } from "@/lib/api";
import { formatDate, money, ROLE_LABEL } from "@/lib/format";
import { useAction, useResource } from "@/lib/hooks";

export default function SettingsPage() {
  const { me, isOwner, refresh } = useSession();
  const toast = useToast();
  const { busy, run } = useAction();
  const members = useResource(api.organization.members, `members:${me.organization.id}`);
  const autopilot = useResource(api.autopilot.settings, `autopilot-settings:${me.organization.id}`);
  const [org, setOrg] = useState({ name: me.organization.name, budget: me.organization.monthly_budget_cents / 100 });
  const [invite, setInvite] = useState({ name: "", email: "", role: "editor" as Role, password: "" });

  const saveOrganization = (event: FormEvent) => {
    event.preventDefault();
    run("org", async () => {
      try {
        await api.organization.update({ name: org.name, monthly_budget_cents: Math.round(org.budget * 100) });
        toast.success("Organização atualizada");
        refresh();
      } catch (error) {
        toast.error(error);
      }
    });
  };

  const addMember = (event: FormEvent) => {
    event.preventDefault();
    run("invite", async () => {
      try {
        await api.organization.addMember({ ...invite, password: invite.password || undefined });
        toast.success(`${invite.email} adicionado`);
        setInvite({ name: "", email: "", role: "editor", password: "" });
        members.reload();
      } catch (error) {
        toast.error(error);
      }
    });
  };

  const memberAction = (name: string, task: () => Promise<unknown>, message: string) =>
    run(name, async () => {
      try {
        await task();
        toast.success(message);
        members.reload();
      } catch (error) {
        toast.error(error);
      }
    });

  return (
    <>
      <section className="page-head">
        <div>
          <p className="eyebrow">ADMINISTRAÇÃO</p>
          <h1 className="page-title">Configurações</h1>
          <p className="hero-copy">Organização, equipe, papéis e limites de gasto.</p>
        </div>
      </section>

      <div className="tab-grid">
        <Panel title="Organização" description={isOwner ? undefined : "Somente proprietários podem editar."}>
          <form className="form" onSubmit={saveOrganization}>
            <label>
              Nome
              <input required value={org.name} disabled={!isOwner} onChange={(event) => setOrg({ ...org, name: event.target.value })} />
            </label>
            <label>
              Orçamento mensal (R$)
              <input
                type="number"
                min={0}
                step={1}
                value={org.budget}
                disabled={!isOwner}
                onChange={(event) => setOrg({ ...org, budget: Number(event.target.value) })}
              />
              <small>Atual: {money(me.organization.monthly_budget_cents)}. Cada projeto também tem um teto próprio.</small>
            </label>
            {isOwner && <button className="primary-button" disabled={busy !== null}>{busy === "org" ? "Salvando…" : "Salvar"}</button>}
          </form>
        </Panel>

        <Panel title="Sua conta">
          <dl className="details">
            <dt>Nome</dt><dd>{me.user.name}</dd>
            <dt>E-mail</dt><dd>{me.user.email}</dd>
            <dt>Papel</dt><dd>{ROLE_LABEL[me.role]}</dd>
            <dt>Organizações</dt><dd>{me.organizations.map((item) => item.name).join(", ")}</dd>
          </dl>
        </Panel>
      </div>

      <Panel
        title="Piloto automático"
        description="Quanto a plataforma pode fazer sozinha: cadência, nota mínima, publicação e limites."
        actions={<Link className="secondary-button small" href="/autopilot">Abrir painel</Link>}
      >
        {autopilot.error && <ErrorNotice error={autopilot.error} onRetry={autopilot.reload} />}
        {autopilot.data ? <AutopilotSettingsForm initial={autopilot.data} onSaved={(value) => autopilot.mutate(value)} /> : <Loading />}
      </Panel>

      <Panel title="Equipe" description="Proprietários gerenciam membros; editores produzem e aprovam; leitores apenas acompanham.">
        {members.error && <ErrorNotice error={members.error} onRetry={members.reload} />}
        {members.loading && <Loading />}
        {members.data && (
          <table className="table">
            <thead><tr><th>Nome</th><th>E-mail</th><th>Papel</th><th>Desde</th><th /></tr></thead>
            <tbody>
              {members.data.map((member) => (
                <tr key={member.user_id}>
                  <td><strong>{member.name}</strong></td>
                  <td>{member.email}</td>
                  <td>
                    {isOwner && member.user_id !== me.user.id ? (
                      <select
                        value={member.role}
                        disabled={busy !== null}
                        onChange={(event) =>
                          memberAction(`role-${member.user_id}`, () => api.organization.updateMember(member.user_id, event.target.value as Role), "Papel atualizado")
                        }
                      >
                        {Object.entries(ROLE_LABEL).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                      </select>
                    ) : (
                      ROLE_LABEL[member.role]
                    )}
                  </td>
                  <td>{formatDate(member.created_at)}</td>
                  <td className="row-actions">
                    {isOwner && member.user_id !== me.user.id && (
                      <button
                        className="icon-button"
                        aria-label={`Remover ${member.name}`}
                        disabled={busy !== null}
                        onClick={() => memberAction(`rm-${member.user_id}`, () => api.organization.removeMember(member.user_id), "Membro removido")}
                      >
                        <Trash2 size={14} />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {isOwner && (
          <form className="invite-form" onSubmit={addMember}>
            <input required placeholder="Nome" value={invite.name} onChange={(event) => setInvite({ ...invite, name: event.target.value })} />
            <input required type="email" placeholder="E-mail" value={invite.email} onChange={(event) => setInvite({ ...invite, email: event.target.value })} />
            <select value={invite.role} onChange={(event) => setInvite({ ...invite, role: event.target.value as Role })}>
              {Object.entries(ROLE_LABEL).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
            <input
              type="password"
              minLength={8}
              placeholder="Senha inicial (novos usuários)"
              value={invite.password}
              onChange={(event) => setInvite({ ...invite, password: event.target.value })}
            />
            <button className="secondary-button" disabled={busy !== null}><UserPlus size={15} />Adicionar</button>
          </form>
        )}
      </Panel>
    </>
  );
}
