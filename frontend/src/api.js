export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

async function request(path, { method = "GET", body } = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload?.detail || `Request failed (${response.status})`);
  }
  if (response.status === 204) {
    return null;
  }
  return response.json();
}

export const api = {
  getBriefing: ({ baselineCompanyId, analysisWorkspaceId, focusAnchorCompanyId } = {}) => {
    const params = new URLSearchParams();
    if (analysisWorkspaceId) params.set("analysis_workspace_id", analysisWorkspaceId);
    if (focusAnchorCompanyId) params.set("focus_anchor_company_id", focusAnchorCompanyId);
    if (baselineCompanyId && !analysisWorkspaceId) params.set("baseline_company_id", baselineCompanyId);
    const query = params.toString();
    return request(`/briefing${query ? `?${query}` : ""}`);
  },
  askConcentric: (body) => request("/ai/ask", { method: "POST", body }),
  getDecisionPolicy: () => request("/decision-policy"),
  listEnrichmentConnectors: () => request("/enrichment-connectors"),
  autoDiscoverCompetitors: ({
    maxCandidates = 30,
    includeNews = false,
    refreshMarketSignals = false,
    analysisWorkspaceId,
  } = {}) =>
    request(
      `/competitors/auto-discover?max_candidates=${maxCandidates}&include_news=${includeNews ? "true" : "false"}&refresh_market_signals=${refreshMarketSignals ? "true" : "false"}${analysisWorkspaceId ? `&analysis_workspace_id=${analysisWorkspaceId}` : ""}`,
      { method: "POST" },
    ),
  listCompetitorCatalog: () => request("/competitors/catalog"),
  listSources: ({ analysisWorkspaceId } = {}) => {
    const params = new URLSearchParams();
    if (analysisWorkspaceId) params.set("analysis_workspace_id", analysisWorkspaceId);
    const query = params.toString();
    return request(`/competitive-urls${query ? `?${query}` : ""}`);
  },
  addSource: (body) => request("/competitive-urls", { method: "POST", body }),
  deleteSource: (id) => request(`/competitive-urls/${id}`, { method: "DELETE" }),
  rescrapeSource: (id) => request(`/competitive-urls/${id}/rescrape`, { method: "POST" }),
  listCompanies: () => request("/companies"),
  listAnalysisWorkspaces: () => request("/analysis-workspaces"),
  createAnalysisWorkspace: (body) => request("/analysis-workspaces", { method: "POST", body }),
  updateAnalysisWorkspace: (id, body) => request(`/analysis-workspaces/${id}`, { method: "PUT", body }),
  deleteAnalysisWorkspace: (id) => request(`/analysis-workspaces/${id}`, { method: "DELETE" }),
  retargetWorkspace: (body) => request("/api/v1/workspace/re-target", { method: "POST", body }),
  getCompany: (id) => request(`/companies/${id}`),
  listCompanyClaims: (id) => request(`/companies/${id}/claims`),
  refreshCompanyNews: (id) => request(`/companies/${id}/refresh-news`, { method: "POST" }),
  refreshCompanyEnrichment: (id) => request(`/companies/${id}/refresh-enrichment`, { method: "POST" }),
  listMergeReviews: (status = "pending") => request(`/merge-reviews?status=${encodeURIComponent(status)}`),
  approveMergeReview: (id, body = {}) => request(`/merge-reviews/${id}/approve`, { method: "POST", body }),
  rejectMergeReview: (id, body = {}) => request(`/merge-reviews/${id}/reject`, { method: "POST", body }),
  listIngestionJobs: (limit = 50) => request(`/ingestion-jobs?limit=${limit}`),
  runIngestionCycle: () => request("/ingestion-jobs/run-cycle", { method: "POST" }),
  getComparison: ({ baselineCompanyId, analysisWorkspaceId, focusAnchorCompanyId } = {}) => {
    const params = new URLSearchParams();
    if (analysisWorkspaceId) params.set("analysis_workspace_id", analysisWorkspaceId);
    if (focusAnchorCompanyId) params.set("focus_anchor_company_id", focusAnchorCompanyId);
    if (baselineCompanyId && !analysisWorkspaceId) params.set("baseline_company_id", baselineCompanyId);
    const query = params.toString();
    return request(`/comparison${query ? `?${query}` : ""}`);
  },
};
