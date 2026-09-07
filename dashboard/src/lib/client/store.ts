"use client";

import { create } from "zustand";

export type DashView =
  | "overview"
  | "members"
  | "works"
  | "records"
  | "months"
  | "specialties"
  | "live"
  | "settings";

interface AppState {
  view: DashView;
  sidebarOpen: boolean;
  selectedMember: string | null;
  setView: (v: DashView) => void;
  setSidebarOpen: (v: boolean) => void;
  setSelectedMember: (id: string | null) => void;
}

export const useApp = create<AppState>((set) => ({
  view: "overview",
  sidebarOpen: false,
  selectedMember: null,
  setView: (view) => set({ view, sidebarOpen: false }),
  setSidebarOpen: (sidebarOpen) => set({ sidebarOpen }),
  setSelectedMember: (selectedMember) => set({ selectedMember }),
}));
