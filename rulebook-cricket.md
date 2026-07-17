# Cricket Rules Reference — with T20 Focus

This document is a precision reference for a cricket analytics/simulation engine. Every rule below is sourced from a primary rules document — the **MCC Laws of Cricket** (the sport's foundational rulebook, maintained by Marylebone Cricket Club, Lord's) and the **ICC Men's T20 World Cup 2026 Playing Conditions** (the competition-specific regulations that sit on top of, and in places override or add detail to, the Laws for international T20 matches) — fetched and read directly during research. Wikipedia/ESPNcricinfo/secondary sources are used only to confirm statistical conventions that aren't formally codified in law (e.g. strike rate).

**Important framing for implementers:** the *Laws of Cricket* are the universal rulebook that applies to all cricket everywhere (Tests, club cricket, backyard cricket). *Playing Conditions* are issued per competition (ICC white-ball cricket, IPL, etc.) and layer competition-specific numbers (over limits, powerplay overs, DRS reviews) on top of the Laws — the Laws themselves mostly say "as agreed for the match" for things like innings length. Where a number below (e.g. "4 overs per bowler") is a Playing Condition rather than a universal Law, this is called out explicitly, because a different league could set a different number.

---

## 1. Match Structure

- **Teams and innings:** A T20 match is played between two sides of **11 players each** (one innings per side). This is fixed by Playing Condition, clause 1.1: "A match is played between two sides, each of eleven players, one of whom shall be captain." The Laws (Law 13) generically say each side gets one or more innings "as prearranged"; T20 fixes it at exactly one innings per side.
- **Overs per innings:** Each innings is limited to a maximum of **20 overs** (ICC PC cl. 13.6.1, 13.7.1.1). If a team is bowled out (all out) or otherwise completes its innings early (loses all wickets, or an interruption reduces the overs), the innings ends sooner.
- **The over — 6 legal deliveries:** An over consists of **6 valid ("legal") balls**, bowled from one end (Law 17.1 / ICC PC cl. 17.1). A delivery does **not** count toward the 6 if it is: a No ball, a Wide, called Dead ball before the striker had a chance to play it, or voided under a small number of other specific-offence clauses (PC cl. 17.3.2). Consecutive overs are bowled from opposite ends of the pitch.
- **End of an over:** When 6 valid balls have been bowled and the ball is dead, the umpire calls "Over" (PC cl. 17.4). At that point:
  - The bowling side **changes ends** — the next over is bowled from the opposite end.
  - The striker and non-striker **swap** (the batter who was at the non-striker's end now faces, unless a wicket fell/odd number of runs was run on the last ball, etc. — standard end-of-over strike rotation).
  - A **different bowler must bowl the next over** — see bowling restrictions below. The fielding captain chooses who bowls each over (subject to the consecutive-over restriction), so a genuinely "new" bowler is not strictly required each over, only a bowler who did not bowl the immediately preceding over.

---

## 2. Bowling Restrictions

This is the area most critical to verify precisely, and it splits cleanly into a **universal Law** (never varies) and a **competition-specific number** (varies by format/competition).

### 2.1 No two consecutive overs by the same bowler (universal Law)

**Law 17.6** (mirrored verbatim in ICC PC cl. 17.6): *"A bowler shall be allowed to change ends as often as desired, provided he does not bowl two overs consecutively, nor bowl parts of each of two consecutive overs, in the same innings."*

- This is a Law of Cricket, not a T20-specific Playing Condition — it is identical in Tests, ODIs, and T20s.
- It also covers the edge case of a bowler being incapacitated or suspended mid-over: the replacement bowler completing that over is still barred from bowling the next over, and a bowler who bowled the *earlier* part of a two-part over is treated as having bowled that over for consecutive-over purposes (PC cl. 17.8).
- For a simulator: track "last over's bowler ID" and disallow selecting that same bowler for the next over, in addition to their overs-remaining count.

### 2.2 Maximum overs per bowler in a full 20-over innings

**ICC PC clause 13.9.1**: *"No bowler shall bowl more than 4 overs in an innings."*

- 4 overs = 20⁄5 = exactly **one-fifth of a full 20-over innings**, confirming the general "1/5 of the innings" ratio the user asked about. The same 1/5 ratio applies at other limited-overs lengths (e.g. 10 overs per bowler in a 50-over ODI innings).
- **This is a Playing Condition, not a Law** — the Laws of Cricket impose no bowler-overs cap at all (relevant in Tests/first-class cricket, where a single bowler can bowl unlimited overs). The cap is purely a limited-overs regulatory addition.

### 2.3 Reduced/rain-shortened innings — the 1/5 ratio does *not* apply uniformly

This is a genuine nuance worth flagging explicitly, since it is **not** a clean 1/5 scaling in all cases. Per **ICC PC clause 13.9.2**:

| Rescheduled innings length | Max overs per bowler | Rule |
|---|---|---|
| ≥ 10 overs | `ceil-ish(overs ÷ 5)` | "no bowler may bowl more than one-fifth of the total overs allowed. Where the total overs is not divisible by 5, **one additional over** shall be allowed to the maximum number per bowler necessary to make up the balance" (cl. 13.9.2.1) |
| 5–9 overs | **flat 2 overs** | "no bowler may bowl more than two overs" (cl. 13.9.2.2) — a flat cap, *not* a 1/5 calculation |

Worked examples from the Law text's own logic:
- 17-over innings → 17/5 = 3.4 → rounded up to distribute the "balance" → some bowlers may bowl 4 overs, most 3 (total must sum to 17).
- 12-over innings → 12/5 = 2.4 → similar distribution logic, max per bowler is 3.
- 9-over innings → falls under the **flat 2-overs rule** (not 9/5=1.8→2, which coincidentally matches, but 7-over or 6-over innings also get flat 2, e.g. 6/5=1.2 would round to 2 either way, but the flat rule is what's actually specified, not a calculation).
- **Implementation implication:** do not hard-code `ceil(overs/5)` as a universal formula — for innings of 5–9 overs the Law specifies a flat 2-over cap regardless of the exact 1/5 arithmetic, and for ≥10-over innings the "make up the balance" language means the *maximum-per-bowler* figure is a team-wide constraint (not every bowler individually gets the ceiling — the overs are distributed so the total adds up), which needs bespoke over-allocation logic rather than a single per-bowler formula.
- **Also relevant:** if a bowler breaks down mid-over and cannot finish it, the partial over still counts as a **full over** against that bowler's personal limit (PC cl. 13.9.3), even though only part of it was bowled.

### 2.4 Domestic-league note

The IPL and most major T20 leagues follow the same "max 4 overs per bowler / no consecutive overs" structure as the ICC playing conditions above (this is close to a de facto global T20 standard). No conflicting domestic convention was found during this research; if your simulator targets a specific league (e.g. The Hundred, which uses non-standard "balls" instead of 6-ball overs), verify that league's own playing conditions separately — this document does not cover that format.

---

## 3. Powerplay Rules in T20

- **Powerplay overs:** The first **6 overs** of each innings (PC cl. 28.7.2), applying to a full 20-over innings.
- **Fielding restriction during Powerplay:** Only **2 fielders** may be positioned outside the 30-yard circle at the instant of delivery (PC cl. 28.7.4).
- **Fielding restriction outside Powerplay (overs 7–20):** Up to **5 fielders** may be outside the circle (PC cl. 28.7.5).
- **The 30-yard circle** is formally defined as two semicircles of radius 30 yards (27.43 m) centred on the middle stump at each end, joined by two straight lines parallel to the pitch (PC cl. 28.7.3) — marked by a continuous line or dots at 5-yard intervals.
- **Additional standing fielding limits (apply throughout the innings, not just Powerplay):**
  - No more than **5 fielders on the leg side** at the instant of delivery (PC cl. 28.4.1).
  - No more than **2 fielders behind the popping crease on the leg side** (other than the wicket-keeper) at the instant of delivery (PC cl. 28.4.2). Breach of either → No ball.
- **Reduced-overs matches:** the Powerplay length scales down with a lookup table, and — as of a July 2025 ICC rule refinement — is rounded to the **nearest ball, not the nearest over** (PC cl. 28.7.6). Examples from the official table: a 5-over innings gets 1.3 overs of Powerplay; an 8-over innings gets 2.2 overs; a 19-over innings gets 5.4 overs. (Before this refinement, rounding was to the nearest whole over, which could be less proportionally fair in heavily-reduced matches — worth noting as a "rule that recently changed" if replaying historical matches.)
- Breach of a fielding-restriction clause is called and signalled as a **No ball** by the relevant umpire (PC cl. 28.7.8).

---

## 4. Extras and Illegal Deliveries

### 4.1 Wide ball

- **Definition (Law 22 / PC cl. 22.1):** A delivery (not a No ball) is a Wide if it passes wide enough of the striker — accounting for where the striker is standing, up to a normal batting-position reach with a normal cricket stroke — that they could not hit it with a normal shot. **T20-specific addition:** a ball passing **above the striker's head height** while they stand upright at the popping crease is also called Wide (PC cl. 22.1.1.2) — see the "ambiguity" note below.
- **Runs conceded:** 1 run penalty, awarded instantly on the call (PC cl. 22.6), plus any additional runs completed/boundary scored while the ball is loose.
- **Does it count as one of the 6 legal balls?** **No.** A Wide is explicitly excluded from the over count (PC cl. 22.8 / 17.3.2.4) — the delivery is **replayed** (an extra ball is bowled in its place).
- **Bowler debit:** all runs from a Wide (the 1-run penalty plus any run-outs/overthrows off it) are debited against the bowler's figures (PC cl. 22.7, 18.10.3), except for separately-awarded 5-run team penalties.
- **Dismissals possible off a Wide:** only **Hit wicket, Obstructing the field, Run out, or Stumped** (PC cl. 22.9). A batter cannot be Bowled, Caught, or LBW off a Wide.

**Ambiguity flagged:** In the *current* (2017 Code, 3rd edition 2022) MCC Law 22, a delivery that bounces over head height is treated as a dangerous/unfair short-pitched ball under Law 41 and called a **No ball**, not a Wide. However, current ICC white-ball Playing Conditions (as confirmed directly from the fetched 2026 T20 World Cup document, cl. 22.1.1.2 and cl. 41.6.1.7) already call such a delivery a **Wide**. MCC has since announced that the **next edition of the Laws (effective 1 October 2026)** will change the base Law itself to align with this ICC practice and call head-height bouncers a Wide rather than a No ball. So: as of today (per Laws currently in force until 30 Sept 2026), the *base* Law and the *ICC T20I Playing Condition* diverge on this point; from 1 Oct 2026 they will align. **If simulating pre-October-2026 non-international cricket under bare Laws, use No ball for this case; for ICC T20I play at any date, use Wide.**

### 4.2 No ball

- **Common causes** (PC cl. 21): front foot landing entirely in front of the popping crease (no part behind it), back foot not landing within/touching the return crease, an illegal ("thrown") bowling action, underarm bowling, the bowler failing to notify the umpire of a change of bowling arm/side, a full-pitched delivery reaching the batter above waist height ("beamer" — automatically a No ball, and further judged for danger separately), more than one bounce or the ball rolling before reaching the batter, a fielder illegally encroaching on the pitch, wicket-keeper standing in front of the stumps too early, and fielding-restriction breaches (Powerplay/leg-side limits above).
- **Runs conceded:** 1 run penalty, awarded instantly (PC cl. 21.15), regardless of whether a batter is subsequently out.
- **Free Hit rule:** The delivery immediately following any No ball is a **Free Hit** for whichever batter faces it (PC cl. 21.19). On a Free Hit, the striker can only be dismissed under the same restricted modes that apply to a No ball itself (essentially Run out, Obstructing the field, or Hit the ball twice) — even if the Free Hit delivery itself is called Wide. **The Free Hit rule is a limited-overs Playing Condition, not a Law of Cricket** — it does not exist in Test cricket.
- **Does it count as one of the 6 legal balls?** **No.** A No ball is excluded from the over count (PC cl. 21.17) — the delivery is **replayed**.
- **Dismissals possible off a No ball:** only **Hit the ball twice, Obstructing the field, or Run out** (PC cl. 21.18). Note this differs slightly from the Wide-ball dismissal list (Stumped and Hit wicket are *not* possible off a No ball, but *are* possible off a Wide).
- **Bowler debit:** the 1-run penalty plus all runs off the bat/byes on that ball are debited to the bowler (PC cl. 21.16, 18.10.3) — except if runs come as byes/leg-byes off a No ball, only the 1-run penalty is scored as "No ball extra"; the remainder is scored as Byes/Leg byes (still not credited to the batter, but also not debited as "bowler's runs" beyond the 1-run penalty — see distinction in section 6 below).

### 4.3 Byes and leg-byes

- **Byes (Law 23.1 / PC cl. 23.1):** runs scored when the ball (not a Wide) passes the striker without touching bat or person, and the batters run (or it reaches the boundary).
- **Leg-byes (Law 23.2 / PC cl. 23.2):** runs scored when the ball first strikes the striker's body — but **only** if the umpire is satisfied the batter either attempted a genuine cricket stroke or was genuinely trying to avoid being hit. If neither condition is met, no leg-byes are awarded at all (dead ball is called, PC cl. 23.3) — this is a stricter test than many simulators assume; a ball that hits an unmoving/deliberately-blocking batter's pad with no shot attempted and no evasion attempt scores **nothing**, not leg-byes.
- **Do byes/leg-byes count toward the team total?** Yes — added to the team's extras/total.
- **Are they credited to the batter's personal score?** **No** — explicitly excluded from the striker's runs (PC cl. 18.10.2).
- **Do they count as one of the 6 legal balls of the over?** **Yes.** Unlike Wides and No balls, a bye/leg-bye delivery is a normal, valid delivery (it is simply *not* a Wide or No ball), so it counts toward the 6-ball over (confirmed by omission from the "does not count" list in PC cl. 17.3.2).
- **Bowler's figures:** byes and leg-byes are **not** debited against the bowler's runs-conceded (PC cl. 18.10.3 explicitly lists only "runs scored by the striker," "No ball extras," and "Wide extras" as debited to the bowler — byes/leg-byes are conspicuously absent). This is the key rule for a simulator's economy-rate calculation: **team total = runs off bat + byes + leg-byes + no-ball extras + wide extras + penalty extras; bowler's runs conceded = runs off bat (while they were bowling) + no-ball extras + wide extras only.**

### 4.4 Penalty runs

- A 5-run team penalty is awarded for a range of unfair-play/technical offences under Law 41/PC cl. 41 and elsewhere: repeated ball-tampering, illegal fielding, deliberate distraction/obstruction of a batter, fielders encroaching on the protected area, time-wasting, deliberate short running, a struck ball hitting a fielding-side helmet left on the ground, and several others.
- These are scored as **"Penalty extras"**, added to the team's total in addition to any other runs from that delivery, and are **not** debited to the bowler (PC cl. 41.17.3–41.17.4).

---

## 5. Dismissal Types

The Laws of Cricket (2017 Code, Laws 32–40) formally define **9 dismissal Laws**. In addition, a batter can end their innings by **retiring out** (Law 25.4 / PC cl. 25.4), which is not an "appeal" dismissal under Laws 32–40 but is scored as an out. Common cricket writing (scorecards, ESPNcricinfo-style commentary) therefore still popularly describes "**10 ways to get out**," folding Retired Out in as the tenth. This is a genuine terminology ambiguity worth flagging: **the Laws themselves formally enumerate 9 numbered dismissal clauses (Laws 32–40); "10 ways to get out" is a colloquial count that adds Retired Out.**

Historical note confirmed during research: prior to the 2017 Code, "Handled the ball" was a separate, tenth dismissal Law. In 2017, MCC folded it into **Obstructing the field** (Law 37) as a specific sub-case, reducing the Law-numbered dismissals from 10 to 9. A batter who deliberately touches the ball with a hand not holding the bat is still out — but the mode is recorded as **Obstructing the field**, not "Handled the ball."

| # | Dismissal | Law / PC clause | Credited to bowler? |
|---|---|---|---|
| 1 | **Bowled** | Law/PC cl. 32 | Yes |
| 2 | **Caught** | Law/PC cl. 33 | Yes |
| 3 | **LBW** (leg before wicket) | Law/PC cl. 36 | Yes |
| 4 | **Stumped** | Law/PC cl. 39 | Yes |
| 5 | **Hit wicket** | Law/PC cl. 35 | Yes |
| 6 | **Run out** | Law/PC cl. 38 | **No** (PC cl. 38.6) |
| 7 | **Obstructing the field** (incl. former "Handled the ball") | Law/PC cl. 37 | **No** (PC cl. 37.6) |
| 8 | **Hit the ball twice** | Law/PC cl. 34 | **No** (PC cl. 34.5) |
| 9 | **Timed out** | Law/PC cl. 40 | **No** (PC cl. 40.2) |
| 10* | **Retired out** | Law/PC cl. 25.4 | **No** (not a bowler-credited dismissal at all) |

*Not a formally Law-numbered dismissal — see note above.

Key implementation notes:
- **Timed out:** an incoming batter must be ready to face (or the other batter ready to face the next ball) within **1 minute 30 seconds** of the previous dismissal/retirement (PC cl. 40.1.1) — this specific time limit is a Playing Condition figure (traditionally 3 minutes in the base Laws/older conventions; ICC's white-ball limit is shorter — verify against whichever ruleset you're modelling if precision matters here).
- **Hit the ball twice:** rare; only applies if the batter *wilfully* strikes the ball a second time other than to guard their wicket or return it to a fielder.
- **Run out and Stumped both possible from certain deliveries; mutual exclusivity:** a batter cannot be given out Stumped if the wicket is broken with the intervention of a fielder other than the wicket-keeper (that becomes Run out instead) — see PC cl. 38.2.2.1 / 39 cross-references.
- **Which batter is out on a Run out** is determined by whose "ground" (crease) is at the end where the wicket is broken, not by who was originally at that end (PC cl. 38.4, 30.2) — relevant for simulators tracking mid-run crossing.

---

## 6. Scoring Conventions

- **Batting strike rate:** `(runs scored ÷ balls faced) × 100`. **Balls faced excludes Wides** (a Wide is not a legal delivery faced by the batter) but **includes No balls** that the batter faced and played at. This is a scorekeeping/statistical convention (confirmed via ESPNcricinfo-derived secondary sources), not something defined in the Laws themselves — the Laws only define what counts as a legal ball for the *over*, not for individual batter statistics, though in practice the two align (a ball that counts toward the over also counts as a "ball faced").
- **Bowling economy rate:** `runs conceded ÷ overs bowled`. Caution for implementers: cricket overs are recorded in **ball-in-over notation** (e.g., "10.2 overs" = 10 completed overs + 2 balls, i.e. 10⅓ overs, not 10.2 decimal overs) — convert to `overs + balls/6` before dividing, or compute on total balls bowled and multiply by 6.
- **Byes/leg-byes and the bowler's figures:** as established in section 4.3, byes and leg-byes inflate the **team total** but are excluded from the **bowler's runs-conceded** figure (PC cl. 18.10.3) — this is the single most important distinction for an accurate economy-rate implementation. Wides and No-ball penalty runs, by contrast, **do** count against the bowler.
- **Runs off the bat vs. extras:** the team total is the sum of (a) runs credited to the striker (all bat-struck runs except the No-ball 1-run penalty itself), (b) byes, (c) leg-byes, (d) no-ball extras (the 1-run penalty plus any subsequent byes/leg-byes off that no ball, which are separately categorized), (e) wide extras, and (f) penalty extras (PC cl. 18.10.1–18.10.3, 41.17.3).

---

## 7. Result Mechanics Specific to T20

### 7.1 Tie-break via Super Over

Per **ICC PC Appendix F**:
- If both innings finish with equal scores, the match is a **Tie**, and a **Super Over** is played to determine a winner (PC cl. 16.3.1.2).
- Each team faces **one over** (max 6 balls); an innings ends early if **2 wickets** fall (Appendix F, para. 2) — note this differs from the 10-wickets-standard of a full innings.
- The team scoring more runs in its Super Over wins; if the Super Over is also tied, **subsequent Super Overs are played until there is a winner** — in principle unlimited, subject to genuine time constraints (e.g. ground curfews), in which case the match reverts to a Tie (Appendix F, paras. 3, 25–26).
- The team that batted **second** in the original match bats **first** in the Super Over (Appendix F, para. 11). In a repeated (tied) Super Over, the team that batted second in the *previous* Super Over bats first in the next one (para. 19).
- Batters dismissed in a previous Super Over, and bowlers who bowled in it, are ineligible to bat/bowl again in a subsequent Super Over (paras. 22–23).
- Each team is limited to only nominated match players (including any Concussion Replacement) for the Super Over — no fresh player nominations (Appendix F, para. 8).

### 7.2 Duckworth-Lewis-Stern (DLS) method — conceptual summary

DLS is used to set a fair revised target (or determine a result) when a match is shortened by weather/interruption. Conceptual basis (confirmed via Wikipedia, cross-checked against the ICC's own reference to "DLS" in PC cl. 16.4 and Appendix A definition 1.8):

- Each batting side is considered to hold two combined **"resources"**: overs remaining and wickets remaining. A full, uninterrupted innings starts at 100% of its resources.
- If Team 1's innings is completed and Team 2's is then shortened by a delay, **Team 2's revised target** is calculated (conceptually) as: `Team 2's target ≈ Team 1's score × (Team 2's resource % ÷ Team 1's resource %)`, rounded appropriately (the target is always set as a whole number, with the target being one more run than the Par Score, per PC cl. 16.4.1.1).
- If a match is abandoned mid-chase, the result is determined by comparing the actual score to the DLS **"Par Score"** at the moment of abandonment — above it is a win, below it is a loss, equal is a Tie (PC cl. 16.4.2.1).
- **This document does not reproduce the full DLS resource-percentage table or formula** — that is a proprietary, licensed calculation (owned/administered by the ICC and its statisticians), not something publishable from the Laws/Playing Conditions text. Implementers needing the actual resource table should obtain it through an official/licensed source; do not assume a simplified formula is accurate for production use.

### 7.3 Minimum overs required for a result

- **Standard ICC T20I minimum:** each side must have had the opportunity to bat for at least **5 overs** for any result (other than a walkover) to stand; otherwise the match is a **No Result** (PC cl. 16.1.2, 16.1.3, 13.7.2.1.2).
- **Tournament-specific variant flagged:** in the ICC Men's T20 World Cup 2026 Playing Conditions specifically, the **semi-finals and final** raise this minimum to **10 overs** for the side batting second (PC cl. 16.1.2). This is an explicit example of a knockout-stage variant on top of the general 5-over minimum — don't assume 5 overs is universal for all match types within the same competition.
- Where overs are reduced due to an interruption, a revised target is set via DLS as above (minimum 5 overs bowled to the second side, again 10 for these tournament's semi-finals/final).

---

## 8. Batting Order / Team Composition Basics

- **11 players per side**, one of whom is captain (PC cl. 1.1). This is fixed for all recognized formats.
- **Openers:** the two batters who start the innings are conventionally called "openers"; the batter facing the very first ball is "number 1," the non-striker "number 2" — this is a naming/scorecard convention, not a Law requirement (the Laws do not mandate who bats when; the batting captain/team decides the order and can even change the order between overs, subject to only the two already-in batters at any time and once dismissed a batter cannot bat again in that innings, per PC cl. 25).
- **Middle order:** no rule fixes numbers 3–6 etc.; by strong convention, a team's most reliable/aggressive batters occupy these slots. This is pure cricketing custom, not codified.
- **Wicketkeeper:** the only fielder permitted to wear gloves and external leg guards (PC cl. 27.1); must stand **wholly behind the wicket** at the striker's end until the ball touches the bat/passes the wicket, or the striker attempts a run — infringement is called as a **No ball** (PC cl. 27.3). By convention (not Law) the wicketkeeper often bats around number 6–7, though many modern T20 sides bat a keeper anywhere from opener to finisher depending on their skillset.
- **All-rounder:** not a Law-defined role — a cricketing convention/term for a player whose **batting or bowling ability alone** would be strong enough to merit a place in the side, i.e., who contributes meaningfully in both disciplines. There is no official statistical threshold; usage is subjective (confirmed via Wikipedia's "All-rounder" article).
- **Concussion Replacements** (PC cl. 1.2.7): a modern addition allowing a like-for-like substitute to fully replace (bat/bowl/field) a player diagnosed with a concussion during the match, subject to match-referee approval. The replaced player takes no further part; both players are credited with having played the match for record purposes.
- **Domestic-league variant — IPL "Impact Player" (flagged explicitly as non-ICC):** since 2023, the Indian Premier League allows each team to make **one tactical substitution** from a pool of nominated substitutes at any point in the match; the substituted-in player ("Impact Player") can bat and/or bowl their full quota exactly as an original XI member, and the replaced player takes no further part. This is **not** part of the ICC's T20 International Playing Conditions and would not apply to international matches — it is specific to the IPL's own domestic playing conditions. Do not apply this rule when simulating official T20Is.

---

## Sources

MCC Laws of Cricket (primary):
- [The Over – The Laws Of Cricket | Lord's](https://www.lords.org/mcc/the-laws/the-over)
- [No Ball – The Laws Of Cricket | Lord's](https://www.lords.org/mcc/the-laws/no-ball)
- [Wide Ball – The Laws Of Cricket | Lord's](https://www.lords.org/mcc/the-laws/wide-ball)
- [Bye And Leg Bye – The Laws Of Cricket | Lord's](https://www.lords.org/mcc/the-laws/bye-and-leg-bye)
- [The Laws of Cricket | MCC](https://www.lords.org/mcc/the-laws) (full Law list/numbering, Laws 1–42)
- [Changes to the Laws of Cricket for 2026 edition (PDF) | Lord's](https://www.lords.org/getmedia/0855ddfe-e219-4363-8652-2d7de233c4b9/Changes-to-Laws-for-2026-edition_1.pdf) (summary of all 73 changes effective 1 October 2026, including the Wide/No-ball head-height change and the "Handled the ball" merger history)

ICC Playing Conditions (primary):
- [ICC Men's T20 World Cup 2026 | Playing Conditions (PDF)](https://images.icc-cricket.com/image/upload/prd/yyt7m8uh9c1uehrbvuwb.pdf) — full text fetched and read; all numbered clause citations above (Laws/clauses 1–42 and Appendices A–J, including Appendix F Super Over Procedure and Appendix E Calculations) are drawn directly from this document.

Secondary/confirmatory sources:
- [Laws of Cricket - Wikipedia](https://en.wikipedia.org/wiki/Laws_of_Cricket)
- [Handled the ball - Wikipedia](https://en.wikipedia.org/wiki/Handled_the_ball)
- [Obstructing the field - Wikipedia](https://en.wikipedia.org/wiki/Obstructing_the_field)
- [Duckworth–Lewis–Stern method - Wikipedia](https://en.wikipedia.org/wiki/Duckworth%E2%80%93Lewis%E2%80%93Stern_method)
- [How the Duckworth-Lewis-Stern method works | ESPNcricinfo](https://www.espncricinfo.com/story/how-the-duckworth-lewis-stern-method-works-1102000)
- [Nearest ball, not nearest over - ICC tweaks powerplay rules for shortened men's T20Is | ESPNcricinfo](https://www.espncricinfo.com/story/icc-tweaks-powerplay-rules-for-shortened-t20is-in-men-s-cricket-1492013)
- [All-rounder - Wikipedia](https://en.wikipedia.org/wiki/All-rounder)
- [IPL 2023 Impact Player - all you need to know about the new rule | ESPNcricinfo](https://www.espncricinfo.com/story/ipl-2023-impact-player-all-you-need-to-know-about-the-new-rule-1350616)
- Cricket strike-rate/economy-rate calculation convention pages (calcgami.com, captaincalculator.com, Wikipedia "Economy rate") used only to confirm the standard arithmetic conventions in Section 6, which are statistical/scorekeeping conventions rather than Laws.

**Note on currency:** As of this document's research date (July 2026), the governing MCC Laws in force are the **2017 Code, 3rd Edition (2022)**. A new 4th edition takes effect **1 October 2026**; where a forthcoming change is directly relevant to simulator logic (the Wide/No-ball head-height bouncer rule), this is flagged explicitly above. All ICC Playing Conditions clause numbers cited are from the **ICC Men's T20 World Cup 2026 Playing Conditions** document, which itself already incorporates the July 2025 Powerplay-rounding refinement.
