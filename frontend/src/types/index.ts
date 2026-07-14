import React from "react";

export type Role = "Admin" | "Coach" | "Player";

export type UserRole = "Coach" | "Player";

export type SelectionState = "select" | "reserve" | "exclude" | "undecided";

export type PlayerStatus = "ACTIVE" | "INCONSISTENT" | "INACTIVE" | "UNKNOWN";

export interface AppContextValue {
  dark: boolean;
  setDark: (d: boolean) => void;
  selections: Record<string, SelectionState>;
  setSelections: React.Dispatch<React.SetStateAction<Record<string, SelectionState>>>;
}

export interface Player {
  id: string; name: string; role: string; archetype: string;
  battingHand: "Right" | "Left"; bowlingStyle: string;
  status: PlayerStatus; team: string; initials: string; color: string;
  isBatsman: boolean; recentForm: number[]; recentSR: number[];
  vsOpponent: number; vsInsight: string;
  powerplay: number; middle: number; death: number;
  career: { matches: number; innings: number; runs?: number; avg?: number; sr?: number; fifties?: number; hundreds?: number; wickets?: number; economy?: number; bowlingAvg?: number; best?: string };
  score: number;
  breakdown: { form: number; vsOpponent: number; venueFit: number; matchupAdvantage: number };
}

export interface Match {
  id: string; team1: string; team2: string; venue: string;
  date: string; time: string; format: string;
  status: "Upcoming" | "Live" | "Completed";
  result?: string; paceSupport: number; spinSupport: number; battingAnchors: number; finishersFit: number;
  opponentForm: ("W" | "L")[];
}

export interface AppUser {
  id: number; name: string; email: string; password: string;
  role: Role; status: "Active" | "Inactive" | "Suspended";
  lastLogin: string; team: string; avatar: string;
}

export interface AdminCtxValue { users: AppUser[]; setUsers: React.Dispatch<React.SetStateAction<AppUser[]>>; }

export type AuthMode = "user-login" | "admin-login" | "user-app" | "admin-app";
