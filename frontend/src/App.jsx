import { BrowserRouter, Navigate, Outlet, Route, Routes, Link, useLocation, useNavigate } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth";
import "./App.css";
import LogoMark from "./components/LogoMark";
import LoginView from "./views/LoginView";
import DriverHome from "./views/DriverHome";
import DispatchBoard from "./views/DispatchBoard";
import ExplorePlanner from "./views/ExplorePlanner";
import SafetyView from "./views/SafetyView";
import AdminConsole from "./views/AdminConsole";

function RequireAuth() {
  const { user } = useAuth();
  if (!user) return <Navigate to="/login" replace />;
  if (user.role === "Dispatcher" || user.role === "Admin") return <Navigate to="/dispatch" replace />;
  if (user.role === "Auditor") return <Navigate to="/safety" replace />;
  return <DriverHome />;
}

function RequireDispatcher() {
  const { user } = useAuth();
  if (!user) return <Navigate to="/login" replace />;
  if (user.role !== "Dispatcher" && user.role !== "Admin") return <Navigate to="/" replace />;
  return <DispatchBoard />;
}

function RequireAuditor() {
  const { user } = useAuth();
  if (!user) return <Navigate to="/login" replace />;
  if (user.role !== "Auditor") return <Navigate to="/" replace />;
  return <SafetyView />;
}

function RequireAdmin() {
  const { user } = useAuth();
  if (!user) return <Navigate to="/login" replace />;
  if (user.role !== "Admin") return <Navigate to="/dispatch" replace />;
  return <AdminConsole />;
}

function Shell() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const loc = useLocation();

  if (!user) return <Navigate to="/login" replace />;

  const isBoard = ["/", "/dispatch", "/admin"].includes(loc.pathname);
  const isAdmin = user.role === "Admin";

  function signOut() {
    logout();
    navigate("/login", { replace: true });
  }

  return (
    <div className="app">
      <header className="topbar">
        {isBoard && (
          <button className="menu-btn" onClick={() => window.dispatchEvent(new Event("spotter:toggle-nav"))} aria-label="Toggle menu">
            <span />
          </button>
        )}
        <div className="topbar-brand">
          <LogoMark />
        </div>
        <span className="topbar-label">
          {user.role === "Dispatcher" && "Dispatch board"}
          {user.role === "Admin" && "Admin"}
          {user.role === "Auditor" && "Safety & compliance"}
          {user.role === "Driver" && "Cab"}
        </span>
        <div className="topbar-right">
          {user.role === "Dispatcher" && (
            <Link className={`topbar-link ${loc.pathname === "/dispatch" ? "topbar-link--active" : ""}`} to="/dispatch">Board</Link>
          )}
          {isAdmin && (
            <>
              <Link className={`topbar-link ${loc.pathname === "/dispatch" ? "topbar-link--active" : ""}`} to="/dispatch">Board</Link>
              <Link className={`topbar-link ${loc.pathname === "/admin" ? "topbar-link--active" : ""}`} to="/admin">Admin</Link>
            </>
          )}
          {user.role === "Auditor" && (
            <Link className={`topbar-link ${loc.pathname === "/safety" ? "topbar-link--active" : ""}`} to="/safety">Safety</Link>
          )}
          {user.role === "Driver" && (
            <Link className={`topbar-link ${loc.pathname === "/" ? "topbar-link--active" : ""}` } to="/">Home</Link>
          )}
          <span className="topbar-user num">{user.first_name || user.username}</span>
          <button className="btn-mini" onClick={signOut}>Sign out</button>
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
            <Route path="/safety" element={<RequireAuditor />} />
            <Route path="/admin" element={<RequireAdmin />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}