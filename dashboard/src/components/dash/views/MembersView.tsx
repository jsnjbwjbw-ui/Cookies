"use client";

import { useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type MemberDTO } from "@/lib/client/api";
import { useApp } from "@/lib/client/store";
import { Avatar, money, timeAgo, Reveal } from "@/components/dash/fx";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Search, Crown, Pencil, Check, X, MoonStar, CalendarClock } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

export default function MembersView({ isAdmin }: { isAdmin: boolean }) {
  const { selectedMember, setSelectedMember } = useApp();
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<"all" | "active" | "inactive">("all");
  const [editing, setEditing] = useState<string | null>(null);
  const [nickDraft, setNickDraft] = useState("");

  const { data, isLoading } = useQuery({ queryKey: ["members"], queryFn: api.members, refetchInterval: 25000 });

  const rename = useMutation({
    mutationFn: (p: { id: string; nickname: string }) => api.updateNickname(p.id, p.nickname),
    onSuccess: () => {
      toast.success("تم تحديث الاسم المعروض");
      setEditing(null);
      qc.invalidateQueries({ queryKey: ["members"] });
      qc.invalidateQueries({ queryKey: ["overview"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const members = useMemo(() => {
    let list = data?.members ?? [];
    if (filter === "active") list = list.filter((m) => m.hasActivityThisMonth);
    if (filter === "inactive") list = list.filter((m) => !m.hasActivityThisMonth);
    if (q.trim()) {
      const needle = q.trim().toLowerCase();
      list = list.filter(
        (m) => m.name.toLowerCase().includes(needle) || (m.username || "").toLowerCase().includes(needle)
      );
    }
    return list.sort((a, b) => b.amountThisMonth - a.amountThisMonth || b.chaptersAllTime - a.chaptersAllTime);
  }, [data, q, filter]);

  const selected = members.find((m) => m.id === selectedMember) ?? (data?.members ?? []).find((m) => m.id === selectedMember);

  if (isLoading) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {[...Array(6)].map((_, i) => <div key={i} className="glass-card h-40 animate-pulse" />)}
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {/* أدوات التصفية */}
      <Reveal>
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative flex-1 sm:max-w-xs">
            <Search className="absolute start-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <Input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="ابحث بالاسم أو اليوزر…"
              className="border-gold/20 bg-ink-850 ps-9"
              aria-label="بحث عن عضو"
            />
          </div>
          <Select value={filter} onValueChange={(v) => setFilter(v as typeof filter)}>
            <SelectTrigger className="w-44 border-gold/20 bg-ink-850" aria-label="تصفية الأعضاء">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">كل الأعضاء</SelectItem>
              <SelectItem value="active">نشط هذا الشهر</SelectItem>
              <SelectItem value="inactive">بلا عمل هذا الشهر</SelectItem>
            </SelectContent>
          </Select>
          <span className="text-xs text-muted-foreground">{members.length} عضو</span>
        </div>
      </Reveal>

      {/* الشبكة */}
      {members.length === 0 ? (
        <div className="glass-card p-12 text-center">
          <MoonStar className="mx-auto mb-3 h-8 w-8 text-gold/50" aria-hidden />
          <p className="text-sm text-muted-foreground">لا نتائج مطابقة</p>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {members.map((m, i) => (
            <Reveal key={m.id} delay={Math.min(i * 50, 300)}>
              <button
                onClick={() => setSelectedMember(m.id)}
                className="glass-card spot-card block w-full p-4 text-start"
              >
                <div className="flex items-center gap-3">
                  <Avatar src={m.avatar} name={m.name} size={44} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <span className="truncate text-sm font-extrabold">{m.name}</span>
                      {members[i]?.amountThisMonth > 0 && members.findIndex((x) => x.amountThisMonth > 0) === i && (
                        <Crown className="h-3.5 w-3.5 shrink-0 text-gold" aria-label="المركز الأول" />
                      )}
                    </div>
                    <div className="truncate text-[11px] text-muted-foreground" dir="ltr">@{m.username || m.id.slice(0, 8)}</div>
                  </div>
                </div>
                <div className="mt-4 grid grid-cols-3 gap-2 border-t border-gold/10 pt-3 text-center">
                  <div>
                    <div className="text-lg font-black text-cream">{m.chaptersThisMonth}</div>
                    <div className="text-[10px] text-muted-foreground">فصل الشهر</div>
                  </div>
                  <div>
                    <div className="text-lg font-black text-[#57f287]">{money(m.amountThisMonth)}</div>
                    <div className="text-[10px] text-muted-foreground">صافي الشهر</div>
                  </div>
                  <div>
                    <div className="text-lg font-black text-gold-bright">{m.chaptersAllTime}</div>
                    <div className="text-[10px] text-muted-foreground">كل الوقت</div>
                  </div>
                </div>
                {!m.hasActivityThisMonth && (
                  <div className="mt-3 rounded-lg border border-gold/15 bg-gold/5 px-3 py-1.5 text-center text-[11px] font-semibold text-gold-bright/80">
                    بلا عمل مسجل هذا الشهر — لكنه محفوظ دائمًا
                  </div>
                )}
              </button>
            </Reveal>
          ))}
        </div>
      )}

      {/* نافذة التفاصيل */}
      <Dialog open={Boolean(selected)} onOpenChange={(o) => !o && setSelectedMember(null)}>
        <DialogContent className="max-h-[85vh] max-w-lg overflow-y-auto border-gold/25 bg-ink-900" dir="rtl">
          {selected && <MemberDetail
            m={selected as MemberDTO}
            isAdmin={isAdmin}
            editing={editing === selected.id}
            nickDraft={nickDraft}
            setNickDraft={setNickDraft}
            startEdit={() => {
              setEditing(selected.id);
              setNickDraft(selected.nickname || "");
            }}
            cancelEdit={() => setEditing(null)}
            saveEdit={() => rename.mutate({ id: selected.id, nickname: nickDraft })}
            saving={rename.isPending}
          />}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function MemberDetail({
  m, isAdmin, editing, nickDraft, setNickDraft, startEdit, cancelEdit, saveEdit, saving,
}: {
  m: MemberDTO;
  isAdmin: boolean;
  editing: boolean;
  nickDraft: string;
  setNickDraft: (v: string) => void;
  startEdit: () => void;
  cancelEdit: () => void;
  saveEdit: () => void;
  saving: boolean;
}) {
  const works = Object.entries(m.perWork).sort((a, b) => b[1] - a[1]);
  const types = Object.entries(m.perType).sort((a, b) => b[1] - a[1]);
  const maxWork = Math.max(1, ...works.map(([, v]) => v));

  return (
    <div>
      <DialogHeader>
        <DialogTitle className="flex items-center gap-3">
          <Avatar src={m.avatar} name={m.name} size={48} />
          <div>
            {editing ? (
              <div className="flex items-center gap-2">
                <Input value={nickDraft} onChange={(e) => setNickDraft(e.target.value)} className="h-9 w-48 border-gold/30" placeholder="النك الجديد" autoFocus />
                <Button size="icon" variant="secondary" className="h-9 w-9" onClick={saveEdit} disabled={saving} aria-label="حفظ الاسم">
                  <Check className="h-4 w-4" />
                </Button>
                <Button size="icon" variant="secondary" className="h-9 w-9" onClick={cancelEdit} aria-label="إلغاء">
                  <X className="h-4 w-4" />
                </Button>
              </div>
            ) : (
              <span className="flex items-center gap-2">
                {m.name}
                {isAdmin && (
                  <button onClick={startEdit} className="rounded-md p-1 text-muted-foreground hover:bg-gold/10 hover:text-gold" aria-label="تعديل الاسم المعروض" title="تعديل الاسم المعروض">
                    <Pencil className="h-3.5 w-3.5" />
                  </button>
                )}
              </span>
            )}
            <div className="text-xs font-normal text-muted-foreground" dir="ltr">@{m.username || m.id}</div>
          </div>
        </DialogTitle>
      </DialogHeader>

      <div className="mt-5 grid grid-cols-3 gap-3 text-center">
        <div className="glass-card p-3">
          <div className="text-xl font-black text-cream">{m.chaptersThisMonth}</div>
          <div className="text-[10px] text-muted-foreground">فصل هذا الشهر</div>
        </div>
        <div className="glass-card p-3">
          <div className="text-xl font-black text-[#57f287]">{money(m.amountThisMonth)}</div>
          <div className="text-[10px] text-muted-foreground">صافي الشهر</div>
        </div>
        <div className="glass-card p-3">
          <div className="text-xl font-black text-gold-bright">{m.chaptersAllTime}</div>
          <div className="text-[10px] text-muted-foreground">فصول كل الوقت</div>
        </div>
      </div>

      <div className="mt-5 space-y-4">
        <div>
          <h4 className="mb-2 text-xs font-extrabold text-gold-bright">تفصيل الأعمال — هذا الشهر</h4>
          {works.length === 0 ? (
            <p className="rounded-xl border border-gold/15 bg-gold/5 px-4 py-3 text-xs text-muted-foreground">
              لا عمل مسجل لهذا العضو في الشهر النشط — سجلاته من الشهور السابقة محفوظة بالكامل.
            </p>
          ) : (
            <div className="space-y-2">
              {works.map(([w, c]) => (
                <div key={w} className="flex items-center gap-3">
                  <span className="w-32 truncate text-xs font-bold">{w}</span>
                  <div className="h-2 flex-1 overflow-hidden rounded-full bg-ink-700">
                    <div className="gold-bar h-full" style={{ width: `${(c / maxWork) * 100}%` }} />
                  </div>
                  <span className="w-14 text-end text-xs font-black text-gold-bright">{c} فصل</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <div>
          <h4 className="mb-2 text-xs font-extrabold text-gold-bright">التخصصات</h4>
          <div className="flex flex-wrap gap-2">
            {types.length === 0 && <span className="text-xs text-muted-foreground">لا تخصصات هذا الشهر</span>}
            {types.map(([tp, c]) => (
              <span key={tp} className="rounded-full border border-gold/25 bg-gold/8 px-3 py-1 text-[11px] font-bold text-gold-bright">
                {tp.replace("_", " ")} • {c}
              </span>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
          <CalendarClock className="h-3.5 w-3.5" aria-hidden />
          آخر نشاط: {m.lastActivity ? timeAgo(m.lastActivity) : "لا يوجد"}
        </div>
      </div>
    </div>
  );
}
