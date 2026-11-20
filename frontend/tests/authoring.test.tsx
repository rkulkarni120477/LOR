import { afterEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { ThemeProvider, createTheme } from "@mui/material";
import Create from "@/views/Create";
import Editor from "@/views/Editor";
import { FilePreview } from "@/components/FilePreview";
import { AssessmentPlayer } from "@/components/AssessmentPlayer";
import { apiFetch, postJson } from "@/lib/api";
vi.mock("@/lib/auth", () => ({
  can: () => true,
  loadSession: () => ({ subject: "author", roles: ["Content Creator"] }),
}));
vi.mock("@/components/AiAssistPanel", () => ({ AiAssistPanel: () => null }));
vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
  postJson: vi.fn(),
  putJson: vi.fn(),
}));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  localStorage.clear();
});
function wrap(child: React.ReactNode, path = "/") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <ThemeProvider theme={createTheme()}>
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[path]}>{child}</MemoryRouter>
      </QueryClientProvider>
    </ThemeProvider>,
  );
}
describe("complete authoring workflows", () => {
  it("offers real creation routes separate from upload", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ items: [] });
    wrap(<Create />);
    expect(
      screen
        .getByRole("link", { name: "Create document" })
        .getAttribute("href"),
    ).toBe("/library/new/rich_text");
    expect(
      screen.getByRole("link", { name: "Create quiz" }).getAttribute("href"),
    ).toBe("/library/new/quiz");
    expect(
      screen
        .getByRole("link", { name: "Upload existing content" })
        .getAttribute("href"),
    ).toBe("/contribute");
    await screen.findByText(/No shared templates/);
  });
  it("sanitizes source HTML before returning to the visual editor", async () => {
    wrap(
      <Routes>
        <Route path="/library/new/:kind" element={<Editor />} />
      </Routes>,
      "/library/new/rich_text",
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "HTML source" }));
    fireEvent.change(screen.getByRole("textbox", { name: "HTML source" }), {
      target: { value: '<h2>Example</h2><img src="x" onerror="alert(1)">' },
    });
    await user.click(screen.getByRole("button", { name: "Visual editor" }));
    const editor = screen.getByRole("textbox", { name: "Content" });
    expect(editor.innerHTML).toContain("Example");
    expect(editor.innerHTML).not.toContain("onerror");
    expect(postJson).not.toHaveBeenCalled();
  });
  it("renders isolated interactive previews without granting same-origin access", async () => {
    vi.mocked(postJson).mockResolvedValue({
      url: "/api/preview/scoped",
      mode: "package",
      filename: "course.zip",
    });
    const { container } = wrap(<FilePreview id="course" />);
    await screen.findByTitle("Preview: course.zip");
    expect(container.querySelector("iframe")?.getAttribute("sandbox")).toBe(
      "allow-scripts",
    );
    expect(postJson).toHaveBeenCalledWith(
      "/v1/library/course/preview-session",
      {},
    );
  });
  it("submits only learner answers and displays the server-calculated score", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ items: [] });
    vi.mocked(postJson).mockResolvedValue({ score: 100, passed: true });
    wrap(
      <AssessmentPlayer
        item={{
          id: "quiz",
          title: "Quiz",
          kind: "quiz",
          revision: 2,
          questions: [
            {
              prompt: "2+2?",
              type: "single_choice",
              options: ["3", "4"],
              points: 1,
            },
          ],
        }}
      />,
    );
    await userEvent.click(screen.getByRole("radio", { name: "4" }));
    await userEvent.click(
      screen.getByRole("button", { name: "Submit answers" }),
    );
    await waitFor(() =>
      expect(postJson).toHaveBeenCalledWith("/v1/library/quiz/attempts", {
        revision: 2,
        answers: [1],
      }),
    );
    expect(await screen.findByText(/Score: 100%/)).toBeTruthy();
  });
});
