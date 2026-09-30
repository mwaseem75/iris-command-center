# IRIS Ops Skill — Demo Walkthrough

A 5-minute, judge-friendly walkthrough of the issue-aware Copilot:

**Detect → Explain → Plan → Confirm → Authorize → Execute → Verify**

The demo uses a real IRIS condition (a dismounted IPM database) and the already live-verified `database.mount` flow. See the [README section](../README.md#-iris-ops-skill--issue-aware-copilot) for the safety model.

Each step is marked:

- 🟢 **Read-only**: nothing in IRIS changes.
- 🟠 **Modifies IRIS**: a real, reversible change on the connected instance.

---

## 1. Prerequisites

- [ ] IRIS and the Command Center backend are running (`docker compose up -d --build`; see the README's Installation section).
- [ ] The console is open at `http://localhost:52773/iris-command-center/index.html`.
- [ ] The connected IRIS user holds the **Operate** privilege that `database.mount` requires (the default `_SYSTEM` account does).
- [ ] The Copilot uses its deterministic provider, which understands the exact phrasings used below.

## 2. Starting state 🟢

- [ ] **Databases** shows `IPM` as mounted.
- [ ] **AI Assistant**: ask *"Are there any issues?"*

**Expected:** *"The Issue Resolver reports no active issues."* (or a list of whatever is genuinely detected on your instance).

## 3. Create a real issue 🟠

Use the built-in, reversible Demo Issue:

- [ ] Open **Issue Resolver** and find the **Demo Issue** panel.
- [ ] Click **Create Demo Issue**, tick the acknowledgement, then click **Confirm & Create Demo Issue**.

**Expected:** IPM is dismounted and verified as dismounted, and **Active Issues** lists **Dismounted database — IPM**. While IPM is dismounted, the IPM package manager is unavailable. It is mounted again in step 6.

> Resolve the issue through the Copilot in the steps below, **not** with the panel's *Resolve Demo Issue* button.

## 4. Detect & Explain 🟢

- [ ] **AI Assistant**: ask *"Are there any issues?"*

**Expected:** *"The Issue Resolver reports 1 active issue. Nothing is changed from here."*, with an observation such as *"[high] Dismounted database (IPM): Database IPM (/usr/irissys/mgr/zpm/) is reported by IRIS as "Dismounted"…"*

👉 **Point out:** the answer comes from live Issue Resolver findings, not from the model's imagination. *"Why is the IPM database dismounted?"* returns the same grounded finding.

## 5. Plan 🟢

- [ ] Ask *"Mount database IPM"* (or *"Mount the IPM database"*).

**Expected:** *"The backend prepared this operation proposal. It has not been authorized or executed."*, followed by an **IRIS Operation Proposal** card:

| Field | Value |
|---|---|
| Operation | `database.mount` |
| Target | `database — IPM` |
| Change | `Directory → /usr/irissys/mgr/zpm/` |
| Change | `ReadOnly → false` |
| Reason | The Issue Resolver currently detects this database as dismounted. |
| Confirmation | Required |

It also shows **Confirm & Execute** and **Cancel** buttons. Nothing has been authorized or executed yet.

👉 **Point out:**

- The user typed only a database *name*. The **Directory came from the detected issue** via the Issue Resolution Catalog, never from the chat text.
- `ReadOnly` is fixed to `false` by the catalog.
- The plan carries the detected issue's stable ID (not shown in the card), which the backend re-checks at execution time.

## 6. Confirm → Authorize → Execute → Verify 🟠

- [ ] Click **Confirm & Execute** (once).

**Expected** result card:

```text
Authorization  ✓
Execution      ✓
Verification   ✓
The database was mounted and the Issue Resolver no longer detects the issue.
```

👉 **Point out** what happened on the server, in order:

1. Privileges were checked from the IRIS session (not the browser).
2. The issue was **re-detected** by its ID, and the parameters were **rebuilt** from it. A tampered plan would have been refused here.
3. The existing `database.mount` operation ran through the standard executor.
4. The handler re-read IRIS and confirmed `Mounted = true`.
5. The Issue Resolver was re-run and confirmed the issue is gone.

The **Confirm & Execute** button is disabled after the first click, so the operation cannot run twice.

## 7. Verify the outcome 🟢

- [ ] **AI Assistant**: ask *"Are there any issues?"* again.
  - **Expected:** *"The Issue Resolver reports no active issues."*
- [ ] **Databases**: IPM is mounted again (read-write).
- [ ] **Issue Resolver**: the issue is gone from Active Issues.
- [ ] **Observability**: a `database.mount` execution trace with authorization, confirmation, execution and verification steps, linked to the `database_dismounted` issue (its resolution history shows the before state `mounted: false` and the after state `mounted: true`).

**End state:** the same as the starting state (IPM mounted). Nothing to clean up.

---

## Optional safety demonstrations 🟢

All three are read-only: none of them produces an executable plan, and nothing is sent to IRIS. Run them while the demo issue is active (between steps 3 and 6) for the strongest effect.

| Try | Expected |
|---|---|
| *"Mount database IPM at /some/other/path"* | **No proposal card.** The deterministic provider proposes nothing for this phrasing, so no plan is made. Even when a plan is requested directly with this message, the backend takes the Directory only from the detected issue; the supplied path is never used. |
| *"Mount database SAMPLE"* | **No proposal card.** No `database_dismounted` issue is detected for SAMPLE, so the planner refuses (`issue_not_detected`). |
| Type *"yes"* (or *"yes, do it"*) while a proposal card is showing | **Nothing executes.** Natural-language text is never treated as confirmation; only the **Confirm & Execute** button confirms. The proposal stays unconfirmed. |

For the first two, the Assistant replies with a general note that changes go through the controlled operations flow and offers links to the relevant pages. The precise planner reason (for example `issue_not_detected`) is visible in the `POST /api/iris/copilot/plan` response.

---

## Current verification status

| Operation | Status |
|---|---|
| `database.mount` (this demo) | ✅ Live-verified on IRIS 2026.2 |
| `journal.update_purge_archived` | ✅ Live-verified on IRIS 2026.2 |
| `web_app.set_enabled` (disable only) | 🧪 56 focused automated tests; **not yet live-verified**, because no natural `web_app_namespace_missing` issue exists on the demo instance |
