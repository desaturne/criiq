1. Product Summary

A data-driven cricket team management platform for coaches and analysts. Core
loop: input match context (opponent, venue, pitch, format) → AI recommendation
engine scores every player → coach reviews explainable recommendations → coach
builds and locks the Playing XI → system generates a pre-match report.

Reference screenshots show a functional but generic dashboard (white cards,
orange/navy, static bars). Build something sharper, more "sports broadcast
meets fintech terminal" — confident, data-dense, kinetic — not a generic SaaS
admin template. Light mode only — do not design a dark theme.


2. Design Direction

Visual identity — "Match Command Center," in light mode.


Base theme: Clean, bright canvas — near-white background (#F7F8FA) with
pure white (#FFFFFF) card panels. No dark mode, no near-black canvas
anywhere in the design.
Accent system: A confident two-tone signal system that still reads
clearly on a light background:

Deep lime/signal green (#5FA800 or similar — saturated enough to
stay legible on white, not the pale electric lime that only works on
dark) for primary actions & "in-form/selected" states
Signal coral (#E5484D) for risk/excluded/alerts
Deep cyan/teal (#0891B2) for secondary data (venue/weather/pitch)



Cards: Instead of glass-panels-on-dark, use crisp white cards with a
soft, subtle drop shadow (not a border-only flat look), 1px hairline border
in a light neutral grey, 12–16px radius. Depth comes from shadow layering,
not glow.
Typography: A grotesk/condensed display face for big stat numbers (e.g.,
Space Grotesk, General Sans, or Inter Tight) paired with a neutral body font
(Inter). Big numbers should feel like a scoreboard — tabular nums, tight
tracking, high-contrast dark text on white.
Data viz: Radial/gauge meters for percentages (success rate, pace/spin
support), animated sparkline trends for "recent form," and a horizontal
xG-style momentum strip instead of plain progress bars — same energy as a
dark broadcast graphic, just recolored for a light background with strong
contrast.
Player cards: Circular photo with a colored status ring (green ring =
selected, red ring = excluded, dashed grey = reserve) instead of a small
badge — status should be readable at a glance from across a room.
Iconography: Custom line-icon set, 1.5px stroke, rounded caps —
consistent with a "broadcast graphics" feel (think Hawk-Eye / CricViz
overlays), not generic dashboard icon packs.



3. Motion & Animation Spec

Motion should feel like a live sports broadcast graphic, not a corporate
fade-in.


Page transitions: 200–260ms shared-axis slide + fade between sidebar
sections (Framer Motion AnimatePresence).
Number counters: All stat numbers (runs, avg, win %, success rate) count
up from 0 on mount (~600ms, ease-out).
Bars/gauges: Radial gauges sweep from 0 to value on load (~800ms
cubic-bezier), horizontal bars grow left-to-right with a slight overshoot
bounce.
Player card selection: Tapping Select/Exclude/Reserve triggers a
ring-pulse animation on the avatar + a 150ms scale-bounce on the button;
card border color morphs over 200ms.
Recommendation results: Top-20 list animates in as a staggered list
(30–40ms delay per row), rows slide up + fade in, sorted by AI score with
the score bar filling in after the row settles.
Live match mode: Ball-by-ball ticker uses a marquee/scroll-in effect per
event; run/wicket events flash a colored highlight strip that fades over 1s.
Hover states: Cards lift 2–4px with a slightly deeper shadow on hover
(desktop); tap-scale 0.97 on mobile.
Loading: Skeleton shimmer (diagonal gradient sweep, light grey tones)
for all async data — never a jarring flash.
Micro-interaction: Toggle switches, tabs, and filter chips use spring
physics (stiffness ~300, damping ~20) rather than linear transitions.


Recommended stack: Framer Motion for React, or GSAP if using vanilla/Vue. If
prototyping in Figma, use Smart Animate with these same timing values so dev
handoff timing matches.


4. Information Architecture

Sidebar nav — Dashboard and Player Form are separate, distinct sections.
The Dashboard is a high-level overview only; it must never show the detailed
player-by-player analytics grid. That grid lives exclusively under its own
"Player Form" nav item.


Dashboard (Overview) — top banner + team snapshot, upcoming match
countdown, squad availability, quick recommendation CTA (see Section 5.2)
Player Form (Analytics) — the full filterable player-card grid with
recent form, career stats, and vs-opposition analysis (see Section 5.3)
Match Details — venue/pitch/weather/opponent breakdown for a match
Squads — CRUD for players & coaches
Recommendation — the core AI feature: input context → get ranked Top 20
→ build Playing XI
Live Match — ball-by-ball tracking view
Reports — generated pre-match scouting reports (PDF/shareable)
Auth — Login / Register / Profile
Settings



5. Screen-by-Screen Spec (with backend field mapping)

For each screen: Purpose → Key UI elements → Data fields (map to Pydantic
models) → Backend endpoint(s) it consumes.

5.1 Auth — Login / Register / Profile


UI: Split-screen layout — left: light gradient hero (white → pale
green/cyan wash) with an animated stat ticker (looping player stats as
ambient motion); right: form panel. Role-aware — after login, route
Admin/Coach/Player to different dashboard defaults.
Fields: email, password, full_name, role (admin/coach/player — role not
user-selectable on register unless Admin-invited), confirm_password.
States: loading, invalid credentials (shake animation + coral border),
token expired → silent refresh via auth/refresh, logged out.
Endpoints: POST /auth/register, POST /auth/login,
POST /auth/logout, POST /auth/refresh, GET /auth/profile.
Profile page: avatar upload, role badge, editable name/email, "linked
player profile" if role=player.


5.2 Dashboard (Overview)


Top banner (required): A full-width hero banner at the very top of the
page — similar in spirit to the "Upcoming Match" hero in the Match Details
reference, but this one anchors the whole Dashboard. Light gradient
background (white → pale lime or cyan wash, not a dark panel), showing: the
next upcoming match (teams, venue, countdown timer ticking down live),
overall squad readiness at a glance, and a prominent "Run Recommendation"
primary CTA button (deep lime, subtle glow/shadow on hover). This banner
should feel like the page's hero — largest visual element, sits above
everything else.
Below the banner: a row of 4 stat tiles (Squad size, Selected 11/15,
Reserves, Days to next match) with count-up animation, then a compact
"recent activity" or "quick insights" panel (e.g. injury flags, form
alerts). No individual player cards or the detailed player-form grid
here — that content belongs only on the Player Form page.
Data: aggregate from GET /players, upcoming match info from
GET /venues/{id}/analysis + match schema.


5.3 Player Form (its own nav item — redesign of Image 1)


UI: A filterable grid of player cards (2–3 columns desktop, 1 mobile) +
a sticky filter bar (role, form trend, selection status). Each card:

Avatar with status ring, name, role tag
Mini sparkline for "Recent Form (Last 5)" instead of 3 flat number boxes
Radial gauge for "Success Rate vs Opposition"
Expandable drawer (click card → slide-down panel) revealing Career
Summary + full vs-opposition narrative, instead of always-visible dense
text
Select / Exclude / Reserve as a segmented control (animated pill slides
between the 3 states) instead of 3 separate buttons



Fields (per player): player_id, name, role (e.g. top-order batsman, right-arm fast), photo_url, selection_status (selected/excluded/reserve), recent_form: {runs|wickets, strike_rate|economy, average, best}, consistency_trend (%), career_summary: {matches, innings, runs|wickets, average, strike_rate, elite_percentile_note}, vs_opponent: {success_rate, narrative_text, key_matchups[]}.
Endpoints: GET /players, GET /players/{id}/recent-form,
GET /players/{id}/against-opponent.
Header counters: Selected X/15, Reserve Y — animated count, live-updates
as coach toggles cards.


5.3b Player Profile & Compare (extends the PlayerCard from selection tool into a full profile + comparison system)

A. Card → Profile (view)


Clicking anywhere on a player card (outside the segmented
Select/Exclude/Reserve control) opens a full Player Profile as a right-side
slide-in panel (desktop) or full-screen sheet (mobile) — not a small
popover, since there's a lot of data to show.
Profile header: large photo, name, role, jersey/cap number, status ring, and
the Select/Exclude/Reserve control repeated here so the coach can act
without closing the panel.
Body organized into tabs or stacked sections: Overview (career summary,
recent-form sparkline, radial success-rate gauge), Vs. Opposition (matchup
narrative + key head-to-heads), Match History (scrollable list of recent
innings/spells), Vs. Bowler/Batsman Matchups (table, feeds
GET /matchups/batsman-vs-bowler).
A persistent "Compare" button sits in the profile header (icon: two
overlapping bars/silhouettes) — entry point into comparison mode.
Panel opens/closes with a spring slide (~280ms) + light backdrop dim;
closing via swipe-down (mobile) or click-outside/Esc (desktop).


B. Compare flow


Tapping Compare — either from the profile panel or from a small
compare-icon on the card itself (appears on hover/long-press) — puts the UI
into "comparison picker" mode: a lightweight search/select overlay listing
other players (filterable by role, so batsmen compare against batsmen by
default but any pairing is allowed).
Alternative entry point: a persistent compare tray — as the coach browses
the Player Form grid, each card gets a small checkbox/"+" affordance;
checking two (or up to 4) cards shows a floating "Compare Selected (2)" bar
pinned to the bottom of the screen, tapping it opens the comparison view
directly.
Comparison view: side-by-side (2-up on desktop, swipeable stacked cards on
mobile) layout. Top: both player photos/names/roles mirrored left-right.
Below: row-by-row stat comparison (Recent Form, Career Avg, Strike
Rate/Economy, Success Rate vs Opposition, Consistency Trend) where the
better value in each row is highlighted (lime background chip) and the
difference is called out (e.g. "+12.4 avg"). Include an overlaid
radar/spider chart plotting normalized scores across 5–6 dimensions (form,
consistency, matchup strength, venue fit, experience) so the two players'
shapes visually overlap for instant read.
Coach can swap either player out via a small "Change" control on their
column without leaving the comparison view, and can add a third/fourth
player if comparing more than two (columns compress responsively).
Comparison animates in with both columns sliding in from opposite edges
(~250ms, slight stagger) and the radar chart polygon morphing/drawing in
over ~500ms.


Fields: comparison_request: {player_ids: []}, comparison_result: [{player_id, stats: {...same shape as player profile...}, radar_scores: {form, consistency, matchup, venue_fit, experience}}].

Endpoints: reuse GET /players/{id}/recent-form,
GET /players/{id}/against-opponent, GET /matchups/batsman-vs-bowler per
selected player, plus a new composite endpoint POST /players/compare
(accepts a list of player_ids, returns all comparison fields for each in one
call) — cheaper than firing N parallel requests, and keeps the radar-chart
normalization logic (which needs relative scaling across the compared set) on
the backend rather than duplicated in the client.

5.4 Match Details (redesign of Image 2)


UI: Hero banner card (light gradient, match title, venue pin + date/time,
"Upcoming/Live/Completed" status chip) with an animated countdown timer
instead of static text. Three-column grid below: Opponent Profile (crest,
recent form W/L strip as animated dots, link to full scouting report),
Pitch Report (radial meters for Pace/Spin/Batting/Finishers instead of flat
bars, pro-tip in a highlighted quote card), Weather (animated weather icon,
rain probability as a radial dial, impact alert banner with icon).
Fields: match: {id, teams, venue, datetime, status}, opponent: {name, crest_url, recent_form[], scouting_report_url}, pitch_report: {wicket_condition_text, pace_support, spin_support, batting_anchors, finishers, pro_tip, updated_at}, weather: {rain_probability, summary_text, wind_speed, impact_alert}.
Endpoints: GET /venues/{id}/analysis, GET /opponents/{id}/analysis,
GET /reports/pre-match (for "Detailed Scouting Report" link).


5.5 Squads (CRUD — Players & Coaches)


UI: Table/grid toggle view. Table: sortable columns (name, role,
matches, avg, status), inline row actions (edit/deactivate), bulk-select
toolbar animates in from top when rows are checked. "Add Player/Coach" opens
a slide-in side panel form (not a modal — keeps context visible),
multi-step: Basic Info → Stats/Role → Photo.
Fields — Player: id, full_name, role, batting_style, bowling_style, dob, nationality, photo_url, career_stats{}, contact_info, active_status.
Fields — Coach: id, full_name, specialization (batting/bowling/fielding/head), email, assigned_squad_id, active_status.
Endpoints: standard CRUD — GET/POST/PATCH/DELETE /players,
GET/POST/PATCH/DELETE /coaches (see Section 6).


5.6 Recommendation (core feature — most important screen)


Step 1 — Context Input panel: Card with dropdowns/searchable selects for
opponent, venue, pitch_type, format (T20/ODI/Test), weather_conditions, plus
a prominent "Generate Recommendation" button with a loading state that
morphs into a progress animation (e.g., "Analyzing 285 matches... Scoring 22
players... Ranking...") — makes the AI computation feel tangible, 2–3s
staged progress even if the real call is fast.
Step 2 — Results: Ranked list of Top 20 players, each row showing: rank,
avatar, name, role, AI score (0–100, shown as animated horizontal fill bar +
number), and a "Why" chip. Clicking "Why" expands an inline explanation
panel (feeds POST /selection/explain) showing weighted factors as a
horizontal stacked bar (e.g., Opponent Matchup 35%, Venue Fit 25%, Recent
Form 20%, Pitch Suitability 20%) — makes the recommendation explainable and
trustworthy.
Step 3 — Build XI: Drag-and-drop from the ranked list into a "Playing
XI" tray (11 slots) and "Reserves" tray (4 slots) at the bottom, sticky on
scroll. Slot count updates live. "Confirm Squad" button locks selection and
triggers report generation.
Bonus panel: Win probability meter (POST /prediction/win-probability)
updates live as the coach swaps players in/out of the XI — dragging a player
in/out should visibly move a probability needle.
Fields: recommendation_request: {opponent_id, venue_id, pitch_type, format, weather}, recommendation_result: [{player_id, score, rank, factor_breakdown[]}], selection_state: {playing_xi[11], reserves[4]},
win_probability: {value, delta_on_change}.
Endpoints: POST /selection/recommend, POST /selection/explain,
POST /strategy/game-plan, POST /prediction/win-probability.


5.7 Live Match


UI: Ball-by-ball ticker (scrollable horizontal strip, current over
highlighted), live scorecard, run-rate graph (line chart updating in real
time), momentum meter (animated horizontal gauge shifting between teams).
Fields: live_match: {score, overs, current_batsmen[], current_bowler, recent_balls[], run_rate, required_rate}.
Endpoints: WebSocket or polling endpoint for live data (flag to backend
dev: needs a GET /matches/{id}/live or WS channel — not yet in the todo
list, worth adding).


5.8 Reports


UI: Gallery of generated pre-match reports as cards (thumbnail preview,
match name, generated date), click to open a formatted report view with
sections mirroring Match Details + Recommendation summary. "Generate Report"
button triggers this with a document-assembling animation (pages stacking).
Endpoint: GET /reports/pre-match.


5.9 AI Assistant (chat) — persistent element


UI: Floating chat bubble (bottom-right) that expands into a slide-up
panel. Coach can ask natural-language questions ("Who's our best death
bowler vs left-handers on a spin pitch?"). Messages stream in
token-by-token (typewriter effect). Suggested prompt chips above the input
for common queries.
Endpoint: POST /assistant/chat.



6. Backend Alignment Notes (for the backend developer)


Auth: JWT access + refresh token pattern. Store role in the JWT payload
so the frontend can route without an extra call. Roles: admin, coach,
player (read-only views for player role — they should see only their own
form/analytics).
Missing CRUD endpoints to add to the table:
POST/GET/PATCH/DELETE /players/{id} (full CRUD, not just GET),
POST/GET/PATCH/DELETE /coaches/{id}, POST /matches (create/schedule a
match), GET /matches/{id}/live (or WS) for the Live Match screen,
POST /players/compare (batch comparison — see Section 5.3b).
Consistent response envelope: { data, meta: { page, total }, error } —
needed since Player Form, Squads, and Recommendation screens all use
paginated/filterable lists.
Score/percentage fields: always return raw 0–1 floats from the API; let
the frontend format as % — keeps chart libraries consistent.
selection/explain response shape: must return a factor list with
{factor_name, weight, contribution_score}[] so the frontend can render the
stacked "Why" bar without extra transformation.
Enums to standardize early: player_role, selection_status (selected|excluded|reserve), match_format (T20|ODI|Test), pitch_type.



7. Component Library to Build


StatTile (animated counter)
RadialGauge (percentage meter)
Sparkline (mini trend line)
PlayerCard (grid + list variants)
SegmentedSelectionControl (Select/Exclude/Reserve)
RankedListRow (recommendation results, with expandable "Why" panel)
DragDropSlot (XI/Reserve tray)
ProbabilityMeter (win % needle)
StatusRing (avatar wrapper)
SlidePanel (CRUD forms)
SkeletonShimmer
ToastNotification (for save/error states)
ChatBubble + StreamingMessage
PlayerProfilePanel (slide-in, tabbed, view/act on a single player)
CompareTray (floating bottom bar for multi-select comparison)
ComparisonView (side-by-side stat rows + radar chart)
RadarChart (normalized multi-dimension comparison)
DashboardBanner (top hero banner: countdown, squad readiness, primary CTA)



8. Responsive & Accessibility Notes


Breakpoints: mobile (<640px) collapses sidebar to bottom tab bar;
tablet (640–1024px) collapses sidebar to icon-only rail; desktop (>1024px)
full sidebar.
All color-coded status (selected/excluded/reserve) must also carry a text
label or icon — don't rely on color alone (colorblind accessibility).
Respect prefers-reduced-motion: fall back to simple opacity fades, no
counters/bounces.
Minimum tap target 44px on mobile controls (segmented select, drag handles
need a larger invisible hit area).
Ensure sufficient contrast throughout, since this is a light-mode-only
product — test accent colors (lime, coral, cyan) against white backgrounds
for WCAG AA text contrast, not just decorative use.



9. Suggested Prompt for Figma AI (condensed version)


Design a light-mode-only "Match Command Center" web app for cricket team
analytics. Base canvas near-white (#F7F8FA) with clean white cards (soft
drop shadow, subtle hairline border, 12–16px radius) — no dark theme
anywhere. Accent colors: deep signal green (#5FA800) for primary/selected
states, coral (#E5484D) for excluded/risk, deep cyan (#0891B2) for
secondary data. Typography: condensed grotesk display font for large stat
numbers, Inter for body. Replace flat progress bars with radial gauge meters
and sparklines. Player cards use circular avatars with colored status rings
(green=selected, red=excluded, dashed grey=reserve) and a segmented pill
control for Select/Exclude/Reserve.

The Dashboard is a separate page from Player Form — Dashboard shows only
a large top hero banner (next match countdown, squad readiness, "Run
Recommendation" CTA) plus a row of summary stat tiles; it must NOT show the
individual player cards grid. "Player Form" is its own nav item containing
the full filterable player-analytics grid with expandable detail drawers.

Also include: a match-details page with animated pitch/weather gauges, a
squad CRUD table with slide-in edit panels, a core "Recommendation" flow —
context input form → animated scoring/loading state → ranked top-20 list
with explainable "why" score breakdowns → drag-and-drop Playing XI builder
with a live win-probability needle, and a player profile + compare system —
clicking a card opens a tabbed slide-in profile panel with a "Compare"
action, plus a floating multi-select compare tray that opens a side-by-side
comparison view with highlighted stat differences and an overlaid radar
chart. Add a floating AI assistant chat bubble.

Motion throughout should feel like broadcast sports graphics: counters count
up, gauges sweep in, list rows stagger in, selection states pulse. Fully
responsive with a collapsible sidebar. Build in React + Next.js (App
Router) with Tailwind CSS.




Next step suggestion: once the design is built in Figma, export the token
set (colors, spacing, radii, font scale) as a JSON/CSS-variable file first —
that becomes the single source of truth for both the frontend build and keeps
the backend developer's enum/response-shape decisions (Section 6) aligned with
what the UI actually needs.