"use client";

import { Film, ImageIcon, Trash2, Upload } from "lucide-react";
import { useRef, useState } from "react";

import { api, uploadFile, type Asset } from "@/lib/api";
import { formatBytes } from "@/lib/format";
import { useResource } from "@/lib/hooks";

import { useToast } from "../Toast";
import { ProgressBar } from "../ui";

const ACCEPT = "image/jpeg,image/png,image/webp,video/mp4,video/quicktime,video/webm";

export function AssetThumb({ asset, className = "" }: { asset: Asset; className?: string }) {
  const preview = useResource(() => api.uploads.url(asset.id), `asset:${asset.id}`);
  if (!preview.data) {
    return <div className={`thumb ${className}`}>{asset.kind === "video" ? <Film size={18} /> : <ImageIcon size={18} />}</div>;
  }
  if (asset.kind === "video") {
    return <video className={`thumb ${className}`} src={preview.data.url} muted playsInline preload="metadata" />;
  }
  return <div className={`thumb ${className}`} style={{ backgroundImage: `url("${preview.data.url}")` }} role="img" aria-label={asset.filename ?? "mídia"} />;
}

export function UploadDropzone({ projectId, onUploaded }: { projectId: number; onUploaded: (asset: Asset) => void }) {
  const toast = useToast();
  const input = useRef<HTMLInputElement>(null);
  const [progress, setProgress] = useState<{ name: string; value: number } | null>(null);
  const [dragging, setDragging] = useState(false);

  async function upload(files: FileList | null) {
    for (const file of Array.from(files ?? [])) {
      setProgress({ name: file.name, value: 0 });
      try {
        const ticket = await api.uploads.create(projectId, file);
        await uploadFile(ticket, file, (value) => setProgress({ name: file.name, value }));
        const asset = await api.uploads.complete(ticket.asset.id);
        toast.success(`${file.name} enviado`);
        onUploaded(asset);
      } catch (error) {
        toast.error(error);
      }
    }
    setProgress(null);
    if (input.current) input.current.value = "";
  }

  return (
    <div
      className={`dropzone ${dragging ? "dragging" : ""}`}
      onDragOver={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(event) => {
        event.preventDefault();
        setDragging(false);
        upload(event.dataTransfer.files);
      }}
    >
      <Upload size={20} />
      {progress ? (
        <div className="dropzone-progress">
          <span>Enviando {progress.name}… {progress.value}%</span>
          <ProgressBar value={progress.value} />
        </div>
      ) : (
        <>
          <span>Arraste imagens ou vídeos aqui, ou</span>
          <button type="button" className="text-button" onClick={() => input.current?.click()}>escolha arquivos</button>
          <small>JPG, PNG, WEBP, MP4, MOV ou WEBM · apenas mídias com direito de uso</small>
        </>
      )}
      <input ref={input} type="file" accept={ACCEPT} multiple hidden onChange={(event) => upload(event.target.files)} />
    </div>
  );
}

export function AssetGrid({ assets, onRemove, canEdit }: { assets: Asset[]; onRemove: (asset: Asset) => void; canEdit: boolean }) {
  if (!assets.length) return <p className="muted">Nenhuma mídia enviada. Cenas sem mídia usam um fundo gerado.</p>;
  return (
    <div className="asset-grid">
      {assets.map((asset) => (
        <figure key={asset.id}>
          <AssetThumb asset={asset} />
          <figcaption>
            <span title={asset.filename ?? ""}>{asset.filename}</span>
            <small>{formatBytes(asset.size_bytes)}</small>
          </figcaption>
          {canEdit && (
            <button className="icon-button" onClick={() => onRemove(asset)} aria-label={`Remover ${asset.filename}`}>
              <Trash2 size={14} />
            </button>
          )}
        </figure>
      ))}
    </div>
  );
}
