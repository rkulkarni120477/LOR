"use client";

import { useState, useSyncExternalStore } from "react";
import { BrowserRouter, Route, Routes, Link } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Alert, ThemeProvider, createTheme } from "@mui/material";
import { ApiError } from "@/lib/api";
import { readStoredToken, subscribeToSession } from "@/lib/auth";
import { Nav } from "@/components/Nav";
import Home from "@/views/Home";
import Search from "@/views/Search";
import Login from "@/views/Login";
import Contribute from "@/views/Contribute";
import Review from "@/views/Review";
import Reports from "@/views/Reports";
import ObjectDetail from "@/views/ObjectDetail";
import Collections from "@/views/Collections";
import Favorites from "@/views/Favorites";
import Versioning from "@/views/Versioning";
import { SessionBootstrap } from "@/components/SessionBootstrap";
import Administration from "@/views/Administration";
import Library from "@/views/Library";
import SchemaPage from "@/views/Schema";
import IntegrationsPage from "@/views/Integrations";
import TaxonomyPage from "@/views/Taxonomy";
import Editor from "@/views/Editor";
import Create from "@/views/Create";
import FileEditor from "@/views/FileEditor";

const theme = createTheme({
  palette: { primary: { main: "#1762c4" }, background: { default: "#f5f7fb" } },
  typography: { fontFamily: "Arial, Helvetica, sans-serif", fontSize: 14 },
  shape: { borderRadius: 10 },
});
const subscribe = () => () => {};

function SessionQueries() {
  const token = useSyncExternalStore(
    subscribeToSession,
    readStoredToken,
    () => null,
  );
  // A fresh cache per identity prevents data from a previous session appearing after sign-out.
  return <QuerySession key={token || "anonymous"} />;
}

function QuerySession() {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 15_000,
            retry: (count, error) =>
              !(error instanceof ApiError && error.status < 500) && count < 1,
          },
          mutations: { retry: false },
        },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <Nav>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/search" element={<Search />} />
          <Route path="/login" element={<Login />} />
          <Route path="/contribute" element={<Contribute />} />
          <Route path="/create" element={<Create />} />
          <Route path="/review" element={<Review />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="/objects" element={<ObjectDetail />} />
          <Route path="/collections" element={<Collections />} />
          <Route path="/favorites" element={<Favorites />} />
          <Route path="/versioning" element={<Versioning />} />
          <Route path="/administration" element={<Administration />} />
          <Route path="/library" element={<Library />} />
          <Route path="/schema" element={<SchemaPage />} />
          <Route path="/integrations" element={<IntegrationsPage />} />
          <Route path="/taxonomy" element={<TaxonomyPage />} />
          <Route path="/library/new/:kind" element={<Editor />} />
          <Route path="/library/:id/edit" element={<Editor />} />
          <Route path="/library/:id/file" element={<FileEditor />} />
          <Route
            path="*"
            element={
              <Alert severity="warning">
                Page not found. <Link to="/">Go home</Link>
              </Alert>
            }
          />
        </Routes>
      </Nav>
    </QueryClientProvider>
  );
}

export function Application() {
  const mounted = useSyncExternalStore(
    subscribe,
    () => true,
    () => false,
  );
  if (!mounted)
    return (
      <main role="status" aria-busy="true" style={{ padding: "2rem" }}>
        Loading application…
      </main>
    );
  return (
    <ThemeProvider theme={theme}>
      <BrowserRouter>
        <SessionBootstrap />
        <SessionQueries />
      </BrowserRouter>
    </ThemeProvider>
  );
}
