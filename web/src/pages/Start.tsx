import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { getResume } from "../api";
import type { ResumeTarget } from "../types";
import Home from "./Home";

export default function Start() {
  const [target, setTarget] = useState<ResumeTarget | null>(null);
  const [settled, setSettled] = useState(false);

  useEffect(() => {
    getResume()
      .then(setTarget)
      .catch(() => undefined)
      .then(() => setSettled(true));
  }, []);

  if (!settled) {
    return <main className="reader">loading…</main>;
  }
  if (target) {
    return (
      <Navigate to={`/read/${target.article_id}`} replace state={{ resumed: true }} />
    );
  }
  return <Home />;
}
