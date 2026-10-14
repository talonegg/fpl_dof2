import { Navigate } from "react-router-dom";

/** `/history` was its own tab; it is now the History section of `/models`. Old links still land. */
export function HistoryRoute() {
  return <Navigate to="/models?section=history" replace />;
}
