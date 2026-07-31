import { LayoutDashboard, Users, Calendar, Star, Activity, Zap, UserCheck } from "lucide-react";

export const NAV_ITEMS = [
  { id: "dashboard",       path: "dashboard",       label: "Dashboard",       icon: LayoutDashboard },
  { id: "players",         path: "players",         label: "Player Form",     icon: Activity },
  { id: "squads",          path: "squads",          label: "Squads",          icon: Users },
  { id: "build-xi",        path: "build-xi",        label: "Build XI",        icon: UserCheck },
  { id: "matches",         path: "matches",         label: "Matches",         icon: Calendar },
  { id: "recommendations", path: "recommendations", label: "Recommendations", icon: Star },
  { id: "simulator",       path: "simulator",       label: "Simulator",       icon: Zap },
];
