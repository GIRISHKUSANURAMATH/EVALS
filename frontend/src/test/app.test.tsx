import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import App from "../App";
import { categories, dataset, emptyMetrics, example, health, metrics, mockFetch, page } from "./mockApi";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

const base = {
  "GET /health": () => health,
  "GET /api/v1/categories": () => categories,
  "GET /api/v1/datasets": () => page([dataset]),
};

describe("navigation", () => {
  it("renders every sidebar section and navigates", async () => {
    mockFetch({ ...base, "GET /api/v1/dashboard/metrics": () => metrics, "GET /api/v1/ingestion/samples": () => [] });
    renderAt("/");
    const nav = screen.getByRole("navigation", { name: "Main navigation" });
    for (const label of ["Dashboard", "Upload Logs", "Processing Pipeline", "Traces Explorer", "Failure Analysis", "Semantic Clusters", "Generated Datasets", "Human Review", "Export Center", "Settings"]) {
      expect(within(nav).getByRole("link", { name: label })).toBeInTheDocument();
    }
    await userEvent.click(within(nav).getByRole("link", { name: "Upload Logs" }));
    expect(await screen.findByRole("heading", { name: "Upload Logs" })).toBeInTheDocument();
    expect(await screen.findByText("Backend online")).toBeInTheDocument();
  });
});

describe("dashboard", () => {
  it("shows live metrics from the API", async () => {
    mockFetch({ ...base, "GET /api/v1/dashboard/metrics": () => metrics });
    renderAt("/");
    expect(await screen.findByTestId("stat-Logs ingested")).toHaveTextContent("286");
    expect(screen.getByTestId("stat-Candidate examples")).toHaveTextContent("82");
    expect(screen.getByTestId("stat-Avg latency")).toHaveTextContent("2.33s");
    expect(screen.getByTestId("stat-Duplicate rate")).toHaveTextContent("65.0%");
    expect(screen.getByText("production_logs.jsonl")).toBeInTheDocument();
  });

  it("shows empty state and loads the sample dataset", async () => {
    let loaded = false;
    const calls = mockFetch({
      ...base,
      "GET /api/v1/dashboard/metrics": () => (loaded ? metrics : emptyMetrics),
      "POST /api/v1/ingestion/sample": () => {
        loaded = true;
        return { id: "j1" };
      },
    });
    renderAt("/");
    await userEvent.click(await screen.findByRole("button", { name: "Load synthetic sample data" }));
    expect(await screen.findByTestId("stat-Logs ingested")).toHaveTextContent("286");
    expect(calls.some((c) => c.method === "POST" && c.url.searchParams.get("name") === "production_logs")).toBe(true);
  });

  it("shows an error banner when the backend is unreachable", async () => {
    mockFetch({ "GET /health": () => new Response("", { status: 500 }) });
    renderAt("/");
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });
});

describe("upload", () => {
  it("rejects unsupported files client-side", async () => {
    const calls = mockFetch({ ...base, "GET /api/v1/ingestion/samples": () => [] });
    renderAt("/upload");
    const input = await screen.findByTestId("file-input");
    await userEvent.upload(input, new File(["MZ"], "evil.exe", { type: "application/octet-stream" }), { applyAccept: false });
    expect(await screen.findByRole("alert")).toHaveTextContent("Unsupported file type");
    expect(calls.some((c) => c.url.pathname.includes("upload"))).toBe(false);
  });

  it("uploads a file and shows the processing result", async () => {
    const calls = mockFetch({
      ...base,
      "GET /api/v1/ingestion/samples": () => [],
      "POST /api/v1/ingestion/upload": () => ({
        id: "j9", filename: "logs.jsonl", status: "completed", total_records: 10, valid_records: 9, invalid_records: 1,
        trace_count: 8, redaction_counts: { email: 3 }, events: [], stats: {},
      }),
    });
    renderAt("/upload");
    await userEvent.upload(await screen.findByTestId("file-input"), new File(['{"input":"x"}'], "logs.jsonl", { type: "application/json" }));
    await userEvent.click(screen.getByRole("button", { name: "Upload & process" }));
    const result = await screen.findByTestId("job-result");
    expect(result).toHaveTextContent("Processed logs.jsonl");
    expect(result).toHaveTextContent("8");
    const up = calls.find((c) => c.url.pathname.endsWith("/upload"))!;
    expect(up.method).toBe("POST");
    expect(up.body).toBeInstanceOf(FormData);
  });

  it("surfaces server-side validation errors", async () => {
    mockFetch({
      ...base,
      "GET /api/v1/ingestion/samples": () => [],
      "POST /api/v1/ingestion/upload": () => new Response(JSON.stringify({ detail: "Malformed JSON document" }), { status: 422 }),
    });
    renderAt("/upload");
    await userEvent.upload(await screen.findByTestId("file-input"), new File(["{"], "bad.json"));
    await userEvent.click(screen.getByRole("button", { name: "Upload & process" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Malformed JSON document");
  });
});

describe("human review", () => {
  it("approves an example with an edited expected output", async () => {
    let current = { ...example };
    const calls = mockFetch({
      ...base,
      "GET /api/v1/datasets/[^/]+/examples": () => page([current]),
      "GET /api/v1/examples/ex1": () => current,
      "POST /api/v1/examples/ex1/review": (_u, init) => {
        const body = JSON.parse(String(init?.body));
        current = { ...current, review_status: "approved", expected_output: body.expected_output, expected_output_source: "human_approved" };
        return current;
      },
    });
    renderAt(`/review?dataset=${dataset.id}`);
    const textarea = await screen.findByLabelText("Expected output");
    await userEvent.type(textarea, "Go to Settings > Security.");
    await userEvent.click(screen.getByRole("button", { name: /Approve/ }));
    expect(await screen.findByRole("status")).toHaveTextContent("Approved");
    const review = calls.find((c) => c.method === "POST" && c.url.pathname.endsWith("/review"))!;
    expect(review.body).toMatchObject({ action: "approve", expected_output: "Go to Settings > Security.", reviewer: "reviewer" });
    await waitFor(() => expect(screen.getAllByText("human_approved").length).toBeGreaterThan(0));
  });

  it("rejects and flags examples", async () => {
    const calls = mockFetch({
      ...base,
      "GET /api/v1/datasets/[^/]+/examples": () => page([example]),
      "GET /api/v1/examples/ex1": () => example,
      "POST /api/v1/examples/ex1/review": () => example,
    });
    renderAt(`/review?dataset=${dataset.id}`);
    await userEvent.click(await screen.findByRole("button", { name: /Reject/ }));
    await userEvent.click(await screen.findByRole("button", { name: /Flag uncertain/ }));
    await waitFor(() => {
      const actions = calls.filter((c) => c.url.pathname.endsWith("/review")).map((c) => (c.body as { action: string }).action);
      expect(actions).toEqual(["reject", "flag"]);
    });
  });

  it("filters by status and searches", async () => {
    const calls = mockFetch({
      ...base,
      "GET /api/v1/datasets/[^/]+/examples": () => page([example]),
      "GET /api/v1/examples/ex1": () => example,
    });
    renderAt(`/review?dataset=${dataset.id}`);
    await userEvent.click(await screen.findByRole("tab", { name: "approved" }));
    await userEvent.type(screen.getByLabelText("Search examples"), "password{Enter}");
    await waitFor(() => {
      const last = calls.filter((c) => c.url.pathname.endsWith("/examples")).at(-1)!;
      expect(last.url.searchParams.get("status")).toBe("approved");
      expect(last.url.searchParams.get("search")).toBe("password");
    });
  });
});

describe("datasets", () => {
  it("generates a dataset with selected categories", async () => {
    const calls = mockFetch({
      ...base,
      "POST /api/v1/datasets/generate": () => ({ ...dataset, stats: { total: 0, by_status: {}, by_category: {}, by_expected_source: {}, avg_quality: 0, category_coverage: 0 }, versions: [] }),
      "GET /api/v1/datasets/[^/]+": () => ({ ...dataset, stats: { total: 0, by_status: {}, by_category: {}, by_expected_source: {}, avg_quality: 0, category_coverage: 0 }, versions: [] }),
      "GET /api/v1/datasets/[^/]+/examples": () => page([]),
    });
    renderAt("/datasets");
    await userEvent.click(await screen.findByRole("button", { name: "latency" }));
    await userEvent.click(screen.getByRole("button", { name: /Generate dataset/ }));
    await waitFor(() => {
      const gen = calls.find((c) => c.url.pathname.endsWith("/generate"));
      expect(gen?.body).toMatchObject({ categories: ["latency"], include_successful: true, exclude_duplicates: true });
    });
  });
});

describe("export", () => {
  it("builds the download URL from filters and previews content", async () => {
    mockFetch({
      ...base,
      "GET /api/v1/exports/[^/]+": () => new Response('{"id":"ex1"}\n', { status: 200, headers: { "X-Example-Count": "1" } }),
    });
    renderAt(`/export?dataset=${dataset.id}`);
    await userEvent.click(await screen.findByRole("radio", { name: ".csv" }));
    await userEvent.click(screen.getByRole("button", { name: "safety" }));
    const link = screen.getByTestId("download-link");
    const href = new URL(link.getAttribute("href")!, "http://x");
    expect(href.pathname).toBe(`/api/v1/exports/${dataset.id}`);
    expect(href.searchParams.get("format")).toBe("csv");
    expect(href.searchParams.get("approved_only")).toBe("true");
    expect(href.searchParams.get("categories")).toBe("safety");
    await userEvent.click(screen.getByRole("button", { name: /Preview/ }));
    expect(await screen.findByTestId("export-preview")).toHaveTextContent('{"id":"ex1"}');
  });
});
