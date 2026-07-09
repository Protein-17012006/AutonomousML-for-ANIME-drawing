# Stage 3 — AWS infra request for R0 (Hoàng)

> From: frontend (chatbox/auth owner) · Date: 2026-07-09 · Re: gating `/copilot` + per-user chat history
> Plan of record: `frontend/docs/plans/layout-refinement-stage-3-plan.md`

Hi Hoàng — Stage 3 makes `/copilot` sign-in-gated and gives each user saved, reopenable chats. I've
settled the design on **AWS-native**: **Cognito** (reusing our existing site User Pool) + **client-direct
DynamoDB/S3** (the browser gets temp creds from a Cognito **Identity Pool**; IAM policy is the per-user
access rule — no server/Lambda). The frontend code is ready to wire; it just needs some infra from you.
Everything below is on **AWS only** — I won't touch the box.

## 1. One blocking question (please confirm first)

**Is `https://inbetween-copilot.click` currently gated at the ALB with `authenticate-cognito` (i.e. the
browser hits Cognito's Hosted UI login before the SPA loads)?**

- **If yes** → please **remove or scope that edge gate** for the app. Otherwise users log in at AWS's
  hosted page first, our in-app `/login` + `/signup` are never seen, and they'd have to log in *again*
  inside the app to get the Cognito session the data layer needs (double login). Decision: the app's
  **in-app pages should be the single canonical login** everywhere.
- **If no** → nothing to change here; skip to §2.

## 2. Infra to provision (AWS only, `ap-southeast-1`, acct `834996123571`)

**a) Existing User Pool — enable/confirm:**
- [ ] Self-service **sign-up** (currently only hand-issued users like `hoang/long/…`).
- [ ] Email **verification by code** + **password reset by code** (6-digit).
- [ ] A **Hosted UI domain**.
- [ ] **Google** as an identity provider (needs a Google OAuth client).
- [ ] An **app client** (SPA, no secret) whose allowed callback/sign-out URLs include
      `http://localhost:3000/sso-callback` **and** `https://inbetween-copilot.click/sso-callback`.

**b) Cognito Identity Pool** linked to that User Pool, with an **authenticated IAM role**.

**c) New DynamoDB table `copilot_chats`** (on-demand): partition key `identityId` (S), sort key `sk`
(S). *(This is separate from — not — the `copilot_sessions` table.)*

**d) New S3 bucket `copilot-g4-cos30018-userdata`** with a **CORS** config allowing
`https://inbetween-copilot.click` and `http://localhost:3000` (GET/PUT/POST/DELETE/HEAD).
*(Separate from — not — the `…-artifacts` bucket.)*

**e) IAM policy on the authenticated role** (per-user isolation):
- DynamoDB `copilot_chats`: condition `dynamodb:LeadingKeys = ["${cognito-identity.amazonaws.com:sub}"]`.
- S3 `copilot-g4-cos30018-userdata`: restrict to prefix `private/${cognito-identity.amazonaws.com:sub}/*`.

## 3. What I need back (to fill `frontend/.env`)

- `NEXT_PUBLIC_AWS_REGION` (= `ap-southeast-1`)
- `NEXT_PUBLIC_COGNITO_USER_POOL_ID`
- `NEXT_PUBLIC_COGNITO_USER_POOL_CLIENT_ID`
- `NEXT_PUBLIC_COGNITO_IDENTITY_POOL_ID`
- `NEXT_PUBLIC_COGNITO_DOMAIN` (Hosted UI domain)
- `NEXT_PUBLIC_CHATS_TABLE` (= `copilot_chats`)
- `NEXT_PUBLIC_USERDATA_BUCKET` (= `copilot-g4-cos30018-userdata`)

## 4. Guardrails (so you know the blast radius)

- I will **not** touch the forbidden `copilot_sessions` table, the `…-artifacts` bucket, the box, or any
  `copilot-*` CloudFormation stack. The two new resources above are the only additions.
- All `NEXT_PUBLIC_*` values are inlined at build → a config change just means a rebuild + redeploy (the
  usual `BUILD_EXPORT=1` → `s3 sync` → SSM refresh).

Happy to hop on a quick call if easier — thanks! *(Vietnamese version available on request.)*
