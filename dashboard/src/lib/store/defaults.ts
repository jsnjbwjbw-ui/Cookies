import type { SpecialtyDoc } from "./types";

/** مطابق لـ DEFAULT_SPECIALTIES في config.py الخاص بالبوت */
export const DEFAULT_SPECIALTIES: Record<string, SpecialtyDoc> = {
  تحرير: { price: 0.5, active: true },
  ترجمة_كوري: { price: 0.5, active: true },
  ترجمة_انجليزي: { price: 0.25, active: true },
  تبييض: { price: 0.25, active: true },
  سحب: { price: 0.01, active: true },
  دمج: { price: 0.01, active: true },
  رفع: { price: 0.005, active: true },
};

export const BONUS_WORK_NAME = "نظام المكافآت والخصومات";
