#!/usr/bin/env bash
# copilot AWS front door - CloudFormation orchestration.
# Usage: deploy.sh up | frontend <dist-dir> | sync-userdata | outputs | teardown
set -euo pipefail
# Git-Bash/MSYS on Windows rewrites leading-slash args (e.g. the SSM parameter name
# /copilot/tailscale-authkey) into Windows paths before aws.exe sees them; disable that.
export MSYS_NO_PATHCONV=1
cd "$(dirname "$0")"
[ -f params.env ] || { echo "ERROR: copy params.env.example -> params.env and fill it in"; exit 1; }
# shellcheck disable=SC1091
source params.env
REGION="${REGION:-ap-southeast-1}"
ENABLE_GOOGLE_OAUTH="${ENABLE_GOOGLE_OAUTH:-false}"
GOOGLE_OAUTH_SECRET_VERSION_ID="${GOOGLE_OAUTH_SECRET_VERSION_ID:-PENDING}"

# conditionally forwards remaining args as --parameter-overrides; ${1:+...} is safe under set -u
dep() {  # dep <stack> <template> <region> [param-overrides...]
  local stack="$1" tpl="$2" region="$3"; shift 3
  echo "== deploy $stack ($region)"
  aws cloudformation deploy --region "$region" --stack-name "$stack" \
    --template-file "$tpl" --no-fail-on-empty-changeset \
    --capabilities CAPABILITY_NAMED_IAM --tags project=copilot \
    ${1:+--parameter-overrides "$@"}
}

up() {
  dep copilot-data 30-data.yaml "$REGION" "BucketPrefix=$BUCKET_PREFIX"
  dep copilot-auth 10-auth.yaml "$REGION" \
      "AppDomain=$APP_DOMAIN" "HostedUiPrefix=$HOSTED_UI_PREFIX" \
      "EnableGoogleOAuth=$ENABLE_GOOGLE_OAUTH" \
      "GoogleOAuthSecretVersionId=$GOOGLE_OAUTH_SECRET_VERSION_ID"
  dep copilot-cert-use1 15-cert-us-east-1.yaml us-east-1 \
      "DomainName=$APP_DOMAIN" "HostedZoneId=$HOSTED_ZONE_ID"
  echo "== secrets + EC2 bootstrap assets"
  aws ssm put-parameter --region "$REGION" --name /copilot/tailscale-authkey \
    --type SecureString --value "$TS_AUTHKEY" --overwrite >/dev/null
  aws s3 cp ec2-userdata.sh "s3://${BUCKET_PREFIX}-deploy/infra/ec2-userdata.sh" --region "$REGION"
  dep copilot-frontdoor 20-frontdoor.yaml "$REGION" \
      "VpcId=$VPC_ID" "SubnetIds=$SUBNET_IDS" "OriginDomain=origin.$APP_DOMAIN" \
      "HostedZoneId=$HOSTED_ZONE_ID" "CloudFrontPrefixListId=$CF_PREFIX_LIST_ID" \
      "BoxHost=$BOX_HOST" "BucketPrefix=$BUCKET_PREFIX"
  local cf_cert
  cf_cert=$(aws cloudformation describe-stacks --region us-east-1 --stack-name copilot-cert-use1 \
    --query "Stacks[0].Outputs[?OutputKey=='CertArn'].OutputValue" --output text)
  dep copilot-cdn 40-cdn.yaml "$REGION" \
      "AppDomain=$APP_DOMAIN" "CFCertArn=$cf_cert" "OriginDomain=origin.$APP_DOMAIN" \
      "HostedZoneId=$HOSTED_ZONE_ID" "BucketPrefix=$BUCKET_PREFIX"
  dep copilot-budget 50-budget.yaml "$REGION" "NotificationEmail=$BUDGET_EMAIL"
  outputs
}

sync_userdata() {   # push a changed ec2-userdata.sh; reboot does NOT re-run it (cloud-init runs once)
  aws s3 cp ec2-userdata.sh "s3://${BUCKET_PREFIX}-deploy/infra/ec2-userdata.sh" --region "$REGION"
  local iid
  iid=$(aws cloudformation describe-stacks --region "$REGION" --stack-name copilot-frontdoor \
    --query "Stacks[0].Outputs[?OutputKey=='InstanceId'].OutputValue" --output text)
  echo "synced. Re-run on the instance via SSM: aws ssm send-command --region $REGION --instance-ids $iid --document-name AWS-RunShellScript --parameters 'commands=[\"aws s3 cp s3://${BUCKET_PREFIX}-deploy/infra/ec2-userdata.sh /root/setup.sh\", \"bash /root/setup.sh $REGION $BOX_HOST $BUCKET_PREFIX\"]'"
}

frontend() {
  local dist="${1:?usage: deploy.sh frontend <dist-dir>}"
  aws s3 sync "$dist" "s3://${BUCKET_PREFIX}-deploy/frontend/" --delete --region "$REGION"
  local iid
  iid=$(aws cloudformation describe-stacks --region "$REGION" --stack-name copilot-frontdoor \
    --query "Stacks[0].Outputs[?OutputKey=='InstanceId'].OutputValue" --output text)
  aws ssm send-command --region "$REGION" --instance-ids "$iid" \
    --document-name AWS-RunShellScript \
    --parameters 'commands=["/usr/local/bin/refresh-frontend.sh"]' >/dev/null
  echo "frontend synced to EC2 via SSM ($iid)"
}

outputs() {
  for s in copilot-data copilot-auth copilot-frontdoor copilot-cdn; do
    echo "-- $s"
    aws cloudformation describe-stacks --region "$REGION" --stack-name "$s" \
      --query "Stacks[0].Outputs" --output table 2>/dev/null || echo "   (not deployed)"
  done
}

teardown() {
  echo "Deleting all copilot stacks (buckets must be EMPTY or their stack delete fails)."
  for s in copilot-budget copilot-cdn copilot-frontdoor copilot-auth copilot-data; do
    aws cloudformation delete-stack --region "$REGION" --stack-name "$s"
    echo "delete requested: $s"
    if [ "$s" = "copilot-frontdoor" ]; then
      echo "waiting for copilot-frontdoor to finish deleting (copilot-auth imports its exports)..."
      aws cloudformation wait stack-delete-complete --region "$REGION" --stack-name copilot-frontdoor
    fi
  done
  aws cloudformation delete-stack --region us-east-1 --stack-name copilot-cert-use1
  echo "delete requested: copilot-cert-use1 (us-east-1)"
}

case "${1:-}" in
  up) up ;;
  frontend) frontend "${2:-}" ;;
  sync-userdata) sync_userdata ;;
  outputs) outputs ;;
  teardown) teardown ;;
  *) echo "usage: $0 up | frontend <dist-dir> | sync-userdata | outputs | teardown"; exit 1 ;;
esac
