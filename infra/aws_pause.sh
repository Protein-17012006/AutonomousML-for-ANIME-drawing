#!/usr/bin/env bash
# ── Quick AWS cost-pause ──────────────────────────────────────────────────────
# STOP the EC2 front-door instance. Compute billing stops immediately; everything
# else is preserved: the EBS volume (nginx config, tailscale identity, /var/www)
# and all CloudFormation stacks (ALB, CloudFront, Cognito, S3, DynamoDB, DNS).
# Fully reversible in ~1-2 min with aws_resume.sh — no re-setup, no tailscale re-auth.
#
# Still billing while paused (small): ALB ~$0.55/day, Route53 zone $0.50/mo,
# CloudFront/S3/DynamoDB idle ~$0. For a LONG break (weeks) where the ALB cost
# matters more than fast resume, run `bash deploy.sh teardown` instead (deletes the
# ALB + everything) and `bash deploy.sh up` to rebuild (~15 min, re-provisions all).
#
# The 5090 box is NOT AWS — stop its GPU server separately if idle (printed below).
# Created 2026-07-05.
set -euo pipefail
export MSYS_NO_PATHCONV=1          # keep leading-slash ARNs/paths intact on git-bash/Windows
cd "$(dirname "$0")"
[ -f params.env ] && source params.env
REGION="${REGION:-ap-southeast-1}"

IID=$(aws ec2 describe-instances --region "$REGION" \
  --filters "Name=tag:project,Values=copilot" \
            "Name=instance-state-name,Values=running,pending" \
  --query "Reservations[].Instances[].InstanceId" --output text)

if [ -z "$IID" ] || [ "$IID" = "None" ]; then
  echo ">> No running copilot EC2 instance — already paused (or torn down). Nothing to do."
  exit 0
fi

echo ">> stopping EC2 $IID (front door) ..."
aws ec2 stop-instances --region "$REGION" --instance-ids $IID >/dev/null
aws ec2 wait instance-stopped --region "$REGION" --instance-ids $IID
echo ">> DONE — EC2 stopped. The public site (https://${APP_DOMAIN:-inbetween-copilot.click}) is now DOWN."
echo ""
echo "   Resume:                bash aws_resume.sh"
echo "   Max savings (long gap): bash deploy.sh teardown   (rebuild later: bash deploy.sh up)"
echo "   Free the box GPU too:   ssh long@${BOX_HOST:-100.71.161.102} 'pkill -f serve_openai.py'"
