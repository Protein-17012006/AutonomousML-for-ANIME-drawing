# infra/ handoff for Stage 3 (from R0/Hoàng, 2026-07-09)

This is the COMPLETE IaC for the live front door (https://inbetween-copilot.click), copied
from the team repo so the Stage-3 work (gating `/copilot` + per-user chat history) can be
done here. Answer to your blocking question: **yes** — the site is gated at the ALB with
`authenticate-cognito` on **every** route (see `20-frontdoor.yaml`), and removing it is
agreed **under the conditions below**.

## The one secret

`infra/params.env` is GIT-IGNORED (rule added to this repo's `.gitignore`) and is NOT in
git — Hoàng sends it over a private channel. Put it at `infra/params.env` and never commit
or screenshot it: it contains the **Tailscale auth key** that can join our tailnet and reach
the box. `params.env.example` shows the shape; `README.md` has the lookup commands.

## Map to your request

| Your request | Where |
|---|---|
| §2a User Pool: self-signup, email code verify/reset, hosted domain, SPA app client | `10-auth.yaml` |
| §1 remove the ALB `authenticate-cognito` whole-site gate | `20-frontdoor.yaml` (the listener default action) |
| §2b–e Identity Pool + `copilot_chats` DDB + userdata bucket + CORS + per-user IAM | **NEW template** — suggested `45-userdata.yaml` (leave `30-data.yaml` / `40-cdn.yaml` untouched) |
| §2a Google IdP | **phase-2** — needs a Google OAuth client + consent screen; don't block Stage 3 on it |
| §3 the seven `NEXT_PUBLIC_*` values | declare them as CloudFormation **Outputs** in your new template so `deploy.sh outputs` prints them |

## Hard conditions (agreed with Hoàng — please keep)

1. **Change via CloudFormation only** (edit template → stack update). No console/CLI one-off
   edits: the stacks are the source of truth, console changes drift and get silently reverted
   on the next stack update.
2. **Sequencing:** removing the ALB gate is safe TODAY (the box is offline training, `/session*`
   returns "brain offline"). It must NOT still be open *without auth* once the box comes back
   (~2026-07-15) — Hoàng ships a FastAPI JWT-verification middleware for `/session*` before
   then (your app will attach `Authorization: Bearer <access token>`; the fetch-based SSE
   supports headers). **Coordinate the timing with Hoàng.**
3. Identity Pool: **unauthenticated identities disabled**; the new bucket keeps
   **Block Public Access ON** (CORS ≠ public).
4. Forbidden zone unchanged: `copilot_sessions` table, `*-artifacts` bucket, the existing
   `30-data`/`40-cdn`/`50-budget` stacks, the EC2/tailscale plumbing, anything on the box.
5. Update `frontend/docs/plans/layout-refinement-stage-3-plan.md` to this AWS-native design
   in your wiring PR — it still describes the Clerk+Firebase version.

## Working notes

- `README.md` in this folder: bring-up, params lookups, frontend deploy, teardown.
- Windows/git-bash gotcha: `deploy.sh` sets `MSYS_NO_PATHCONV=1`, so pass **Windows-style**
  paths (`C:/Users/...`) to `deploy.sh frontend`.
- Existing mitigations that stay: nginx 200MB body cap + POST rate-limit on the EC2, security
  group restricted to the CloudFront origin-facing prefix list, VLM `:8001` unreachable from AWS.
- Cost: your two new resources (on-demand DDB + small S3) are ~pennies inside the $200 credit;
  tag them `project=copilot` so the budget alarm covers them.
