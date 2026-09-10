// thin fetch wrapper for the spotter API.
// - attaches the JWT from localStorage
// - transparently refreshes once when a call comes back 401
// - single shared refresh promise so a burst of 401s doesn't hammer the
//   refresh endpoint

export const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export const ACCESS_KEY = "spotter.access";
export const REFRESH_KEY = "spotter.refresh";
export const USER_KEY = "spotter.user";

export function storedUser() {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) || "null");
  } catch {
    return null;
  }
}

export function storeAuth({ access, refresh, user }) {
  if (access) localStorage.setItem(ACCESS_KEY, access);
  if (refresh) localStorage.setItem(REFRESH_KEY, refresh);
  if (user) localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearAuth() {
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
  localStorage.removeItem(USER_KEY);
}

let refreshPromise = null;

function tryRefresh() {
  if (refreshPromise) return refreshPromise;
  refreshPromise = (async () => {
    const refresh = localStorage.getItem(REFRESH_KEY);
    if (!refresh) return false;
    const resp = await fetch(`${API_BASE}/api/auth/refresh/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh }),
    });
    if (resp.ok) {
      const data = await resp.json();
      storeAuth({ access: data.access, refresh: data.refresh || refresh });
      return true;
    }
    clearAuth();
    return false;
  })().finally(() => {
    refreshPromise = null;
  });
  return refreshPromise;
}

export async function api(path, { method = "GET", body } = {}) {
  const headers = { "Content-Type": "application/json" };
  const access = localStorage.getItem(ACCESS_KEY);
  if (access) headers.Authorization = `Bearer ${access}`;

  const request = () => fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  let resp = await request();
  if (resp.status === 401 && access && path !== "/api/auth/login/") {
    const refreshed = await tryRefresh();
    if (refreshed) resp = await request();
  }
  return resp;
}

export async function apiJson(path, init) {
  const resp = await api(path, init);
  const ct = resp.headers.get("content-type") || "";
  const data = ct.includes("application/json") ? await resp.json() : null;
  return { ok: resp.ok, status: resp.status, data };
}