// Regression tests: with the backend stopped, the Vite dev proxy (and nginx in Docker) answer
// with a bare 5xx and no JSON body. That must read as "backend unreachable", not as a server
// crash, while genuine backend errors (JSON {"detail": ...}) keep their own message.
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";

function stubFetch(response: () => Response | Promise<Response>) {
  vi.stubGlobal("fetch", vi.fn(async () => response()));
}

afterEach(() => vi.unstubAllGlobals());

describe("API client error messages", () => {
  it.each([500, 502, 503, 504])("reports an unreachable backend for a bare proxy %i", async (status) => {
    stubFetch(() => new Response("", { status, headers: { "Content-Type": "text/plain" } }));
    await expect(api.datasets()).rejects.toThrow(/Cannot reach the EVALS backend/);
  });

  it("reports an unreachable backend when the network request itself fails", async () => {
    stubFetch(() => Promise.reject(new TypeError("Failed to fetch")));
    await expect(api.datasets()).rejects.toThrow(/Cannot reach the EVALS backend/);
  });

  it("keeps the backend's own message for a JSON 500", async () => {
    stubFetch(() => new Response(JSON.stringify({ detail: "Internal server error" }), { status: 500 }));
    await expect(api.datasets()).rejects.toThrow("Internal server error");
  });

  it("keeps validation details for 4xx responses", async () => {
    stubFetch(() => new Response(JSON.stringify({ detail: "Dataset not found" }), { status: 404 }));
    await expect(api.datasets()).rejects.toThrow("Dataset not found");
  });
});
