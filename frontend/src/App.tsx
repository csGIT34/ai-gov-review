import { useEffect, useState } from "react";
import { Link, Route, Routes } from "react-router-dom";
import { DEV_USERS, getDevUser, setDevUser, api, Me } from "./api";
import Dashboard from "./pages/Dashboard";
import NewReview from "./pages/NewReview";
import ReviewDetail from "./pages/ReviewDetail";
import Admin from "./pages/Admin";

export default function App() {
  const [me, setMe] = useState<Me | null>(null);
  useEffect(() => {
    api.get<Me>("/me").then(setMe).catch(() => setMe(null));
  }, []);
  const isAdmin = !!me?.roles.includes("admin");

  return (
    <>
      <header className="topbar">
        <span className="brand">🛡 AI Governance Review</span>
        <nav>
          <Link to="/">Dashboard</Link>
          <Link to="/new">New Review</Link>
          {isAdmin && <Link to="/admin">Admin</Link>}
        </nav>
        <span className="spacer" />
        <div className="whoami">
          <span>acting as</span>
          <select
            value={getDevUser()}
            onChange={(e) => {
              setDevUser(e.target.value);
              window.location.reload();
            }}
          >
            {DEV_USERS.map((u) => (
              <option key={u.email} value={u.email}>{u.label}</option>
            ))}
          </select>
          {me && <span>· {me.roles.join(", ")}</span>}
        </div>
      </header>
      <div className="container">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/new" element={<NewReview />} />
          <Route path="/reviews/:id" element={<ReviewDetail />} />
          <Route path="/admin" element={<Admin isAdmin={isAdmin} />} />
        </Routes>
      </div>
    </>
  );
}
