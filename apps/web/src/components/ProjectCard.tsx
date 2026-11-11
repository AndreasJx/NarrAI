import { ChevronRight, CirclePlay } from "lucide-react";
import Link from "next/link";

import type { Project } from "@/lib/api";
import { formatDateTime, money, statusInfo } from "@/lib/format";

const COVERS = ["violet", "blue", "green"];

export function ProjectCard({ project }: { project: Project }) {
  const status = statusInfo(project.status);
  return (
    <Link className="project-card" href={`/projects/${project.id}`}>
      <div className={`project-cover cover-${COVERS[project.id % COVERS.length]}`}>
        <div className="cover-grid" />
        <span className="duration">#{project.id}</span>
        <span className="cover-play" aria-hidden><CirclePlay /></span>
      </div>
      <div className="project-info">
        <div className="project-status"><i className={status.tone} />{status.label}</div>
        <h3>{project.name}</h3>
        <p>{money(project.spent_cents)} de {money(project.budget_cents)}</p>
        <div className="project-foot">
          <span>Atualizado {formatDateTime(project.updated_at ?? project.created_at)}</span>
          <ChevronRight size={14} />
        </div>
      </div>
    </Link>
  );
}
