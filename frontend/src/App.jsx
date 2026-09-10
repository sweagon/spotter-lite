import { BrowserRouter, Navigate, Outlet, Route, Routes, Link, useNavigate } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth";
import "./App.css";
import LogoMark from "./components/LogoMark";
import LoginView from "./views/LoginView";
import DriverHome from "./views/DriverHome";
import DispatchBoard from "./views/DispatchBoard";
import ExplorePlanner from "./views/ExplorePlanner";

function RequireAuth() {
  const { user } = useAuth();
  if (!user) return <Navigate to="/login" replace />;
  if (user.role === "Dispatcher") return <Navigate to="/dispatch" replace />;
  return <DriverHome />;
}

function RequireDispatcher() {
  const { user } = useAuth();
  if (!user) return <Navigate to="/login" replace />;
  if (user.role !== "Dispatcher") return <Navigate to="/" replace />;
  return <DispatchBoard />;
}

function Shell() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  if (!user) return <Navigate to="/login" replace />;

  function signOut() {
    logout();
    navigate("/login", { replace: true });
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar-brand">
          <LogoMark />
        </div>
        <span className="topbar-label">{user.role === "Dispatcher" ? "dispatch board" : "driver home"}</span>
        <div className="topbar-right">
          {user.role === "Dispatcher" && (
            <Link className="topbar-link" to="/dispatch">board</Link>
          )}
          <Link className="topbar-link" to="/">home</Link>
          <span className="topbar-user num">{user.first_name || user.username}</span>
          <button className="btn-mini" onClick={signOut}>sign out</button>
        </div>
      </header>
      <Outlet />
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/explore" element={<ExplorePlanner />} />
          <Route path="/login" element={<LoginView />} />
          <Route element={<Shell />}>
            <Route path="/" element={<RequireAuth />} />
            <Route path="/dispatch" element={<RequireDispatcher />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}