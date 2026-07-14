Project Overview

Build a web application called Criiq — a cricket team selection and analytics
platform used by coaches and selectors to pick the best playing XI using
data-driven insights (player form, opponent history, venue conditions, and an
AI recommendation engine).

Tech stack: Build this using React with Next.js (App Router), styled with
Tailwind CSS. Structure the project as real Next.js pages/routes (not a single
scrollable mockup) — one route per screen, listed below, so it can be handed
directly to a frontend developer to wire up to a REST API. Use component-based
architecture: shared layout (navbar + sidebar), reusable card/table/chart
components, and page-level components per route.

Design direction: Do NOT copy a generic dark-navy-sidebar-with-orange-accent
admin dashboard look. Design something distinct and more premium: think a hybrid
of a modern sports-analytics broadcast graphic (like Hawk-Eye/CricViz overlays)
and a clean SaaS product (like Linear or Vercel's dashboard). Use a confident,
editorial type scale (large serif or geometric-sans headlines paired with a
clean sans body font), generous whitespace, and one strong accent color against
a mostly neutral (off-white / charcoal) palette — avoid pure black-on-navy panels
everywhere. Data visualizations (bars, radial gauges, win-probability curves)
should feel like the visual hero of each page, not an afterthought. Support both
light and dark mode.

Animation requirements: Use subtle, purposeful motion throughout —


Page transitions: fade + slight slide on route change
Cards: stagger-in on load (each card appears ~50ms after the previous)
Numbers/stats: count-up animation when a stat first appears on screen
Bars/gauges/progress rings: animate from 0 to value on load
Hover states: gentle scale (1.02) + shadow lift on interactive cards
Recommendation engine result: players animate into their ranked position
(like a leaderboard reveal) rather than just appearing
Toasts/alerts: slide in from top-right, auto-dismiss with a shrinking progress bar
Modals: scale + fade in from center with a backdrop blur



Global Layout


Top navbar: Logo (Criiq), primary nav (Dashboard, Squads, Matches,
Recommendations, Reports, AI Assistant), notification bell, user avatar with
role badge (Admin / Coach / Player) and dropdown (Profile, Settings, Logout).
Left sidebar (collapsible): section-specific sub-navigation that changes
depending on which top-level area you're in.
Role-aware UI: Admin sees user management; Coach sees squad/recommendation
tools; Player sees only their own profile and stats (read-only). Design all
three states for the dashboard home.



Pages / Routes

1. /login and /register


Split-screen layout: left side branded panel with a subtle animated cricket-ball
seam-line pattern or particle effect; right side the form.
Login: email, password, "remember me", forgot password link.
Register: name, email, password, confirm password, role selector (Coach /
Player — Admin is seeded, not self-registerable).
Inline validation with animated shake on error, success checkmark animation
on valid field blur.
Maps to: POST /auth/register, POST /auth/login, POST /auth/refresh.


2. /forgot-password


Simple centered card, email input, confirmation state after submit.


3. /dashboard (Player Performance Dashboard — home after login)


Redesign of the reference screenshot's core idea, not its style.
Header: title, current opposition context selector (dropdown: "vs Australia"),
and a squad summary chip cluster ("Selected 11/15", "Reserve 4").
A filterable, sortable list/grid of player cards. Each card shows:

Photo, name, role/archetype badge (e.g. "Top-order Batsman", "Right-arm Fast")
Recent form (last 5): key stat chips (Runs/SR/Avg for batters,
Wkts/Econ/BBI for bowlers) — animate these as small sparkline trends, not
just numbers
Career summary block
"vs current opposition" success-rate radial gauge + one-line insight text
Selection action: three-state toggle (Select / Exclude / Undecided) with
distinct colors and icon, animated on click



"Generate Report" primary CTA (floating or sticky at bottom of sidebar).
Maps to: GET /players, GET /players/{id}/recent-form,
GET /players/{id}/against-opponent.


4. /squads


CRUD interface for managing player and coach records (Admin/Coach only).
Table view with search, filters (role, team, status: Active/Inconsistent/
Inactive/Unknown), sortable columns, pagination.
Row actions: view profile, edit, deactivate.
"Add Player" / "Add Coach" opens a slide-over panel (not a full page) with a
form: name, DOB, role, batting hand, bowling style, team, contact info.
Bulk actions toolbar appears when rows are checked.
Maps to: player/coach CRUD endpoints, GET /players.


5. /squads/[id] (Player Profile / Detail page)


Full profile: photo, bio, career batting AND bowling stat blocks side by
side, phase-split chart (powerplay/middle/death performance as a
segmented bar), vs-pace/vs-spin and vs-RHB/vs-LHB split cards, venue
performance table, and a "record vs every opponent" expandable table.
A plain-language "Strengths Summary" callout box (styled like a scouting
note, e.g. handwritten-note card style but clean, not gimmicky).
Maps to: player detail, GET /players/{id}/recent-form,
GET /players/{id}/against-opponent, GET /matchups/batsman-vs-bowler.


6. /matches


List of upcoming/past matches as cards: teams, venue, date, status badge
(Upcoming/Live/Completed).
Clicking a match goes to Match Details.


7. /matches/[id] (Match Details)


Redesign of the second reference screenshot with a distinct visual language.
Hero panel: match title, venue, date/time, opponent
profile card with recent form (W/L pill sequence) and a "Detailed Scouting
Report" link.
Pitch Report panel: condition description + animated horizontal bars for
Pace Support / Spin Support / Batting Anchors / Finishers suitability, plus
a "Pro Tip" callout.
Pitch panel: pace/spin support as animated radial gauges, short pitch note
note, and a conditional "Impact Alert" banner (e.g. wind assisting swing).
Maps to: GET /venues/{id}/analysis, GET /opponents/{id}/analysis,
GET /reports/pre-match.


8. /recommendations (Core AI feature — most important screen)


Input panel (left or top): opponent selector, venue selector, pitch
condition selector, match format, and a "Generate Recommendation" button.
Results: ranked list of top 20 recommended players, each with:

Overall recommendation score (animated radial or bar, 0–100)
A breakdown chip row of the contributing factors (form, vs-opponent,
venue fit, matchup advantage) — clicking a player expands an
"Explain this pick" panel with the reasoning in plain language.
Select/exclude toggle to build the final XI from the ranked list, with a
live-updating "Selected X/11" counter.



A secondary results panel: predicted win probability for the currently
assembled XI, shown as an animated probability bar/gauge that updates live
as the coach adjusts selections.
Maps to: POST /selection/recommend, POST /selection/explain,
POST /prediction/win-probability, POST /strategy/game-plan.


9. /reports


List of generated pre-match scouting reports (cards with match, date,
status: Draft/Final).
Report detail view: a clean, print-friendly document layout combining
match details, recommended XI, key matchups, pitch notes, and
strategy recommendations — designed so it could be exported as PDF.
Maps to: GET /reports/pre-match, POST /strategy/game-plan.


10. /assistant


Chat interface, coach-facing natural-language AI assistant.
Left: conversation list/history. Right: chat thread with message bubbles,
typing indicator animation, and support for the assistant returning rich
content (e.g. an inline mini player card or stat table inside a chat
bubble, not just plain text).
Maps to: POST /assistant/chat.


11. /settings and /profile


Account settings, notification preferences, theme toggle (light/dark),
and role-specific fields.



Component Library to Design

Design these as reusable, consistently styled components (Figma components /
React components), since the same visual language repeats across pages:


Player card (compact + expanded variants)
Stat chip / stat block
Radial gauge (for percentages/scores/probabilities)
Segmented phase bar (powerplay/middle/death)
Three-state selection toggle (Select/Exclude/Undecided)
Data table with sort, filter, pagination, row expand
Slide-over panel (for forms/CRUD)
Modal (confirm actions, e.g. "Confirm retirement alert")
Toast/notification
Badge/pill (role, status, form trend)
Chat bubble (user + assistant variants, including rich-content variant)
Empty state illustration (e.g. "No matches scheduled yet")
Loading skeletons for every card/table type (match the shape of the real
content, animate with a shimmer)



Data Shape Notes (for backend alignment)

Design each card/table to display fields that map directly to these backend
concepts, so the frontend dev and backend dev agree on shape early:


Player: id, name, role, battingHand, bowlingStyle, status (ACTIVE/INCONSISTENT/INACTIVE/UNKNOWN), team, photoUrl
Recent form: last 5 matches array with per-match runs/SR/avg or
wkts/econ/BBI
Career: matches, innings, runs, average, SR, 50s/100s (batting); overs,
wickets, economy, average, SR, best (bowling)
vs-opponent: success rate %, notable matchups, W/L record
Recommendation result: playerId, score (0-100), factorBreakdown {form, vsOpponent, venueFit, matchupAdvantage}, explanation (string)
Win probability: battingTeamWinProb, bowlingTeamWinProb, phase



Deliverable

Produce this as a working Next.js + Tailwind project with the routes above,
using mock/sample data matching the field names described, so the structure
and component props are ready to swap for real API calls.