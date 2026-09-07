"use client";

import { useState } from "react";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { api } from "@/lib/client/api";
import Landing from "@/components/site/Landing";
import Shell from "@/components/dash/Shell";
import { toast } from "sonner";

function Boot() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-5 bg-ink-950">
      { }
      <img
        src="/cookie-logo.png"
        alt="Cookies Tracker"
        className="h-20 w-20 rounded-full object-cover ring-1 ring-gold/40 shadow-[0_0_60px_-10px_rgba(212,175,55,0.5)]"
        style={{ animation: "dust-float 3s ease-in-out infinite" }}
        onError={(e) => (e.currentTarget as HTMLImageElement).style.visibility = "hidden"}
      />
      <div className="gold-text text-lg font-black">Cookies Tracker</div>
      <div className="h-1 w-40 overflow-hidden rounded-full bg-ink-800">
        <div className="gold-bar h-full w-1/2 rounded-full" />
      </div>
    </div>
  );
}

function CookiesApp() {
  const [demoLoading, setDemoLoading] = useState(false);
  const [authError, setAuthError] = useState<string | undefined>(
    typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("auth") || undefined : undefined
  );

  const { data: me, isLoading, refetch } = useQuery({
    queryKey: ["me"],
    queryFn: api.me,
    staleTime: 60_000,
  });

  async function demoLogin() {
    setDemoLoading(true);
    try {
      await api.demoLogin();
      await refetch();
      toast.success("تم الدخول بالجلسة التجريبية");
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setDemoLoading(false);
    }
  }

  if (isLoading || !me) return <Boot />;

  if (me.authenticated && me.user) {
    return <Shell me={me} />;
  }
  return (
    <Landing
      config={me.config}
      onDemoLogin={demoLogin}
      demoLoading={demoLoading}
      authError={authError}
    />
  );
}

export default function App() {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { retry: 1, refetchOnWindowFocus: true, staleTime: 5000 },
        },
      })
  );
  return (
    <QueryClientProvider client={client}>
      <CookiesApp />
    </QueryClientProvider>
  );
}
