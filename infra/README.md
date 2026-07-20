# infra/ — AWS Front Door (sub-project 3)

cd /c/Users/huyho/OneDrive/Desktop/COS30018

bash infra/aws_pause.sh     # TẮT — stop EC2 (site sập, tiết kiệm)
bash infra/aws_resume.sh    # BẬT LẠI — start EC2 + verify

CloudFormation for: CloudFront → ALB (Cognito auth, whole site) → EC2 nginx →
tailscale → box `:8000`. GPU never on AWS. Design + rationale: vault
`05 - Plans and Roadmap/AWS Front Door (sub-project 3) - Design.md`.

## One-time prerequisites (console/manual)
1. AWS account, `aws configure` with an admin key, region `ap-southeast-1`.
2. Register a domain in Route53 (cheapest: a `.click`, ~$3/yr). Note the hosted zone id.
3. Tailscale admin console → Settings → Keys → new **auth key** tagged `tag:aws-proxy`,
   and add to the tailnet ACL:
   `"tagOwners": {"tag:aws-proxy": ["autogroup:admin"]}` and an accept rule
   `{"action":"accept","src":["tag:aws-proxy"],"dst":["<BOX_TAILNET_IP>:8000"]}`
   (**only :8000** — the VLM :8001 must stay unreachable).

## Lookups for params.env
- `cp params.env.example params.env` then fill:
- VPC_ID: `aws ec2 describe-vpcs --filters Name=isDefault,Values=true --query "Vpcs[0].VpcId" --output text`
- SUBNET_IDS (two AZs): `aws ec2 describe-subnets --filters Name=vpc-id,Values=<VPC_ID> --query "Subnets[:2].SubnetId" --output text` (join with a comma)
- CF_PREFIX_LIST_ID: `aws ec2 describe-managed-prefix-lists --filters Name=prefix-list-name,Values=com.amazonaws.global.cloudfront.origin-facing --query "PrefixLists[0].PrefixListId" --output text`
- HOSTED_ZONE_ID: `aws route53 list-hosted-zones --query "HostedZones[0].Id" --output text` (strip `/hostedzone/`)

## Bring-up
    bash deploy.sh up          # ~15-25 min first run (2 ACM certs validate via DNS)
    bash deploy.sh outputs     # StaffUrl = https://<APP_DOMAIN>

Then: Cognito users, box publisher key, frontend — see the vault runbook
`06 - Operations/Running the AWS Front Door.md` (bring-up §, demo-day checklist,
auth-bypass emergency command, teardown).

## Frontend deploy

From the repository root:

    bash infra/deploy.sh frontend

The command builds `frontend/out/`, validates it, syncs it to the private deploy bucket,
waits for the EC2 SSM refresh, atomically switches the nginx-served directory, and checks the
public HTTPS root. An optional relative path is resolved from the directory where you invoke the
command; normally do not supply one.

## Phase 2 session-history backend deploy

The box service needs the durable session-history routes (`/sessions/...`) as
well as the existing SSE routes. Before restarting it, make sure its protected
`~/.copilot_aws_env` contains `AWS_PUBLISH=1`, `AWS_ARTIFACT_BUCKET`,
`AWS_SESSIONS_TABLE`. The launcher enables session history once those durable
publisher settings are present; set `COPILOT_SESSION_HISTORY_ENABLED=0` only to
block startup intentionally. Memory and per-frame feedback use in-memory
storage unless their separate DynamoDB backends are configured. Then, from the
repository root with `BOX_HOST` set to the teammate box's Tailscale hostname or
tailnet IP:

    bash scripts/deploy_box.sh --restart

For the public AWS path, sync this updated nginx configuration and re-run it on
the EC2 proxy before smoke-testing `/sessions` through the front door:

    bash infra/deploy.sh sync-userdata

## Teardown (back to ~$0)
    # empty the buckets first:
    aws s3 rm s3://<BUCKET_PREFIX>-artifacts --recursive
    aws s3 rm s3://<BUCKET_PREFIX>-deploy --recursive
    bash deploy.sh teardown
