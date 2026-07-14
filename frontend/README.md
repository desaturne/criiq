# Criiq — Frontend

A data-driven cricket team selection and analytics platform for coaches and
selectors, built around a dark, broadcast-inspired "Match Command Center"
aesthetic. Includes a user-facing coach/player app and a separate admin
console.

## Tech Stack

- React 18 + TypeScript
- Vite 6
- Tailwind CSS 4
- React Router 7
- Framer Motion (`motion`)
- lucide-react (icons)

## Getting Started

```bash
npm install
npm run dev
```

The dev server will start on the port Vite assigns (typically `http://localhost:5173`).

### Build for production

```bash
npm run build
```

### Type-check

```bash
npx tsc --noEmit
```

## Project Structure

The app was split from a single-file prototype into a conventional
feature-based layout. Each screen, shared component, and data source lives
in its own file so it's easy to find, test, and hand off.

```
.
├── docs/                            Product & design reference docs
│   ├── project-overview.md
│   └── design-spec.md
├── index.html                       Vite entry HTML
├── tsconfig.json
├── vite.config.ts
└── src/
    ├── main.tsx                     App bootstrap
    ├── vite-env.d.ts
    │
    ├── types/
    │   └── index.ts                 All shared TS types & interfaces
    │
    ├── data/                        Mock data (stand-in for a future API)
    │   ├── players.ts
    │   ├── matches.ts
    │   ├── chat.ts
    │   ├── nav.ts
    │   ├── ticker.ts
    │   └── admin-users.ts
    │
    ├── context/
    │   └── AppContext.ts            Global app context (theme, selections)
    │
    ├── hooks/
    │   ├── useCountUp.ts
    │   └── useInView.ts
    │
    ├── components/
    │   ├── common/                  Small reusable UI primitives
    │   │   ├── CricketBall.tsx
    │   │   ├── RadialGauge.tsx
    │   │   ├── SparkLine.tsx
    │   │   ├── PhaseBar.tsx
    │   │   ├── SelectionControl.tsx
    │   │   ├── AvatarWithRing.tsx
    │   │   ├── StatusBadge.tsx
    │   │   ├── FactorBar.tsx
    │   │   ├── AnimatedStat.tsx
    │   │   ├── CountdownTimer.tsx
    │   │   └── LiveTicker.tsx
    │   ├── layout/                  App shell
    │   │   ├── Navbar.tsx
    │   │   ├── Sidebar.tsx
    │   │   └── Root.tsx             Route layout (renders <Outlet/>)
    │   ├── player/
    │   │   ├── PlayerCard.tsx
    │   │   └── PlayerCompareModal.tsx
    │   └── squad/
    │       └── SquadSelectionPanel.tsx
    │
    ├── pages/                       One file per user-facing route
    │   ├── auth/
    │   │   ├── LoginPage.tsx
    │   │   └── AdminLoginPage.tsx
    │   ├── DashboardOverviewPage.tsx
    │   ├── DashboardPage.tsx
    │   ├── SquadsPage.tsx
    │   ├── PlayerProfilePage.tsx
    │   ├── MatchesPage.tsx
    │   ├── MatchDetailPage.tsx
    │   ├── RecommendationsPage.tsx
    │   ├── AssistantPage.tsx
    │   ├── ReportsPage.tsx
    │   └── SettingsPage.tsx
    │
    ├── admin/                       Admin console (separate from user app)
    │   ├── AdminShell.tsx
    │   ├── context/
    │   │   └── AdminContext.ts
    │   └── pages/
    │       ├── AdminOverview.tsx
    │       ├── AdminUsers.tsx
    │       ├── AdminRoles.tsx
    │       ├── AdminSystem.tsx
    │       └── AdminActivity.tsx
    │
    ├── app/
    │   └── App.tsx                  Auth gate + router config (entry component)
    │
    └── styles/
        ├── index.css                 Master stylesheet (imports the rest)
        ├── fonts.css
        ├── tailwind.css
        └── theme.css
```

## Auth Flow

The app has two independent auth flows managed by `authMode` state in
`AppWithAuth` (`src/app/App.tsx`):

- **User login** (`pages/auth/LoginPage.tsx`) — coach/player sign-in.
- **Admin login** (`pages/auth/AdminLoginPage.tsx`) — reached via the
  "Admin access" link on the sign-in screen. Demo credentials (mock/hardcoded
  in `src/data/admin-users.ts`, no real backend):
  - Email: `admin@criiq.in`
  - Password: `Admin@2024`

> These are placeholder credentials for the frontend prototype only. Replace
> with real authentication before connecting to a production backend.

## Routing

`src/app/App.tsx` defines the React Router tree. All authenticated routes
render inside `components/layout/Root.tsx`, which provides the navbar,
sidebar, live ticker, and an `<Outlet/>` for the active page.

| Path                  | Page                          |
|------------------------|-------------------------------|
| `/dashboard`           | `DashboardOverviewPage`       |
| `/players`              | `DashboardPage`               |
| `/players/:id`          | `PlayerProfilePage`           |
| `/squads`               | `SquadsPage`                  |
| `/matches`              | `MatchesPage`                 |
| `/matches/:id`          | `MatchDetailPage`             |
| `/recommendations`      | `RecommendationsPage`         |
| `/assistant`            | `AssistantPage`               |
| `/reports`              | `ReportsPage`                 |
| `/settings`             | `SettingsPage`                |

## Notes

- This is currently a frontend-only prototype: all data (users, players,
  matches, selections) is mocked in `src/data/`. Types in `src/types/index.ts`
  are written to map cleanly onto a future REST API.
- The codebase is fully typed and passes `tsc --noEmit` with `strict` mode on.
- See `docs/project-overview.md` and `docs/design-spec.md` for the original
  product and design brief this build follows.
