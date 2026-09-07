"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/client/api";
import { useApp } from "@/lib/client/store";
import { Avatar, Counter, money, timeAgo, Reveal } from "@/components/dash/fx";
import { Users, FileText, Banknote, FolderKanban, Crown, ChevronLeft, Activity } from "lucide-react";
import { cn } from "@/lib/utils";

function KPI({
  icon: Icon, label, value, decimals = 0, prefix = "", hint, delay,
}: {
  icon: typeof Users; label: string; value: number; decimals?: number; prefix?: string; hint?: string; delay: number;
}) {
  return (
    <Reveal delay={delay}>
      <div className="glass-card spot-card relative overflow-hidden p-5">
        <div className="flex items-start justify-between">
          <div>
            <div className="text-xs font-semibold text-muted-foreground">{label}</div>
            <div className="mt-2 text-3xl font-black text-cream">
              <Counter value={value} decimals={decimals} prefix={prefix} />
            </div>
            {hint && <div className="mt-1 text-[11px] text-muted-foreground">{hint}</div>}
          </div>
          <div className="rounded-xl border border-gold/20 bg-gold/8 p-2.5">
            <Icon className="h-5 w-5 text-gold" aria-hidden />
          </div>
        </div>
      </div>
    </Reveal>
  );
}

/** رسم أعمدة SVG خفيف — بلا مكتبات */
function DailyChart({ data }: { data: Array<{ label: string; count: number; amount: number }> }) {
  const max = Math.max(1, ...data.map((d) => d.count));
  return (
    <div className="flex h-44 items-end gap-1.5" dir="ltr">
      {data.map((d, i) => {
        const h = Math.max(4, (d.count / max) * 100);
        const isLast = i === data.length - 1;
        return (
          <div key={d.label + i} className="group relative flex h-full flex-1 flex-col justify-end">
            <div
              className={cn(
                "w-full rounded-t-md transition-all duration-500",
                isLast ? "gold-bar" : "bg-gradient-to-t from-[#6b5417] to-gold/70 hover:to-gold-bright"
              )}
              style={{ height: `${h}%`, animation: `tick-in 0.6s ${i * 0.03}s both` }}
            />
            <span className="pointer-events-none absolute -top-7 left-1/2 z-10 -translate-x-1/2 whitespace-nowrap rounded-md border border-gold/25 bg-ink-950 px-2 py-1 text-[10px] font-bold opacity-0 transition-opacity group-hover:opacity-100">
              {d.label} — {d.count} فصل ({money(d.amount)})
            </span>
          </div>
        );
      })}
    </div>
  );
}

function Donut({ items, currency }: { items: Array<{ type: string; count: number; amount: number }>; currency: string }) {
  const total = items.reduce((s, i) => s + i.count, 0);
  const colors = ["#d4af37", "#f3d98b", "#9a7a24", "#8a6d1f", "#e8c96a", "#6b5417", "#c8a232", "#b18e24"];
  if (!total) return <p className="py-10 text-center text-sm text-muted-foreground">لا تخصصات مسجلة هذا الشهر بعد</p>;
  const R = 52;
  const C = 2 * Math.PI * R;
  const arcs = items.slice(0, 8).reduce<Array<{ type: string; dash: string; offset: number }>>((acc, it) => {
    const frac = it.count / total;
    const prev = acc.reduce((s, a) => s + a.frac, 0);
    acc.push({ type: it.type, frac, dash: `${frac * C} ${C - frac * C}`, offset: -prev * C });
    return acc;
  }, []);
  return (
    <div className="flex flex-wrap items-center justify-center gap-6">
      <svg viewBox="0 0 140 140" className="h-40 w-40 -rotate-90" aria-hidden>
        {arcs.map((a, i) => (
          <circle
            key={a.type}
            cx="70" cy="70" r={R}
            fill="none"
            stroke={colors[i % colors.length]}
            strokeWidth="16"
            strokeDasharray={a.dash}
            strokeDashoffset={a.offset}
            className="transition-all duration-700"
          />
        ))}
        <circle cx="70" cy="70" r="36" fill="#0a0a0c" />
      </svg>
      <div className="space-y-1.5 text-xs" dir="rtl">
        {items.slice(0, 6).map((it, i) => (
          <div key={it.type} className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: colors[i % colors.length] }} />
            <span className="font-semibold">{it.type.replace("_", " ")}</span>
            <span className="text-muted-foreground">{it.count} فصل • {money(it.amount, currency)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function Overview() {
  const { setView, setSelectedMember } = useApp();
  const { data, isLoading } = useQuery({ queryKey: ["overview"], queryFn: api.overview, refetchInterval: 20000 });
  const { data: live } = useQuery({ queryKey: ["live"], queryFn: api.live, refetchInterval: 10000 });

  if (isLoading || !data) {
    return (
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="glass-card h-28 animate-pulse p-5" />
        ))}
        <div className="glass-card h-72 animate-pulse md:col-span-2 lg:col-span-3" />
        <div className="glass-card h-72 animate-pulse" />
      </div>
    );
  }

  const t = data.totals;

  return (
    <div className="space-y-5">
      {/* لافتة الشهر */}
      <Reveal>
        <button
          onClick={() => setView("months")}
          className="glass-card spot-card flex w-full flex-wrap items-center justify-between gap-3 p-4 text-start"
        >
          <div>
            <div className="text-xs text-muted-foreground">الشهر النشط — كل الأرقام أدناه له</div>
            <div className="mt-0.5 text-xl font-black text-gold-bright">{data.activeMonthName}</div>
          </div>
          <span className="inline-flex items-center gap-1 text-xs font-bold text-muted-foreground transition-colors hover:text-gold-bright">
            إدارة الأشهر
            <ChevronLeft className="h-4 w-4" />
          </span>
        </button>
      </Reveal>

      {/* KPIs */}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KPI icon={Users} label="أعضاء الفريق" value={t.members} hint={`${t.activeMembers} نشط هذا الشهر • ${t.inactiveMembers} بلا عمل`} delay={0} />
        <KPI icon={FileText} label="فصول محتسبة" value={t.chapters} hint={`مكافآت ${money(t.bonuses, data.currency)}`} delay={70} />
        <KPI icon={Banknote} label="الصافي المستحق" value={t.revenue} decimals={2} prefix={data.currency} hint={`خصومات ${money(t.deductions, data.currency)}`} delay={140} />
        <KPI icon={FolderKanban} label="أعمال" value={t.works} hint={data.workStats.filter((w) => !w.isolated).length + " غير معزول"} delay={210} />
      </div>

      {/* الرسوم */}
      <div className="grid gap-4 lg:grid-cols-3">
        <Reveal className="lg:col-span-2">
          <div className="glass-card p-5">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-sm font-extrabold">إيقاع الفريق — آخر 14 يومًا</h3>
              <span className="text-[11px] text-muted-foreground">فصول/يوم</span>
            </div>
            <DailyChart data={data.dailySeries} />
          </div>
        </Reveal>
        <Reveal delay={100}>
          <div className="glass-card p-5">
            <h3 className="mb-4 text-sm font-extrabold">التخصصات هذا الشهر</h3>
            <Donut items={data.specialtyCounts} currency={data.currency} />
          </div>
        </Reveal>
      </div>

      {/* المتصدرون + البث */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Reveal>
          <div className="glass-card p-5">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-sm font-extrabold">متصدرو الشهر</h3>
              <Crown className="h-4 w-4 text-gold" aria-hidden />
            </div>
            {data.topMembers.length === 0 ? (
              <p className="py-8 text-center text-sm text-muted-foreground">لا سجلات هذا الشهر بعد</p>
            ) : (
              <div className="space-y-2.5">
                {data.topMembers.map((m, i) => {
                  const top = data.topMembers[0].amount || 1;
                  return (
                    <button
                      key={m.userId}
                      onClick={() => {
                        setSelectedMember(m.userId);
                        setView("members");
                      }}
                      className="group flex w-full items-center gap-3 rounded-xl border border-transparent p-2 text-start transition-all hover:border-gold/20 hover:bg-gold/5"
                    >
                      <span className={cn("w-6 text-center text-sm font-black", i === 0 ? "text-gold" : "text-muted-foreground")}>
                        {i + 1}
                      </span>
                      <Avatar src={m.avatar} name={m.name} size={34} ring={i === 0} />
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-bold group-hover:text-gold-bright">{m.name}</div>
                        <div className="text-[11px] text-muted-foreground">{m.chapters} فصل</div>
                      </div>
                      <div className="w-24 sm:w-36">
                        <div className="h-1.5 overflow-hidden rounded-full bg-ink-700">
                          <div className="gold-bar h-full rounded-full" style={{ width: `${Math.max(6, (m.amount / top) * 100)}%` }} />
                        </div>
                      </div>
                      <span className="w-16 text-end text-xs font-black text-[#57f287]">{money(m.amount, data.currency)}</span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </Reveal>

        <Reveal delay={100}>
          <div className="glass-card p-5">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="flex items-center gap-2 text-sm font-extrabold">
                <Activity className="h-4 w-4 text-gold" aria-hidden />
                آخر الأحداث
              </h3>
              <button onClick={() => setView("live")} className="text-[11px] font-bold text-gold transition-colors hover:text-gold-bright">
                البث الكامل
              </button>
            </div>
            <div className="scroll-area max-h-72 space-y-2">
              {(live?.events ?? []).slice(0, 7).map((e, i) => (
                <div key={`${e.at}-${i}`} className="flex items-center gap-3 rounded-xl border border-gold/8 bg-ink-850/60 px-3.5 py-2.5">
                  <span className={cn("h-2 w-2 shrink-0 rounded-full", e.kind === "record" ? "bg-gold" : "bg-[#57f287]")} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-xs font-bold">{e.title}</div>
                    {e.detail && <div className="truncate text-[11px] text-muted-foreground">{e.detail}</div>}
                  </div>
                  {typeof e.amount === "number" && (
                    <span className={cn("text-[11px] font-black", e.amount < 0 ? "text-[#ff7a7c]" : "text-[#57f287]")}>
                      {money(e.amount, data.currency)}
                    </span>
                  )}
                  <span className="shrink-0 text-[10px] text-muted-foreground">{timeAgo(e.at)}</span>
                </div>
              ))}
              {!live?.events?.length && (
                <p className="py-8 text-center text-sm text-muted-foreground">لا أحداث بعد</p>
              )}
            </div>
          </div>
        </Reveal>
      </div>
    </div>
  );
}
