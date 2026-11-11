import { ShieldCheck, Sparkles } from "lucide-react";
import type { ReactNode } from "react";

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <main className="auth-shell">
      <section className="auth-aside">
        <div className="brand">
          <span className="brand-mark"><Sparkles size={19} /></span>
          <span>Narra</span>
        </div>
        <div>
          <h1>Transforme ideias em<br /><em>histórias que explicam.</em></h1>
          <p>Da pesquisa à publicação, com você no controle de cada decisão.</p>
        </div>
        <small><ShieldCheck size={14} /> Nenhum conteúdo é publicado sem sua aprovação.</small>
      </section>
      <section className="auth-main">{children}</section>
    </main>
  );
}
