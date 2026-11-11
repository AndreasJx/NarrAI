"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { useSession } from "@/components/Session";
import { EmptyState, ErrorNotice, Loading, Panel, StatusBadge } from "@/components/ui";
import { api, type CalendarItem } from "@/lib/api";
import { formatDateTime, PLATFORM_LABEL, toDate } from "@/lib/format";
import { useResource } from "@/lib/hooks";

const WEEKDAYS = ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"];
const monthLabel = new Intl.DateTimeFormat("pt-BR", { month: "long", year: "numeric" });

const when = (item: CalendarItem) => toDate(item.published_at ?? item.scheduled_at ?? item.created_at);
const dayKey = (date: Date) => `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;

export default function CalendarPage() {
  const { me } = useSession();
  const calendar = useResource(api.calendar, `calendar:${me.organization.id}`);
  const [cursor, setCursor] = useState(() => {
    const now = new Date();
    return { year: now.getFullYear(), month: now.getMonth() };
  });

  const byDay = useMemo(() => {
    const map = new Map<string, CalendarItem[]>();
    for (const item of calendar.data ?? []) {
      const key = dayKey(when(item));
      map.set(key, [...(map.get(key) ?? []), item]);
    }
    return map;
  }, [calendar.data]);

  const first = new Date(cursor.year, cursor.month, 1);
  const days = new Date(cursor.year, cursor.month + 1, 0).getDate();
  const cells = [...Array(first.getDay()).fill(null), ...Array.from({ length: days }, (_, index) => index + 1)];
  const move = (delta: number) =>
    setCursor(({ year, month }) => {
      const date = new Date(year, month + delta, 1);
      return { year: date.getFullYear(), month: date.getMonth() };
    });
  const upcoming = (calendar.data ?? []).filter((item) => item.status === "scheduled");

  return (
    <>
      <section className="page-head">
        <div>
          <p className="eyebrow">PLANEJAMENTO</p>
          <h1 className="page-title">Calendário</h1>
          <p className="hero-copy">Publicações agendadas e realizadas em todos os projetos.</p>
        </div>
      </section>
      {calendar.error && <ErrorNotice error={calendar.error} onRetry={calendar.reload} />}
      {calendar.loading && <Loading />}
      {calendar.data && (
        <div className="tab-grid wide-left">
          <Panel
            title={monthLabel.format(first)}
            actions={
              <>
                <button className="icon-button" onClick={() => move(-1)} aria-label="Mês anterior"><ChevronLeft size={16} /></button>
                <button className="icon-button" onClick={() => move(1)} aria-label="Próximo mês"><ChevronRight size={16} /></button>
              </>
            }
          >
            <div className="calendar">
              {WEEKDAYS.map((day) => <div key={day} className="calendar-weekday">{day}</div>)}
              {cells.map((day, index) => {
                const items = day ? byDay.get(dayKey(new Date(cursor.year, cursor.month, day))) ?? [] : [];
                return (
                  <div key={index} className={`calendar-cell ${day ? "" : "empty"}`}>
                    {day && <span className="calendar-day">{day}</span>}
                    {items.map((item) => (
                      <Link key={item.id} href={`/projects/${item.project_id}?tab=publicacao`} className={`calendar-event event-${item.status}`}>
                        {PLATFORM_LABEL[item.platform]?.split(" ")[0]} · {item.title}
                      </Link>
                    ))}
                  </div>
                );
              })}
            </div>
          </Panel>
          <Panel title="Próximos agendamentos">
            {upcoming.length ? (
              <ul className="insight-list">
                {upcoming.map((item) => (
                  <li key={item.id}>
                    <p><Link href={`/projects/${item.project_id}?tab=publicacao`}>{item.title}</Link></p>
                    <small>{item.project_name} · {PLATFORM_LABEL[item.platform]} · {formatDateTime(item.scheduled_at)} · <StatusBadge status={item.status} /></small>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState title="Nada agendado">Agende publicações na aba Publicação de cada projeto.</EmptyState>
            )}
          </Panel>
        </div>
      )}
    </>
  );
}
