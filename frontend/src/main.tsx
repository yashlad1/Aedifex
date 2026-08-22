import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Link, Route, Routes } from "react-router-dom";
import { BrowserRouter } from "react-router-dom";

import { DocumentPage } from "./pages/DocumentPage";
import { FindingPage } from "./pages/FindingPage";
import { ProjectList } from "./pages/ProjectList";
import { ProjectPage } from "./pages/ProjectPage";
import "./styles.css";

/**
 * Four routes, one per surface that has a place: the project list, one project, one finding, one
 * document. The banner is not decoration — this build has no authentication, and anyone who opens it
 * should be able to see that from the screen rather than from a document.
 */
function App() {
  return (
    <>
      <header className="app">
        <Link to="/">Aedifex</Link>
        <span className="small">review workspace</span>
        <span className="warn">LOCAL / INTERNAL ONLY — NO AUTHENTICATION, NO TENANT ISOLATION</span>
      </header>
      <main className="wide">
        <Routes>
          <Route path="/" element={<ProjectList />} />
          <Route path="/projects/:projectId" element={<ProjectPage />} />
          <Route path="/projects/:projectId/findings/:findingId" element={<FindingPage />} />
          <Route path="/projects/:projectId/documents/:documentId" element={<DocumentPage />} />
        </Routes>
      </main>
    </>
  );
}

const root = document.getElementById("root");
if (root === null) throw new Error("no #root element");
createRoot(root).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
