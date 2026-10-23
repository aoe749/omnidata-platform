import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { useAuthStore } from "../store/auth";

export function LoginPage() {
  const { token, login, loading, error } = useAuthStore();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const from = (location.state as { from?: string } | null)?.from ?? "/";

  if (token) return <Navigate to={from} replace />;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (await login(email, password)) navigate(from, { replace: true });
  };

  return (
    <main className="login">
      <form className="card login-card" onSubmit={submit}>
        <h1>OmniData Console</h1>
        <p className="muted">Sign in to manage cross-database synchronisation.</p>
        <label>
          E-mail
          <input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label>
          Password
          <input
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {error && (
          <p role="alert" className="banner banner-error">
            {error}
          </p>
        )}
        <button type="submit" className="btn btn-primary" disabled={loading}>
          {loading ? "Signing in…" : "Sign in"}
        </button>
        <p className="muted small">
          Demo accounts (<code>admin@</code>, <code>operator@</code>, <code>analyst@</code>, <code>viewer@omnidata.example</code>)
          use the <code>DEMO_PASSWORD</code> from your environment file.
        </p>
      </form>
    </main>
  );
}
