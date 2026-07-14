import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { RouterProvider, createBrowserRouter, Navigate } from "react-router";
import { AdminShell } from "../admin/AdminShell";
import { Root } from "../components/layout/Root";
import { AppContext } from "../context/AppContext";
import { AssistantPage } from "../pages/AssistantPage";
import { DashboardOverviewPage } from "../pages/DashboardOverviewPage";
import { DashboardPage } from "../pages/DashboardPage";
import { MatchDetailPage } from "../pages/MatchDetailPage";
import { MatchesPage } from "../pages/MatchesPage";
import { PlayerProfilePage } from "../pages/PlayerProfilePage";
import { RecommendationsPage } from "../pages/RecommendationsPage";
import { ReportsPage } from "../pages/ReportsPage";
import { SettingsPage } from "../pages/SettingsPage";
import { SquadsPage } from "../pages/SquadsPage";
import { AdminLoginPage } from "../pages/auth/AdminLoginPage";
import { LoginPage } from "../pages/auth/LoginPage";
import { AuthMode, SelectionState } from "../types/index";

export function AppWithAuth() {
  const [authMode, setAuthMode] = useState<AuthMode>("user-login");
  const [dark, setDark] = useState(true);
  const [selections, setSelections] = useState<Record<string, SelectionState>>({});

  // Admin login — completely separate, no user context
  if (authMode === "admin-login") {
    return <AdminLoginPage onLogin={() => setAuthMode("admin-app")} onBack={() => setAuthMode("user-login")} />;
  }

  // Admin app — own shell, no cricket components
  if (authMode === "admin-app") {
    return <AdminShell onLogout={() => setAuthMode("admin-login")} />;
  }

  // User login
  if (authMode === "user-login") {
    return (
      <div className={`${dark ? "dark" : ""} h-screen`} style={{ fontFamily: "var(--font-sans)" }}>
        <div className="bg-background text-foreground h-full">
          <AnimatePresence mode="wait">
            <motion.div key="login" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="h-full">
              <LoginPage onLogin={() => setAuthMode("user-app")} onAdminAccess={() => setAuthMode("admin-login")} />
            </motion.div>
          </AnimatePresence>
        </div>
      </div>
    );
  }

  // User app — react-router, no admin routes
  const router = createBrowserRouter([
    {
      path: "/",
      Component: Root,
      children: [
        { index: true, element: <Navigate to="/dashboard" replace /> },
        { path: "dashboard",       Component: DashboardOverviewPage },
        { path: "players",         Component: DashboardPage },
        { path: "players/:id",     Component: PlayerProfilePage },
        { path: "squads",          Component: SquadsPage },
        { path: "matches",         Component: MatchesPage },
        { path: "matches/:id",     Component: MatchDetailPage },
        { path: "recommendations", Component: RecommendationsPage },
        { path: "assistant",       Component: AssistantPage },
        { path: "reports",         Component: ReportsPage },
        { path: "settings",        Component: SettingsPage },
        { path: "*",               element: <Navigate to="/dashboard" replace /> },
      ],
    },
  ]);

  return (
    <AppContext.Provider value={{ dark, setDark, selections, setSelections }}>
      <RouterProvider router={router} />
    </AppContext.Provider>
  );
}

export default function App() {
  return <AppWithAuth />;
}
