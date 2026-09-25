import { useState } from "react";
import { useAuth } from "../auth/AuthContext";
import { api } from "../api";

type Mode = "login" | "bootstrap" | "forgot" | "reset";

/**
 * The previous version of this screen showed the same generic "Login failed" text
 * for every possible failure -- wrong password, backend not running, CORS blocked,
 * network error, server crash -- which made this impossible to debug from the UI
 * alone. This distinguishes the failure modes that are actually distinguishable
 * from a browser fetch() error, so the message on screen tells you which of those
 * it actually was.
 */
function describeLoginError(err: unknown): string {
  const msg = err instanceof Error ? err.message : String(err);

  // fetch() throws a TypeError with no HTTP status at all when it can't reach the
  // server -- wrong port, backend not running, CORS preflight rejected, etc.
  if (err instanceof TypeError || /Failed to fetch|NetworkError|Load failed/i.test(msg)) {
    return "Could not reach the backend server at all. Is it running? Check the " +
      "terminal where you ran 'uvicorn app.main:app --reload' -- if that window " +
      "shows no incoming request when you click Sign in, this is a connectivity " +
      "problem (wrong VITE_API_URL, backend not started, or a CORS block), not a " +
      "wrong password.";
  }
  if (msg.startsWith("401")) {
    return "Wrong username or password.";
  }
  if (msg.startsWith("403")) {
    return `Server refused the request (403): ${msg}`;
  }
  if (/^5\d\d/.test(msg)) {
    return `Server error (${msg.slice(0, 3)}) -- check the backend terminal for a ` +
      `Python traceback. This is not a credentials problem.`;
  }
  // Fallback: show the raw error rather than hiding it behind a guess.
  return `Login failed: ${msg}`;
}

export function LoginScreen() {
  const { login } = useAuth();
  const [mode, setMode] = useState<Mode>("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [token, setToken] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function resetMessages() {
    setError(null);
    setInfo(null);
  }

  async function handleLogin(e: React.FormEvent) {
    e.preventDefault();
    resetMessages();
    setSubmitting(true);
    try {
      await login(username, password);
    } catch (err) {
      setError(describeLoginError(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleBootstrap(e: React.FormEvent) {
    e.preventDefault();
    resetMessages();
    setSubmitting(true);
    try {
      await api.registerFirstAdmin({ username, full_name: fullName, password });
      await login(username, password);
    } catch (err) {
      const msg = String(err);
      setError(msg.includes("403")
        ? "An admin account already exists. Switch to Log in."
        : msg);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleForgot(e: React.FormEvent) {
    e.preventDefault();
    resetMessages();
    setSubmitting(true);
    try {
      const res = await api.forgotPassword(username);
      setInfo(res.message);
    } catch (err) {
      setError(String(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleReset(e: React.FormEvent) {
    e.preventDefault();
    resetMessages();
    setSubmitting(true);
    try {
      const res = await api.resetPassword(token, newPassword);
      setInfo(`${res.message} Switching to login…`);
      setTimeout(() => { setMode("login"); setInfo(null); }, 1500);
    } catch (err) {
      setError(String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-screen">
      <div className="auth-card">
        <h1>KAVACH RFID Tag/TIN Platform</h1>
        <p className="muted small">
          {mode === "login" && "Sign in to continue."}
          {mode === "bootstrap" && "No account exists yet on this instance — create the first admin account."}
          {mode === "forgot" && "Enter your username. If a reset token was generated, your administrator can find it in the server console."}
          {mode === "reset" && "Paste the reset token your administrator gave you, and choose a new password."}
        </p>

        {mode === "login" && (
          <form onSubmit={handleLogin} className="auth-form">
            <input placeholder="Username" value={username} onChange={(e) => setUsername(e.target.value)} required />
            <input type="password" placeholder="Password" value={password} onChange={(e) => setPassword(e.target.value)} required />
            <button type="submit" disabled={submitting}>{submitting ? "Signing in…" : "Sign in"}</button>
          </form>
        )}

        {mode === "bootstrap" && (
          <form onSubmit={handleBootstrap} className="auth-form">
            <input placeholder="Username" value={username} onChange={(e) => setUsername(e.target.value)} required />
            <input placeholder="Full name" value={fullName} onChange={(e) => setFullName(e.target.value)} required />
            <input type="password" placeholder="Password" value={password} onChange={(e) => setPassword(e.target.value)} required />
            <button type="submit" disabled={submitting}>{submitting ? "Creating…" : "Create admin account"}</button>
          </form>
        )}

        {mode === "forgot" && (
          <form onSubmit={handleForgot} className="auth-form">
            <input placeholder="Username" value={username} onChange={(e) => setUsername(e.target.value)} required />
            <button type="submit" disabled={submitting}>{submitting ? "Requesting…" : "Request reset"}</button>
          </form>
        )}

        {mode === "reset" && (
          <form onSubmit={handleReset} className="auth-form">
            <textarea
              placeholder="Paste reset token here"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              required
              rows={3}
              style={{ fontFamily: "monospace", fontSize: "0.75rem" }}
            />
            <input type="password" placeholder="New password (min 8 characters)" value={newPassword}
                   onChange={(e) => setNewPassword(e.target.value)} required minLength={8} />
            <button type="submit" disabled={submitting}>{submitting ? "Resetting…" : "Reset password"}</button>
          </form>
        )}

        {error && <div className="error">{error}</div>}
        {info && <div className="info">{info}</div>}

        <div className="auth-links">
          {mode !== "login" && (
            <button className="link-btn" onClick={() => { setMode("login"); resetMessages(); }}>
              Back to log in
            </button>
          )}
          {mode === "login" && (
            <>
              <button className="link-btn" onClick={() => { setMode("bootstrap"); resetMessages(); }}>
                First time setting this up? Create the admin account
              </button>
              <button className="link-btn" onClick={() => { setMode("forgot"); resetMessages(); }}>
                Forgot password?
              </button>
            </>
          )}
          {mode === "forgot" && (
            <button className="link-btn" onClick={() => { setMode("reset"); resetMessages(); }}>
              Already have a reset token?
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
