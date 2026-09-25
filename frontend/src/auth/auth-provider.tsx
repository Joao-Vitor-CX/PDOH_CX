import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

export type SessionUser = { name: string; email: string; roles: string[] };
type AuthContextValue = { user: SessionUser | null; loading: boolean; signIn: () => void; signOut: () => Promise<void> };

const AuthContext = createContext<AuthContextValue | null>(null);
const sessionUrl = import.meta.env.VITE_CX_PDOH_SESSION_URL as string | undefined;
const loginUrl = import.meta.env.VITE_CX_PDOH_LOGIN_URL as string | undefined;
const logoutUrl = import.meta.env.VITE_CX_PDOH_LOGOUT_URL as string | undefined;
// A sessão local não pode entrar em builds de produção.
const demoEnabled = import.meta.env.DEV && import.meta.env.VITE_CX_PDOH_DEMO_AUTH === 'true';
const localUser: SessionUser = { name: 'Consulta local', email: 'Desenvolvimento · somente leitura', roles: ['consulta'] };

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<SessionUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    async function loadSession() {
      if (sessionUrl) {
        try {
          const response = await fetch(sessionUrl, { credentials: 'include', headers: { Accept: 'application/json' } });
          if (response.ok && active) setUser(await response.json() as SessionUser);
        } catch { /* The login screen remains available when the identity service is offline. */ }
      } else if (demoEnabled && localStorage.getItem('cx-pdoh-demo-session') === 'active') {
        setUser(localUser);
      }
      if (active) setLoading(false);
    }
    void loadSession();
    return () => { active = false; };
  }, []);

  const value = useMemo<AuthContextValue>(() => ({
    user,
    loading,
    signIn: () => {
      if (loginUrl) { window.location.assign(loginUrl); return; }
      if (demoEnabled) { localStorage.setItem('cx-pdoh-demo-session', 'active'); setUser(localUser); }
    },
    signOut: async () => {
      if (demoEnabled) localStorage.removeItem('cx-pdoh-demo-session');
      setUser(null);
      if (logoutUrl) window.location.assign(logoutUrl);
    },
  }), [user, loading]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used within AuthProvider');
  return context;
}
