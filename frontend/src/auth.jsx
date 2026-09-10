import { createContext, useContext, useState } from "react";
import { apiJson, clearAuth, storeAuth, storedUser } from "./api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(storedUser);

  async function login(username, password) {
    const { ok, data } = await apiJson("/api/auth/login/", {
      method: "POST",
      body: { username, password },
    });
    if (!ok) {
      const err = data && data.detail
        ? data.detail
        : "Login failed. Check your username and password.";
      throw new Error(err);
    }
    storeAuth(data);
    setUser(data.user);
    return data.user;
  }

  function logout() {
    const refresh = localStorage.getItem("spotter.refresh");
    if (refresh) {
      apiJson("/api/auth/logout/", {
        method: "POST",
        body: { refresh },
      }).catch(() => {});
    }
    clearAuth();
    setUser(null);
  }

  if (!user) return (
    <AuthContext.Provider value={{ user: null, login, logout }}>
      {children}
    </AuthContext.Provider>
  );

  return (
    <AuthContext.Provider value={{ user, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}