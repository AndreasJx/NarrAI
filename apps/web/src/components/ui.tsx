"use client";

import { Check, X } from "lucide-react";
import type { ReactNode } from "react";

import { statusInfo } from "@/lib/format";

export function StatusBadge({ status }: { status: string }) {
  const info = statusInfo(status);
  return (
    <span className={`badge badge-${info.tone}`}>
      <i />
      {info.label}
    </span>
  );
}

export function Modal({
  onClose,
  icon,
  eyebrow,
  title,
  children,
}: {
  onClose: () => void;
  icon?: ReactNode;
  eyebrow?: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <section className="composer" role="dialog" aria-modal="true" aria-label={title} onMouseDown={(event) => event.stopPropagation()}>
        <button className="modal-close" onClick={onClose} aria-label="Fechar"><X /></button>
        {icon && <span className="composer-icon">{icon}</span>}
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h2>{title}</h2>
        {children}
      </section>
    </div>
  );
}

export function Panel({
  title,
  description,
  actions,
  children,
  className = "",
}: {
  title?: string;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      {(title || actions) && (
        <header className="panel-head">
          <div>
            {title && <h3>{title}</h3>}
            {description && <p>{description}</p>}
          </div>
          {actions && <div className="panel-actions">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty-state">
      <strong>{title}</strong>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}

export function Loading({ label = "Carregando" }: { label?: string }) {
  return (
    <div className="loading-row">
      <div className="spinner" aria-hidden />
      <span>{label}…</span>
    </div>
  );
}

export function ErrorNotice({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  return (
    <div className="notice notice-error">
      {error.message}
      {onRetry && (
        <button className="text-button" onClick={onRetry}>Tentar novamente</button>
      )}
    </div>
  );
}

export function ProgressBar({ value }: { value: number }) {
  return (
    <div className="bar" role="progressbar" aria-valuenow={value} aria-valuemin={0} aria-valuemax={100}>
      <i style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
    </div>
  );
}

export type WorkflowStep = { label: string; detail: string; state: "done" | "active" | "todo" };

export function Workflow({ steps }: { steps: WorkflowStep[] }) {
  return (
    <div className="workflow">
      {steps.map((step, index) => (
        <div className={`workflow-step ${step.state === "done" ? "done" : ""} ${step.state === "active" ? "active" : ""}`} key={step.label}>
          <div className="step-line">
            <span className="step-node">{step.state === "done" ? <Check size={14} /> : index + 1}</span>
            {index < steps.length - 1 && <i />}
          </div>
          <strong>{step.label}</strong>
          <small>{step.detail}</small>
        </div>
      ))}
    </div>
  );
}
