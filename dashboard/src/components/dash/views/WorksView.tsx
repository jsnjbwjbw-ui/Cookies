"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/client/api";
import { Avatar, money, timeAgo, Reveal } from "@/components/dash/fx";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import {
  FolderKanban, Plus, Lock, Unlock, Pencil, Trash2, Tag, Users2, FileText, CalendarDays,
} from "lucide-react";
import { toast } from "sonner";

export default function WorksView({ isAdmin }: { isAdmin: boolean }) {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["works"], queryFn: api.works, refetchInterval: 25000 });

  const [addOpen, setAddOpen] = useState(false);
  const [editOpen, setEditOpen] = useState<string | null>(null);

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["works"] });
    qc.invalidateQueries({ queryKey: ["overview"] });
  };

  const addWork = useMutation({
    mutationFn: (p: { name: string; paid_start: number | null }) => api.addWork(p.name, p.paid_start),
    onSuccess: () => { toast.success("أُضيف العمل"); setAddOpen(false); invalidate(); },
    onError: (e: Error) => toast.error(e.message),
  });

  const patchWork = useMutation({
    mutationFn: (p: { name: string; newName?: string; paid_start?: number | null; isolated?: boolean }) => api.patchWork(p),
    onSuccess: () => { toast.success("تم التحديث"); setEditOpen(null); invalidate(); },
    onError: (e: Error) => toast.error(e.message),
  });

  const deleteWork = useMutation({
    mutationFn: (name: string) => api.deleteWork(name),
    onSuccess: () => { toast.success("حُذف العمل — سجلاته تبقى محفوظة"); invalidate(); },
    onError: (e: Error) => toast.error(e.message),
  });

  if (isLoading) {
    return (
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {[...Array(6)].map((_, i) => <div key={i} className="glass-card h-48 animate-pulse" />)}
      </div>
    );
  }

  const works = data?.stats ?? [];
  const maxCh = Math.max(1, ...works.map((w) => w.chaptersThisMonth));

  return (
    <div className="space-y-5">
      {isAdmin && (
        <Reveal>
          <div className="flex justify-end">
            <Button onClick={() => setAddOpen("new")} className="gold-btn border-0 font-extrabold">
              <Plus className="h-4 w-4" />
              عمل جديد
            </Button>
          </div>
        </Reveal>
      )}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {works.map((w, i) => (
          <Reveal key={w.name} delay={Math.min(i * 60, 300)}>
            <div className="glass-card spot-card flex h-full flex-col p-5">
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2.5">
                  <div className="rounded-xl border border-gold/20 bg-gold/8 p-2.5">
                    <FolderKanban className="h-5 w-5 text-gold" aria-hidden />
                  </div>
                  <div>
                    <h3 className="font-extrabold leading-tight">{w.name}</h3>
                    <div className="mt-1 flex flex-wrap gap-1.5">
                      {w.isolated ? (
                        <span className="inline-flex items-center gap-1 rounded-full border border-bad/30 bg-bad/10 px-2 py-0.5 text-[10px] font-bold text-[#ff9a9c]">
                          <Lock className="h-2.5 w-2.5" /> معزول
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 rounded-full border border-gold/20 bg-gold/5 px-2 py-0.5 text-[10px] font-bold text-gold-bright/80">
                          <Unlock className="h-2.5 w-2.5" /> نشط
                        </span>
                      )}
                      {w.paidStart != null && (
                        <span className="rounded-full border border-gold/20 bg-gold/5 px-2 py-0.5 text-[10px] font-bold text-gold-bright/80">
                          مدفوع من فصل {w.paidStart}
                        </span>
                      )}
                      {w.customPrices && Object.keys(w.customPrices).length > 0 && (
                        <span className="inline-flex items-center gap-1 rounded-full border border-gold/20 bg-gold/5 px-2 py-0.5 text-[10px] font-bold text-gold-bright/80">
                          <Tag className="h-2.5 w-2.5" /> {Object.keys(w.customPrices).length} سعر مخصص
                        </span>
                      )}
                    </div>
                  </div>
                </div>
                {isAdmin && (
                  <div className="flex gap-1">
                    <button
                      onClick={() => setEditOpen(w.name)}
                      className="rounded-lg p-1.5 text-muted-foreground hover:bg-gold/10 hover:text-gold"
                      aria-label={`تعديل ${w.name}`}
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                    {!w.isolated && (
                      <button
                        onClick={() => {
                          if (confirm(`حذف العمل «${w.name}»؟ سجلاته تبقى محفوظة.`)) deleteWork.mutate(w.name);
                        }}
                        className="rounded-lg p-1.5 text-muted-foreground hover:bg-bad/10 hover:text-[#ff7a7c]"
                        aria-label={`حذف ${w.name}`}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    )}
                  </div>
                )}
              </div>

              <div className="mt-4 flex-1 space-y-2.5 text-xs">
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">فصول هذا الشهر</span>
                  <span className="font-black text-cream">{w.chaptersThisMonth}</span>
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-ink-700">
                  <div className="gold-bar h-full transition-all duration-700" style={{ width: `${(w.chaptersThisMonth / maxCh) * 100}%` }} />
                </div>
                <div className="grid grid-cols-3 gap-2 border-t border-gold/10 pt-3 text-center">
                  <div>
                    <div className="flex items-center justify-center gap-1 font-black text-gold-bright">
                      <FileText className="h-3 w-3" />{w.chaptersAllTime}
                    </div>
                    <div className="text-[10px] text-muted-foreground">كل الوقت</div>
                  </div>
                  <div>
                    <div className="flex items-center justify-center gap-1 font-black text-cream">
                      <Users2 className="h-3 w-3" />{w.contributors}
                    </div>
                    <div className="text-[10px] text-muted-foreground">مساهمون</div>
                  </div>
                  <div>
                    <div className="flex items-center justify-center gap-1 font-black text-[#57f287]">
                      {money(w.amountThisMonth)}
                    </div>
                    <div className="text-[10px] text-muted-foreground">الشهر</div>
                  </div>
                </div>
              </div>

              {w.lastActivity && (
                <div className="mt-3 flex items-center gap-1.5 text-[10px] text-muted-foreground">
                  <CalendarDays className="h-3 w-3" />
                  آخر تسجيل: {timeAgo(w.lastActivity)}
                </div>
              )}
            </div>
          </Reveal>
        ))}
      </div>

      {/* إضافة عمل */}
      <AddWorkDialog
        open={Boolean(addOpen)}
        onClose={() => setAddOpen(null)}
        onSubmit={(name, paid) => addWork.mutate({ name, paid_start: paid })}
        saving={addWork.isPending}
      />

      {/* تعديل عمل */}
      <Dialog open={Boolean(editOpen)} onOpenChange={(o) => !o && setEditOpen(null)}>
        <DialogContent className="max-w-md border-gold/25 bg-ink-900" dir="rtl">
          {editOpen && editOpen !== "new" && (() => {
            const w = works.find((x) => x.name === editOpen);
            if (!w) return null;
            return <EditWorkBody
              initial={{ name: w.name, paid_start: w.paidStart, isolated: w.isolated }}
              saving={patchWork.isPending}
              onSubmit={(p) => patchWork.mutate({ name: w.name, ...p })}
            />;
          })()}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function AddWorkDialog({
  open, onClose, onSubmit, saving,
}: {
  open: boolean; onClose: () => void; onSubmit: (name: string, paid: number | null) => void; saving: boolean;
}) {
  const [name, setName] = useState("");
  const [paid, setPaid] = useState("");
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md border-gold/25 bg-ink-900" dir="rtl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FolderKanban className="h-5 w-5 text-gold" /> عمل جديد
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div className="space-y-1.5">
            <Label htmlFor="work-name">اسم العمل</Label>
            <Input id="work-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="مثال: سولو ليفلنج" className="border-gold/25 bg-ink-850" autoFocus />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="work-paid">فصل بداية الدفع (اختياري)</Label>
            <Input id="work-paid" value={paid} onChange={(e) => setPaid(e.target.value)} placeholder="مثال: 12 — الفصول قبله مجانية" className="border-gold/25 bg-ink-850" inputMode="numeric" dir="ltr" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="secondary" onClick={onClose}>إلغاء</Button>
          <Button
            className="gold-btn border-0 font-bold"
            disabled={!name.trim() || saving}
            onClick={() => onSubmit(name.trim(), paid.trim() ? Number(paid) : null)}
          >
            {saving ? "جارٍ الإضافة…" : "إضافة"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function EditWorkBody({
  initial, onSubmit, saving,
}: {
  initial: { name: string; paid_start: number | null; isolated: boolean };
  onSubmit: (p: { newName?: string; paid_start?: number | null; isolated?: boolean }) => void;
  saving: boolean;
}) {
  const [name, setName] = useState(initial.name);
  const [paid, setPaid] = useState(initial.paid_start?.toString() ?? "");
  const [isolated, setIsolated] = useState(initial.isolated);
  return (
    <div>
      <DialogHeader>
        <DialogTitle className="flex items-center gap-2">
          <Pencil className="h-5 w-5 text-gold" /> تعديل: {initial.name}
        </DialogTitle>
      </DialogHeader>
      <div className="space-y-4 py-2">
        <div className="space-y-1.5">
          <Label htmlFor="edit-name">الاسم</Label>
          <Input id="edit-name" value={name} onChange={(e) => setName(e.target.value)} className="border-gold/25 bg-ink-850" />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="edit-paid">فصل بداية الدفع</Label>
          <Input id="edit-paid" value={paid} onChange={(e) => setPaid(e.target.value)} placeholder="فارغ = كل الفصول مدفوعة" className="border-gold/25 bg-ink-850" inputMode="numeric" dir="ltr" />
        </div>
        <div className="flex items-center justify-between rounded-xl border border-gold/15 bg-gold/5 p-3">
          <div>
            <div className="text-sm font-bold">عمل معزول</div>
            <div className="text-[11px] text-muted-foreground">سجلاته مخفية عن الإحصائيات العامة ومحمية من الحذف</div>
          </div>
          <Switch checked={isolated} onCheckedChange={setIsolated} aria-label="عزل العمل" />
        </div>
      </div>
      <DialogFooter>
        <Button variant="secondary" onClick={() => onSubmit({})} disabled={saving}>حفظ</Button>
        <Button
          className="gold-btn border-0 font-bold"
          disabled={saving}
          onClick={() =>
            onSubmit({
              newName: name.trim() !== initial.name ? name.trim() : undefined,
              paid_start: paid.trim() ? Number(paid) : null,
              isolated,
            })
          }
        >
          {saving ? "جارٍ الحفظ…" : "حفظ"}
        </Button>
      </DialogFooter>
    </div>
  );
}
