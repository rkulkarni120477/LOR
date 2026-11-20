import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ThemeProvider, createTheme } from "@mui/material";
import { OrganizationWorkspace } from "@/components/OrganizationWorkspace";
import Link from "@/components/Link";
import { apiFetch, postJson } from "@/lib/api";

vi.mock("@/lib/auth", () => ({
  loadSession: () => ({ subject: "author", roles: ["Contributor"] }),
  hasAnyRole: () => true,
}));
vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
  postJson: vi.fn(),
  putJson: vi.fn(),
  apiBlob: vi.fn(),
}));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderWorkspace(mode: "collections" | "favorites") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  vi.mocked(apiFetch).mockImplementation(async (path) => {
    if (path === "/v1/favorites/folders")
      return { items: ["AI in Education", "Leadership"] };
    return { items: [], total: 0 };
  });
  return render(
    <ThemeProvider theme={createTheme()}>
      <MemoryRouter>
        <QueryClientProvider client={client}>
          <OrganizationWorkspace mode={mode} />
        </QueryClientProvider>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

describe("requested frontend stack", () => {
  it("navigates through React Router without a document reload", async () => {
    render(
      <MemoryRouter>
        <Routes>
          <Route
            path="/"
            element={<Link href="/favorites">Open favorites</Link>}
          />
          <Route path="/favorites" element={<h1>Personal favorites</h1>} />
        </Routes>
      </MemoryRouter>,
    );
    await userEvent.click(screen.getByRole("link", { name: "Open favorites" }));
    expect(
      screen.getByRole("heading", { name: "Personal favorites" }),
    ).toBeTruthy();
  });

  it("validates and persists the MUI collection form, then refetches queries", async () => {
    renderWorkspace("collections");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Create collection" }));
    expect(await screen.findByText("Name is required")).toBeTruthy();
    expect(postJson).not.toHaveBeenCalled();
    await user.type(
      screen.getByRole("textbox", { name: "Collection name" }),
      "Leadership skills",
    );
    await user.type(
      screen.getByRole("textbox", { name: "Description" }),
      "Manager onboarding",
    );
    vi.mocked(postJson).mockResolvedValueOnce({ id: "new" });
    await user.click(screen.getByRole("button", { name: "Create collection" }));
    await waitFor(() =>
      expect(postJson).toHaveBeenCalledWith("/v1/collections", {
        name: "Leadership skills",
        description: "Manager onboarding",
        visibility: "private",
      }),
    );
    expect(await screen.findByText("Changes saved.")).toBeTruthy();
    expect(
      vi
        .mocked(apiFetch)
        .mock.calls.filter(([path]) => path === "/v1/collections?page=1")
        .length,
    ).toBeGreaterThan(1);
  });

  it("displays query failures with an accessible MUI alert", async () => {
    renderWorkspace("favorites");
    vi.mocked(apiFetch).mockRejectedValue(
      new Error("Repository temporarily unavailable"),
    );
    // Switching folders triggers a new query rather than serving another folder's cache.
    await userEvent.click(screen.getByRole("combobox", { name: "Folder" }));
    await userEvent.click(
      await screen.findByRole("option", { name: "Leadership" }),
    );
    expect(await screen.findByRole("alert")).toHaveProperty(
      "textContent",
      "Repository temporarily unavailable",
    );
  });
});
