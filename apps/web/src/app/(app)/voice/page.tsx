"use client";

import { Check, Mic2, UserRound } from "lucide-react";
import { useState } from "react";

import { useSession } from "@/components/Session";
import { useToast } from "@/components/Toast";
import { ErrorNotice, Loading, Panel } from "@/components/ui";
import { api, type Language, type Organization } from "@/lib/api";
import { LANGUAGE_LABEL } from "@/lib/format";
import { useAction, useResource } from "@/lib/hooks";

const DEFAULT_VOICE: Record<Language, string> = { "pt-BR": "pf_dora", "en-US": "af_heart", "en-GB": "bf_emma" };

function activeVoice(organization: Organization, language: Language): string {
  const preferred = organization.voices?.[language];
  if (preferred) return preferred;
  return organization.voice.startsWith({ "pt-BR": "p", "en-US": "a", "en-GB": "b" }[language])
    ? organization.voice
    : DEFAULT_VOICE[language];
}

export default function VoicePage() {
  const { me, isOwner, refresh } = useSession();
  const toast = useToast();
  const { busy, run } = useAction();
  const voices = useResource(api.organization.voices, "voices");
  const [language, setLanguage] = useState<Language>("pt-BR");
  const current = activeVoice(me.organization, language);

  const choose = (voice: string) =>
    run(voice, async () => {
      try {
        await api.organization.update({ voice });
        toast.success(`Voz padrão em ${LANGUAGE_LABEL[language]} atualizada`);
        refresh();
      } catch (error) {
        toast.error(error);
      }
    });

  return (
    <>
      <section className="page-head">
        <div>
          <p className="eyebrow">BIBLIOTECA</p>
          <h1 className="page-title">Voz e avatar</h1>
          <p className="hero-copy">A narração é sintetizada localmente com Kokoro, sem enviar o roteiro a terceiros.</p>
        </div>
      </section>
      {voices.error && <ErrorNotice error={voices.error} onRetry={voices.reload} />}
      {voices.loading && <Loading />}
      <div className="tab-grid wide-left">
        <Panel
          title="Voz da narração"
          description={
            isOwner
              ? "Escolha uma voz padrão por idioma. Cada projeto usa a voz do idioma dele."
              : "Apenas proprietários podem alterar as vozes padrão."
          }
        >
          <div className="chips voice-languages">
            {(Object.keys(DEFAULT_VOICE) as Language[]).map((item) => (
              <button key={item} className={`chip ${item === language ? "active" : ""}`} onClick={() => setLanguage(item)}>
                {LANGUAGE_LABEL[item]}
              </button>
            ))}
          </div>
          <div className="voice-grid">
            {voices.data
              ?.filter((voice) => voice.language === language)
              .map((voice) => {
                const selected = voice.id === current;
                return (
                  <article key={voice.id} className={`voice-card ${selected ? "selected" : ""}`}>
                    <div className="voice-head">
                      <span className="voice-icon"><Mic2 size={18} /></span>
                      <div>
                        <strong>{voice.label}</strong>
                        <small>{voice.language} · voz {voice.gender} · {voice.id}</small>
                      </div>
                      {selected && <Check size={18} className="voice-check" />}
                    </div>
                    {voice.sample_available ? (
                      <audio controls preload="none" src={`/api/v1/voices/${voice.id}/sample`} />
                    ) : (
                      <small className="muted">Amostra disponível após o worker iniciar com o modelo Kokoro.</small>
                    )}
                    {isOwner && !selected && (
                      <button className="secondary-button small" disabled={busy !== null} onClick={() => choose(voice.id)}>
                        {busy === voice.id ? "Salvando…" : "Usar esta voz"}
                      </button>
                    )}
                  </article>
                );
              })}
          </div>
        </Panel>
        <Panel title="Avatar">
          <div className="empty-state">
            <UserRound size={28} />
            <strong>Avatar indisponível nesta versão</strong>
            <p>Os vídeos usam cenas, mídias pesquisadas ou enviadas e legendas. A integração com avatar exige contrato com fornecedor e consentimento de imagem.</p>
          </div>
        </Panel>
      </div>
    </>
  );
}
