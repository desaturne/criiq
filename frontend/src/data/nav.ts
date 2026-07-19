import { LayoutDashboard, Users, Calendar, FileText, Star, Activity, Zap } from "lucide-react";

export const NAV_ITEMS = [
  { id: "dashboard",       path: "dashboard",       label: "Dashboard",       icon: LayoutDashboard },
  { id: "players",         path: "players",         label: "Player Form",     icon: Activity },
  { id: "squads",          path: "squads",          label: "Squads",          icon: Users },
  { id: "matches",         path: "matches",         label: "Matches",         icon: Calendar },
  { id: "recommendations", path: "recommendations", label: "Recommendations", icon: Star },
  { id: "simulator",       path: "simulator",       label: "Simulator",       icon: Zap },
  { id: "reports",         path: "reports",         label: "Reports",         icon: FileText },
];
