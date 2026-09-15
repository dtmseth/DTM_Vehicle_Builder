# Scheduling revamp — prompt for a separate session

Work in `/Users/skreev/Desktop/DTM_BuildSheet_POC_v7` on the existing unreleased Calendar. Read AGENTS.md, docs/CURRENT_STATE.md, docs/GOTCHAS.md and docs/CALENDAR.md first. The owner now wants a simpler, scheduler-controlled system. Treat the requirements below as replacing the automatic-replanning product direction where they conflict.

## Desired behavior

The current automatic schedule looks good when every estimate is exact, but real changes make it unstable and give technicians whiplash. Keep useful capacity calculations while making saved bookings stable and changes deliberate.

- Anyone with existing scheduling permission must clearly see projects in acceptance order, including their actual acceptance dates and individual vehicles. Preserve manual acceptance dates and existing QBO AcceptedDate semantics. Missing dates require review; never invent them.
- Show the next available opening to quote a prospective customer. Explain the job duration/team assumptions and distinguish a calculated opening from a reserved customer commitment. A read/refresh must never move another booking.
- Lock in the customer's agreed spot when their quote is accepted. Design the connection between a proposed opening, acceptance, and a durable reservation, including acceptance that arrives without a previously selected spot or after that opening has been taken. Never silently invent a promised date, double-book, or displace someone else. Bring genuinely unresolved business choices to the owner early while progressing independent work.
- Schedulers choose which team handles a project. Changing a team should preserve promised dates when feasible; show conflicts and specific impacts before saving when it is not feasible. Support existing multi-vehicle projects, split teams, and joint-team work without silently reshuffling the queue.
- Duration overruns, early completion, parts delays, vehicle readiness, absences, and team changes should show useful warnings and proposed choices. They must not automatically shuffle the shop schedule. Schedulers approve any consequential move, see affected vehicles and before/after dates, and record an explanation. Retain a readable change history.
- Keep customer commitments separate from working forecasts. Never move the existing 60-day delivery deadline or manual delivery override merely to hide lateness. Flag at-risk promises and allow an intentional, explained rescheduling workflow.
- Explore a sidebar showing accepted, unscheduled projects in acceptance order. Users should be able to drag a project or individual vehicle into a team/date slot. A drop stages the choice, shows duration/capacity/conflicts, and uses explicit save/review for consequential changes. Include a click/keyboard alternative. Keep project-level convenience backed by exact vehicle identities and per-vehicle scheduling events.
- Keep the first version simple: stable reservations, a useful acceptance queue, next-opening calculations, manual team/date choices, clear conflicts and reviewed changes. Defer optimization and broader automation.

Inspect existing behavior, propose a concrete interaction and booking model, and work with the owner to settle meaningful scheduling choices before implementing them. Use existing domain/service/revision and authorization boundaries. Preserve Shop Start/Finish, manual labor estimates, fixed starts, protected manual acceptance dates, durable background-save progress, stale-write rejection, and partial-publication recovery. Shop and Sales roles retain their existing permissions unless explicitly changed by the owner. No production schedule publication is requested by this prompt.

## Coordination with the photo-folder session

Another session is implementing Company per-vehicle photo folder provisioning, reference discovery/group assignment, photo UI folder actions, and an additive SharePoint backfill. Azure work is also present in this dirty checkout. Preserve all pre-existing tracked and untracked changes.

Prefer a separate worktree/snapshot that includes the CURRENT working tree, because much of Calendar is untracked/uncommitted; a worktree from HEAD alone will omit it. Do not commit or discard unrelated work to establish isolation. If working directly in this checkout, confine changes to Calendar/Operations-specific files and coordinate before touching shared files.

Calendar-owned files include `domain/calendar_planning.py`, `app/adapters/calendar_store.py`, `app/services/calendar_service.py`, `app/services/calendar_save_jobs.py`, `app/routes/calendar.py`, `ui/js/calendar.js`, `tests/test_calendar.py`, and `docs/CALENDAR.md`. Operations changes may be needed. Do not edit photo/folder services, project photo models/codecs, photo routes, project photo/gallery JavaScript, or photo tests. Avoid shared `ui/index.html`, `ui/styles.css`, `tools/ui_smoke/flows.py`, `tools/verify.py`, wiring, server registration, and central roadmap/handoff documents without coordination. Prefer a dedicated scheduling document for interim notes.

Use cloud-off isolated fixtures and a different preview port/workspace from any running session. Do not start production sync or change live schedule dates. Run `tools/verify.py changed` after meaningful implementation batches, reporting compact summaries. Do not run the full release gate until an actual release/merge checkpoint. Do not commit, merge, publish a release, or deploy Azure as part of this parallel development session.
