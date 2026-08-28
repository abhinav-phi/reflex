import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { ApiError, getToken, isTokenExpired, clearToken } from "./lib/api";
import Dashboard from "./pages/Dashboard";
import Login from "./pages/Login";
import Landing from "./pages/Landing";
import Approvals from "./pages/Approvals";
import Results from "./pages/Results";
import Audit from "./pages/Audit";
import Ops from "./pages/Ops";
import Onboarding from "./pages/Onboarding";

const qc = new QueryClient({
  defaultOptions: {
    queries: {
      // Never multiply a throttled burst: retry only 5xx/transport errors,
      // not 4xx (401/403/429 already tell the user what to do).
      retry: (failureCount, error) => {
        if (error instanceof ApiError) return error.status >= 500 && failureCount < 2;
        return failureCount < 1; // transport-level failure (NetworkError/TypeError)
      },
      refetchOnWindowFocus: false,
      staleTime: 5_000,
    },
  },
});

function Protected({ children }: { children: React.ReactNode }) {
  // Gate on both presence and JWT exp — a stale token must not keep a broken
  // session alive; drop it and send the user back to login.
  if (!getToken() || isTokenExpired()) {
    if (isTokenExpired()) clearToken();
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Landing />} />
          <Route path="/login" element={<Login />} />
          <Route path="/onboarding" element={<Protected><Onboarding /></Protected>} />
          <Route path="/dashboard" element={<Protected><Dashboard /></Protected>} />
          <Route path="/approvals" element={<Protected><Approvals /></Protected>} />
          <Route path="/results" element={<Protected><Results /></Protected>} />
          <Route path="/audit" element={<Protected><Audit /></Protected>} />
          <Route path="/ops" element={<Protected><Ops /></Protected>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
