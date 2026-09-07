"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type MonthDTO } from "@/lib/client/api";
import { money, Reveal } from "@/components/dash/fx";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { CalendarRange, Plus, CheckCircle2, Pencil, Trash2, Info } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

function nextMonthKey(active: string): string {
  const [y, m] = active.split("-").map(Number);
  return new Date(Date.UTC(y, m, 1)).toISOString().slice(0, 7);
}

export default function MonthsView({ isAdmin }: { isAdmin: boolean }) {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["months"], queryFn: api.months, refetchInterval: 30000 });

  const [createOpen, setCreateOpen] = useState(false);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");

  const invalidate = () => qc.invalidateQueries();

  const activate = useMutation({
    mutationFn: (key: string) => api.patchMonth({ key, activate: true }),
    onSuccess: () => { toast.success("تم تفعيل الشهر — كل الأوامر والعرض عليه الآن"); invalidate(); },
    onError: (e: Error) => toast.error(e.message),
  });

  const rename = useMutation({
    mutationFn: (p: { key: string; name: string }) => api.patchMonth({ key: p.key, name: p.name }),
    onSuccess: () => { toast.success("تم تسمية الشهر"); setRenaming(null); invalidate(); },
    onError: (e: Error) => toast.error(e.message),
  });

  const remove = useMutation({
    mutationFn: (key: string) => api.deleteMonth(key),
    onSuccess: (res) => { toast.success(`حُذف الشهر مع ${res.removed} سجل — بقية الشهور سليمة`); invalidate(); },
    onError: (e: Error) => toast.error(e.message),
  });

  if (isLoading) {
    return (
      <div className="space-y-4">
        {[...Array(3)].map((_, i) => <div key={i} className="glass-card h-32 animate-pulse" />)}
      </div>
    );
  }

  const months = [...(data?.months ?? [])].sort((a, b) => b._id.localeCompare(a._id));
  const active = data?.activeMonth ?? "";

  return (
    <div className="space-y-5">
      {/* شرح النظام */}
      <Reveal>
        <div className="glass-card flex items-start gap-3 border-gold/25 p-4">
          <Info className="mt-0.5 h-5 w-5 shrink-0 text-gold" aria-hidden />
          <div className="text-xs leading-6 text-muted-foreground">
            <span className="font-extrabold text-gold-bright">نظام مستدام: </span>
            الأعمال والأعضاء لا يُعاد تعيينهم أبدًا عند انتقال الشهور —
            السجلات فقط تُختم باسم الشهر. أنشئ شهرًا جديدًا وستبدأ الصفحة نظيفة مع بقاء كل التاريخ.
          </div>
        </div>
      </Reveal>

      {isAdmin && (
        <Reveal>
          <div className="flex justify-end">
            <Button onClick={() => setCreateOpen(true)} className="gold-btn border-0 font-extrabold">
              <Plus className="h-4 w-4" /> شهر جديد
            </Button>
          </div>
        </Reveal>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        {months.map((m, i) => (
          <MonthCard
            key={m._id}
            m={m}
            isActive={m._id === active}
            isAdmin={isAdmin}
            delay={i * 70}
            onActivate={() => activate.mutate(m._id)}
            activating={activate.isPending}
            onRenameStart={() => { setRenaming(m._id); setRenameDraft(m.name || ""); }}
            renaming={renaming === m._id}
            renameDraft={renameDraft}
            setRenameDraft={setRenameDraft}
            onRenameSave={() => rename.mutate({ key: m._id, name: renameDraft })}
            onRenameCancel={() => setRenaming(null)}
            busy={rename.isPending}
            onDelete={() => {
              if (confirm(`حذف شهر «${m.name || m._id}» مع ${m.recordsCount} سجل؟ لا يمكن التراجع.`)) remove.mutate(m._id);
            }}
          />
        ))}
      </div>

      <CreateMonthDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        suggestedKey={nextMonthKey(active)}
        currency={""}
      />
    </div>
  );
}

function MonthCard({
  m, isActive, isAdmin, delay, onActivate, activating, onRenameStart, renaming, renameDraft, setRenameDraft, onRenameSave, onRenameCancel, busy, onDelete,
}: {
  m: MonthDTO; isActive: boolean; isAdmin: boolean; delay: number;
  onActivate: () => void; activating: boolean;
  onRenameStart: () => void; renaming: boolean; renameDraft: string; setRenameDraft: (v: string) => void;
  onRenameSave: () => void; onRenameCancel: () => void; busy: boolean; onDelete: () => void;
}) {
  return (
    <Reveal delay={delay}>
      <div className={cn("glass-card spot-card relative p-5", isActive && "border-gold/45 shadow-[0_0_50px_-18px_rgba(212,175,55,0.45)]")}>
        {isActive && (
          <span className="absolute -top-2.5 end-4 inline-flex items-center gap-1 rounded-full bg-gradient-to-l from-[#b18e24] to-[#ecd27f] px-3 py-0.5 text-[10px] font-black text-[#171006]">
            <CheckCircle2 className="h-3 w-3" /> الشهر النشط
          </span>
        )}
        <div className="flex items-start gap-3">
          <div className="rounded-xl border border-gold/20 bg-gold/8 p-2.5">
            <CalendarRange className="h-5 w-5 text-gold" aria-hidden />
          </div>
          <div className="min-w-0 flex-1">
            {renaming ? (
              <div className="flex items-center gap-2">
                <Input
                  value={renameDraft}
                  onChange={(e) => setRenameDraft(e.target.value)}
                  className="h-9 border-gold/30 bg-ink-850 text-sm"
                  autoFocus
                  onKeyDown={(e) => e.key === "Enter" && onRenameSave()}
                />
                <Button size="sm" className="gold-btn border-0" onClick={onRenameSave} disabled={busy}>حفظ</Button>
                <Button size="sm" variant="secondary" onClick={onRenameCancel}>إلغاء</Button>
              </div>
            ) : (
              <>
                <div className="flex items-center gap-2">
                  <h3 className="truncate text-lg font-black text-gold-bright">{m.name || `شهر ${m._id}`}</h3>
                  {isAdmin && (
                    <button onClick={onRenameStart} className="rounded-md p-1 text-muted-foreground hover:bg-gold/10 hover:text-gold" aria-label="إعادة تسمية الشهر" title="إعادة تسمية">
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
                <div className="text-xs text-muted-foreground" dir="ltr">{m._id}</div>
              </>
            )}
          </div>
        </div>
        <div className="mt-4 grid grid-cols-3 gap-2 border-t border-gold/10 pt-3 text-center">
          <div>
            <div className="text-lg font-black text-cream">{m.chapters}</div>
            <div className="text-[10px] text-muted-foreground">فصل</div>
          </div>
          <div>
            <div className="text-lg font-black text-cream">{m.recordsCount}</div>
            <div className="text-[10px] text-muted-foreground">سجل</div>
          </div>
          <div>
            <div className="text-lg font-black text-[#57f287]">{money(m.amount)}</div>
            <div className="text-[10px] text-muted-foreground">إجمالي</div>
          </div>
        </div>
        {isAdmin && (
          <div className="mt-4 flex gap-2">
            {!isActive && (
              <Button variant="secondary" className="flex-1 text-xs" onClick={onActivate} disabled={activating}>
                {activating ? "جارٍ التفعيل…" : "تفعيل هذا الشهر"}
              </Button>
            )}
            <Button
              variant="secondary"
              className="flex-1 border-bad/25 text-xs text-[#ff9a9c] hover:bg-bad/10 disabled:opacity-40"
              disabled={isActive}
              onClick={onDelete}
            >
              <Trash2 className="h-3.5 w-3.5" /> حذف
            </Button>
          </div>
        )}
      </div>
    </Reveal>
  );
}

function CreateMonthDialog({
  open, onClose, suggestedKey,
}: {
  open: boolean; onClose: () => void; suggestedKey: string; currency: string;
}) {
  const qc = useQueryClient();
  const [key, setKey] = useState("");
  const [name, setName] = useState("");
  const [activate, setActivate] = useState(true);
  const showKey = open ? (key || suggestedKey) : suggestedKey;

  const create = useMutation({
    mutationFn: () => api.addMonth({ key: key.trim() || undefined, name: name.trim() || undefined, activate }),
    onSuccess: (res) => {
      toast.success(`أُنشئ الشهر ${res.key}${activate ? " — ومُفعّل الآن" : ""}`);
      qc.invalidateQueries();
      onClose();
      setKey(""); setName(""); setActivate(true);
    },
    onError: (e: Error) => toast.error(e.message),
  });

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md border-gold/25 bg-ink-900" dir="rtl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <CalendarRange className="h-5 w-5 text-gold" /> شهر جديد
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-1">
          <div className="space-y-1.5">
            <Label htmlFor="month-key">المفتاح (YYYY-MM)</Label>
            <Input id="month-key" value={key} onChange={(e) => setKey(e.target.value)} placeholder={suggestedKey} className="border-gold/25 bg-ink-850" dir="ltr" />
            <p className="text-[10px] text-muted-foreground">المقترح تلقائيًا: {suggestedKey} — الشهر التالي للنشط.</p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="month-name">تسمية الشهر</Label>
            <Input id="month-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="مثال: شهر العاصفة" className="border-gold/25 bg-ink-850" />
          </div>
          <div className="flex items-center justify-between rounded-xl border border-gold/15 bg-gold/5 p-3">
            <div>
              <div className="text-sm font-bold">تفعيله فورًا</div>
              <div className="text-[11px] text-muted-foreground">الشهر الحالي ({showKey}) سيستقبل السجلات الجديدة</div>
            </div>
            <Switch checked={activate} onCheckedChange={setActivate} aria-label="تفعيل الشهر فورًا" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="secondary" onClick={onClose}>إلغاء</Button>
          <Button className="gold-btn border-0 font-extrabold" onClick={() => create.mutate()} disabled={create.isPending}>
            {create.isPending ? "جارٍ الإنشاء…" : "إنشاء الشهر"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
