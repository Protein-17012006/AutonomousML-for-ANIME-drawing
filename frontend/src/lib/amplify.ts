"use client";

import { Amplify } from "aws-amplify";
import { fetchAuthSession, getCurrentUser } from "aws-amplify/auth";
import { getUrl, uploadData, downloadData, remove } from "aws-amplify/storage";
import { DynamoDBClient } from "@aws-sdk/client-dynamodb";
import { DynamoDBDocumentClient } from "@aws-sdk/lib-dynamodb";

let configured = false;

const region = process.env.NEXT_PUBLIC_AWS_REGION || "ap-southeast-1";
const userPoolId = process.env.NEXT_PUBLIC_COGNITO_USER_POOL_ID || "";
const userPoolClientId = process.env.NEXT_PUBLIC_COGNITO_USER_POOL_CLIENT_ID || "";
const identityPoolId = process.env.NEXT_PUBLIC_COGNITO_IDENTITY_POOL_ID || "";
const domain = process.env.NEXT_PUBLIC_COGNITO_DOMAIN || "";
const bucketName = process.env.NEXT_PUBLIC_USERDATA_BUCKET || "";

function currentOrigin() {
  if (typeof window === "undefined") return "http://localhost:3000";
  return window.location.origin;
}

export function configureAmplify() {
  if (configured || !userPoolId || !userPoolClientId || !identityPoolId) return;

  const redirectBase = currentOrigin();
  Amplify.configure({
    Auth: {
      Cognito: {
        userPoolId,
        userPoolClientId,
        identityPoolId,
        loginWith: {
          email: true,
          ...(domain
            ? { oauth: {
                domain,
                scopes: ["openid", "email", "profile"],
                redirectSignIn: [`${redirectBase}/sso-callback`],
                redirectSignOut: [`${redirectBase}/login`],
                responseType: "code",
              } }
            : {}),
        },
      },
    },
    ...(bucketName
      ? { Storage: {
          S3: {
            bucket: bucketName,
            region,
          },
        } }
      : {}),
  });
  configured = true;
}

export async function requireCurrentUser() {
  configureAmplify();
  return getCurrentUser();
}

export async function getIdentityId(): Promise<string> {
  configureAmplify();
  const session = await fetchAuthSession();
  if (!session.identityId) {
    throw new Error("Cognito Identity Pool did not return an identityId.");
  }
  return session.identityId;
}

export async function getAccessToken(): Promise<string | null> {
  configureAmplify();
  try {
    const session = await fetchAuthSession();
    return session.tokens?.accessToken?.toString() ?? null;
  } catch {
    return null;
  }
}

export async function authHeaders(): Promise<Record<string, string>> {
  const token = await getAccessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function getDynamoDoc() {
  configureAmplify();
  const session = await fetchAuthSession();
  if (!session.credentials) {
    throw new Error("Cognito Identity Pool did not return AWS credentials.");
  }
  return DynamoDBDocumentClient.from(
    new DynamoDBClient({
      region,
      credentials: session.credentials,
    }),
  );
}

export function chatsTableName() {
  const table = process.env.NEXT_PUBLIC_CHATS_TABLE;
  if (!table) throw new Error("NEXT_PUBLIC_CHATS_TABLE is not configured.");
  return table;
}

export function userdataBucket() {
  if (!bucketName) throw new Error("NEXT_PUBLIC_USERDATA_BUCKET is not configured.");
  return { bucketName, region };
}

export function storageKey(identityId: string, cid: string, name: string) {
  return `private/${identityId}/conversations/${cid}/${name}`;
}

export function markS3Key(key: string) {
  return `s3key:${key}`;
}

export function unmarkS3Key(value: string | null | undefined) {
  return value?.startsWith("s3key:") ? value.slice("s3key:".length) : null;
}

export async function putStorageObject(path: string, data: Blob | string, contentType?: string) {
  configureAmplify();
  await uploadData({
    path,
    data,
    options: {
      bucket: userdataBucket(),
      contentType,
    },
  }).result;
}

export async function getSignedStorageUrl(path: string) {
  configureAmplify();
  const signed = await getUrl({
    path,
    options: {
      bucket: userdataBucket(),
      expiresIn: 900,
    },
  });
  // Fragments are never sent to S3. Keeping the source key there lets the persistence layer
  // turn a rendered URL back into a durable s3key: value during a later light-save.
  return `${signed.url.toString()}#s3key=${encodeURIComponent(path)}`;
}

export async function getStorageText(path: string) {
  configureAmplify();
  const result = await downloadData({
    path,
    options: { bucket: userdataBucket() },
  }).result;
  return result.body.text();
}

export async function removeStorageObject(path: string) {
  configureAmplify();
  await remove({ path, options: { bucket: userdataBucket() } });
}
