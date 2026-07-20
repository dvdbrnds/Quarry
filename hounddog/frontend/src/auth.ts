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
  campus_lat: number;
  campus_lng: number;
  public_map_requires_auth: boolean;
  school_name: string;
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
  // Record logout in audit trail before clearing tokens
  try {
    const headers = await authHeaders();
    await fetch("/api/auth/logout", { method: "POST", headers });
  } catch {}

  if (!oktaAuth) {
    window.location.href = "/";
    return;
  }

  // Grab ID token before clearing — needed for Okta's logout endpoint
  let idToken: string | undefined;
  try {
    const tok = await oktaAuth.tokenManager.get("idToken");
    idToken = (tok as { idToken: string })?.idToken;
  } catch {}

  try { await oktaAuth.revokeAccessToken(); } catch {}
  try { await oktaAuth.revokeRefreshToken(); } catch {}
  await oktaAuth.tokenManager.clear();

  // Redirect to Okta's logout endpoint to kill the SSO session,
  // then Okta redirects back to our post-logout URI.
  const config = await loadConfig();
  const logoutUrl = new URL(`https://${config.okta_domain}/oauth2/default/v1/logout`);
  logoutUrl.searchParams.set("post_logout_redirect_uri", window.location.origin);
  if (idToken) logoutUrl.searchParams.set("id_token_hint", idToken);
  logoutUrl.searchParams.set("client_id", config.okta_client_id);
  window.location.href = logoutUrl.toString();
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

export async function authHeaders(): Promise<Record<string, string>> {
  const token = await getAccessToken();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  return headers;
}

export async function fetchCurrentUser(): Promise<AuthUser | null> {
  const token = await getAccessToken();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch("/api/auth/me", { headers });
  if (!res.ok) return null;
  return res.json();
}
