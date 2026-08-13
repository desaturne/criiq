import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { RouterProvider, createBrowserRouter, Navigate } from "react-router";
import { AdminShell } from "../admin/AdminShell";
import { Root } from "../components/layout/Root";
import { AppContext } from "../context/AppContext";
import * as api from "../lib/api";
import { DashboardOverviewPage } from "../pages/DashboardOverviewPage";
import { DashboardPage } from "../pages/DashboardPage";
import { BuildXiPage } from "../pages/BuildXiPage";
import { MatchDetailPage } from "../pages/MatchDetailPage";
import { MatchesPage } from "../pages/MatchesPage";
import { PlayerProfilePage } from "../pages/PlayerProfilePage";
import { RecommendationsPage } from "../pages/RecommendationsPage";
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
      { path: "build-xi",        Component: BuildXiPage },
      { path: "matches",         Component: MatchesPage },
      { path: "matches/:id",     Component: MatchDetailPage },
      { path: "recommendations", Component: RecommendationsPage },
      { path: "simulator",       Component: SimulationPage },
      { path: "settings",        Component: SettingsPage },
      { path: "*",               element: <Navigate to="/dashboard" replace /> },
    ],
  },
]);

// The admin portal authenticates client-side against ADMIN_CREDENTIALS and
// never gets a server token, so unlike the user app there is nothing in
// api.getToken() to rebuild its session from after a reload. Without a flag of
// its own, refreshing the admin portal recomputed authMode as "user-login" and
// dumped the admin back on the user sign-in screen; only Log out should end
// the session.
const ADMIN_SESSION_KEY = "criiq_admin_session";

export function AppWithAuth() {
  const [authMode, setAuthMode] = useState<AuthMode>(() => {
    if (localStorage.getItem(ADMIN_SESSION_KEY) === "1") return "admin-app";
    return api.getToken() ? "user-app" : "user-login";
  });
  const [dark, setDark] = useState(true);
  const [selections, setSelections] = useState<Record<string, SelectionState>>({});
  const [token, setToken] = useState<string | null>(api.getToken());
  const [user, setUser] = useState<AuthUser | null>(null);

  const login = async (email: string, password: string) => {
    const result = await api.login(email, password);
    api.setToken(result.token);
    setToken(result.token);
    setUser(result.user);
    // Signing in as a user ends any admin session: the two modes are mutually
    // exclusive, and a flag left behind by an admin who closed the tab without
    // logging out would otherwise win on the next reload and send this user to
    // the admin portal instead of their own app.
    localStorage.removeItem(ADMIN_SESSION_KEY);
    setAuthMode("user-app");
  };

  const register = async (name: string, email: string, password: string, country: string) => {
    await api.register(name, email, password, country);
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
        .then(me => setUser({ id: 0, name: me.name, role: me.role, country: me.country, status: me.status }))
      .catch(() => { api.clearToken(); setToken(null); setAuthMode("user-login"); });
  }, [token, user]);

  // `selections` is the shared board that Build XI, Recommendations and the
  // squad panel all read and write. Saving it hits PUT /selection/{match_id},
  // but nothing ever called the matching GET, so a reload silently threw away
  // a saved XI while the backend still held it. Restore it here, once per
  // session, against the same fixture the save path targets (the next upcoming
  // match — neither end has a match picker yet).
  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    (async () => {
      try {
        const { upcoming } = await api.listMatches();
        const matchId = upcoming[0]?.id;
        if (!matchId) return;
        const saved = await api.getSelection(matchId);
        if (cancelled) return;
        const restored: Record<string, SelectionState> = {};
        for (const id of saved.xi) restored[id] = "select";
        for (const id of saved.extra) restored[id] = "reserve";
        for (const id of saved.excluded) restored[id] = "exclude";
        if (!Object.keys(restored).length) return;
        // Never clobber picks the coach made while this request was in flight.
        setSelections(prev => (Object.keys(prev).length ? prev : restored));
      } catch {
        /* nothing saved yet, or the fixture list is empty — start from a clean board */
      }
    })();
    return () => { cancelled = true; };
  }, [token]);

  // Admin login — completely separate, no user context
  if (authMode === "admin-login") {
    return (
      <AdminLoginPage
        onLogin={() => { localStorage.setItem(ADMIN_SESSION_KEY, "1"); setAuthMode("admin-app"); }}
        onBack={() => setAuthMode("user-login")}
      />
    );
  }

  // Admin app — own shell, no cricket components
  if (authMode === "admin-app") {
    return <AdminShell onLogout={() => { localStorage.removeItem(ADMIN_SESSION_KEY); setAuthMode("admin-login"); }} />;
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
