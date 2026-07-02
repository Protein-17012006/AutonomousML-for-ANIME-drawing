import type { NextConfig } from "next";

// Two build modes:
//  • DEV / normal build — the co-pilot SPA fetches the FastAPI service with
//    same-origin relative paths (/session, /session/video, /demo, /session/{sid}/…).
//    localhost != box origin, so we proxy them to the box via rewrites (the Next
//    equivalent of the old Vite dev proxy). Override target with NEXT_PUBLIC_API_TARGET.
//  • BUILD_EXPORT=1 — a STATIC export (`out/`) served same-origin by the box FastAPI
//    (like the Vite dist, via COPILOT_WEB_DIR). Same-origin → NO rewrites needed;
//    trailingSlash makes /copilot land on out/copilot/index.html for StaticFiles(html=True).
const EXPORT = process.env.BUILD_EXPORT === "1";
const API_TARGET =
  process.env.NEXT_PUBLIC_API_TARGET || "http://100.71.161.102:8000";

const nextConfig: NextConfig = EXPORT
  ? {
      reactCompiler: true,
      output: "export",
      trailingSlash: true,
    }
  : {
      reactCompiler: true,
      async rewrites() {
        return [
          { source: "/session", destination: `${API_TARGET}/session` },
          { source: "/session/:path*", destination: `${API_TARGET}/session/:path*` },
          { source: "/demo", destination: `${API_TARGET}/demo` },
        ];
      },
    };

export default nextConfig;
