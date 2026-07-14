import { useNavigate } from "react-router";
import { Mail, BadgeInfo, UserCircle2, MapPin, ChevronLeft } from "lucide-react";

export function ProfilePage() {
  const navigate = useNavigate();

  const profile = {
    name: "Rahul Coach",
    email: "rahul@teamcricket.com",
    role: "Coach",
    team: "India A",
    initials: "RC",
    linkedPlayer: "Rahul Sharma",
  };

  return (
    <div className="p-5 max-w-screen-lg mx-auto space-y-5">
      <button onClick={() => navigate(-1)} className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors">
        <ChevronLeft size={14} /> Back
      </button>

      <div className="grid grid-cols-1 lg:grid-cols-[320px,1fr] gap-5">
        <section className="bg-card border border-border rounded-2xl p-6 shadow-sm">
          <div className="w-20 h-20 rounded-full bg-[#AAFF57]/15 border border-[#AAFF57]/30 flex items-center justify-center text-2xl font-bold text-[#5FA800] mx-auto">
            {profile.initials}
          </div>
          <div className="text-center mt-4">
            <h1 className="font-display text-2xl font-bold text-foreground">{profile.name}</h1>
            <div className="mt-2 inline-flex items-center gap-2 px-2.5 py-1 rounded-full bg-secondary text-muted-foreground text-[11px] font-medium">
              <BadgeInfo size={12} /> {profile.role}
            </div>
          </div>

          <div className="mt-5 space-y-3">
            <div className="flex items-center gap-3 text-sm text-foreground">
              <Mail size={14} className="text-muted-foreground" />
              <span>{profile.email}</span>
            </div>
            <div className="flex items-center gap-3 text-sm text-foreground">
              <MapPin size={14} className="text-muted-foreground" />
              <span>{profile.team}</span>
            </div>
            <div className="flex items-center gap-3 text-sm text-foreground">
              <UserCircle2 size={14} className="text-muted-foreground" />
              <span>Linked player profile: {profile.linkedPlayer}</span>
            </div>
          </div>
        </section>

        <section className="bg-card border border-border rounded-2xl p-6 shadow-sm space-y-5">
          <div>
            <h2 className="font-display text-xl font-semibold text-foreground">Account Profile</h2>
            <p className="text-sm text-muted-foreground mt-1">View and manage the current signed-in user profile.</p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="rounded-xl border border-border p-4">
              <div className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">Display name</div>
              <div className="mt-1 text-sm font-medium text-foreground">{profile.name}</div>
            </div>
            <div className="rounded-xl border border-border p-4">
              <div className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">Email address</div>
              <div className="mt-1 text-sm font-medium text-foreground">{profile.email}</div>
            </div>
            <div className="rounded-xl border border-border p-4">
              <div className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">Role</div>
              <div className="mt-1 text-sm font-medium text-foreground">{profile.role}</div>
            </div>
            <div className="rounded-xl border border-border p-4">
              <div className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">Team</div>
              <div className="mt-1 text-sm font-medium text-foreground">{profile.team}</div>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}