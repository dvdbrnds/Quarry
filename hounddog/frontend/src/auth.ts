import { OktaAuth } from "@okta/okta-auth-js";

export interface AuthUser {
  sub: string;
  email: string;
  role: string;
  groups: string[];
}

// ── Global 401 interceptor ──────────────────────────────────────────
// Wraps window.fetch so any API call that gets a 401 will silently
// attempt a token refresh + retry.  If that also fails the user is
// redirected to the Okta login page automatically.
let _redirectingToLogin = false;
const _originalFetch = window.fetch.bind(window);

window.fetch = async function patchedFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const res = await _originalFetch(input, init);

  // Only intercept 401s on our own authenticated API routes
  const url = typeof input === "string" ? input : input instanceof URL ? input.href : (input as Request).url;
  if (res.status !== 401 || !url.includes("/api/")) return res;
  if (url.includes("/api/auth/config/public")) return res;
  if (_redirectingToLogin || !oktaAuth) return res;

  // Try a silent token renewal
  try {
    await oktaAuth.tokenManager.renew("accessToken");
    const newToken = await getAccessToken();
    if (newToken) {
      const retryHeaders = new Headers(init?.headers);
      retryHeaders.set("Authorization", `Bearer ${newToken}`);
      const retryRes = await _originalFetch(input, { ...init, headers: retryHeaders });
      if (retryRes.status !== 401) return retryRes;
    }
  } catch { /* renewal failed */ }

  // Token is truly expired — redirect to login
  _redirectingToLogin = true;
  sessionStorage.setItem("quarry_return_path", window.location.pathname);
  login().catch(() => { window.location.href = "/"; });
  return res;
} as typeof window.fetch;

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
    tokenManager: { autoRenew: true, expireEarlySeconds: 120 },
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
  let accessToken = await tokenManager.get("accessToken");

  // If the token is expired or about to expire, try to renew it silently
  if (accessToken && oktaAuth.tokenManager.hasExpired(accessToken)) {
    try {
      accessToken = await tokenManager.renew("accessToken");
    } catch {
      // Renewal failed — token is dead
      return null;
    }
  }

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

export async function authHeadersAs(impersonateEmail?: string | null): Promise<Record<string, string>> {
  const headers = await authHeaders();
  if (impersonateEmail) {
    headers["X-Impersonate"] = impersonateEmail;
  }
  return headers;
}

export function getImpersonateEmail(): string | null {
  const params = new URLSearchParams(window.location.search);
  return params.get("impersonate");
}

export async function fetchCurrentUser(): Promise<AuthUser | null> {
  const token = await getAccessToken();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch("/api/auth/me", { headers });
  if (!res.ok) return null;
  return res.json();
}

export function isOfficeRole(role?: string | null): boolean {
  return role === "admin" || role === "operator";
}

export function isAdminRole(role?: string | null): boolean {
  return role === "admin";
}
