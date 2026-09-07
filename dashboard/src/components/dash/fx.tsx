"use client";

import { useEffect, useRef, useState, type ReactNode, type CSSProperties } from "react";
import { cn } from "@/lib/utils";

/* ─────────── الظهور عند التمرير (IntersectionObserver خفيف) ─────────── */
export function Reveal({
  children,
  delay = 0,
  className,
  as: Tag = "div",
}: {
  children: ReactNode;
  delay?: number;
  className?: string;
  as?: "div" | "section" | "span" | "li";
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [shown, setShown] = useState(false);
  useEffect(() => {
    const el = ref.current;
    // مؤقت أمان: المحتوى لا يبقى مخفيًا أبدًا حتى لو فشل الـ Observer
    const failSafe = setTimeout(() => setShown(true), 2600);
    if (!el) return;
    if (typeof IntersectionObserver === "undefined") {
      const raf = requestAnimationFrame(() => setShown(true));
      return () => {
        cancelAnimationFrame(raf);
        clearTimeout(failSafe);
      };
    }
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) {
            setShown(true);
            io.disconnect();
            clearTimeout(failSafe);
          }
        }
      },
      { threshold: 0.12 }
    );
    io.observe(el);
    return () => {
      io.disconnect();
      clearTimeout(failSafe);
    };
  }, []);
  return (
    <Tag
      ref={ref as never}
      className={cn("reveal", shown && "in", className)}
      style={{ "--reveal-delay": `${delay}ms` } as CSSProperties}
    >
      {children}
    </Tag>
  );
}

/* ─────────── عدّاد متحرك يعمل مرة واحدة عند الظهور ─────────── */
export function Counter({
  value,
  decimals = 0,
  prefix = "",
  suffix = "",
  duration = 1200,
  className,
}: {
  value: number;
  decimals?: number;
  prefix?: string;
  suffix?: string;
  duration?: number;
  className?: string;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const [display, setDisplay] = useState(0);
  const started = useRef(false);
  const fromRef = useRef(0);
  const visibleRef = useRef(false);

  useEffect(() => {
    const el = ref.current;
    // مؤقت أمان: العدّاد يعمل حتى لو لم يُطلق الـ Observer
    const failSafe = setTimeout(() => {
      visibleRef.current = true;
    }, 2200);
    if (!el) return;
    if (typeof IntersectionObserver === "undefined") {
      visibleRef.current = true;
      clearTimeout(failSafe);
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          if (e.isIntersecting) {
            visibleRef.current = true;
            io.disconnect();
            clearTimeout(failSafe);
          }
        }
      },
      { threshold: 0.3 }
    );
    io.observe(el);
    return () => {
      io.disconnect();
      clearTimeout(failSafe);
    };
  }, []);

  useEffect(() => {
    let raf = 0;
    const animate = () => {
      started.current = true;
      const from = fromRef.current;
      const t0 = performance.now();
      const tick = (t: number) => {
        const p = Math.min(1, (t - t0) / duration);
        const eased = 1 - Math.pow(1 - p, 3);
        const v = from + (value - from) * eased;
        setDisplay(v);
        fromRef.current = v;
        if (p < 1) raf = requestAnimationFrame(tick);
      };
      raf = requestAnimationFrame(tick);
    };

    if (visibleRef.current) {
      raf = requestAnimationFrame(animate);
      return () => cancelAnimationFrame(raf);
    }
    const wait = setInterval(() => {
      if (visibleRef.current) {
        clearInterval(wait);
        animate();
      }
    }, 120);
    return () => clearInterval(wait);
  }, [value, duration]);

  const formatted = display.toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
  return (
    <span ref={ref} className={className}>
      {prefix}
      {formatted}
      {suffix}
    </span>
  );
}

/* ─────────── غبار ذهبي — عدد ثابت قليل، CSS فقط ─────────── */
const DUST = [
  { l: "6%", t: "18%", s: 5, d: 9, dx: 14 },
  { l: "14%", t: "64%", s: 3, d: 11, dx: -10 },
  { l: "24%", t: "34%", s: 4, d: 8, dx: 8 },
  { l: "38%", t: "78%", s: 3, d: 12, dx: -14 },
  { l: "52%", t: "12%", s: 5, d: 10, dx: 12 },
  { l: "63%", t: "58%", s: 4, d: 9, dx: -8 },
  { l: "74%", t: "26%", s: 3, d: 13, dx: 10 },
  { l: "84%", t: "66%", s: 5, d: 8, dx: -12 },
  { l: "91%", t: "38%", s: 3, d: 11, dx: 8 },
  { l: "45%", t: "44%", s: 3, d: 10, dx: -6 },
  { l: "70%", t: "86%", s: 4, d: 12, dx: 10 },
  { l: "18%", t: "88%", s: 3, d: 9, dx: -10 },
];

export function GoldDust() {
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
      {DUST.map((d, i) => (
        <span
          key={i}
          className="dust"
          style={
            {
              left: d.l,
              top: d.t,
              width: d.s,
              height: d.s,
              "--dur": `${d.d}s`,
              "--dx": `${d.dx}px`,
              "--delay": `${(i % 5) * 0.9}s`,
            } as CSSProperties
          }
        />
      ))}
    </div>
  );
}

/* ─────────── أفاتار عضو — صورة ديسكورد أو حرف أول ذهبي ─────────── */
export function Avatar({
  src,
  name,
  size = 40,
  ring = true,
}: {
  src?: string;
  name: string;
  size?: number;
  ring?: boolean;
}) {
  const [err, setErr] = useState(false);
  const initial = (name || "؟").trim().charAt(0);
  return (
    <span
      className={cn(
        "relative inline-flex shrink-0 items-center justify-center overflow-hidden rounded-full",
        ring && "ring-1 ring-gold/40"
      )}
      style={{ width: size, height: size }}
    >
      {src && !err ? (
         
        <img
          src={src}
          alt={`أفاتار ${name}`}
          width={size}
          height={size}
          className="h-full w-full object-cover"
          loading="lazy"
          onError={() => setErr(true)}
        />
      ) : (
        <span
          className="flex h-full w-full items-center justify-center font-bold"
          style={{
            background: "linear-gradient(140deg, #2a2410, #16130a)",
            color: "#e9cf7d",
            fontSize: size * 0.42,
          }}
        >
          {initial}
        </span>
      )}
    </span>
  );
}

/* ─────────── شارة مباشر ─────────── */
export function LiveBadge({ label = "مباشر" }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-[rgba(87,242,135,0.25)] bg-[rgba(87,242,135,0.06)] px-3 py-1 text-xs font-semibold text-[#57f287]">
      <span className="live-dot" />
      {label}
    </span>
  );
}

/* ─────────── عنوان قسم ─────────── */
export function SectionTitle({ kicker, title, desc }: { kicker?: string; title: string; desc?: string }) {
  return (
    <div className="mb-8">
      {kicker && (
        <div className="mb-2 inline-flex items-center gap-2 text-xs font-bold tracking-wide text-gold">
          <span className="h-px w-8 bg-gradient-to-l from-gold to-transparent" />
          {kicker}
        </div>
      )}
      <h2 className="text-2xl font-extrabold md:text-3xl">{title}</h2>
      {desc && <p className="mt-2 max-w-2xl text-sm leading-7 text-muted-foreground">{desc}</p>}
    </div>
  );
}

/* ─────────── تنسيق المال ─────────── */
export function money(n: number, currency = "$"): string {
  const abs = Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${n < 0 ? "−" : ""}${currency}${abs}`;
}

export function timeAgo(iso?: string): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const s = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (s < 60) return "الآن";
  const m = Math.floor(s / 60);
  if (m < 60) return `منذ ${m} د`;
  const h = Math.floor(m / 60);
  if (h < 24) return `منذ ${h} س`;
  const d = Math.floor(h / 24);
  if (d < 30) return `منذ ${d} يوم`;
  return new Date(iso).toLocaleDateString("ar", { day: "numeric", month: "long" });
}
