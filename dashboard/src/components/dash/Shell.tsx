"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type MeResponse } from "@/lib/client/api";
import { useApp, type DashView } from "@/lib/client/store";
import { Avatar, LiveBadge } from "@/components/dash/fx";
import { cn } from "@/lib/utils";
import Overview from "@/components/dash/views/OverviewView";
import MembersView from "@/components/dash/views/MembersView";
import WorksView from "@/components/dash/views/WorksView";
import RecordsView from "@/components/dash/views/RecordsView";
import MonthsView from "@/components/dash/views/MonthsView";
import SpecialtiesView from "@/components/dash/views/SpecialtiesView";
import LiveView from "@/components/dash/views/LiveView";
import SettingsView from "@/components/dash/views/SettingsView";
import {
  LayoutDashboard, Users, FolderKanban, ListPlus, CalendarRange, Tags,
  Radio, Settings, LogOut, Menu, X, RefreshCcw,
} from "lucide-react";
import { toast } from "sonner";

const NAV: Array<{ key: DashView; label: string; icon: typeof Users }> = [
  { key: "overview", label: "نظرة عامة", icon: LayoutDashboard },
  { key: "members", label: "الأعضاء", icon: Users },
  { key: "works", label: "الأعمال", icon: FolderKanban },
  { key: "records", label: "السجلات", icon: ListPlus },
  { key: "months", label: "الأشهر", icon: CalendarRange },
  { key: "specialties", label: "التخصصات والأسعار", icon: Tags },
  { key: "live", label: "البث المباشر", icon: Radio },
  { key: "settings", label: "الإعدادات", icon: Settings },
];

const TITLES: Record<DashView, string> = {
  overview: "نظرة عامة",
  members: "الأعضاء",
  works: "الأعمال",
  records: "السجلات",
  months: "الأشهر",
  specialties: "التخصصات والأسعار",
  live: "البث المباشر",
  settings: "الإعدادات",
};

export default function Shell({ me }: { me: MeResponse }) {
  const { view, setView, sidebarOpen, setSidebarOpen } = useApp();
  const qc = useQueryClient();
  const user = me.user ?? { id: "", username: "", isAdmin: false };

  const { data: ov } = useQuery({
    queryKey: ["overview"],
    queryFn: api.overview,
    refetchInterval: 20000,
  });

  async function refreshAll() {
    await qc.invalidateQueries();
    toast.success("تم تحديث كل البيانات");
  }

  async function logout() {
    await api.logout();
    window.location.reload();
  }

  const sidebar = (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-3 px-5 py-5">
        { }
        <img
          src="/cookie-logo.png"
          alt="شعار Cookies Tracker"
          className="h-10 w-10 rounded-full object-cover ring-1 ring-gold/40"
          onError={(e) => (e.currentTarget as HTMLImageElement).style.visibility = "hidden"}
        />
        <div className="leading-tight">
          <div className="gold-text-static text-sm font-extrabold">Cookies Tracker</div>
          <div className="text-[10px] text-muted-foreground">لوحة تحكم فريق كوكيز</div>
        </div>
        <button
          className="ms-auto rounded-lg p-1.5 text-muted-foreground hover:bg-gold/10 lg:hidden"
          onClick={() => setSidebarOpen(false)}
          aria-label="إغلاق القائمة"
        >
          <X className="h-5 w-5" />
        </button>
      </div>
      <div className="hairline mx-5" />
      <nav className="scroll-area flex-1 space-y-1 px-3 py-4" aria-label="أقسام اللوحة">
        {NAV.map((item) => (
          <button
            key={item.key}
            onClick={() => setView(item.key)}
            className={cn(
              "group flex w-full items-center gap-3 rounded-xl px-4 py-2.5 text-sm font-semibold transition-all",
              view === item.key
                ? "border border-gold/25 bg-gold/10 text-gold-bright shadow-[inset_0_0_20px_-10px_rgba(212,175,55,0.4)]"
                : "border border-transparent text-muted-foreground hover:bg-gold/5 hover:text-cream"
            )}
            aria-current={view === item.key ? "page" : undefined}
          >
            <item.icon className={cn("h-4.5 w-4.5 h-[18px] w-[18px]", view === item.key ? "text-gold" : "text-muted-foreground group-hover:text-gold/70")} />
            {item.label}
            {view === item.key && <span className="ms-auto h-1.5 w-1.5 rounded-full bg-gold" />}
          </button>
        ))}
      </nav>
      <div className="hairline mx-5" />
      <div className="p-4">
        <div className="glass-card flex items-center gap-3 p-3">
          <Avatar src={user.avatar} name={user.globalName || user.username} size={38} />
          <div className="min-w-0 flex-1 leading-tight">
            <div className="truncate text-sm font-bold">{user.globalName || user.username}</div>
            <div className="text-[10px] text-muted-foreground">
              {user.demo ? "جلسة تجريبية" : user.isAdmin ? "مشرف" : "عضو"}
            </div>
          </div>
          <button
            onClick={logout}
            className="rounded-lg p-2 text-muted-foreground transition-colors hover:bg-bad/10 hover:text-[#ff7a7c]"
            aria-label="تسجيل الخروج"
            title="تسجيل الخروج"
          >
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  );

  return (
    <div className="flex min-h-screen bg-ink-950">
      {/* سايدبار سطح المكتب */}
      <aside className="sticky top-0 hidden h-screen w-64 shrink-0 border-s border-gold/10 bg-ink-900/60 lg:block">
        {sidebar}
      </aside>

      {/* سايدبار الجوال */}
      {sidebarOpen && (
        <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setSidebarOpen(false)} />
          <aside className="absolute inset-y-0 start-0 w-72 border-s border-gold/20 bg-ink-900 shadow-2xl">
            {sidebar}
          </aside>
        </div>
      )}

      {/* المحتوى */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-40 border-b border-gold/10 bg-ink-950/80 backdrop-blur-xl">
          <div className="flex h-16 items-center gap-3 px-4 md:px-6">
            <button
              className="rounded-lg border border-gold/20 p-2 text-gold-bright lg:hidden"
              onClick={() => setSidebarOpen(true)}
              aria-label="فتح القائمة"
            >
              <Menu className="h-5 w-5" />
            </button>
            <h1 className="text-lg font-extrabold">{TITLES[view]}</h1>
            <div className="ms-auto flex items-center gap-2.5">
              {ov?.activeMonthName && (
                <span className="hidden rounded-full border border-gold/25 bg-gold/8 px-3.5 py-1.5 text-xs font-bold text-gold-bright sm:inline-block">
                  {ov.activeMonthName}
                </span>
              )}
              <LiveBadge />
              <button
                onClick={refreshAll}
                className="rounded-lg border border-gold/20 p-2 text-muted-foreground transition-colors hover:bg-gold/10 hover:text-gold-bright"
                aria-label="تحديث البيانات"
                title="تحديث البيانات"
              >
                <RefreshCcw className="h-4 w-4" />
              </button>
              <Avatar src={user.avatar} name={user.globalName || user.username} size={34} />
            </div>
          </div>
        </header>

        <main className="flex-1 p-4 pb-[max(1.5rem,env(safe-area-inset-bottom))] md:p-6">
          <div className="mx-auto max-w-7xl">
            {view === "overview" && <Overview />}
            {view === "members" && <MembersView isAdmin={user.isAdmin} />}
            {view === "works" && <WorksView isAdmin={user.isAdmin} />}
            {view === "records" && <RecordsView isAdmin={user.isAdmin} />}
            {view === "months" && <MonthsView isAdmin={user.isAdmin} />}
            {view === "specialties" && <SpecialtiesView isAdmin={user.isAdmin} />}
            {view === "live" && <LiveView />}
            {view === "settings" && <SettingsView me={me} />}
          </div>
        </main>

        <footer className="border-t border-gold/10 bg-ink-900/40 py-3">
          <p className="text-center text-[11px] text-muted-foreground">
            Cookies Tracker — مترابط مع البوت لحظيًا • {ov?.mode === "demo" ? "وضع تجريبي" : "متصل بقاعدة البيانات"}
          </p>
        </footer>
      </div>
    </div>
  );
}
