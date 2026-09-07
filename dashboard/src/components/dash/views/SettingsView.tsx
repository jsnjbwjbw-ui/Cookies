"use client";

import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type MeResponse } from "@/lib/client/api";
import { money, Reveal } from "@/components/dash/fx";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { RefreshCw, Coins, Bell, Hash, Database, Bot, PlugZap, Info } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

export default function SettingsView({ me }: { me: MeResponse }) {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const isAdmin = me.user?.isAdmin ?? false;

  const [currency, setCurrency] = useState("");
  const [threshold, setThreshold] = useState("");
  const [syncing, setSyncing] = useState(false);

  useEffect(() => {
    if (data) {
      setCurrency(data.settings.currency);
      setThreshold(String(data.settings.alert_threshold));
    }
  }, [data]);

  const patch = useMutation({
    mutationFn: (p: { currency?: string; alert_threshold?: number }) => api.patchSettings(p),
    onSuccess: () => { toast.success("حُفظت الإعدادات — البوت يقرأها من نفس المكان"); qc.invalidateQueries({ queryKey: ["settings"] }); },
    onError: (e: Error) => toast.error(e.message),
  });

  async function sync() {
    setSyncing(true);
    try {
      const res = await api.syncDiscord();
      toast.success(`تمت مزامنة ${res.synced} عضو من ديسكورد — الأسماء والأفاتارات محدثة`);
      qc.invalidateQueries();
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setSyncing(false);
    }
  }

  if (isLoading || !data) {
    return <div className="glass-card h-72 animate-pulse" />;
  }

  const cfg = me.config;
  const isDemo = cfg.mode === "demo";

  const connections = [
    {
      icon: Database,
      title: "قاعدة البيانات (MongoDB)",
      status: !isDemo,
      detail: isDemo
        ? "وضع تجريبي ببيانات نموذجية — اضبط MONGODB_URI لتصلك بيانات البوت الحقيقية"
        : `متصل بنفس قاعدة البوت (${process.env.NEXT_PUBLIC_DB_HINT || "work_bot"}) — تحديث لحظي`,
    },
    {
      icon: Bot,
      title: "تسجيل الدخول (Discord OAuth)",
      status: cfg.oauthEnabled,
      detail: cfg.oauthEnabled
        ? "مفعّل — الدخول عبر ديسكورد مع فحص عضوية السيرفر"
        : "غير مضبوط — ضبط DISCORD_CLIENT_ID و DISCORD_CLIENT_SECRET و DISCORD_GUILD_ID",
    },
    {
      icon: PlugZap,
      title: "توكن البوت (مزامنة الأعضاء)",
      status: cfg.botLinked,
      detail: cfg.botLinked
        ? "مربوط — يمكن سحب الأسماء والأفاتارات الحية من السيرفر"
        : "اختياري: DISCORD_BOT_TOKEN يتيح مزامنة النك نيم والأفاتارات بضغطة",
    },
  ];

  return (
    <div className="space-y-5">
      {/* حالة الربط */}
      <Reveal>
        <div className="glass-card p-5">
          <h3 className="mb-4 text-base font-extrabold">حالة الربط مع البوت</h3>
          <div className="grid gap-3 md:grid-cols-3">
            {connections.map((c) => (
              <div key={c.title} className={cn("rounded-xl border p-4", c.status ? "border-[#57f287]/25 bg-[#57f287]/5" : "border-gold/20 bg-gold/5")}>
                <div className="mb-2 flex items-center justify-between">
                  <c.icon className={cn("h-5 w-5", c.status ? "text-[#57f287]" : "text-gold")} aria-hidden />
                  <span className={cn("rounded-full px-2.5 py-0.5 text-[10px] font-black", c.status ? "bg-[#57f287]/15 text-[#57f287]" : "bg-gold/15 text-gold-bright")}>
                    {c.status ? "مربوط" : "غير مضبوط"}
                  </span>
                </div>
                <div className="text-sm font-extrabold">{c.title}</div>
                <p className="mt-1 text-[11px] leading-5 text-muted-foreground">{c.detail}</p>
              </div>
            ))}
          </div>
          {isAdmin && (
            <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-gold/10 pt-4">
              <Button variant="secondary" onClick={sync} disabled={syncing}>
                <RefreshCw className={cn("h-4 w-4", syncing && "animate-spin")} />
                {syncing ? "جارٍ السحب من ديسكورد…" : "مزامنة الأعضاء من ديسكورد"}
              </Button>
              <p className="text-[11px] text-muted-foreground">تجلب أحدث النك نيم والأفاتارات لكل أعضاء السيرفر وتحدّث مجموعة members.</p>
            </div>
          )}
        </div>
      </Reveal>

      {/* إعدادات عامة */}
      <Reveal delay={80}>
        <div className="glass-card p-5">
          <h3 className="mb-4 text-base font-extrabold">إعدادات عامة</h3>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div className="space-y-1.5">
              <Label htmlFor="cur" className="flex items-center gap-1.5 text-xs">
                <Coins className="h-3.5 w-3.5 text-gold" /> رمز العملة
              </Label>
              <Input id="cur" value={currency} disabled={!isAdmin} onChange={(e) => setCurrency(e.target.value)} className="border-gold/20 bg-ink-850" dir="ltr" maxLength={4} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="thr" className="flex items-center gap-1.5 text-xs">
                <Bell className="h-3.5 w-3.5 text-gold" /> حد التنبيه
              </Label>
              <Input id="thr" value={threshold} disabled={!isAdmin} onChange={(e) => setThreshold(e.target.value)} className="border-gold/20 bg-ink-850" inputMode="decimal" dir="ltr" />
            </div>
            <div className="space-y-1.5">
              <Label className="flex items-center gap-1.5 text-xs">
                <Hash className="h-3.5 w-3.5 text-gold" /> الشهر النشط
              </Label>
              <Input value={data.activeMonthName} disabled className="border-gold/20 bg-ink-850 font-bold" />
              <p className="text-[10px] text-muted-foreground">يُدار من شاشة الأشهر</p>
            </div>
            {isAdmin && (
              <div className="flex items-end">
                <Button
                  className="gold-btn w-full border-0 font-extrabold"
                  disabled={patch.isPending}
                  onClick={() =>
                    patch.mutate({
                      currency: currency.trim() || undefined,
                      alert_threshold: threshold && !Number.isNaN(Number(threshold)) ? Number(threshold) : undefined,
                    })
                  }
                >
                  {patch.isPending ? "جارٍ الحفظ…" : "حفظ الإعدادات"}
                </Button>
              </div>
            )}
          </div>
          <div className="mt-5">
            <Label className="mb-2 block text-xs">القنوات المسموحة في البوت (قراءة فقط)</Label>
            <div className="flex flex-wrap gap-2">
              {data.settings.allowed_channels.length === 0 && <span className="text-xs text-muted-foreground">لا قنوات محددة — تُدار من أمر /تحديد_قنوات</span>}
              {data.settings.allowed_channels.map((ch) => (
                <span key={String(ch)} className="rounded-full border border-gold/20 bg-gold/8 px-3 py-1 text-[11px] font-bold text-gold-bright" dir="ltr">
                  {String(ch)}
                </span>
              ))}
            </div>
          </div>
        </div>
      </Reveal>

      {/* دليل الربط */}
      <Reveal delay={140}>
        <div className="glass-card p-5">
          <h3 className="mb-1 flex items-center gap-2 text-base font-extrabold">
            <Info className="h-[18px] w-[18px] text-gold" aria-hidden />
            دليل الربط السريع
          </h3>
          <p className="mb-4 text-xs text-muted-foreground">
            انشر هذا الموقع على Railway/Vercel وأضف نفس متغيرات البيانات — سيقرأ بيانات البوت فورًا.
          </p>
          <div className="scroll-area max-h-64 rounded-xl border border-gold/12 bg-ink-850/60 p-4 font-mono text-[11px] leading-6" dir="ltr">
            {[
              ["MONGODB_URI", "نفس رابط البوت — مثل mongodb+srv://… (Atlas موصى به)"],
              ["MONGODB_DB_NAME", "اختياري — الافتراضي work_bot"],
              ["DISCORD_CLIENT_ID / SECRET", "من تطبيق ديسكورد → OAuth2"],
              ["DISCORD_GUILD_ID", "معرف سيرفر الفريق (فقط أعضاؤه يدخلون)"],
              ["DISCORD_OWNER_IDS", "آيديات مشرفين مفصولة بفواصل"],
              ["DISCORD_BOT_TOKEN", "اختياري — لمزامنة الأعضاء"],
              ["SESSION_SECRET", "أي نص طويل عشوائي لتوقيع الجلسات"],
            ].map(([k, v]) => (
              <div key={k} className="flex flex-wrap gap-2">
                <span className="font-bold text-gold-bright">{k}</span>
                <span className="text-muted-foreground">— {v}</span>
              </div>
            ))}
          </div>
          <p className="mt-3 text-[11px] text-muted-foreground">
            بدون MONGODB_URI يعمل الموقع بوضع تجريبي كامل ببيانات نموذجية — مثالي للمعاينة.
          </p>
        </div>
      </Reveal>

      {/* ملخص الصلاحيات */}
      <Reveal delay={180}>
        <div className="glass-card p-5 text-xs leading-6 text-muted-foreground">
          حسابك الحالي: <span className="font-extrabold text-cream">{me.user?.globalName || me.user?.username}</span>
          {" "}— الصلاحية: <span className={cn("font-extrabold", isAdmin ? "text-gold-bright" : "text-cream")}>{isAdmin ? "مشرف (تعديل كامل)" : "عضو (عرض فقط)"}</span>
          {" "}• إجمالي المستحقات المعروضة محسوبة مباشرة من السجلات: {money(0) === "$0.00" ? "نفس محرك البوت" : ""}
        </div>
      </Reveal>
    </div>
  );
}
