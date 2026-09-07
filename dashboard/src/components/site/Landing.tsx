"use client";

import { useQuery } from "@tanstack/react-query";
import { api, type MeResponse } from "@/lib/client/api";
import { Reveal, Counter, GoldDust, LiveBadge, money } from "@/components/dash/fx";
import {
  Zap, Users, FolderKanban, CalendarRange, Tags, Radio,
  LogIn, Compass, Database, Link2, ShieldCheck, ArrowDown,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface LandingProps {
  config: MeResponse["config"];
  onDemoLogin: () => void;
  demoLoading: boolean;
  authError?: string;
}

function DiscordIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className={className} aria-hidden>
      <path d="M20.317 4.37a19.79 19.79 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.058a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028c.462-.63.874-1.295 1.226-1.994a.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128c.126-.094.252-.192.372-.291a.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.3 12.3 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.84 19.84 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.06.06 0 0 0-.031-.03ZM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.418 2.157-2.418 1.21 0 2.176 1.095 2.157 2.418 0 1.334-.956 2.419-2.157 2.419Zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.418 2.157-2.418 1.21 0 2.176 1.095 2.157 2.418 0 1.334-.946 2.419-2.157 2.419Z" />
    </svg>
  );
}

const FEATURES = [
  {
    icon: Zap,
    title: "تحديث لحظي",
    desc: "أي تسجيل يحدث في ديسكورد يظهر هنا خلال ثوانٍ — دون تحديث الصفحة. نفس قاعدة البيانات، بلا نسخ ولا مزامنة يدوية.",
  },
  {
    icon: Users,
    title: "الأعضاء كاملين دائمًا",
    desc: "الأعضاء يُحفظون عبر كل الشهور — حتى من لا عمل له يظهر بحالة واضحة، مع نك السيرفر وأفاتاره وتفاصيل مسيرته.",
  },
  {
    icon: FolderKanban,
    title: "الأعمال والفصول",
    desc: "بطاقة لكل عمل: الفصول المسجلة، المساهمون، فصل بداية الدفع، والأسعار المخصصة — مع إضافة وتعديل مباشرة.",
  },
  {
    icon: CalendarRange,
    title: "نظام أشهر مستدام",
    desc: "أنشئ شهرًا جديدًا وسمِّه وانتقل إليه بضغطة. الأعمال والأعضاء تبقى، والسجلات فقط تبدأ صفحة جديدة.",
  },
  {
    icon: Tags,
    title: "التخصصات والأسعار",
    desc: "أسعار عامة وتخصيصات لكل عمل، تفعيل وتعطيل، وكل تعديل ينعكس على البوت فورًا لأن المصدر واحد.",
  },
  {
    icon: Radio,
    title: "سجل عمليات كامل",
    desc: "بث مباشر لكل حدث: تسجيلات، مكافآت، خصومات، وتعديلات إدارية — مع أثر تدقيق لا يُمحى.",
  },
];

const STEPS = [
  { n: "01", title: "اربط حسابك", desc: "اضغط زر ديسكورد ووافق — نقرأ هويتك وعضويتك في سيرفر الفريق فقط." },
  { n: "02", title: "تُفتح لك بيانات البوت", desc: "كل ما سجّله فريقك في ديسكورد يصبح لوحات وأرقامًا ورسومًا أمامك." },
  { n: "03", title: "تحكّم من الموقع", desc: "سجّل، عدّل الأسعار، أدر الأشهر والأعمال — والبوت يقرأ نفس التغييرات لحظيًا." },
];

export default function Landing({ config, onDemoLogin, demoLoading, authError }: LandingProps) {
  const { data: stats } = useQuery({
    queryKey: ["public-stats"],
    queryFn: api.publicStats,
    refetchInterval: 15000,
  });

  const s = stats ?? { members: 0, works: 0, chapters: 0, revenue: 0, activeMonthName: "" };

  const marqueeItems = [
    `الشهر الحالي: ${s.activeMonthName || "—"}`,
    `فصول هذا الشهر: ${s.chapters.toLocaleString("en-US")}`,
    `أعمال الفريق: ${s.works}`,
    `أعضاء مسجلون: ${s.members}`,
    `إجمالي المستحق: ${money(s.revenue)}`,
    "مترابط مع MongoDB لحظيًا",
    "أشهر مستدامة بلا فقدان بيانات",
    "هوية كوكيز — ذهبي على أسود",
  ];

  return (
    <div className="flex min-h-screen flex-col overflow-x-clip">
      {/* ═══════════ الشريط العلوي ═══════════ */}
      <header className="fixed inset-x-0 top-0 z-50 border-b border-gold/10 bg-ink-950/70 backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 md:px-6">
          <div className="flex items-center gap-3">
            { }
            <img
              src="/cookie-logo.png"
              alt="شعار Cookies Tracker"
              className="h-9 w-9 rounded-full object-cover ring-1 ring-gold/40"
              onError={(e) => {
                (e.currentTarget as HTMLImageElement).style.visibility = "hidden";
              }}
            />
            <div className="leading-tight">
              <div className="gold-text-static text-sm font-extrabold">Cookies Tracker</div>
              <div className="text-[10px] text-muted-foreground">لوحة تحكم فريق كوكيز</div>
            </div>
          </div>
          <nav className="hidden items-center gap-6 text-sm text-muted-foreground md:flex" aria-label="روابط الصفحة">
            <a href="#features" className="transition-colors hover:text-gold-bright">المميزات</a>
            <a href="#how" className="transition-colors hover:text-gold-bright">كيف يعمل</a>
            <a href="#integration" className="transition-colors hover:text-gold-bright">الربط</a>
          </nav>
          <div className="flex items-center gap-2">
            {!config.oauthEnabled && (
              <button
                onClick={onDemoLogin}
                disabled={demoLoading}
                className="hidden rounded-lg border border-gold/25 px-3 py-2 text-xs font-semibold text-gold-bright transition-colors hover:bg-gold/10 sm:block"
              >
                {demoLoading ? "..." : "دخول تجريبي"}
              </button>
            )}
            <a href="/api/auth/discord" className={cn("gold-btn inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-bold", !config.oauthEnabled && "opacity-90")}>
              <DiscordIcon className="h-4 w-4" />
              دخول عبر ديسكورد
            </a>
          </div>
        </div>
      </header>

      {/* ═══════════ الهيرو ═══════════ */}
      <main className="flex-1">
        <section className="relative overflow-hidden pt-28 pb-16 md:pt-36 md:pb-24">
          <div className="bg-grid absolute inset-0" aria-hidden />
          <div
            className="glow-orb h-72 w-72 bg-[rgba(212,175,55,0.14)]"
            style={{ top: "-60px", insetInlineStart: "62%", "--dur": "18s", "--dx": "50px", "--dy": "40px" } as React.CSSProperties}
            aria-hidden
          />
          <div
            className="glow-orb h-64 w-64 bg-[rgba(212,175,55,0.09)]"
            style={{ bottom: "-40px", insetInlineEnd: "70%", "--dur": "14s", "--dx": "-40px" } as React.CSSProperties}
            aria-hidden
          />
          <GoldDust />

          <div className="relative mx-auto grid max-w-7xl items-center gap-12 px-4 md:px-6 lg:grid-cols-2">
            {/* النص */}
            <div>
              <Reveal>
                <span className="inline-flex items-center gap-2 rounded-full border border-gold/25 bg-gold/5 px-4 py-1.5 text-xs font-semibold text-gold-bright">
                  <span className="h-1.5 w-1.5 rounded-full bg-gold" />
                  الواجهة الرسمية لبوت فريق كوكيز
                </span>
              </Reveal>
              <Reveal delay={90}>
                <h1 className="mt-5 text-5xl font-black leading-[1.15] md:text-6xl lg:text-7xl">
                  <span className="gold-text">كوكيز تراكر</span>
                  <span className="mt-3 block text-2xl font-extrabold text-cream md:text-3xl">
                    قوة البوت… بوجهٍ أقوى.
                  </span>
                </h1>
              </Reveal>
              <Reveal delay={180}>
                <p className="mt-5 max-w-xl text-base leading-8 text-muted-foreground md:text-lg">
                  كل ما يسجله فريقك في ديسكورد — فصول، أعمال، مكافآت، أشهر —
                  يصبح هنا لوحة تحكم كاملة تُدار بضغطة، وتُحدَّث لحظيًا من نفس قاعدة البيانات.
                </p>
              </Reveal>
              <Reveal delay={260}>
                <div className="mt-8 flex flex-wrap items-center gap-3">
                  <a
                    href="/api/auth/discord"
                    className="gold-btn inline-flex items-center gap-2.5 rounded-xl px-7 py-3.5 text-base font-extrabold"
                  >
                    <DiscordIcon className="h-5 w-5" />
                    ربط حساب ديسكورد
                  </a>
                  {!config.oauthEnabled && (
                    <button
                      onClick={onDemoLogin}
                      disabled={demoLoading}
                      className="inline-flex items-center gap-2 rounded-xl border border-gold/30 px-6 py-3.5 text-sm font-bold text-gold-bright transition-all hover:bg-gold/10"
                    >
                      <Compass className="h-4 w-4" />
                      {demoLoading ? "جارٍ الدخول…" : "استكشاف اللوحة (تجريبي)"}
                    </button>
                  )}
                  <a
                    href="#features"
                    className="inline-flex items-center gap-1.5 rounded-xl px-4 py-3.5 text-sm font-semibold text-muted-foreground transition-colors hover:text-cream"
                  >
                    <ArrowDown className="h-4 w-4" />
                    تعرّف أكثر
                  </a>
                </div>
              </Reveal>
              <Reveal delay={340}>
                <div className="mt-8 flex flex-wrap gap-x-8 gap-y-3 text-sm">
                  <div>
                    <div className="font-black text-gold-bright"><Counter value={s.chapters} />+</div>
                    <div className="text-xs text-muted-foreground">فصل محتسب هذا الشهر</div>
                  </div>
                  <div>
                    <div className="font-black text-gold-bright"><Counter value={s.members} /></div>
                    <div className="text-xs text-muted-foreground">عضو في الفريق</div>
                  </div>
                  <div>
                    <div className="font-black text-gold-bright"><Counter value={s.works} /></div>
                    <div className="text-xs text-muted-foreground">عمل جارٍ</div>
                  </div>
                </div>
              </Reveal>
              {authError && (
                <Reveal delay={400}>
                  <p className="mt-4 rounded-lg border border-bad/30 bg-bad/10 px-4 py-2.5 text-sm text-[#ff9a9c]">
                    {authError === "notmember"
                      ? "حسابك ليس عضوًا في سيرفر الفريق — انضم أولًا ثم أعد المحاولة."
                      : "تعذّر إكمال تسجيل الدخول — حاول من جديد."}
                  </p>
                </Reveal>
              )}
            </div>

            {/* البطاقة البصرية */}
            <Reveal delay={200} className="relative mx-auto w-full max-w-md lg:max-w-none">
              <div className="relative aspect-square">
                {/* مدار */}
                <div className="orbit rounded-full border border-dashed border-gold/20" style={{ "--dur": "26s" } as React.CSSProperties} aria-hidden>
                  <span className="absolute -top-1.5 left-1/2 h-3 w-3 -translate-x-1/2 rounded-full bg-gold shadow-[0_0_14px_rgba(212,175,55,0.9)]" />
                </div>
                <div className="orbit rounded-full border border-gold/10" style={{ inset: "9%", "--dur": "17s", animationDirection: "reverse" } as React.CSSProperties} aria-hidden>
                  <span className="absolute bottom-2 left-1/2 h-2 w-2 -translate-x-1/2 rounded-full bg-gold-bright/80" />
                </div>

                {/* الشعار */}
                <div className="glass-card absolute inset-[14%] flex items-center justify-center overflow-hidden rounded-[2rem]">
                  <div
                    className="glow-orb inset-x-8 top-8 h-40 bg-[rgba(212,175,55,0.18)]"
                    style={{ "--dur": "12s" } as React.CSSProperties}
                    aria-hidden
                  />
                  { }
                  <img
                    src="/cookie-logo.png"
                    alt="شعار كوكيز تراكر الذهبي"
                    className="relative h-3/5 w-3/5 rounded-full object-cover shadow-[0_0_80px_-10px_rgba(212,175,55,0.55)]"
                    onError={(e) => {
                      const el = e.currentTarget as HTMLImageElement;
                      el.style.display = "none";
                      el.parentElement?.classList.add("after:content-['C']");
                    }}
                  />
                </div>

                {/* شرائح عائمة — مواقع فعلية خارج حدود البطاقة */}
                <div
                  className="glass-card absolute -top-3 right-0 flex items-center gap-2 px-3.5 py-2 text-xs font-bold"
                  style={{ animation: "dust-float 7s ease-in-out infinite" }}
                >
                  <LiveBadge label="" />
                  بث حي للسجلات
                </div>
                <div
                  className="glass-card absolute top-[40%] -left-2 flex items-center gap-2 px-3.5 py-2 text-xs font-bold text-gold-bright"
                  style={{ animation: "dust-float 9s ease-in-out infinite", animationDelay: "1.2s" }}
                >
                  <Zap className="h-3.5 w-3.5 text-gold" />
                  تسجيل جديد الآن
                </div>
                <div
                  className="glass-card absolute -bottom-3 left-6 flex items-center gap-2 px-3.5 py-2 text-xs font-bold"
                  style={{ animation: "dust-float 8s ease-in-out infinite", animationDelay: "0.6s" }}
                >
                  <span className="text-cream-dim">مستحق كيربي</span>
                  <span className="ms-2 font-black text-[#57f287]">{money(12.4)}</span>
                </div>
              </div>
            </Reveal>
          </div>
        </section>

        {/* ═══════════ الماركي ═══════════ */}
        <div className="marquee border-y border-gold/12 bg-ink-900/60 py-3" aria-hidden>
          <div className="marquee-track text-sm font-semibold text-gold-bright/80">
            {[...marqueeItems, ...marqueeItems].map((item, i) => (
              <span key={i} className="flex items-center gap-3 whitespace-nowrap">
                <span className="h-1 w-1 rounded-full bg-gold/60" />
                {item}
              </span>
            ))}
          </div>
        </div>

        {/* ═══════════ الأرقام ═══════════ */}
        <section className="mx-auto max-w-7xl px-4 py-16 md:px-6 md:py-20">
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            {[
              { label: "فصول هذا الشهر", value: s.chapters, icon: Zap },
              { label: "أعضاء الفريق", value: s.members, icon: Users },
              { label: "أعمال نشطة", value: s.works, icon: FolderKanban },
              { label: "المستحقات", value: s.revenue, money: true, icon: Database },
            ].map((card, i) => (
              <Reveal key={card.label} delay={i * 80}>
                <div className="glass-card spot-card p-6">
                  <card.icon className="mb-4 h-5 w-5 text-gold" aria-hidden />
                  <div className="text-3xl font-black text-cream md:text-4xl">
                    {card.money ? (
                      <Counter value={card.value} decimals={2} prefix="$" />
                    ) : (
                      <Counter value={card.value} />
                    )}
                  </div>
                  <div className="mt-1 text-sm text-muted-foreground">{card.label}</div>
                </div>
              </Reveal>
            ))}
          </div>
        </section>

        {/* ═══════════ المميزات ═══════════ */}
        <section id="features" className="mx-auto max-w-7xl scroll-mt-24 px-4 pb-16 md:px-6 md:pb-24">
          <Reveal>
            <div className="mb-10 text-center">
              <div className="mb-2 inline-flex items-center gap-2 text-xs font-bold tracking-wide text-gold">
                <span className="h-px w-8 bg-gradient-to-l from-gold to-transparent" />
                لماذا الداشبورد؟
                <span className="h-px w-8 bg-gradient-to-r from-gold to-transparent" />
              </div>
              <h2 className="text-3xl font-black md:text-4xl">كل شيء يفعله البوت… <span className="gold-text-static">وأكثر بكثير</span></h2>
              <p className="mx-auto mt-3 max-w-2xl text-sm leading-7 text-muted-foreground md:text-base">
                ليس بديلًا مبتسرًا — بل واجهة تحكم أقوى بنفس البيانات، مصممة للفريق كله.
              </p>
            </div>
          </Reveal>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map((f, i) => (
              <Reveal key={f.title} delay={i * 70}>
                <article className="glass-card spot-card group h-full p-6">
                  <div className="mb-4 inline-flex rounded-xl border border-gold/20 bg-gold/8 p-3 transition-transform duration-300 group-hover:scale-110">
                    <f.icon className="h-5 w-5 text-gold-bright" aria-hidden />
                  </div>
                  <h3 className="mb-2 text-lg font-extrabold">{f.title}</h3>
                  <p className="text-sm leading-7 text-muted-foreground">{f.desc}</p>
                </article>
              </Reveal>
            ))}
          </div>
        </section>

        {/* ═══════════ كيف يعمل ═══════════ */}
        <section id="how" className="border-y border-gold/10 bg-ink-900/40 py-16 md:py-24">
          <div className="mx-auto max-w-7xl scroll-mt-24 px-4 md:px-6">
            <Reveal>
              <div className="mb-12 text-center">
                <div className="mb-2 inline-flex items-center gap-2 text-xs font-bold tracking-wide text-gold">
                  <span className="h-px w-8 bg-gradient-to-l from-gold to-transparent" />
                  ثلاث خطوات
                  <span className="h-px w-8 bg-gradient-to-r from-gold to-transparent" />
                </div>
                <h2 className="text-3xl font-black md:text-4xl">من ديسكورد إلى <span className="gold-text-static">التحكم الكامل</span></h2>
              </div>
            </Reveal>
            <div className="relative grid gap-10 md:grid-cols-3">
              <div className="hairline absolute top-8 hidden w-full md:block" aria-hidden />
              {STEPS.map((st, i) => (
                <Reveal key={st.n} delay={i * 120} className="relative text-center md:text-start">
                  <div className="relative z-10 mx-auto mb-5 flex h-16 w-16 items-center justify-center rounded-2xl border border-gold/30 bg-ink-950 text-xl font-black text-gold shadow-[0_0_30px_-8px_rgba(212,175,55,0.5)] md:mx-0">
                    {st.n}
                  </div>
                  <h3 className="mb-2 text-xl font-extrabold">{st.title}</h3>
                  <p className="mx-auto max-w-xs text-sm leading-7 text-muted-foreground md:mx-0">{st.desc}</p>
                </Reveal>
              ))}
            </div>
          </div>
        </section>

        {/* ═══════════ الربط المباشر ═══════════ */}
        <section id="integration" className="mx-auto max-w-7xl scroll-mt-24 px-4 py-16 md:px-6 md:py-24">
          <div className="grid items-center gap-10 lg:grid-cols-2">
            <Reveal>
              <div className="mb-2 inline-flex items-center gap-2 text-xs font-bold tracking-wide text-gold">
                <span className="h-px w-8 bg-gradient-to-l from-gold to-transparent" />
                ربط وثيق حقيقي
              </div>
              <h2 className="text-3xl font-black md:text-4xl">
                مصدر واحد للحقيقة: <span className="gold-text-static">MongoDB</span>
              </h2>
              <p className="mt-4 max-w-xl text-sm leading-8 text-muted-foreground md:text-base">
                البوت يكتب في قاعدة البيانات، والموقع يقرأها مباشرة — والعكس صحيح.
                أي تسجيل في ديسكورد يظهر هنا، وأي تعديل من هنا يراه البوت.
                بلا وسطاء، وبلا فقدان بيانات عند نقل الاستضافة.
              </p>
              <ul className="mt-6 space-y-3 text-sm">
                {[
                  "نفس المجموعات: records و months و members و settings",
                  "حرس ضد الكتابة الفارغة — بياناتك لا تُمسح بالخطأ",
                  "شهر جديد = سجلات نظفة مع بقاء الأعمال والأعضاء",
                ].map((t) => (
                  <li key={t} className="flex items-start gap-2.5">
                    <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-gold" aria-hidden />
                    <span className="text-muted-foreground">{t}</span>
                  </li>
                ))}
              </ul>
            </Reveal>
            <Reveal delay={150}>
              <div className="glass-card overflow-hidden">
                <div className="flex items-center gap-2 border-b border-gold/10 px-5 py-3">
                  <span className="h-2.5 w-2.5 rounded-full bg-bad/70" />
                  <span className="h-2.5 w-2.5 rounded-full bg-gold/70" />
                  <span className="h-2.5 w-2.5 rounded-full bg-[#57f287]/70" />
                  <span className="ms-3 text-xs text-muted-foreground">work_bot — mongodb</span>
                </div>
                <div className="scroll-area max-h-72 p-5 font-mono text-xs leading-6" dir="ltr">
                  {[
                    { c: "records", d: "{ _id: \"records\", data: { … } }", live: true },
                    { c: "records", d: "{ _id: \"works\", data: [ … ] }", live: false },
                    { c: "months", d: "{ _id: \"2025-09\", name: \"شهر كوكيز\" }", live: true },
                    { c: "members", d: "{ _id: \"1095…\", nickname: \"أبورين\" }", live: false },
                    { c: "settings", d: "{ active_month, specialties, currency }", live: false },
                    { c: "audit_log", d: "{ action, moderator_id, details }", live: true },
                  ].map((row, i) => (
                    <div
                      key={i}
                      className="tick-in flex items-center justify-between gap-3 rounded-lg px-3 py-2 hover:bg-gold/5"
                      style={{ animationDelay: `${i * 0.12}s` }}
                    >
                      <span className="text-gold-bright">{row.c}</span>
                      <span className="truncate text-muted-foreground">{row.d}</span>
                      {row.live ? (
                        <span className="inline-flex items-center gap-1.5 text-[10px] font-bold text-[#57f287]">
                          <span className="live-dot" /> live
                        </span>
                      ) : (
                        <Link2 className="h-3.5 w-3.5 text-gold/40" aria-hidden />
                      )}
                    </div>
                  ))}
                </div>
              </div>
            </Reveal>
          </div>
        </section>

        {/* ═══════════ دعوة أخيرة ═══════════ */}
        <section className="mx-auto max-w-5xl px-4 pb-20 md:px-6">
          <Reveal>
            <div className="glass-card spot-card relative overflow-hidden p-10 text-center md:p-14">
              <div
                className="glow-orb left-1/2 top-0 h-56 w-56 -translate-x-1/2 bg-[rgba(212,175,55,0.16)]"
                style={{ "--dur": "10s" } as React.CSSProperties}
                aria-hidden
              />
              <h2 className="relative text-3xl font-black md:text-4xl">
                جاهز تتحكم بفريقك <span className="gold-text">كاملًا؟</span>
              </h2>
              <p className="relative mx-auto mt-3 max-w-lg text-sm leading-7 text-muted-foreground md:text-base">
                اربط حسابك الآن — ثلاثون ثانية تفصلك عن كل بيانات الفريق.
              </p>
              <div className="relative mt-8 flex flex-wrap justify-center gap-3">
                <a href="/api/auth/discord" className="gold-btn inline-flex items-center gap-2.5 rounded-xl px-8 py-4 text-base font-extrabold">
                  <DiscordIcon className="h-5 w-5" />
                  دخول عبر ديسكورد
                </a>
                {!config.oauthEnabled && (
                  <button
                    onClick={onDemoLogin}
                    disabled={demoLoading}
                    className="rounded-xl border border-gold/30 px-7 py-4 text-sm font-bold text-gold-bright transition-all hover:bg-gold/10"
                  >
                    {demoLoading ? "جارٍ الدخول…" : "دخول تجريبي"}
                  </button>
                )}
              </div>
              {config.mode === "demo" && (
                <p className="relative mt-5 text-xs text-muted-foreground">
                  الوضع الحالي تجريبي ببيانات نموذجية — عند ضبط MONGODB_URI ستصلك بيانات البوت الحقيقية تلقائيًا.
                </p>
              )}
            </div>
          </Reveal>
        </section>
      </main>

      {/* ═══════════ الفوتر ─ ملتصق بالأسفل ═══════════ */}
      <footer className="mt-auto border-t border-gold/10 bg-ink-900/60">
        <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-4 px-4 py-6 pb-[max(1.5rem,env(safe-area-inset-bottom))] text-sm text-muted-foreground md:flex-row md:px-6">
          <div className="flex items-center gap-2.5">
            { }
            <img
              src="/cookie-logo.png"
              alt=""
              className="h-7 w-7 rounded-full object-cover ring-1 ring-gold/30"
              onError={(e) => (e.currentTarget as HTMLImageElement).style.visibility = "hidden"}
            />
            <span className="font-bold text-cream">Cookies Tracker</span>
          </div>
          <p>لوحة تحكم فريق كوكيز — مترابطة مع البوت لحظيًا</p>
          <p className="text-xs">ذكاء بلمسة ذهبية</p>
        </div>
      </footer>
    </div>
  );
}
