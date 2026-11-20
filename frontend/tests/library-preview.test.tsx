import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { LibraryPreview, type Preview } from "@/components/LibraryPreview";

describe("LibraryPreview", () => {
  it("renders server-sanitized rich text as HTML", () => {
    const item: Preview = {
      id: "1",
      title: "Notes",
      kind: "rich_text",
      revision: 2,
      html: "<h2>Cells</h2><p>Membrane</p>",
    };
    const { container } = render(<LibraryPreview item={item} />);
    expect(container.querySelector("h2")?.textContent).toBe("Cells");
    expect(screen.getByTestId("rich-text-preview").textContent).toContain("Membrane");
  });

  it("hides the answer key when the server withholds it", () => {
    const item: Preview = {
      id: "2",
      title: "Quiz",
      kind: "quiz",
      revision: 1,
      passing_score: 70,
      total_points: 2,
      answers_visible: false,
      questions: [{ prompt: "2+2?", type: "single_choice", options: ["3", "4"], points: 2 }],
    };
    render(<LibraryPreview item={item} />);
    expect(screen.getByText(/Answer key is shown to the content owner/)).toBeTruthy();
    expect(screen.queryByText("✓")).toBeNull();
  });

  it("marks the correct option for owners", () => {
    const item: Preview = {
      id: "3",
      title: "Quiz",
      kind: "assessment",
      revision: 1,
      passing_score: 70,
      total_points: 2,
      answers_visible: true,
      questions: [{ prompt: "2+2?", type: "single_choice", options: ["3", "4"], points: 2, correct: 1 }],
    };
    render(<LibraryPreview item={item} />);
    expect(screen.getByText("✓")).toBeTruthy();
  });
});
