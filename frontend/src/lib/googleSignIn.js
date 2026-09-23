import api from "@/lib/api";

// The backend only redeems the one-time login code for the tab that started
// the sign-in, proven by this random key. sessionStorage survives the round
// trip to Google in the same tab and is never sent anywhere else.
const BROWSER_KEY = "xoba_google_browser_key";

export async function startGoogleSignIn(mode = "signin", inviteCode = "") {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  const key = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  sessionStorage.setItem(BROWSER_KEY, key);
  const { data } = await api.post("/auth/google/start", {
    browser_key: key,
    mode,
    invite_code: inviteCode || null,
  });
  window.location.assign(data.auth_url);
}

export function takeGoogleBrowserKey() {
  const key = sessionStorage.getItem(BROWSER_KEY);
  sessionStorage.removeItem(BROWSER_KEY);
  return key;
}

export async function googleSignInConfigured() {
  try {
    const { data } = await api.get("/auth/google/status");
    return Boolean(data?.configured);
  } catch {
    return false;
  }
}

export function isGoogleLanding() {
  return window.location.pathname === "/auth/google" && window.location.hash.includes("code=");
}

const REASONS = {
  access_denied: "Google sign-in was cancelled.",
  password_account_exists:
    "An account with this email already uses a password. Sign in with your password, then choose “Connect Google sign-in” from your account menu.",
  google_account_used_by_another_user: "This Google account is already connected to a different XobaMetrics account.",
  different_google_account_already_linked: "Your account is already connected to a different Google account.",
  google_email_not_verified: "Google has not verified this account's email address.",
  sign_in_expired_or_already_used: "That sign-in link expired or was already used. Please try again.",
  invite_required:
    "XobaMetrics is invite-only for now. Choose \u201cCreate an account\u201d, enter your invite code, then continue with Google.",
};

export function googleErrorMessage(reason) {
  return REASONS[reason] || "Google sign-in could not be completed. Please try again.";
}
