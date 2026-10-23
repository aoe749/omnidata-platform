import { NavLink, Navigate, Outlet, useLocation } from "react-router-dom";

import { useAuthStore } from "../store/auth";
import type { ResourceName } from "../types";

const NAV: { to: string; label: string; resource: ResourceName; end?: boolean }[] = [
  { to: "/", label: "Overview", resource: "metrics", end: true },
  { to: "/transactions", label: "Transactions", resource: "transactions" },
  { to: "/queue", label: "Work queue", resource: "sync" },
  { to: "/runs", label: "Migration runs", resource: "sync" },
];

/** Guards child routes: unauthenticated visitors are sent to /login. */
export function RequireAuth() {
  const token = useAuthStore((s) => s.token);
  const location = useLocation();
  return token ? <AppLayout /> : <Navigate to="/login" replace state={{ from: location.pathname }} />;
}

function AppLayout() {
  const profile = useAuthStore((s) => s.profile);
  const logout = useAuthStore((s) => s.logout);
  const can = useAuthStore((s) => s.can);

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">◈</span> OmniData
        </div>
        <nav aria-label="Main">
          {NAV.filter((item) => can(item.resource, "read")).map((item) => (
            <NavLink key={item.to} to={item.to} end={item.end}>
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <div className="content">
        <header className="topbar">
          <span className="muted">Analytics &amp; Sync Platform</span>
          <div className="user">
            <span>
              {profile?.full_name} <span className="badge badge-role">{profile?.role}</span>
            </span>
            <button type="button" className="btn btn-ghost" onClick={logout}>
              Sign out
            </button>
          </div>
        </header>
        <main>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
