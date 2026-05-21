const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

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
  listEnrichmentConnectors: () => request("/enrichment-connectors"),
  listSources: () => request("/competitive-urls"),
  addSource: (body) => request("/competitive-urls", { method: "POST", body }),
  deleteSource: (id) => request(`/competitive-urls/${id}`, { method: "DELETE" }),
  rescrapeSource: (id) => request(`/competitive-urls/${id}/rescrape`, { method: "POST" }),
  listCompanies: () => request("/companies"),
  getCompany: (id) => request(`/companies/${id}`),
  refreshCompanyNews: (id) => request(`/companies/${id}/refresh-news`, { method: "POST" }),
  refreshCompanyEnrichment: (id) => request(`/companies/${id}/refresh-enrichment`, { method: "POST" }),
  getComparison: () => request("/comparison"),
};
