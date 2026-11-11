"use client";

import { ChevronRight, FileText } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { api, errorMessage, type Language } from "@/lib/api";
import { LANGUAGE_LABEL } from "@/lib/format";

import { Modal } from "./ui";

const STEPS = ["Criando projeto", "Salvando briefing", "Pesquisando o tema", "Escrevendo o roteiro"];

export function NewVideoModal({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const [topic, setTopic] = useState("");
  const [audience, setAudience] = useState("Pessoas curiosas, de 18 a 35 anos");
  const [objective, setObjective] = useState("Explicar de forma clara e gerar retenção");
  const [duration, setDuration] = useState(60);
  const [language, setLanguage] = useState<Language>("pt-BR");
  const [autopilot, setAutopilot] = useState(false);
  const [step, setStep] = useState<number | null>(null);
  const [error, setError] = useState("");

  async function waitForDossier(id: number) {
    const deadline = Date.now() + 5 * 60_000;
    while (Date.now() < deadline) {
      if (await api.projects.dossier(id)) return;
      await new Promise((resolve) => setTimeout(resolve, 3000));
    }
    throw new Error("A pesquisa está demorando mais que o esperado");
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    let projectId: number | null = null;
    if (autopilot) {
      try {
        setStep(0);
        const project = await api.autopilot.start({ topic: topic.trim(), language, audience, duration_seconds: duration });
        onClose();
        router.push(`/projects/${project.id}`);
      } catch (failure) {
        setStep(null);
        setError(errorMessage(failure));
      }
      return;
    }
    try {
      setStep(0);
      const project = await api.projects.create(topic.trim().slice(0, 60), language);
      projectId = project.id;
      setStep(1);
      await api.projects.saveBrief(project.id, {
        topic: topic.trim(),
        audience,
        objective,
        language,
        constraints: { tone: "didático e próximo", duration_seconds: duration, format: "vertical" },
      });
      setStep(2);
      const job = await api.projects.researchJob(project.id);
      if (job.queued) await waitForDossier(project.id);
      setStep(3);
      await api.projects.generateScript(project.id);
      onClose();
      router.push(`/projects/${project.id}?tab=roteiro`);
    } catch (failure) {
      setStep(null);
      setError(
        projectId
          ? `${errorMessage(failure)}. O projeto foi criado e pode ser continuado na página dele.`
          : errorMessage(failure),
      );
      if (projectId) router.push(`/projects/${projectId}`);
    }
  }

  return (
    <Modal onClose={step === null ? onClose : () => undefined} icon={<FileText />} eyebrow="NOVO VÍDEO" title="Qual história vamos explicar?">
      <p>Comece com o tema. No modo manual, a pesquisa e o roteiro passam por você; no piloto automático, só as exceções.</p>
      <form onSubmit={submit}>
        <label>
          Tema
          <textarea
            required
            minLength={2}
            maxLength={500}
            value={topic}
            onChange={(event) => setTopic(event.target.value)}
            placeholder="Ex.: Por que o céu muda de cor ao entardecer?"
          />
        </label>
        <label>
          Público
          <input required value={audience} onChange={(event) => setAudience(event.target.value)} />
        </label>
        <label>
          Objetivo
          <input required value={objective} onChange={(event) => setObjective(event.target.value)} />
        </label>
        <div className="form-row">
          <label>
            Duração
            <select value={duration} onChange={(event) => setDuration(Number(event.target.value))}>
              <option value={30}>30 segundos</option>
              <option value={60}>60 segundos</option>
              <option value={90}>90 segundos</option>
              <option value={180}>3 minutos</option>
            </select>
          </label>
          <label>
            Idioma
            <select value={language} onChange={(event) => setLanguage(event.target.value as Language)}>
              {Object.entries(LANGUAGE_LABEL).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </label>
        </div>
        <label className="checkbox">
          <input type="checkbox" checked={autopilot} onChange={(event) => setAutopilot(event.target.checked)} />
          Piloto automático: pesquisar, escrever, montar, revisar e publicar sozinho
          <small>Você só é chamado se um portão de qualidade reprovar o roteiro ou o vídeo.</small>
        </label>
        {step !== null && !autopilot && (
          <ol className="step-progress">
            {STEPS.map((label, index) => (
              <li key={label} className={index < step ? "done" : index === step ? "active" : ""}>{label}</li>
            ))}
          </ol>
        )}
        {error && <div className="notice notice-error">{error}</div>}
        <button className="primary-button full" disabled={step !== null || topic.trim().length < 2}>
          {step !== null ? (autopilot ? "Iniciando piloto automático…" : `${STEPS[step]}…`) : autopilot ? "Produzir no piloto automático" : "Criar briefing e roteiro"}
          <ChevronRight size={17} />
        </button>
      </form>
    </Modal>
  );
}
