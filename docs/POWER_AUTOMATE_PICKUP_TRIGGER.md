# Power Automate setup: SharePoint → GitHub pickup trigger

## Why this exists

GitHub Actions scheduled workflows (`cron`) are deprioritized on low-traffic
public repos. In practice the `*/5 * * * *` cron on
`pickup-pending-changes.yml` fires every 2–5 hours, not every 5 minutes.
Settings changes from teammates therefore take that long to surface as PRs
in `dtm-shared-settings`, then another sync cycle to land in everyone's app.

The fix is to **stop relying on cron** and use a SharePoint event trigger:
the moment a new file appears in `/PendingChanges/`, a Power Automate flow
calls GitHub's `workflow_dispatch` API and the pickup workflow runs within
~10 seconds. Combined with the app's 60s sync poll, end-to-end latency
drops to roughly 1–2 minutes typical, ~3 minutes worst case.

## Prerequisites

- The DTM Fleet Power Automate environment you already use for **Flow A**
  (settings update → email). The "Office 365" and "SharePoint" connectors
  are Standard tier and included with the M365 subscription.
- A GitHub personal access token (PAT) with `actions: write` scope on
  `dtmseth/dtm-shared-settings`. Store it in Power Automate as a connection
  reference or as a secure input variable on the flow — **never paste it
  into an action's `Headers` field as plain text** (it persists in the flow
  definition and is visible to anyone with read access to the flow).

## Generating the PAT

1. https://github.com/settings/personal-access-tokens/new
2. **Token name**: `dtm-shared-settings-dispatch`
3. **Expiration**: 1 year (Power Automate has no built-in rotation; pick a
   date you'll actually remember to refresh).
4. **Resource owner**: your user.
5. **Repository access**: Only select repositories → `dtm-shared-settings`.
6. **Repository permissions**:
   - **Actions**: Read and write
   - Everything else: leave at "No access"
7. Generate. **Copy the token now** — GitHub won't show it again.

## Building the flow

In https://make.powerautomate.com → **+ Create** → **Automated cloud flow**.

### 1. Trigger
- **Connector**: SharePoint
- **Action**: When a file is created (properties only)
- **Site Address**: `https://netorgft11566699.sharepoint.com/sites/DTMOperations`
- **Library Name**: `DTM Vehicle Builder`
- **Folder**: `/PendingChanges`

The "properties only" variant is intentional — we don't need the file
contents, just the existence signal. The pickup workflow reads the file
content itself via Graph API.

### 2. Action: HTTP — POST to GitHub

- **Method**: `POST`
- **URI**: `https://api.github.com/repos/dtmseth/dtm-shared-settings/actions/workflows/pickup-pending-changes.yml/dispatches`
- **Headers** (set as separate key/value pairs, not pasted as text):
  - `Accept`: `application/vnd.github+json`
  - `X-GitHub-Api-Version`: `2022-11-28`
  - `Authorization`: `Bearer @{outputs('Get_secure_input')?['body/value']}`
    (or however your environment references the stored PAT — adapt to your
    secret-management pattern)
- **Body**:
  ```json
  {
    "ref": "main"
  }
  ```

GitHub responds with HTTP 204 on success (no body). The flow doesn't need
to parse anything.

### 3. Concurrency limit (recommended)
- Open the flow settings → **Concurrency control** → On → **Degree of
  parallelism**: `1`.

Without this, a burst of proposals (e.g., a user saves five agency edits in
quick succession) fires five parallel HTTP calls to GitHub. Setting parallelism
to 1 queues them; each pickup workflow run handles whatever is in
`/PendingChanges/` at that moment, so one run usually clears the queue.

## Save and test

1. **Save** the flow.
2. Submit a test change from the app (add a test agency, etc.).
3. In Power Automate, check the flow's **Run history** — there should be a
   new run within seconds.
4. In GitHub, https://github.com/dtmseth/dtm-shared-settings/actions/workflows/pickup-pending-changes.yml
   should show a new run that started ~10 seconds after the flow fired,
   with the trigger source listed as `workflow_dispatch`.
5. The PR opens, auto-merges (general) or waits for review (advanced), the
   publish workflow dispatches, the file lands in `/Settings/`.

## Cron stays as a backstop

Don't delete the existing cron in `pickup-pending-changes.yml`. If Power
Automate is down or the flow is disabled, the cron still picks up changes
eventually. The trigger model becomes "Power Automate normally, cron as
fallback" — best of both.

## Rotating the PAT

PATs expire. When yours nears expiration (GitHub emails a reminder):
1. Generate a new PAT with the same scopes.
2. Update the secure input / connection in Power Automate.
3. Revoke the old PAT.

If you forget, the flow starts failing silently. Add a calendar reminder a
week before expiration.
