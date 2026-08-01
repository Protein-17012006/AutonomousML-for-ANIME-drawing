#!/usr/bin/env bash
# copilot EC2 one-time setup: tailscale client + nginx (static Next export + SSE-safe
# proxy -> box :8000). Invoked by CloudFormation UserData as:
#   setup.sh <region> <box_host> <bucket_prefix>
# Change nginx/tailscale config here, then: deploy.sh sync-userdata, and re-run via SSM:
#   aws ssm send-command ... 'aws s3 cp s3://<prefix>-deploy/infra/ec2-userdata.sh /root/setup.sh && bash /root/setup.sh <region> <box> <prefix>'
set -euo pipefail
REGION="$1"; BOX_HOST="$2"; BUCKET_PREFIX="$3"

dnf install -y nginx
curl -fsSL https://tailscale.com/install.sh | sh
systemctl enable --now tailscaled
TS_KEY=$(aws ssm get-parameter --region "$REGION" --name /copilot/tailscale-authkey \
  --with-decryption --query Parameter.Value --output text)
tailscale up --authkey "$TS_KEY" --hostname copilot-aws-proxy

mkdir -p /var/www/copilot /var/www/fallback
# Placeholder ONLY on first boot: setup.sh is re-run via SSM for config changes, and an
# unconditional write here clobbered the deployed frontend's index.html (hit live 2026-07-04).
if [ ! -f /var/www/copilot/index.html ]; then
cat > /var/www/copilot/index.html <<'EOF'
<!doctype html><title>In-Between Co-pilot</title>
<p>Frontend not deployed yet - run: infra/deploy.sh frontend &lt;dist-dir&gt;</p>
EOF
fi
cat > /var/www/fallback/box-offline.html <<'EOF'
<!doctype html><title>Co-pilot brain offline</title>
<h1>Co-pilot brain offline</h1>
<p>The GPU box behind this front door is unreachable right now. The site stays up;
sessions need the box. Contact Group 4 (COS30018).</p>
EOF

# --exact-timestamps: plain sync skips a changed file when its SIZE is identical (two Next
# builds differ only in equal-length hashes -> same size) — served stale copilot/index.html
# pointing at deleted chunks (hit live 2026-07-04).
cat > /usr/local/bin/refresh-frontend.sh <<EOF
#!/usr/bin/env bash
set -euo pipefail
stage=\$(mktemp -d /var/www/copilot.next.XXXXXX)
cleanup() { rm -rf "\$stage"; }
trap cleanup EXIT
aws s3 sync "s3://${BUCKET_PREFIX}-deploy/frontend/" "\$stage/" --delete --exact-timestamps --region ${REGION}
test -f "\$stage/index.html"
test -d "\$stage/_next"
# mktemp creates a root-only directory. Give nginx read/traverse access before
# the atomic move, otherwise a fresh frontend publish serves 403 responses.
chmod -R a+rX "\$stage"
rm -rf /var/www/copilot.previous
if [ -d /var/www/copilot ]; then
  mv /var/www/copilot /var/www/copilot.previous
fi
mv "\$stage" /var/www/copilot
trap - EXIT
systemctl reload nginx
EOF
chmod +x /usr/local/bin/refresh-frontend.sh

# Full nginx.conf overwrite (deterministic: no fight with the AL2023 stock server block).
cat > /etc/nginx/nginx.conf <<EOF
user nginx;
worker_processes auto;
error_log /var/log/nginx/error.log notice;
pid /run/nginx.pid;
events { worker_connections 1024; }
http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    sendfile on;
    keepalive_timeout 65;

    # Rate limits (POST only; GETs map to empty key = unlimited).
    # sess  = session-creating endpoints (expensive GPU runs): 5/min/IP
    # inter = in-session interactions (ask/key on an existing sid): 30/min/IP
    limit_req_zone \$limit_key zone=sess:10m rate=5r/m;
    limit_req_zone \$inter_key zone=inter:10m rate=30r/m;
    map "\$request_method:\$uri" \$limit_key {
        "~^POST:/session/[0-9]+/"  "";
        "~^POST:/session"          \$binary_remote_addr;
        "~^POST:/demo"             \$binary_remote_addr;
        default                    "";
    }
    map "\$request_method:\$uri" \$inter_key {
        "~^POST:/session/[0-9]+/"  \$binary_remote_addr;
        default                    "";
    }

    # HTML entry points must NEVER be browser-cached: after a redeploy (s3 sync --delete)
    # a stale index.html points at deleted hashed chunks -> black page + 404s (hit live
    # 2026-07-04; same trap the box FastAPI's _no_cache_html middleware guards). Hashed
    # _next assets are content-addressed -> stay cacheable. Empty value = header omitted.
    map \$uri \$html_no_cache {
        "~\.html\$"  "no-cache, no-store, must-revalidate";
        "~/\$"       "no-cache, no-store, must-revalidate";
        default      "";
    }

    server {
        listen 80 default_server;
        server_name _;
        # CloudFront terminates viewer TLS but reaches this nginx origin over HTTP.
        # Directory canonicalization (for example /copilot -> /copilot/) must be
        # relative, otherwise nginx exposes the origin hop as an http:// redirect.
        absolute_redirect off;
        root /var/www/copilot;
        index index.html;
        client_max_body_size 200m;          # video uploads <= ~2 min
        add_header Cache-Control \$html_no_cache;

        location /artifacts/ { return 404; }   # CloudFront serves these from S3, never via the box

        # API routes must reach FastAPI rather than falling through to the static
        # Next export. The plural sessions route serves durable owned-session
        # history and workspace snapshots; the auth route bootstraps the
        # application cookie.
        location ~ ^/(auth|sessions|session|demo|active-workspace)(?:/|$) {
            limit_req zone=sess burst=3 nodelay;
            limit_req zone=inter burst=10 nodelay;
            proxy_pass http://${BOX_HOST}:8000;
            proxy_http_version 1.1;
            proxy_buffering off;              # SSE must stream
            proxy_request_buffering off;
            proxy_read_timeout 1800s;
            proxy_send_timeout 1800s;
            proxy_set_header Host \$host;
            proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
            error_page 502 504 =503 /box-offline.html;
        }
        location = /box-offline.html { root /var/www/fallback; internal; }
    }
}
EOF
nginx -t
systemctl enable --now nginx
systemctl reload nginx

# Setup re-runs must leave the deployed frontend intact: re-pull it best-effort (no-op on
# first boot when the deploy bucket has no frontend/ yet).
/usr/local/bin/refresh-frontend.sh || true
