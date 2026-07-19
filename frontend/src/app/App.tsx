import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { RouterProvider, createBrowserRouter, Navigate } from "react-router";
import { AdminShell } from "../admin/AdminShell";
import { Root } from "../components/layout/Root";
import { AppContext } from "../context/AppContext";
import * as api from "../lib/api";
import { AssistantPage } from "../pages/AssistantPage";
import { DashboardOverviewPage } from "../pages/DashboardOverviewPage";
import { DashboardPage } from "../pages/DashboardPage";
import { MatchDetailPage } from "../pages/MatchDetailPage";
import { MatchesPage } from "../pages/MatchesPage";
import { PlayerProfilePage } from "../pages/PlayerProfilePage";
import { RecommendationsPage } from "../pages/RecommendationsPage";
import { ReportsPage } from "../pages/ReportsPage";
import { SettingsPage } from "../pages/SettingsPage";
import { SimulationPage } from "../pages/SimulationPage";
import { SquadsPage } from "../pages/SquadsPage";
import { AdminLoginPage } from "../pages/auth/AdminLoginPage";
import { LoginPage } from "../pages/auth/LoginPage";
import { AuthMode, AuthUser, SelectionState } from "../types/index";

// Defined once at module scope, not inside AppWithAuth's render body -- a
// fresh createBrowserRouter() on every render hands RouterProvider a new
// router *instance* each time, which it treats as a brand new router and
// remounts the whole route tree from scratch, discarding any state a page
// had just set (e.g. SimulationPage's prefill from a query-param effect
// calling navigate() -- that re-render was enough to wipe it straight back
// to its initial defaults).
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
      { path: "simulator",       Component: SimulationPage },
      { path: "assistant",       Component: AssistantPage },
      { path: "reports",         Component: ReportsPage },
      { path: "settings",        Component: SettingsPage },
      { path: "*",               element: <Navigate to="/dashboard" replace /> },
    ],
  },
]);

export function AppWithAuth() {
  const [authMode, setAuthMode] = useState<AuthMode>(api.getToken() ? "user-app" : "user-login");
  const [dark, setDark] = useState(true);
  const [selections, setSelections] = useState<Record<string, SelectionState>>({});
  const [token, setToken] = useState<string | null>(api.getToken());
  const [user, setUser] = useState<AuthUser | null>(null);

  const login = async (email: string, password: string) => {
    const result = await api.login(email, password);
    api.setToken(result.token);
    setToken(result.token);
    setUser(result.user);
    setAuthMode("user-app");
  };

  const register = async (name: string, email: string, password: string) => {
    const result = await api.register(name, email, password);
    api.setToken(result.token);
    setToken(result.token);
    setUser(result.user);
    setAuthMode("user-app");
  };

  const logout = async () => {
    try { await api.logout(); } catch { /* token may already be invalid — clear locally regardless */ }
    api.clearToken();
    setToken(null);
    setUser(null);
    setAuthMode("user-login");
  };

  // A persisted token might have expired or been revoked server-side since
  // the last visit — confirm it's still live and recover the user's name/role.
  useEffect(() => {
    if (!token || user) return;
    api.me()
      .then(me => setUser({ id: 0, name: me.name, role: me.role }))
      .catch(() => { api.clearToken(); setToken(null); setAuthMode("user-login"); });
  }, [token, user]);

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
              <LoginPage onLogin={login} onRegister={register} onAdminAccess={() => setAuthMode("admin-login")} />
            </motion.div>
          </AnimatePresence>
        </div>
      </div>
    );
  }

  // User app — react-router, no admin routes (router defined at module scope above)
  return (
    <AppContext.Provider value={{ dark, setDark, selections, setSelections, token, user, login, register, logout }}>
      <RouterProvider router={router} />
    </AppContext.Provider>
  );
}

export default function App() {
  return <AppWithAuth />;
}
