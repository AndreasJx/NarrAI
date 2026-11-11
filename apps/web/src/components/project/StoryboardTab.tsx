"use client";

import { Clapperboard, Images, Save } from "lucide-react";
import { useState } from "react";

import { api, type Asset, type Overview, type Scene, type Shot } from "@/lib/api";
import { useAction, useInterval, useResource } from "@/lib/hooks";
import { scriptApproved } from "@/lib/workflow";

import { useSession } from "../Session";
import { useToast } from "../Toast";
import { EmptyState, Panel } from "../ui";
import { AssetGrid, AssetThumb, UploadDropzone } from "./Media";

type Props = { overview: Overview; reload: () => void; goTo: (tab: string) => void };

const ROLE_LABEL: Record<string, string> = { hook: "Gancho", clip: "Clipe", reveal: "Revelação", broll: "Apoio" };

export function StoryboardTab({ overview, reload, goTo }: Props) {
  const { canEdit } = useSession();
  const toast = useToast();
  const { busy, run } = useAction();
  const script = overview.latest_script;
  const pid = overview.project.id;
  const [sourcingFrom, setSourcingFrom] = useState<number | null>(null);
  const sourcing = sourcingFrom !== null && overview.assets.length <= sourcingFrom;
  useInterval(reload, sourcing ? 5000 : null);
  const resourceKey = script ? `${script.id}:${overview.assets.length}:${overview.scenes.length}` : null;
  const shots = useResource(() => api.media.shots(pid, script!.id), resourceKey && `shots:${resourceKey}`);
  const credits = useResource(() => api.media.credits(pid, script!.id), resourceKey && `credits:${resourceKey}`);

  if (!script) {
    return (
      <Panel>
        <EmptyState title="Sem roteiro" action={<button className="secondary-button" onClick={() => goTo("briefing")}>Ir para o briefing</button>}>
          O storyboard é criado a partir do roteiro.
        </EmptyState>
      </Panel>
    );
  }

  const generate = () =>
    run("storyboard", async () => {
      try {
        await api.projects.storyboard(pid, script.id);
        toast.success("Storyboard criado");
        reload();
      } catch (error) {
        toast.error(error);
      }
    });

  const autoMedia = () =>
    run("media", async () => {
      try {
        const result = await api.media.auto(pid, script.id);
        if (result.queued) {
          setSourcingFrom(overview.assets.length);
          toast.success("Buscando, comparando e posicionando mídias em segundo plano");
        } else {
          toast.success(`${result.assets ?? 0} mídias e ${result.shots ?? 0} shots planejados`);
          reload();
        }
      } catch (error) {
        toast.error(error);
      }
    });

  const removeAsset = (asset: Asset) =>
    run("remove", async () => {
      try {
        await api.uploads.remove(asset.id);
        toast.success("Mídia removida");
        reload();
      } catch (error) {
        toast.error(error);
      }
    });

  const totalSeconds = overview.scenes.reduce((sum, scene) => sum + scene.duration_seconds, 0);

  return (
    <div className="stack">
      {!scriptApproved(overview) && (
        <div className="notice">
          A versão {script.version} do roteiro ainda não foi aprovada. Você pode montar o storyboard, mas a renderização exige aprovação.
        </div>
      )}
      <Panel
        title={`Storyboard · roteiro v${script.version}`}
        description={
          overview.scenes.length
            ? `${overview.scenes.length} cenas · cerca de ${Math.round(totalSeconds)}s (a narração pode alongar cada cena)`
            : "Cada linha do roteiro vira uma cena vertical com narração e legenda."
        }
        actions={
          canEdit && (
            <>
              {!overview.scenes.length && (
                <button className="secondary-button small" disabled={busy !== null} onClick={generate}>
                  <Clapperboard size={14} />{busy === "storyboard" ? "Gerando…" : "Gerar storyboard"}
                </button>
              )}
              <button className="primary-button small" disabled={busy !== null || sourcing} onClick={autoMedia}>
                <Images size={14} />{busy === "media" || sourcing ? "Buscando mídias…" : "Buscar mídias automaticamente"}
              </button>
            </>
          )
        }
      >
        {overview.scenes.length ? (
          <ol className="scene-list">
            {overview.scenes.map((scene) => (
              <SceneCard
                key={`${scene.id}:${scene.media_asset_id}`}
                scene={scene}
                assets={overview.assets}
                shots={(shots.data ?? []).filter((shot) => shot.scene_id === scene.id)}
                reload={reload}
                canEdit={canEdit}
              />
            ))}
          </ol>
        ) : (
          <EmptyState title="Storyboard ainda não gerado">Gere as cenas para escolher mídias e ajustar a narração.</EmptyState>
        )}
      </Panel>

      <Panel title="Mídias do projeto" description="Mídias enviadas e encontradas automaticamente (com licença e crédito) ficam no armazenamento privado da organização.">
        {canEdit && <UploadDropzone projectId={pid} onUploaded={reload} />}
        <AssetGrid assets={overview.assets} onRemove={removeAsset} canEdit={canEdit} />
      </Panel>

      {credits.data && credits.data.length > 0 && (
        <Panel title="Créditos" description="Adicionados automaticamente à descrição das publicações.">
          <ul className="fact-list">{credits.data.map((credit) => <li key={credit}>{credit}</li>)}</ul>
        </Panel>
      )}
    </div>
  );
}

function SceneCard({
  scene,
  assets,
  shots,
  reload,
  canEdit,
}: {
  scene: Scene;
  assets: Asset[];
  shots: Shot[];
  reload: () => void;
  canEdit: boolean;
}) {
  const toast = useToast();
  const { busy, run } = useAction();
  const [narration, setNarration] = useState(scene.narration);
  const [duration, setDuration] = useState(scene.duration_seconds);
  const media = assets.find((asset) => asset.id === scene.media_asset_id);
  const dirty = narration.trim() !== scene.narration || duration !== scene.duration_seconds;

  const update = (body: Parameters<typeof api.scenes.update>[1], message: string) =>
    run("update", async () => {
      try {
        await api.scenes.update(scene.id, body);
        toast.success(message);
        reload();
      } catch (error) {
        toast.error(error);
      }
    });

  return (
    <li className="scene-card">
      <div className="scene-media">
        {media ? <AssetThumb asset={media} className="scene-thumb" /> : <div className="thumb scene-thumb generated">Fundo gerado</div>}
        <span className="scene-index">{scene.position}</span>
      </div>
      <div className="scene-body">
        <textarea value={narration} onChange={(event) => setNarration(event.target.value)} rows={3} disabled={!canEdit} />
        <div className="scene-controls">
          <label>
            Duração mínima (s)
            <input
              type="number"
              min={1}
              max={60}
              step={0.5}
              value={duration}
              onChange={(event) => setDuration(Number(event.target.value))}
              disabled={!canEdit}
            />
          </label>
          <label>
            Mídia
            <select
              value={scene.media_asset_id ?? ""}
              disabled={!canEdit || busy !== null}
              onChange={(event) =>
                update(
                  event.target.value ? { media_asset_id: Number(event.target.value) } : { clear_media: true },
                  "Mídia da cena atualizada",
                )
              }
            >
              <option value="">Fundo gerado</option>
              {assets.map((asset) => (
                <option key={asset.id} value={asset.id}>{asset.filename}</option>
              ))}
            </select>
          </label>
          {canEdit && (
            <button
              className="secondary-button small"
              disabled={!dirty || busy !== null || !narration.trim()}
              onClick={() => update({ narration, duration_seconds: duration }, "Cena salva")}
            >
              <Save size={14} />Salvar
            </button>
          )}
        </div>
        {shots.length > 0 && (
          <ol className="shot-strip" aria-label="Shots planejados">
            {shots.map((shot) => {
              const asset = assets.find((item) => item.id === shot.asset_id);
              return (
                <li key={shot.id} className={`shot shot-${shot.role}`} title={`${shot.effect} · ${shot.duration.toFixed(1)}s`}>
                  {asset ? <AssetThumb asset={asset} className="shot-thumb" /> : <div className="thumb shot-thumb generated" />}
                  <small>{ROLE_LABEL[shot.role] ?? shot.role} · {shot.duration.toFixed(1)}s</small>
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </li>
  );
}
