"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/client/api";
import { money, Reveal } from "@/components/dash/fx";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Tags, Plus, Trash2, ArrowUpLeft, Briefcase, Globe } from "lucide-react";
import { toast } from "sonner";

export default function SpecialtiesView({ isAdmin }: { isAdmin: boolean }) {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["specialties"], queryFn: api.specialties, refetchInterval: 30000 });

  const [addOpen, setAddOpen] = useState(false);
  const [priceEdits, setPriceEdits] = useState<Record<string, string>>({});

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["specialties"] });
    qc.invalidateQueries({ queryKey: ["works"] });
  };

  const patch = useMutation({
    mutationFn: (p: { name: string; price?: number; active?: boolean; work?: string }) => api.patchSpecialty(p),
    onSuccess: () => { toast.success("تم التحديث — ينعكس على البوت فورًا"); invalidate(); },
    onError: (e: Error) => toast.error(e.message),
  });

  const remove = useMutation({
    mutationFn: (p: { name: string; work?: string; toGlobal?: boolean }) => api.deleteSpecialty(p.name, p.work, p.toGlobal),
    onSuccess: () => { toast.success("تم الحذف/النقل"); invalidate(); },
    onError: (e: Error) => toast.error(e.message),
  });

  if (isLoading || !data) {
    return (
      <div className="space-y-4">
        <div className="glass-card h-64 animate-pulse" />
        <div className="glass-card h-48 animate-pulse" />
      </div>
    );
  }

  const specs = Object.entries(data.specialties).sort((a, b) => Number(b[1].active) - Number(a[1].active) || b[1].price - a[1].price);
  const cur = data.currency;

  return (
    <div className="space-y-5">
      {/* القائمة العامة */}
      <Reveal>
        <div className="glass-card overflow-hidden">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-gold/10 p-5">
            <div>
              <h3 className="flex items-center gap-2 text-base font-extrabold">
                <Globe className="h-4.5 w-4.5 h-[18px] w-[18px] text-gold" aria-hidden />
                التخصصات العامة
              </h3>
              <p className="mt-0.5 text-xs text-muted-foreground">
                السعر الافتراضي لأي عمل لا يملك تخصيصًا — العملة الحالية: {cur}
              </p>
            </div>
            {isAdmin && (
              <Button onClick={() => setAddOpen(true)} className="gold-btn border-0 font-extrabold">
                <Plus className="h-4 w-4" /> تخصص جديد
              </Button>
            )}
          </div>
          <div className="scroll-area max-h-96 divide-y divide-gold/8">
            {specs.map(([name, sp]) => (
              <div key={name} className="flex flex-wrap items-center gap-3 px-5 py-3.5 transition-colors hover:bg-gold/4">
                <div className="min-w-40 flex-1">
                  <div className="text-sm font-extrabold">{name.replace("_", " ")}</div>
                  {sp.last_modified && (
                    <div className="text-[10px] text-muted-foreground">آخر تعديل: {new Date(sp.last_modified).toLocaleDateString("ar")}</div>
                  )}
                </div>
                <div className="flex items-center gap-2" dir="ltr">
                  <span className="text-xs font-bold text-muted-foreground">{cur}</span>
                  <Input
                    value={priceEdits[name] ?? String(sp.price)}
                    onChange={(e) => setPriceEdits((s) => ({ ...s, [name]: e.target.value }))}
                    disabled={!isAdmin}
                    className="h-9 w-24 border-gold/20 bg-ink-850 text-center font-black"
                    inputMode="decimal"
                    aria-label={`سعر ${name}`}
                  />
                  {isAdmin && (priceEdits[name] !== undefined && Number(priceEdits[name]) !== sp.price) && (
                    <Button size="sm" className="gold-btn h-9 border-0 text-xs" onClick={() => patch.mutate({ name, price: Number(priceEdits[name]) })}>
                      حفظ
                    </Button>
                  )}
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-[11px] text-muted-foreground">{sp.active ? "نشط" : "معطّل"}</span>
                  <Switch
                    checked={sp.active}
                    disabled={!isAdmin}
                    onCheckedChange={(v) => patch.mutate({ name, active: v })}
                    aria-label={`تفعيل ${name}`}
                  />
                  {isAdmin && (
                    <button
                      onClick={() => { if (confirm(`حذف التخصص «${name}» من القائمة العامة؟`)) remove.mutate({ name }); }}
                      className="rounded-lg p-1.5 text-muted-foreground hover:bg-bad/10 hover:text-[#ff7a7c]"
                      aria-label={`حذف ${name}`}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      </Reveal>

      {/* تخصيصات الأعمال */}
      <Reveal delay={100}>
        <div className="glass-card p-5">
          <h3 className="mb-1 flex items-center gap-2 text-base font-extrabold">
            <Briefcase className="h-[18px] w-[18px] text-gold" aria-hidden />
            تخصيصات الأعمال
          </h3>
          <p className="mb-4 text-xs text-muted-foreground">سعر خاص لتخصص معين داخل عمل معين — يتجاوز السعر العام.</p>
          <div className="grid gap-3 md:grid-cols-2">
            {data.works.map((w) => {
              const entries = Object.entries(w.custom_prices || {});
              return (
                <div key={w.name} className="rounded-xl border border-gold/12 bg-ink-850/60 p-4">
                  <div className="mb-2.5 text-sm font-extrabold text-gold-bright">{w.name}</div>
                  {entries.length === 0 ? (
                    <p className="text-[11px] text-muted-foreground">يستخدم الأسعار العامة</p>
                  ) : (
                    <div className="space-y-2">
                      {entries.map(([sp, price]) => (
                        <div key={sp} className="flex items-center gap-2 text-xs">
                          <span className="flex-1 font-bold">{sp.replace("_", " ")}</span>
                          <span className="font-black text-gold-bright" dir="ltr">{money(price, cur)}</span>
                          {isAdmin && (
                            <>
                              <button
                                onClick={() => remove.mutate({ name: sp, work: w.name, toGlobal: true })}
                                className="rounded-md p-1 text-muted-foreground hover:bg-gold/10 hover:text-gold"
                                title="إعادة إلى القائمة العامة"
                                aria-label={`إعادة ${sp} إلى العام`}
                              >
                                <ArrowUpLeft className="h-3.5 w-3.5" />
                              </button>
                              <button
                                onClick={() => { if (confirm(`حذف تخصيص ${sp} من ${w.name}؟`)) remove.mutate({ name: sp, work: w.name }); }}
                                className="rounded-md p-1 text-muted-foreground hover:bg-bad/10 hover:text-[#ff7a7c]"
                                aria-label={`حذف تخصيص ${sp}`}
                              >
                                <Trash2 className="h-3 w-3" />
                              </button>
                            </>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </Reveal>

      <AddSpecialtyDialog open={addOpen} onClose={() => setAddOpen(false)} />
    </div>
  );
}

function AddSpecialtyDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [price, setPrice] = useState("");
  const add = useMutation({
    mutationFn: () => api.addSpecialty(name.trim().replace(/\s+/g, "_"), Number(price)),
    onSuccess: () => {
      toast.success("أُضيف التخصص");
      qc.invalidateQueries({ queryKey: ["specialties"] });
      onClose(); setName(""); setPrice("");
    },
    onError: (e: Error) => toast.error(e.message),
  });
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-sm border-gold/25 bg-ink-900" dir="rtl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><Tags className="h-5 w-5 text-gold" /> تخصص جديد</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-1">
          <div className="space-y-1.5">
            <Label htmlFor="sp-name">الاسم</Label>
            <Input id="sp-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="مثال: تنسيق" className="border-gold/25 bg-ink-850" autoFocus />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="sp-price">السعر</Label>
            <Input id="sp-price" value={price} onChange={(e) => setPrice(e.target.value)} placeholder="0.50" className="border-gold/25 bg-ink-850" inputMode="decimal" dir="ltr" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="secondary" onClick={onClose}>إلغاء</Button>
          <Button className="gold-btn border-0 font-bold" disabled={!name.trim() || price === "" || add.isPending} onClick={() => add.mutate()}>
            {add.isPending ? "…" : "إضافة"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
