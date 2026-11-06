// Regression tests: the Human Review editor must stay in sync with the filtered example list.
// Bug: after a review action (or a filter change) left the list empty, the page showed
// "No pending examples" while still rendering the previous example's editor, so further
// actions silently applied to an example that was no longer in the list.
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import App from "../App";
import type { Example } from "../api/types";
import { categories, dataset, example, health, mockFetch, page } from "./mockApi";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

/** A tiny in-memory backend that applies review actions and honours status/search filters. */
function reviewBackend(initial: Example[]) {
  const store = new Map(initial.map((e) => [e.id, { ...e }]));
  const statusFor: Record<string, Example["review_status"]> = { approve: "approved", reject: "rejected", flag: "flagged", reset: "pending" };
  const calls = mockFetch({
    "GET /health": () => health,
    "GET /api/v1/categories": () => categories,
    "GET /api/v1/datasets": () => page([dataset]),
    [`GET /api/v1/datasets/${dataset.id}/examples`]: (url) => {
      const status = url.searchParams.get("status");
      const search = (url.searchParams.get("search") ?? "").toLowerCase();
      return page(
        [...store.values()].filter(
          (e) => (!status || e.review_status === status) && (!search || e.input.toLowerCase().includes(search)),
        ),
      );
    },
    "GET /api/v1/examples/[^/]+": (url) => store.get(url.pathname.split("/").pop()!),
    "POST /api/v1/examples/[^/]+/review": (url, init) => {
      const id = url.pathname.split("/")[4];
      const body = JSON.parse(String(init?.body)) as { action: string };
      const updated = { ...store.get(id)!, review_status: statusFor[body.action] };
      store.set(id, updated);
      return updated;
    },
  });
  return { store, calls };
}

const ex1: Example = { ...example, id: "ex1", source_trace_key: "tr_00027", input: "How do I connect a custom domain?" };
const ex2: Example = { ...example, id: "ex2", source_trace_key: "tr_00170", input: "Why is my invoice wrong?" };

const reviewActions = (calls: ReturnType<typeof mockFetch>) =>
  calls.filter((c) => c.method === "POST" && c.url.pathname.endsWith("/review")).map((c) => c.url.pathname.split("/")[4]);

describe("human review list/editor synchronisation", () => {
  it("clears the editor when approving the last example in the filtered list", async () => {
    const { store, calls } = reviewBackend([ex1]);
    renderAt(`/review?dataset=${dataset.id}`);

    await userEvent.click(await screen.findByRole("button", { name: /Approve/ }));

    expect(await screen.findByText("No pending examples")).toBeInTheDocument();
    // The stale editor (and its action buttons) must be gone, so no further action can hit ex1 unseen.
    await waitFor(() => expect(screen.queryByRole("button", { name: /Approve/ })).not.toBeInTheDocument());
    // The reviewer still gets confirmation of what happened to which example.
    expect(screen.getByTestId("review-notice")).toHaveTextContent("Approved tr_00027");
    expect(store.get("ex1")!.review_status).toBe("approved");
    expect(reviewActions(calls)).toEqual(["ex1"]);
  });

  it("clears the editor when a search filter matches nothing", async () => {
    reviewBackend([ex1, ex2]);
    renderAt(`/review?dataset=${dataset.id}`);
    expect(await screen.findByRole("button", { name: /Approve/ })).toBeInTheDocument();

    const search = screen.getByLabelText("Search examples");
    await userEvent.type(search, "no-such-text{Enter}");

    expect(await screen.findByText("No pending examples")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("button", { name: /Approve/ })).not.toBeInTheDocument());
  });

  it("moves to the next pending example after a review and confirms the previous one", async () => {
    const { calls } = reviewBackend([ex1, ex2]);
    renderAt(`/review?dataset=${dataset.id}`);
    expect(await screen.findByText("tr_00027")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Reject/ }));

    expect(await screen.findByText("tr_00170")).toBeInTheDocument();
    expect(screen.getByTestId("review-notice")).toHaveTextContent("Rejected tr_00027");
    await userEvent.click(screen.getByRole("button", { name: /Flag uncertain/ }));
    await waitFor(() => expect(reviewActions(calls)).toEqual(["ex1", "ex2"]));
    expect(await screen.findByText("No pending examples")).toBeInTheDocument();
    expect(screen.getByTestId("review-notice")).toHaveTextContent("Flagged as uncertain tr_00170");
  });
});
