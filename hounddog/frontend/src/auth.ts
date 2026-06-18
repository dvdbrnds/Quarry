import { OktaAuth } from "@okta/okta-auth-js";

export interface AuthUser {
  sub: string;
  email: string;
  role: string;
  groups: string[];
}

export interface AppConfig {
  okta_domain: string;
  okta_client_id: string;
  auth_enabled: boolean;
  google_maps_api_key: string;
}

let oktaAuth: OktaAuth | null = null;
let appConfig: AppConfig | null = null;

export async function loadConfig(): Promise<AppConfig> {
  if (appConfig) return appConfig;
  const res = await fetch("/api/auth/config/public");
  appConfig = await res.json();
  return appConfig!;
}

export function getOktaAuth(): OktaAuth | null {
  return oktaAuth;
}

export async function initAuth(): Promise<OktaAuth | null> {
  const config = await loadConfig();
  if (!config.auth_enabled) return null;

  oktaAuth = new OktaAuth({
    issuer: `https://${config.okta_domain}/oauth2/default`,
    clientId: config.okta_client_id,
    redirectUri: `${window.location.origin}/auth/callback`,
    postLogoutRedirectUri: window.location.origin,
    scopes: ["openid", "email", "profile", "groups"],
    pkce: true,
  });

  return oktaAuth;
}

export async function login(): Promise<void> {
  if (!oktaAuth) return;
  await oktaAuth.signInWithRedirect();
}

export async function handleCallback(): Promise<void> {
  if (!oktaAuth) return;
  await oktaAuth.handleLoginRedirect();
}

export async function logout(): Promise<void> {
  if (!oktaAuth) return;
  await oktaAuth.signOut();
}

export async function getAccessToken(): Promise<string | null> {
  if (!oktaAuth) return null;
  const tokenManager = oktaAuth.tokenManager;
  const accessToken = await tokenManager.get("accessToken");
  if (!accessToken) return null;
  return (accessToken as { accessToken: string }).accessToken;
}

export async function isAuthenticated(): Promise<boolean> {
  const config = await loadConfig();
  if (!config.auth_enabled) return true;
  if (!oktaAuth) return false;
  return oktaAuth.isAuthenticated();
}

export async function fetchCurrentUser(): Promise<AuthUser | null> {
  const token = await getAccessToken();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch("/api/auth/me", { headers });
  if (!res.ok) return null;
  return res.json();
}
