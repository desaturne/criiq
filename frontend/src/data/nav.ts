import { LayoutDashboard, Users, Calendar, FileText, MessageSquare, Star, Activity } from "lucide-react";

export const NAV_ITEMS = [
  { id: "dashboard",       path: "dashboard",       label: "Dashboard",       icon: LayoutDashboard },
  { id: "players",         path: "players",         label: "Player Form",     icon: Activity },
  { id: "squads",          path: "squads",          label: "Squads",          icon: Users },
  { id: "matches",         path: "matches",         label: "Matches",         icon: Calendar },
  { id: "recommendations", path: "recommendations", label: "Recommendations", icon: Star },
  { id: "reports",         path: "reports",         label: "Reports",         icon: FileText },
  { id: "assistant",       path: "assistant",       label: "AI Assistant",    icon: MessageSquare },
];
