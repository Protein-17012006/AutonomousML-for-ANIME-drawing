# DynamoDB Chat Schema — In-Between Co-pilot (Stage 3 persistence)

> **Audience:** the teammate provisioning AWS for Stage 3.
> **Purpose:** everything needed to stand up the chat-history storage so signed-in users get saved,
> reopenable conversations.
> **Source of truth:** `frontend/docs/plans/layout-refinement-stage-3-plan.md` (§2b, §4, §H). Auth /
> Cognito setup is a separate doc: `frontend/docs/plans/stage-3-infra-request-r0.md`.
> Region `ap-southeast-1` · account `834996123571`.

## TL;DR — what you're creating

| # | Resource | Name |
| - | -------- | ---- |
| 1 | DynamoDB table (conversation index/metadata) | **`copilot_chats`** |
| 2 | S3 bucket (the actual message payload + frames) + CORS | **`copilot-g4-cos30018-userdata`** |
| 3 | IAM policy on the Cognito Identity Pool **authenticated role** (per-user isolation) | inline policy |

> ⚠️ These are **new** resources. Do **not** reuse or modify the existing `copilot_sessions` table or
> the `…-artifacts` bucket — those hold real pipeline-run evidence and are off-limits.

The Cognito **User Pool** + **Identity Pool** themselves are covered in the R0 request doc; this doc
assumes the Identity Pool exists and just needs the data policy attached to its authenticated role.

---

## 1. The two-tier model — what lives where

A "chat" = one co-pilot session (the user uploads key drawings/video → the pipeline streams a decision
log → produces a result + QA turns). That payload is large and partly binary, so it is **split**:

| Tier | Holds | Why |
| ---- | ----- | --- |
| **DynamoDB `copilot_chats`** | one small **metadata** item per conversation (title, kind, timestamps…) | fast, sorted, queryable — powers the sidebar list |
| **S3 `…-userdata`** | the heavy **`state.json`** (the messages/transcript state) **+ all frame images** | DynamoDB items cap at **400 KB**; frames are binary; S3 is cheap for blobs |

Both tiers are keyed on the **same per-user id** (the Cognito **`identityId`**), so one IAM condition
isolates a user across both. The browser talks to DynamoDB and S3 **directly** (client-direct, via temp
creds from the Identity Pool) — there is no app server in between; **IAM is the access control**.

---

## 2. DynamoDB table `copilot_chats`

**Table settings**
- Billing mode: **On-demand (PAY_PER_REQUEST)** — no capacity planning, tiny table.
- No GSI needed at this scale (see access patterns). Point-in-time recovery: optional (recommended).

**Key schema**

| Role | Attribute | Type | Example | Notes |
| ---- | --------- | ---- | ------- | ----- |
| **Partition key (HASH)** | `identityId` | `S` | `ap-southeast-1:9f3c…` | the user's Cognito **Identity Pool** id — the isolation key |
| **Sort key (RANGE)** | `sk` | `S` | `CONV#01J8Z…` | `CONV#{cid}`; the prefix keeps room for future item types under the same user |

**Item attributes** (all on the single conversation-metadata item):

| Attribute | Type | Meaning |
| --------- | ---- | ------- |
| `identityId` | S | PK (above) |
| `sk` | S | SK, `CONV#{cid}` |
| `cid` | S | raw conversation id (also embedded in `sk`); client-generated, sortable |
| `title` | S | e.g. `"Genga pair 03 · walk cycle"` |
| `kind` | S | `png` \| `video` \| `planted` |
| `engines` | S | run engine label (e.g. `"box"`) |
| `fps` | N | cadence/fps setting |
| `stride` | N | frame stride setting |
| `sid` | S | original **live** session id (reference only; the box evicts it) |
| `uploadLabel` | S | short label for what was uploaded |
| `thumb` | S | **S3 key** of the montage (sidebar thumbnail; signed to a URL on read — see §9) |
| `createdAt` | N | epoch **milliseconds** |
| `updatedAt` | N | epoch **milliseconds** (drives sidebar ordering) |
| `schemaVersion` | N | forward-migration guard (start at `1`) |

**Example item**

```json
{
  "identityId":  "ap-southeast-1:9f3c1a20-7b4e-4c2f-8b1a-0d2e5f6a7c88",
  "sk":          "CONV#01J8ZK9Q3M7F2VYABCDE",
  "cid":         "01J8ZK9Q3M7F2VYABCDE",
  "title":       "Genga pair 03 · walk cycle",
  "kind":        "png",
  "engines":     "box",
  "fps":         12,
  "stride":      2,
  "sid":         "sess_7f19c4",
  "uploadLabel": "3 keys",
  "thumb":       "private/ap-southeast-1:9f3c…/conversations/01J8ZK9Q3M7F2VYABCDE/montage.png",
  "createdAt":   1752019200000,
  "updatedAt":   1752019456000,
  "schemaVersion": 1
}
```

### 2.1 Access patterns (how the app uses the table)

| # | Operation | DynamoDB call |
| - | --------- | ------------- |
| 1 | **List** a user's chats for the sidebar | `Query` `PK = identityId` → **client-sorts by `updatedAt` desc**. Items are tiny; a whole-partition query is cheap at this scale. *(If a user ever accumulates thousands of chats, add a GSI `byUpdatedAt` = `PK identityId` / `SK updatedAt` and `Query … ScanIndexForward=false`.)* |
| 2 | **Open** one chat | S3 key is deterministic, so the app reads S3 directly; `GetItem(identityId, sk=CONV#{cid})` is only needed if it wants the metadata alone |
| 3 | **Create** | `PutItem` the metadata item (+ upload `state.json` and frames to S3) |
| 4 | **Light save** (new Q&A / verdict) | `UpdateItem` set `updatedAt` (+ overwrite `state.json` in S3; no re-upload of frames) |
| 5 | **Delete** | `DeleteItem` (+ delete the S3 `conversations/{cid}/` prefix) |

---

## 3. Where the messages actually live (S3) — and why there's no "messages" table

The **chat message content is not stored as DynamoDB items.** The full transcript state for a
conversation is one JSON object in S3:

```
s3://copilot-g4-cos30018-userdata/
  private/{identityId}/conversations/{cid}/
    state.json          # <-- the transcript state (all "messages")
    keys/0.png keys/1.png …            # uploaded key drawings
    mids/*  annotated/*  pair_mids/*   # generated / QA'd / per-pair frames
    montage.png                        # result montage (also the sidebar thumb)
    video.mp4                          # video-input source (video flow only)
    report.<ext>                       # exported report
```

`state.json` shape (opaque to AWS — it's just a blob S3 stores):

```jsonc
{
  "schemaVersion": 1,
  "upload":   { /* UserTurn — the user's upload turn */ },
  "log":      [ /* PairEvent[] — the streamed decision-log */ ],
  "result":   { /* ResultEvent — montage, key_urls, artifacts, verdict probs */ },
  "qaTurns":  [ /* QaTurn[] — grounded Q&A history */ ],
  "verdicts": { "0": "accept", "1": "reject" }   // keys = frame indices
}
```

**Design note — why a state-blob in S3 instead of one DynamoDB item per message:**
- The chat bubbles are **derived**, not stored — the app rebuilds them at render time from
  `upload/log/result/qaTurns/verdicts` via `deriveMessages(...)` in
  `frontend/src/components/copilot/lib/chatModel.ts`. So we persist the *source state*, and a
  per-message table would be redundant.
- The payload is heavy and includes **binary frames**, which belong in S3 regardless; a full transcript
  can also exceed DynamoDB's **400 KB** item limit.
- The app writes `state.json` **after** rewriting the ephemeral `/session/{sid}/…` frame URLs to
  **stable S3 keys** (see §9 — the private bucket is read via short-lived pre-signed `getUrl()`), so a reopened chat renders its
  frames even when the GPU box is offline.

For AWS setup you don't need to understand `state.json`'s internals — treat it as an app-owned JSON
object. You only provision the **bucket + layout + CORS + IAM prefix** below.

---

## 4. S3 bucket `copilot-g4-cos30018-userdata`

- Private bucket (no public access). Objects are written under the **`private/{identityId}/…`** prefix —
  this prefix is produced by **Amplify Storage's `private` access level**, and the IAM policy in §5 must
  match it exactly.
- **CORS** (Amplify Storage calls the S3 REST endpoint cross-origin from the SPA):

```json
[
  {
    "AllowedOrigins": ["https://inbetween-copilot.click", "http://localhost:3000"],
    "AllowedMethods": ["GET", "PUT", "POST", "DELETE", "HEAD"],
    "AllowedHeaders": ["*"],
    "ExposeHeaders": ["ETag", "x-amz-request-id", "x-amz-id-2"],
    "MaxAgeSeconds": 3000
  }
]
```

---

## 5. Per-user isolation (IAM) — the important part

Because the browser calls DynamoDB and S3 **directly**, the security lives entirely in the IAM policy on
the Identity Pool's **authenticated role**. Both conditions key on the same
`${cognito-identity.amazonaws.com:sub}` (the caller's own `identityId`), so a user can only ever touch
their own DynamoDB partition and their own S3 prefix.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "OwnChatsOnly",
      "Effect": "Allow",
      "Action": [
        "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem",
        "dynamodb:DeleteItem", "dynamodb:Query", "dynamodb:BatchGetItem", "dynamodb:BatchWriteItem"
      ],
      "Resource": "arn:aws:dynamodb:ap-southeast-1:834996123571:table/copilot_chats",
      "Condition": {
        "ForAllValues:StringEquals": {
          "dynamodb:LeadingKeys": ["${cognito-identity.amazonaws.com:sub}"]
        }
      }
    },
    {
      "Sid": "OwnFilesReadWrite",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::copilot-g4-cos30018-userdata/private/${cognito-identity.amazonaws.com:sub}/*"
    },
    {
      "Sid": "ListOwnPrefixOnly",
      "Effect": "Allow",
      "Action": ["s3:ListBucket"],
      "Resource": "arn:aws:s3:::copilot-g4-cos30018-userdata",
      "Condition": {
        "StringLike": { "s3:prefix": ["private/${cognito-identity.amazonaws.com:sub}/*"] }
      }
    }
  ]
}
```

> **Test it:** from the Cognito console, a second identity must get `AccessDenied` when it queries a
> different `identityId`'s partition or lists another user's S3 prefix.

---

## 6. Setup steps

Per team convention the real definitions should land in the main-repo **`infra/`** CDK/CloudFormation
(so they're version-controlled, not click-ops). The CLI below is fine for a first stand-up / sanity
check; the CloudFormation appendix is the IaC form.

**a) Create the table**

```bash
aws dynamodb create-table \
  --region ap-southeast-1 \
  --table-name copilot_chats \
  --billing-mode PAY_PER_REQUEST \
  --attribute-definitions AttributeName=identityId,AttributeType=S AttributeName=sk,AttributeType=S \
  --key-schema AttributeName=identityId,KeyType=HASH AttributeName=sk,KeyType=RANGE
```

**b) Create the bucket + CORS** (save the §4 JSON as `cors.json`)

```bash
aws s3api create-bucket --region ap-southeast-1 \
  --bucket copilot-g4-cos30018-userdata \
  --create-bucket-configuration LocationConstraint=ap-southeast-1
aws s3api put-bucket-cors --bucket copilot-g4-cos30018-userdata --cors-configuration file://cors.json
# keep public access fully blocked:
aws s3api put-public-access-block --bucket copilot-g4-cos30018-userdata \
  --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
```

**c) Attach the §5 policy** to the Cognito Identity Pool **authenticated** role (the role the Identity
Pool assumes for signed-in users — find it under Identity Pool → *Authenticated role* / the
`Cognito_..._Auth_Role`).

**d) Hand the frontend these `.env` values** (see §7).

---

## 7. Values the frontend needs (`frontend/.env`)

| Env var | Value |
| ------- | ----- |
| `NEXT_PUBLIC_AWS_REGION` | `ap-southeast-1` |
| `NEXT_PUBLIC_CHATS_TABLE` | `copilot_chats` |
| `NEXT_PUBLIC_USERDATA_BUCKET` | `copilot-g4-cos30018-userdata` |
| `NEXT_PUBLIC_COGNITO_USER_POOL_ID` | *(from the User Pool — R0 doc)* |
| `NEXT_PUBLIC_COGNITO_USER_POOL_CLIENT_ID` | *(app client — R0 doc)* |
| `NEXT_PUBLIC_COGNITO_IDENTITY_POOL_ID` | *(the Identity Pool)* |
| `NEXT_PUBLIC_COGNITO_DOMAIN` | *(Hosted UI domain — R0 doc)* |

> `NEXT_PUBLIC_*` are **inlined at build time** by the static export → any change means a rebuild +
> redeploy (`BUILD_EXPORT=1 npm run build` → `s3 sync` → SSM refresh).

---

## 8. Notes & gotchas

- **`identityId` is the Cognito *Identity Pool* id** (format `ap-southeast-1:{uuid}`), **not** the User
  Pool `sub`. It's what `${cognito-identity.amazonaws.com:sub}` resolves to and what the app reads via
  Amplify `fetchAuthSession()`. Keep DynamoDB PK, the S3 prefix, and the IAM conditions all on this same id.
- **The S3 prefix must match Amplify's private level** exactly (`private/{identityId}/…`). If you change
  the layout, change the IAM `Resource`/`prefix` to match or writes will 403.
- **Timestamps are epoch milliseconds (Number)** so range/sort math is trivial.
- **`schemaVersion`** lets the app migrate `state.json`/item shape later without guessing.
- **On-demand billing** keeps this within the team's budget guardrails; no provisioned capacity.
- Again: **do not touch** `copilot_sessions` / `…-artifacts` — those are the pipeline's evidence store,
  not this per-user chat store.

## 9. Additional implementation notes (for the storage owner)

**Reading private files — use short-lived pre-signed URLs, not "permanent" ones.**
Because the userdata bucket is private, the browser can't load `montage.png` / frames by a plain S3 URL.
- **Recommended:** store the **S3 key** (e.g. `private/{identityId}/conversations/{cid}/montage.png`) in
  `state.json` / `thumb`, and let the app mint a **short-lived pre-signed URL** at render time via Amplify
  Storage **`getUrl()`** (signed with the user's temp creds). No CloudFront needed for userdata.
- **Do not persist absolute pre-signed URLs** — they **expire** (minutes–hours; 7-day max), so a chat
  reopened later would show broken images. Persist the **S3 key**; sign on read. (§3 above now reflects this.)
- Fronting the bucket with CloudFront instead would need **OAC + signed URLs/cookies** to keep per-user
  privacy — more moving parts. Either way, **agree with the frontend** whether `state.json` stores keys
  or URLs, because it changes what gets written.

**Agree on the Amplify Storage path convention before writing the IAM prefix.** `private/{identityId}/…`
is Amplify Storage's **Gen-1 access-level** prefix (`accessLevel: 'private'`). If the frontend uses
Amplify **Gen-2** storage (`defineStorage`), the prefix is `entity/{identityId}/…` (a **different
string**) — so the S3 layout **and** the IAM `Resource`/`prefix` in §5 must change to match. (If the app
uses the raw `@aws-sdk/client-s3`, the prefix is fully app-controlled — keep it `private/{identityId}/…`
to match §5.) Lock this down first, or uploads/reads will 403.

**Set `Content-Type` on every upload** — frames `image/png`, `state.json` `application/json`, `video.mp4`
`video/mp4` — else browsers may not render them and `fetch().json()` breaks. (Frontend passes
`options.contentType`; nothing server-side, but verify it in the first end-to-end test.)

**Encryption at rest** is on by default (SSE-S3 + DynamoDB AWS-owned keys) — fine as-is. If you switch
either to a **customer-managed KMS key**, add `kms:Decrypt` + `kms:GenerateDataKey` (scoped to that key)
to the authenticated role in §5, or every read/write 403s.

**Lock down the *unauthenticated* Identity Pool role.** Disable guest access, or ensure its role has
**no** permissions on `copilot_chats` / the userdata bucket. Only the **authenticated** role gets §5.

**Read consistency.** DynamoDB reads are **eventually consistent** by default. The app refetches the list
after each write so it's usually invisible; if a "create → immediately read" ever races, use a
**strongly consistent** `GetItem`/`Query` (`ConsistentRead: true`) — allowed on the base table since
there's no GSI.

**`cid` = sortable, URL-safe id** (ULID / KSUID / `{epochMillis}-{rand}`), client-generated. Time-ordered
ids make `sk` naturally chronological, avoid collisions, and are safe inside S3 keys.

**Deletes span both tiers — watch for orphans.** Deleting a chat must remove the DynamoDB item **and** the
S3 `conversations/{cid}/` prefix. Optional safety nets: an **S3 lifecycle rule** to expire a `trash/`
prefix, or a DynamoDB **TTL** attribute to auto-expire demo/temp accounts.

**Recovery.** PITR is enabled on the table (Appendix). Consider **S3 versioning** on the userdata bucket —
`state.json` is overwritten on every light-save, so versioning lets you roll back a corrupted state (small
extra storage cost). Optional.

**Keep everything in `ap-southeast-1`** (table, bucket, Identity Pool) to avoid cross-region latency/egress.
Bucket names are **globally unique** — `copilot-g4-cos30018-userdata` should be free; if not, pick another
and update §4–§7 + the frontend env.

## Appendix — CloudFormation snippet (for `infra/`)

```yaml
Resources:
  CopilotChatsTable:
    Type: AWS::DynamoDB::Table
    Properties:
      TableName: copilot_chats
      BillingMode: PAY_PER_REQUEST
      AttributeDefinitions:
        - { AttributeName: identityId, AttributeType: S }
        - { AttributeName: sk, AttributeType: S }
      KeySchema:
        - { AttributeName: identityId, KeyType: HASH }
        - { AttributeName: sk, KeyType: RANGE }
      PointInTimeRecoverySpecification: { PointInTimeRecoveryEnabled: true }

  UserDataBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: copilot-g4-cos30018-userdata
      PublicAccessBlockConfiguration:
        BlockPublicAcls: true
        IgnorePublicAcls: true
        BlockPublicPolicy: true
        RestrictPublicBuckets: true
      CorsConfiguration:
        CorsRules:
          - AllowedOrigins: ["https://inbetween-copilot.click", "http://localhost:3000"]
            AllowedMethods: [GET, PUT, POST, DELETE, HEAD]
            AllowedHeaders: ["*"]
            ExposedHeaders: [ETag, x-amz-request-id, x-amz-id-2]
            MaxAge: 3000
```

*(The IAM policy in §5 attaches to the existing Identity Pool authenticated role — reference that
role's logical name in `infra/` rather than creating a new one.)*
