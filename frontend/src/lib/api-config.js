// Only the public API origin belongs in REACT_APP_ variables, never secrets.
export function resolveApiConfig(raw, production = false) {
  const value = typeof raw === "string" ? raw.trim().replace(/\/+$/, "") : "";
  if (!value) {
    return { baseURL: null, error: "The backend address has not been configured yet." };
  }
  try {
    const url = new URL(value);
    const isLocal = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
    if (url.protocol !== "https:" && !(url.protocol === "http:" && isLocal && !production)) {
      throw new Error("Invalid protocol");
    }
    if (url.username || url.password || url.search || url.hash || !["", "/"].includes(url.pathname)) {
      throw new Error("Use an origin without paths or credentials");
    }
    return { baseURL: `${url.origin}/api`, error: null };
  } catch {
    return { baseURL: null, error: "The backend address must be an HTTPS origin without /api, a query, or credentials." };
  }
}
