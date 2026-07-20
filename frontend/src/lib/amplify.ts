"use client";

import "aws-amplify/auth/enable-oauth-listener";
import { Amplify } from "aws-amplify";
import { fetchAuthSession, signOut } from "aws-amplify/auth";
import { cognitoUserPoolsTokenProvider } from "aws-amplify/auth/cognito";
import { sessionStorage as amplifySessionStorage } from "aws-amplify/utils";

let configured = false;

function required(name: string, value: string | undefined) {
  if (!value) throw new Error(`${name} is not configured.`);
  return value;
}

function currentOrigin() {
  return typeof window === "undefined"
    ? "http://localhost:3000"
    : window.location.origin;
}

function sameOriginRedirect(configured: string | undefined, path: string) {
  const fallback = `${currentOrigin()}${path}`;
  if (!configured || typeof window === "undefined") return configured || fallback;
  try {
    return new URL(configured).origin === window.location.origin
      ? configured
      : fallback;
  } catch {
    return fallback;
  }
}

export function cognitoLogoutUrl() {
  const domain = required(
    "NEXT_PUBLIC_COGNITO_DOMAIN",
    process.env.NEXT_PUBLIC_COGNITO_DOMAIN,
  );
  const clientId = required(
    "NEXT_PUBLIC_COGNITO_USER_POOL_CLIENT_ID",
    process.env.NEXT_PUBLIC_COGNITO_USER_POOL_CLIENT_ID,
  );
  const logoutUri = sameOriginRedirect(
    process.env.NEXT_PUBLIC_COGNITO_REDIRECT_SIGN_OUT,
    "/login",
  );
  const url = new URL(`https://${domain}/logout`);
  url.searchParams.set("client_id", clientId);
  url.searchParams.set("logout_uri", logoutUri);
  return url.toString();
}

export function configureAmplify() {
  if (configured) return;

  const userPoolId = required(
    "NEXT_PUBLIC_COGNITO_USER_POOL_ID",
    process.env.NEXT_PUBLIC_COGNITO_USER_POOL_ID,
  );
  const userPoolClientId = required(
    "NEXT_PUBLIC_COGNITO_USER_POOL_CLIENT_ID",
    process.env.NEXT_PUBLIC_COGNITO_USER_POOL_CLIENT_ID,
  );
  const domain = process.env.NEXT_PUBLIC_COGNITO_DOMAIN;
  const redirectSignIn = sameOriginRedirect(
    process.env.NEXT_PUBLIC_COGNITO_REDIRECT_SIGN_IN,
    "/sso-callback",
  );
  const redirectSignOut = sameOriginRedirect(
    process.env.NEXT_PUBLIC_COGNITO_REDIRECT_SIGN_OUT,
    "/login",
  );

  // Amplify needs temporary state across the hosted-UI redirect, but the
  // long-lived application session is the server-issued HttpOnly cookie.
  cognitoUserPoolsTokenProvider.setKeyValueStorage(amplifySessionStorage);
  Amplify.configure({
    Auth: {
      Cognito: {
        userPoolId,
        userPoolClientId,
        loginWith: {
          email: true,
          ...(domain
            ? {
                oauth: {
                  domain,
                  scopes: ["openid", "email", "profile"],
                  redirectSignIn: [redirectSignIn],
                  redirectSignOut: [redirectSignOut],
                  responseType: "code" as const,
                },
              }
            : {}),
        },
      },
    },
  });
  configured = true;
}

export async function getCurrentIdToken() {
  configureAmplify();
  const session = await fetchAuthSession();
  const token = session.tokens?.idToken?.toString();
  if (!token) throw new Error("Cognito did not return an ID token.");
  return token;
}

export async function clearTemporaryAmplifySession() {
  if (typeof window === "undefined") return;
  try {
    // Let Amplify clear its token provider and in-memory auth state. Removing
    // storage keys alone can leave the previous identity active in this tab.
    await signOut();
  } finally {
    window.sessionStorage.removeItem("copilot:pendingEmail");
  }
}
