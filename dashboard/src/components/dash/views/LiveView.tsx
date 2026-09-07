"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/client/api";
import { money, timeAgo, Reveal } from "@/components/dash/fx";
import { Avatar } from "@/components/dash/fx";
import { Radio, Database } from "lucide-react";
import { cn } from "@/lib/utils";

export default function LiveView() {
  const [filter, setFilter] = useState<"all" | "record" | "audit">("all");
  const { data, isLoading, dataUpdatedAt } = useQuery({
    queryKey: ["live"],
    queryFn: api.live,
    refetchInterval: 8000,
    refetchIntervalInBackground: true,
  });

  const { data: ov } = useQuery({ queryKey: ["overview"], queryFn: api.overview, refetchInterval: 20000 });
  const currency = ov?.currency ?? "$";

  const events = (data?.events ?? []).filter((e) => filter === "all" || e.kind === filter);
  const lastEventKey = events[0]?.at ?? "";

  return (
    <div className="space-y-5">
      <Reveal>
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-xs font-bold text-muted-foreground">التصفية:</span>
          {([["all", "الكل"], ["record", "تسجيلات"], ["audit", "إداري"]] as const).map(([k, label]) => (
            <button
              key={k}
              onClick={() => setFilter(k)}
              className={cn(
                "rounded-full border px-4 py-1.5 text-xs font-bold transition-all",
                filter === k
                  ? "border-gold/40 bg-gold/12 text-gold-bright"
                  : "border-gold/15 text-muted-foreground hover:bg-gold/5 hover:text-cream"
              )}
            >
              {label}
            </button>
          ))}
          <div className="ms-auto flex items-center gap-3 text-[11px] text-muted-foreground">
            <span className="inline-flex items-center gap-1.5">
              <Database className="h-3.5 w-3.5" />
              {data?.dbUp ? "قاعدة البيانات متصلة" : "انقطاع اتصال"}
              {data ? ` • ${data.totalRecords.toLocaleString("en-US")} سجل` : ""}
            </span>
            <span>آخر تحديث: {dataUpdatedAt ? timeAgo(new Date(dataUpdatedAt).toISOString()) : "—"}</span>
          </div>
        </div>
      </Reveal>

      <Reveal delay={80}>
        <div className="glass-card overflow-hidden">
          <div className="flex items-center gap-2 border-b border-gold/10 px-5 py-3.5">
            <Radio className="h-4 w-4 text-gold" aria-hidden />
            <h3 className="text-sm font-extrabold">بث الأحداث الحية</h3>
            <span className="live-dot ms-2" aria-hidden />
            <span className="text-[10px] text-muted-foreground">يتحدث تلقائيًا كل 8 ثوانٍ</span>
          </div>
          {isLoading ? (
            <div className="space-y-2 p-5">
              {[...Array(8)].map((_, i) => <div key={i} className="h-12 animate-pulse rounded-xl bg-ink-800" />)}
            </div>
          ) : events.length === 0 ? (
            <p className="p-12 text-center text-sm text-muted-foreground">لا أحداث — سيظهر كل تسجيل من ديسكورد هنا فورًا</p>
          ) : (
            <div className="scroll-area max-h-[34rem] divide-y divide-gold/8">
              {events.map((e, i) => (
                <div
                  key={`${e.at}-${i}-${e.title}`}
                  className={cn("flex items-center gap-3.5 px-5 py-3.5 transition-colors hover:bg-gold/4", i === 0 && lastEventKey && "tick-in")}
                >
                  {e.kind === "record" ? (
                    <Avatar name={e.username || e.user_id || "؟"} size={34} />
                  ) : (
                    <span className="flex h-[34px] w-[34px] items-center justify-center rounded-full border border-gold/25 bg-gold/8 text-gold">
                      <Database className="h-3.5 w-3.5" aria-hidden />
                    </span>
                  )}
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-sm font-bold">{e.title}</span>
                      <span className={cn(
                        "shrink-0 rounded-full px-2 py-0.5 text-[9px] font-black",
                        e.kind === "record" ? "bg-gold/12 text-gold-bright" : "bg-[#57f287]/12 text-[#57f287]"
                      )}>
                        {e.kind === "record" ? "تسجيل" : "إداري"}
                      </span>
                    </div>
                    {e.detail && <div className="truncate text-[11px] text-muted-foreground">{e.detail}</div>}
                  </div>
                  {typeof e.amount === "number" && (
                    <span className={cn("shrink-0 text-xs font-black", e.amount < 0 ? "text-[#ff7a7c]" : "text-[#57f287]")} dir="ltr">
                      {money(e.amount, currency)}
                    </span>
                  )}
                  <span className="w-14 shrink-0 text-end text-[10px] text-muted-foreground">{timeAgo(e.at)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </Reveal>
    </div>
  );
}
