import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { Bell, Moon, Sun, RefreshCw, Download, ArrowRight, Shield, Trash2, Globe, Database, Palette, Monitor, Key, Smartphone, Clock, Check, User, Mail, BadgeCheck } from "lucide-react";
import { useSearchParams } from "react-router";
import { useApp } from "../context/AppContext";

export function SettingsPage() {
  const { dark, setDark, user } = useApp();
  const [searchParams, setSearchParams] = useSearchParams();
  const [notifications, setNotifications] = useState({ matchReminders: true, formAlerts: true, aiUpdates: false, teamChanges: true, reportReady: false });
  const [twoFactor, setTwoFactor] = useState(false);
  const [fontSize, setFontSize] = useState("Medium");
  const [layout, setLayout] = useState("Comfortable");
  const [accentColor, setAccentColor] = useState("#AAFF57");
  const [exportState, setExportState] = useState<"idle" | "loading" | "done">("idle");
  const [syncLoading, setSyncLoading] = useState(false);
  const [country, setCountry] = useState("India");
  const [timezone, setTimezone] = useState("Asia/Kolkata");
  const [language, setLanguage] = useState("English");
  const [dateFormat, setDateFormat] = useState("DD/MM/YYYY");
  const activeTab = searchParams.get("tab") || "notifications";

  const setActiveTab = (tab: string) => {
    setSearchParams({ tab });
  };

  const tabs = [
    { id: "profile",      label: "Profile",        icon: User },
    { id: "notifications", label: "Notifications", icon: Bell },
    { id: "security",      label: "Security",       icon: Shield },
    { id: "appearance",    label: "Appearance",     icon: Palette },
    { id: "data",          label: "Data & Sync",    icon: Database },
    { id: "region",        label: "Region",         icon: Globe },
  ];

  const Toggle = ({ value, onChange }: { value: boolean; onChange: () => void }) => (
    <button onClick={onChange} className={`w-11 h-6 rounded-full relative transition-colors flex-shrink-0 ${value ? "bg-[#AAFF57]" : "bg-border"}`}>
      <div className={`w-4 h-4 rounded-full bg-white absolute top-1 transition-transform ${value ? "translate-x-6" : "translate-x-1"}`} />
    </button>
  );

  const ToggleRow = ({ label, desc, value, onChange }: { label: string; desc: string; value: boolean; onChange: () => void }) => (
    <div className="flex items-center justify-between py-3 border-b border-border last:border-0">
      <div>
        <div className="text-sm font-medium text-foreground">{label}</div>
        <div className="text-[11px] text-muted-foreground mt-0.5">{desc}</div>
      </div>
      <Toggle value={value} onChange={onChange} />
    </div>
  );

  const renderContent = () => {
    switch (activeTab) {
      case "profile":
        return (
          <div className="space-y-5">
            <h2 className="font-display text-xl font-bold text-foreground">Profile</h2>
            <div className="bg-card border border-border rounded-xl p-5 space-y-5">
              <div className="flex items-center gap-4">
                <div className="w-16 h-16 rounded-2xl bg-[#AAFF57] flex items-center justify-center text-2xl font-bold text-[#0D0D06] shadow-sm">
                  {(user?.name || "RC").split(" ").map(part => part[0]).slice(0, 2).join("")}
                </div>
                <div className="min-w-0">
                  <div className="text-lg font-semibold text-foreground truncate">{user?.name || "Rahul Coach"}</div>
                  <div className="text-sm text-muted-foreground">{user?.role || "Coach"}</div>
                </div>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="rounded-xl border border-border bg-secondary/40 p-4">
                  <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground mb-1">Account</div>
                  <div className="text-sm font-medium text-foreground flex items-center gap-2"><BadgeCheck size={14} className="text-[#AAFF57]" /> Verified coaching profile</div>
                  <div className="text-[11px] text-muted-foreground mt-1">This profile is connected to your CRIIQ session.</div>
                </div>
                <div className="rounded-xl border border-border bg-secondary/40 p-4">
                  <div className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground mb-1">Email</div>
                  <div className="text-sm font-medium text-foreground flex items-center gap-2"><Mail size={14} className="text-muted-foreground" /> {user ? `${user.name.toLowerCase().replace(/\s+/g, ".")}@criiq.local` : "coach@teamcricket.com"}</div>
                  <div className="text-[11px] text-muted-foreground mt-1">Update this in the backend auth flow when available.</div>
                </div>
              </div>
              <div className="flex flex-wrap gap-3">
                <button className="px-4 py-2 bg-[#AAFF57] text-[#0D0D06] text-sm font-semibold rounded-lg hover:opacity-90 transition-opacity">Edit Profile</button>
                <button onClick={() => setActiveTab("security")} className="px-4 py-2 border border-border text-sm font-medium text-foreground rounded-lg hover:bg-secondary transition-colors">Security Settings</button>
              </div>
            </div>
          </div>
        );
      case "notifications":
        return (
          <div>
            <h2 className="font-display text-xl font-bold text-foreground mb-1">Notifications</h2>
            <p className="text-sm text-muted-foreground mb-5">Manage how and when you receive alerts</p>
            <div className="bg-card border border-border rounded-xl p-5">
              <ToggleRow label="Match Reminders" desc="Get notified 24h before scheduled matches" value={notifications.matchReminders} onChange={() => setNotifications(p => ({ ...p, matchReminders: !p.matchReminders }))} />
              <ToggleRow label="Player Form Alerts" desc="Alert when a player's form changes significantly" value={notifications.formAlerts} onChange={() => setNotifications(p => ({ ...p, formAlerts: !p.formAlerts }))} />
              <ToggleRow label="AI Recommendation Updates" desc="Notify when AI engine updates player scores" value={notifications.aiUpdates} onChange={() => setNotifications(p => ({ ...p, aiUpdates: !p.aiUpdates }))} />
              <ToggleRow label="Team Changes" desc="Alert on squad selection changes by other coaches" value={notifications.teamChanges} onChange={() => setNotifications(p => ({ ...p, teamChanges: !p.teamChanges }))} />
              <ToggleRow label="Report Ready" desc="Notify when AI pre-match reports are generated" value={notifications.reportReady} onChange={() => setNotifications(p => ({ ...p, reportReady: !p.reportReady }))} />
            </div>
          </div>
        );
      case "security":
        return (
          <div className="space-y-5">
            <h2 className="font-display text-xl font-bold text-foreground">Security</h2>
            <div className="bg-card border border-border rounded-xl p-5 space-y-4">
              <h3 className="font-semibold text-foreground text-sm">Change Password</h3>
              {["Current Password", "New Password", "Confirm New Password"].map(label => (
                <div key={label} className="space-y-1">
                  <label className="text-[12px] text-muted-foreground">{label}</label>
                  <div className="relative">
                    <Key size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
                    <input type="password" placeholder="••••••••"
                      className="w-full pl-9 pr-3 py-2 text-sm bg-secondary border border-border rounded-lg text-foreground focus:outline-none focus:ring-2 focus:ring-[#AAFF57]/40 placeholder:text-muted-foreground" />
                  </div>
                </div>
              ))}
              <button className="px-4 py-2 bg-[#AAFF57] text-[#0D0D06] text-sm font-semibold rounded-lg hover:opacity-90 transition-opacity">Update Password</button>
            </div>
            <div className="bg-card border border-border rounded-xl p-5">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm font-medium text-foreground flex items-center gap-2"><Smartphone size={14} className="text-muted-foreground" /> Two-Factor Authentication</div>
                  <div className="text-[11px] text-muted-foreground mt-0.5">Add an extra layer of security to your account</div>
                </div>
                <Toggle value={twoFactor} onChange={() => setTwoFactor(p => !p)} />
              </div>
            </div>
            <div className="bg-card border border-border rounded-xl p-5">
              <h3 className="font-semibold text-foreground text-sm mb-4">Active Sessions</h3>
              <div className="space-y-3">
                {[
                  { device: "MacBook Pro · Chrome", location: "Mumbai, India", time: "Active now", current: true },
                  { device: "iPhone 15 · Safari", location: "Mumbai, India", time: "2 hours ago", current: false },
                ].map((s, i) => (
                  <div key={i} className="flex items-center justify-between p-3 rounded-lg bg-secondary/40">
                    <div>
                      <div className="text-[13px] font-medium text-foreground flex items-center gap-2">
                        {s.device}
                        {s.current && <span className="text-[10px] bg-[#AAFF57]/15 text-[#AAFF57] px-1.5 py-0.5 rounded-full font-medium">Current</span>}
                      </div>
                      <div className="text-[11px] text-muted-foreground mt-0.5">{s.location} · {s.time}</div>
                    </div>
                    {!s.current && (
                      <button className="text-[11px] text-destructive hover:opacity-80 border border-destructive/30 px-2.5 py-1 rounded-lg transition-opacity">Revoke</button>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>
        );
      case "appearance":
        return (
          <div className="space-y-5">
            <h2 className="font-display text-xl font-bold text-foreground">Appearance</h2>
            <div className="bg-card border border-border rounded-xl p-5 space-y-5">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm font-medium text-foreground flex items-center gap-2"><Monitor size={14} className="text-muted-foreground" /> Theme</div>
                  <div className="text-[11px] text-muted-foreground mt-0.5">Switch between light and dark interface</div>
                </div>
                <div className="flex gap-2">
                  <button onClick={() => setDark(false)} className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] border transition-all ${!dark ? "bg-[#AAFF57] text-[#0D0D06] border-[#AAFF57] font-medium" : "border-border text-muted-foreground hover:text-foreground"}`}>
                    <Sun size={12} /> Light
                  </button>
                  <button onClick={() => setDark(true)} className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] border transition-all ${dark ? "bg-[#AAFF57] text-[#0D0D06] border-[#AAFF57] font-medium" : "border-border text-muted-foreground hover:text-foreground"}`}>
                    <Moon size={12} /> Dark
                  </button>
                </div>
              </div>
              <div>
                <div className="text-sm font-medium text-foreground mb-2">Font Size</div>
                <div className="flex gap-2">
                  {["Small", "Medium", "Large"].map(s => (
                    <button key={s} onClick={() => setFontSize(s)} className={`px-4 py-1.5 rounded-lg text-[12px] border transition-all ${fontSize === s ? "bg-[#AAFF57] text-[#0D0D06] border-[#AAFF57] font-medium" : "border-border text-muted-foreground hover:text-foreground"}`}>{s}</button>
                  ))}
                </div>
              </div>
              <div>
                <div className="text-sm font-medium text-foreground mb-2">Accent Color</div>
                <div className="flex gap-2">
                  {["#AAFF57", "#3ADCFF", "#A78BFA", "#FB923C", "#F87171"].map(c => (
                    <button key={c} onClick={() => setAccentColor(c)}
                      className="w-8 h-8 rounded-full transition-all"
                      style={{ backgroundColor: c, outline: accentColor === c ? `3px solid ${c}` : "none", outlineOffset: "2px" }} />
                  ))}
                </div>
              </div>
              <div>
                <div className="text-sm font-medium text-foreground mb-2">Layout Density</div>
                <div className="flex gap-2">
                  {["Dense", "Comfortable", "Spacious"].map(l => (
                    <button key={l} onClick={() => setLayout(l)} className={`px-4 py-1.5 rounded-lg text-[12px] border transition-all ${layout === l ? "bg-[#AAFF57] text-[#0D0D06] border-[#AAFF57] font-medium" : "border-border text-muted-foreground hover:text-foreground"}`}>{l}</button>
                  ))}
                </div>
              </div>
            </div>
          </div>
        );
      case "data":
        return (
          <div className="space-y-5">
            <h2 className="font-display text-xl font-bold text-foreground">Data & Sync</h2>
            <div className="bg-card border border-border rounded-xl p-5 space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm font-medium text-foreground flex items-center gap-2"><Clock size={14} className="text-muted-foreground" /> Last Synced</div>
                  <div className="text-[11px] text-muted-foreground mt-0.5">Today at 11:42 AM</div>
                </div>
                <button onClick={() => { setSyncLoading(true); setTimeout(() => setSyncLoading(false), 2000); }}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs border border-border rounded-lg text-muted-foreground hover:text-foreground transition-colors disabled:opacity-60"
                  disabled={syncLoading}>
                  <RefreshCw size={11} className={syncLoading ? "animate-spin" : ""} /> {syncLoading ? "Syncing…" : "Sync Now"}
                </button>
              </div>
              <div className="pt-3 border-t border-border">
                <button onClick={() => { setExportState("loading"); setTimeout(() => setExportState("done"), 2000); setTimeout(() => setExportState("idle"), 4000); }}
                  className="flex items-center gap-2 w-full px-4 py-2.5 border border-border rounded-lg text-sm text-foreground hover:bg-secondary transition-colors justify-between"
                  disabled={exportState === "loading"}>
                  <span className="flex items-center gap-2">
                    <Download size={14} className="text-muted-foreground" />
                    {exportState === "idle" && "Export All Data"}
                    {exportState === "loading" && "Preparing export…"}
                    {exportState === "done" && "Downloaded ✓"}
                  </span>
                  {exportState === "idle" && <ArrowRight size={13} className="text-muted-foreground" />}
                  {exportState === "loading" && <RefreshCw size={13} className="animate-spin text-muted-foreground" />}
                  {exportState === "done" && <Check size={13} className="text-[#AAFF57]" />}
                </button>
              </div>
              <div className="pt-1">
                <button className="flex items-center gap-2 w-full px-4 py-2.5 border border-[#E5484D]/30 rounded-lg text-sm text-[#E5484D] hover:bg-[#E5484D]/5 transition-colors">
                  <Trash2 size={14} /> Clear Cache
                </button>
              </div>
            </div>
          </div>
        );
      case "region":
        return (
          <div className="space-y-5">
            <h2 className="font-display text-xl font-bold text-foreground">Region & Language</h2>
            <div className="bg-card border border-border rounded-xl p-5 space-y-4">
              {[
                { label: "Country", value: country, set: setCountry, opts: ["India", "Australia", "England", "South Africa", "New Zealand", "Pakistan"] },
                { label: "Timezone", value: timezone, set: setTimezone, opts: ["Asia/Kolkata", "Australia/Melbourne", "Europe/London", "America/New_York", "Pacific/Auckland"] },
                { label: "Date Format", value: dateFormat, set: setDateFormat, opts: ["DD/MM/YYYY", "MM/DD/YYYY", "YYYY-MM-DD"] },
                { label: "Language", value: language, set: setLanguage, opts: ["English", "Hindi", "Tamil", "Telugu", "Marathi"] },
              ].map(f => (
                <div key={f.label} className="space-y-1">
                  <label className="text-[12px] font-medium text-muted-foreground">{f.label}</label>
                  <select value={f.value} onChange={e => f.set(e.target.value)}
                    className="w-full text-sm bg-secondary border border-border rounded-lg px-3 py-2 text-foreground focus:outline-none focus:ring-2 focus:ring-[#AAFF57]/40">
                    {f.opts.map(o => <option key={o}>{o}</option>)}
                  </select>
                </div>
              ))}
              <button className="px-4 py-2 bg-[#AAFF57] text-[#0D0D06] text-sm font-semibold rounded-lg hover:opacity-90 transition-opacity">Save Preferences</button>
            </div>
          </div>
        );
      default:
        return null;
    }
  };

  return (
    <div className="p-5 max-w-screen-lg mx-auto">
      <h1 className="font-display text-2xl font-bold text-foreground mb-5">Settings</h1>
      <div className="flex gap-5">
        {/* Sidebar */}
        <div className="w-48 flex-shrink-0">
          <div className="bg-card border border-border rounded-xl overflow-hidden">
            {tabs.map(tab => {
              const Icon = tab.icon;
              const active = activeTab === tab.id;
              return (
                <button key={tab.id} onClick={() => setActiveTab(tab.id)}
                  className={`w-full flex items-center gap-2.5 px-4 py-3 text-[13px] transition-colors text-left border-b border-border last:border-0 ${active ? "bg-[#AAFF57]/10 text-[#AAFF57] font-medium" : "text-muted-foreground hover:text-foreground hover:bg-secondary"}`}>
                  <Icon size={14} className="flex-shrink-0" style={active ? { color: "#AAFF57" } : {}} />
                  {tab.label}
                </button>
              );
            })}
          </div>
        </div>
        {/* Content */}
        <div className="flex-1 min-w-0">
          <AnimatePresence mode="wait">
            <motion.div key={activeTab} initial={{ opacity: 0, x: 8 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -8 }} transition={{ duration: 0.15 }}>
              {renderContent()}
            </motion.div>
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}
