"use client";

import { useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type RecordDTO } from "@/lib/client/api";
import { useApp } from "@/lib/client/store";
import { Avatar, money, Reveal } from "@/components/dash/fx";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ListPlus, Plus, Trash2, Filter } from "lucide-react";
import { toast } from "sonner";

/** تحليل إدخال الفصول — مطابق لمنطق البوت: 1-5 أو 3,7 أو 12 */
function parseChapters(input: string): string[] {
  const out: string[] = [];
  for (const part of input.split(/[,،]/)) {
    const seg = part.trim();
    if (!seg) continue;
    const range = seg.match(/^(\d+)\s*[-–]\s*(\d+)$/);
    if (range) {
      const a = Number(range[1]);
      const b = Number(range[2]);
      if (a <= b && b - a < 500) {
        for (let i = a; i <= b; i++) out.push(String(i));
        continue;
      }
    }
    if (/^\d+$/.test(seg)) out.push(seg);
  }
  return out;
}

export default function RecordsView({ isAdmin }: { isAdmin: boolean }) {
  const qc = useQueryClient();
  const { data: membersData } = useQuery({ queryKey: ["members"], queryFn: api.members });
  const { data: worksData } = useQuery({ queryKey: ["works"], queryFn: api.works });
  const { data: monthsData } = useQuery({ queryKey: ["months"], queryFn: api.months });

  const [fUser, setFUser] = useState("all");
  const [fWork, setFWork] = useState("all");
  const [fMonth, setFMonth] = useState("all");
  const [fType, setFType] = useState("all");
  const [addOpen, setAddOpen] = useState(false);

  const params = useMemo(() => {
    const p = new URLSearchParams();
    if (fUser !== "all") p.set("userId", fUser);
    if (fWork !== "all") p.set("work", fWork);
    if (fMonth !== "all") p.set("month", fMonth);
    if (fType !== "all") p.set("type", fType);
    return p;
  }, [fUser, fWork, fMonth, fType]);

  const { data, isLoading } = useQuery({
    queryKey: ["records", params.toString()],
    queryFn: () => api.records(params),
    refetchInterval: 15000,
  });

  const deleteRecord = useMutation({
    mutationFn: (payload: Parameters<typeof api.deleteRecord>[0]) => api.deleteRecord(payload),
    onSuccess: () => {
      toast.success("حُذف السجل");
      qc.invalidateQueries({ queryKey: ["records"] });
      qc.invalidateQueries({ queryKey: ["overview"] });
      qc.invalidateQueries({ queryKey: ["members"] });
      qc.invalidateQueries({ queryKey: ["works"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const members = membersData?.members ?? [];
  const workNames = (worksData?.works ?? []).map((w) => w.name);
  const types = ["تحرير", "ترجمة_كوري", "ترجمة_انجليزي", "تبييض", "سحب", "دمج", "رفع", "مكافأة", "خصم"];

  const records = data?.records ?? [];

  return (
    <div className="space-y-5">
      {/* أدوات */}
      <Reveal>
        <div className="flex flex-wrap items-center gap-2.5">
          <Filter className="h-4 w-4 text-gold" aria-hidden />
          <Select value={fUser} onValueChange={setFUser}>
            <SelectTrigger className="w-40 border-gold/20 bg-ink-850" aria-label="تصفية بالعضو"><SelectValue placeholder="العضو" /></SelectTrigger>
            <SelectContent className="max-h-72">
              <SelectItem value="all">كل الأعضاء</SelectItem>
              {members.map((m) => <SelectItem key={m.id} value={m.id}>{m.name}</SelectItem>)}
            </SelectContent>
          </Select>
          <Select value={fWork} onValueChange={setFWork}>
            <SelectTrigger className="w-44 border-gold/20 bg-ink-850" aria-label="تصفية بالعمل"><SelectValue placeholder="العمل" /></SelectTrigger>
            <SelectContent className="max-h-72">
              <SelectItem value="all">كل الأعمال</SelectItem>
              {workNames.map((w) => <SelectItem key={w} value={w}>{w}</SelectItem>)}
            </SelectContent>
          </Select>
          <Select value={fMonth} onValueChange={setFMonth}>
            <SelectTrigger className="w-40 border-gold/20 bg-ink-850" aria-label="تصفية بالشهر"><SelectValue placeholder="الشهر" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">كل الشهور</SelectItem>
              {(monthsData?.months ?? []).slice().reverse().map((m) => (
                <SelectItem key={m._id} value={m._id}>{m.name || m._id}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={fType} onValueChange={setFType}>
            <SelectTrigger className="w-40 border-gold/20 bg-ink-850" aria-label="تصفية بالتخصص"><SelectValue placeholder="التخصص" /></SelectTrigger>
            <SelectContent className="max-h-72">
              <SelectItem value="all">كل التخصصات</SelectItem>
              {types.map((t) => <SelectItem key={t} value={t}>{t.replace("_", " ")}</SelectItem>)}
            </SelectContent>
          </Select>
          <div className="ms-auto flex items-center gap-3">
            <span className="text-xs text-muted-foreground">{records.length} سجل</span>
            {isAdmin && (
              <Button onClick={() => setAddOpen(true)} className="gold-btn border-0 font-extrabold">
                <Plus className="h-4 w-4" /> تسجيل شغل
              </Button>
            )}
          </div>
        </div>
      </Reveal>

      {/* الجدول */}
      <Reveal>
        <div className="glass-card overflow-hidden">
          {isLoading ? (
            <div className="space-y-2 p-5">
              {[...Array(6)].map((_, i) => <div key={i} className="h-10 animate-pulse rounded-lg bg-ink-800" />)}
            </div>
          ) : records.length === 0 ? (
            <div className="p-12 text-center">
              <ListPlus className="mx-auto mb-3 h-8 w-8 text-gold/50" aria-hidden />
              <p className="text-sm text-muted-foreground">لا سجلات مطابقة للفلاتر</p>
            </div>
          ) : (
            <div className="scroll-area max-h-[32rem]">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-ink-850/95 backdrop-blur text-[11px] text-muted-foreground">
                  <tr>
                    <th className="px-4 py-3 text-start font-bold">العضو</th>
                    <th className="px-4 py-3 text-start font-bold">العمل</th>
                    <th className="px-4 py-3 text-start font-bold">الفصل</th>
                    <th className="px-4 py-3 text-start font-bold">التخصص</th>
                    <th className="px-4 py-3 text-start font-bold">المبلغ</th>
                    <th className="px-4 py-3 text-start font-bold">الشهر</th>
                    {isAdmin && <th className="px-4 py-3" aria-label="حذف" />}
                  </tr>
                </thead>
                <tbody>
                  {records.map((r, i) => {
                    const e = r.entry;
                    const isBonus = e.work_type === "مكافأة";
                    const isDed = e.work_type === "خصم";
                    return (
                      <tr key={`${e.timestamp}-${i}-${r.userId}`} className="border-t border-gold/8 transition-colors hover:bg-gold/5">
                        <td className="px-4 py-2.5">
                          <span className="flex items-center gap-2">
                            <Avatar name={r.memberName} size={26} ring={false} />
                            <span className="font-bold">{r.memberName}</span>
                          </span>
                        </td>
                        <td className="px-4 py-2.5 text-muted-foreground">{e.work_name}</td>
                        <td className="px-4 py-2.5 font-black text-gold-bright" dir="ltr">{e.chapter}</td>
                        <td className="px-4 py-2.5">
                          <span className={isBonus || isDed
                            ? "rounded-full border border-gold/25 bg-gold/8 px-2.5 py-0.5 text-[11px] font-bold text-gold-bright"
                            : "text-muted-foreground"}>
                            {e.work_type.replace("_", " ")}
                          </span>
                        </td>
                        <td className={`px-4 py-2.5 font-black ${e.total < 0 ? "text-[#ff7a7c]" : "text-[#57f287]"}`} dir="ltr">
                          {money(e.total)}
                        </td>
                        <td className="px-4 py-2.5 text-[11px] text-muted-foreground" dir="ltr">{e.month_key}</td>
                        {isAdmin && (
                          <td className="px-4 py-2.5 text-end">
                            <button
                              onClick={() => {
                                if (confirm(`حذف سجل ${r.memberName} — ${e.work_name} فصل ${e.chapter}؟`)) {
                                  deleteRecord.mutate({
                                    userId: r.userId,
                                    work_name: e.work_name,
                                    chapter: e.chapter,
                                    work_type: e.work_type,
                                    timestamp: e.timestamp,
                                  });
                                }
                              }}
                              className="rounded-lg p-1.5 text-muted-foreground hover:bg-bad/10 hover:text-[#ff7a7c]"
                              aria-label="حذف السجل"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </td>
                        )}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </Reveal>

      <AddRecordDialog
        open={addOpen}
        onClose={() => setAddOpen(false)}
        members={members}
        works={workNames}
      />
    </div>
  );
}

function AddRecordDialog({
  open, onClose, members, works,
}: {
  open: boolean; onClose: () => void;
  members: Array<{ id: string; name: string }>;
  works: string[];
}) {
  const qc = useQueryClient();
  const [userId, setUserId] = useState("");
  const [work, setWork] = useState("");
  const [chaptersInput, setChaptersInput] = useState("");
  const [type, setType] = useState("");
  const [notes, setNotes] = useState("");

  const chapters = parseChapters(chaptersInput);

  const add = useMutation({
    mutationFn: () => api.addRecord({ userId, work, chapters, types: type ? [type] : [], notes: notes || undefined }),
    onSuccess: (res) => {
      const skippedTxt = res.skipped.length ? ` • تخطي: ${res.skipped.map((s) => `${s.chapter} (${s.reason})`).join("، ")}` : "";
      toast.success(`سُجّل ${res.added.length} فصل — ربح ${money(res.gained)}${skippedTxt}`, { duration: 7000 });
      qc.invalidateQueries();
      onClose();
      setUserId(""); setWork(""); setChaptersInput(""); setType(""); setNotes("");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const valid = userId && work && chapters.length > 0;

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md border-gold/25 bg-ink-900" dir="rtl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ListPlus className="h-5 w-5 text-gold" /> تسجيل شغل جديد
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-1">
          <div className="space-y-1.5">
            <Label>العضو</Label>
            <Select value={userId} onValueChange={setUserId}>
              <SelectTrigger className="border-gold/25 bg-ink-850" aria-label="اختر العضو">
                <SelectValue placeholder="اختر العضو…" />
              </SelectTrigger>
              <SelectContent className="max-h-72">
                {members.map((m) => <SelectItem key={m.id} value={m.id}>{m.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>العمل</Label>
            <Select value={work} onValueChange={setWork}>
              <SelectTrigger className="border-gold/25 bg-ink-850" aria-label="اختر العمل">
                <SelectValue placeholder="اختر العمل…" />
              </SelectTrigger>
              <SelectContent className="max-h-72">
                {works.map((w) => <SelectItem key={w} value={w}>{w}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="chapters">الفصول</Label>
            <Input
              id="chapters"
              value={chaptersInput}
              onChange={(e) => setChaptersInput(e.target.value)}
              placeholder="مثال: 12-15 أو 3,7,9"
              className="border-gold/25 bg-ink-850"
              dir="ltr"
            />
            {chapters.length > 0 && (
              <p className="text-[11px] text-gold-bright/80">سيُسجّل {chapters.length} فصل: {chapters.slice(0, 12).join("، ")}{chapters.length > 12 ? "…" : ""}</p>
            )}
          </div>
          <div className="space-y-1.5">
            <Label>التخصص (للكل الفصول)</Label>
            <Select value={type} onValueChange={setType}>
              <SelectTrigger className="border-gold/25 bg-ink-850" aria-label="اختر التخصص">
                <SelectValue placeholder="اختر التخصص…" />
              </SelectTrigger>
              <SelectContent className="max-h-72">
                {["تحرير", "ترجمة_كوري", "ترجمة_انجليزي", "تبييض", "سحب", "دمج", "رفع"].map((t) => (
                  <SelectItem key={t} value={t}>{t.replace("_", " ")}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-[10px] text-muted-foreground">الفصول المكررة والمجانية (قبل بداية الدفع) تُتخطى تلقائيًا.</p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="notes">ملاحظة (اختياري)</Label>
            <Textarea id="notes" value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} className="border-gold/25 bg-ink-850" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="secondary" onClick={onClose}>إلغاء</Button>
          <Button className="gold-btn border-0 font-extrabold" disabled={!valid || add.isPending} onClick={() => add.mutate()}>
            {add.isPending ? "جارٍ التسجيل…" : `تسجيل ${chapters.length || ""} فصل`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
