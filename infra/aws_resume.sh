#!/usr/bin/env bash
# ── Resume the AWS front door (undo aws_pause.sh) ─────────────────────────────
# START the EC2 front-door instance and verify. nginx + tailscale come back on
# their own (systemd services; all state lives on the EBS volume), so no re-setup.
# ~1-2 min. NOTE: this covers the case where aws_pause.sh STOPPED the instance.
# If you ran `deploy.sh teardown`, resume with `bash deploy.sh up` instead.
# Created 2026-07-05.
set -euo pipefail
export MSYS_NO_PATHCONV=1
cd "$(dirname "$0")"
[ -f params.env ] && source params.env
REGION="${REGION:-ap-southeast-1}"

IID=$(aws ec2 describe-instances --region "$REGION" \
  --filters "Name=tag:project,Values=copilot" \
            "Name=instance-state-name,Values=running,stopped,stopping,pending" \
  --query "Reservations[].Instances[].InstanceId" --output text)

if [ -z "$IID" ] || [ "$IID" = "None" ]; then
  echo ">> No copilot EC2 instance found — it was likely torn down."
  echo "   Rebuild the whole front door with:  bash deploy.sh up"
  exit 1
fi

state=$(aws ec2 describe-instances --region "$REGION" --instance-ids $IID \
  --query "Reservations[].Instances[].State.Name" --output text)

if [ "$state" = "running" ]; then
  echo ">> EC2 $IID already running."
else
  echo ">> starting EC2 $IID ..."
  aws ec2 start-instances --region "$REGION" --instance-ids $IID >/dev/null
  aws ec2 wait instance-running --region "$REGION" --instance-ids $IID
  echo ">> instance running; waiting for status checks (nginx/tailscale re-init) ..."
  aws ec2 wait instance-status-ok --region "$REGION" --instance-ids $IID
fi

echo ">> verifying the public front door ..."
curl -s -o /dev/null -m 15 \
  -w "   https://${APP_DOMAIN} -> HTTP %{http_code}  (302 = Cognito login = front door healthy)\n" \
  "https://${APP_DOMAIN}/" || echo "   (curl failed — CloudFront may take a minute to warm)"

echo ""
echo ">> The SITE also needs the 5090 box (GPU brain). Bring it up:"
echo "   ssh long@${BOX_HOST:-100.71.161.102} 'source ~/.copilot_deepseek_env; bash ~/copilot_svc/box_start_service.sh 8000'"
echo "   ssh long@${BOX_HOST:-100.71.161.102} 'bash ~/serve.sh 320 ~/anime-ft-data/motion/runs/motion_lora16_on2s_v2'"
echo "   box health:  curl -s -o /dev/null -w '%{http_code}\\n' http://${BOX_HOST:-100.71.161.102}:8000/"
