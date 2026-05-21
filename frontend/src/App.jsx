import { useEffect, useMemo, useState } from "react";
import { ArrowUpRight, Linkedin, Loader2, Newspaper, Plus, RefreshCw, Trash2 } from "lucide-react";

import { api } from "./api";

const VIEWS = [
  { id: "sources", label: "Source Intake" },
  { id: "companies", label: "Company Intelligence" },
  { id: "comparison", label: "Concentric Gap View" },
];

function formatDate(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleDateString();
}

function SignalPills({ items }) {
  if (!items || items.length === 0) return <span className="muted">-</span>;
  return (
    <div className="pill-wrap">
      {items.map((item) => (
        <span key={`${item.category}-${item.name}`} className="pill">
          {item.name}
        </span>
      ))}
    </div>
  );
}

function App() {
  const [activeView, setActiveView] = useState("sources");
  const [urlInput, setUrlInput] = useState("");
  const [sources, setSources] = useState([]);
  const [companies, setCompanies] = useState([]);
  const [comparison, setComparison] = useState(null);
  const [selectedCompanyId, setSelectedCompanyId] = useState(null);
  const [selectedCompany, setSelectedCompany] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [pending, setPending] = useState({
    adding: false,
    sourceRefreshId: null,
    sourceDeleteId: null,
    companyRefreshId: null,
  });

  const loadOverview = async () => {
    setLoading(true);
    setError("");
    try {
      const [nextSources, nextCompanies, nextComparison] = await Promise.all([
        api.listSources(),
        api.listCompanies(),
        api.getComparison(),
      ]);
      setSources(nextSources);
      setCompanies(nextCompanies);
      setComparison(nextComparison);
      if (!selectedCompanyId && nextCompanies.length > 0) {
        setSelectedCompanyId(nextCompanies[0].id);
      }
    } catch (err) {
      setError(err.message || "Failed to load data.");
    } finally {
      setLoading(false);
    }
  };

  const loadCompanyDetail = async (companyId) => {
    if (!companyId) {
      setSelectedCompany(null);
      return;
    }
    try {
      const detail = await api.getCompany(companyId);
      setSelectedCompany(detail);
    } catch (err) {
      setError(err.message || "Failed to load company detail.");
    }
  };

  useEffect(() => {
    loadOverview();
  }, []);

  useEffect(() => {
    if (selectedCompanyId) {
      loadCompanyDetail(selectedCompanyId);
    }
  }, [selectedCompanyId]);

  const totals = useMemo(() => {
    const featureTotal = companies.reduce((sum, company) => sum + company.features.length, 0);
    const toolTotal = companies.reduce((sum, company) => sum + company.tools.length, 0);
    const newsTotal = companies.reduce((sum, company) => sum + company.news_count, 0);
    return {
      companies: companies.length,
      sources: sources.length,
      features: featureTotal,
      tools: toolTotal,
      news: newsTotal,
    };
  }, [companies, sources]);

  const addSource = async (event) => {
    event.preventDefault();
    setError("");
    setPending((prev) => ({ ...prev, adding: true }));
    try {
      await api.addSource({ url: urlInput.trim() });
      setUrlInput("");
      await loadOverview();
    } catch (err) {
      setError(err.message || "Failed to add URL.");
    } finally {
      setPending((prev) => ({ ...prev, adding: false }));
    }
  };

  const refreshSource = async (sourceId) => {
    setPending((prev) => ({ ...prev, sourceRefreshId: sourceId }));
    setError("");
    try {
      await api.rescrapeSource(sourceId);
      await loadOverview();
      if (selectedCompanyId) {
        await loadCompanyDetail(selectedCompanyId);
      }
    } catch (err) {
      setError(err.message || "Failed to re-scrape source.");
    } finally {
      setPending((prev) => ({ ...prev, sourceRefreshId: null }));
    }
  };

  const deleteSource = async (sourceId) => {
    setPending((prev) => ({ ...prev, sourceDeleteId: sourceId }));
    setError("");
    try {
      await api.deleteSource(sourceId);
      await loadOverview();
      if (selectedCompanyId) {
        await loadCompanyDetail(selectedCompanyId);
      }
    } catch (err) {
      setError(err.message || "Failed to delete source.");
    } finally {
      setPending((prev) => ({ ...prev, sourceDeleteId: null }));
    }
  };

  const refreshCompanyNews = async (companyId) => {
    setPending((prev) => ({ ...prev, companyRefreshId: companyId }));
    setError("");
    try {
      const detail = await api.refreshCompanyNews(companyId);
      setSelectedCompany(detail);
      await loadOverview();
    } catch (err) {
      setError(err.message || "Failed to refresh company news.");
    } finally {
      setPending((prev) => ({ ...prev, companyRefreshId: null }));
    }
  };

  return (
    <div className="app-shell">
      <header className="header">
        <div>
          <h1>Concentric Competitive Intelligence Control Center</h1>
          <p>
            Add any source URL. The system resolves company entities, merges records, extracts
            feature/tool signals, and pulls market news for comparison against Concentric AI.
          </p>
        </div>
        <button className="icon-button" onClick={loadOverview} title="Refresh everything">
          <RefreshCw size={16} />
          Refresh
        </button>
      </header>

      <section className="metric-grid">
        <div>
          <span>Tracked Companies</span>
          <strong>{totals.companies}</strong>
        </div>
        <div>
          <span>Source URLs</span>
          <strong>{totals.sources}</strong>
        </div>
        <div>
          <span>Detected Features</span>
          <strong>{totals.features}</strong>
        </div>
        <div>
          <span>Detected Tools</span>
          <strong>{totals.tools}</strong>
        </div>
        <div>
          <span>News Articles</span>
          <strong>{totals.news}</strong>
        </div>
      </section>

      <nav className="tab-bar">
        {VIEWS.map((view) => (
          <button
            key={view.id}
            className={activeView === view.id ? "active" : ""}
            onClick={() => setActiveView(view.id)}
          >
            {view.label}
          </button>
        ))}
      </nav>

      {error ? <p className="error-banner">{error}</p> : null}
      {loading ? <p className="loading-banner">Loading intelligence graph...</p> : null}

      {activeView === "sources" ? (
        <section className="surface">
          <form className="url-form" onSubmit={addSource}>
            <input
              required
              value={urlInput}
              onChange={(event) => setUrlInput(event.target.value)}
              placeholder="Paste any competitor/news/blog/docs URL"
            />
            <button type="submit" disabled={pending.adding}>
              {pending.adding ? <Loader2 size={16} className="spin" /> : <Plus size={16} />}
              Add and Analyze
            </button>
          </form>

          <table className="data-table">
            <thead>
              <tr>
                <th>URL</th>
                <th>Company</th>
                <th>Type</th>
                <th>Features</th>
                <th>Tools</th>
                <th>Status</th>
                <th>Last Scrape</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {sources.length === 0 ? (
                <tr>
                  <td colSpan={8}>No source URLs yet.</td>
                </tr>
              ) : (
                sources.map((source) => (
                  <tr key={source.id}>
                    <td>
                      <a href={source.url} target="_blank" rel="noreferrer">
                        {source.domain}
                      </a>
                    </td>
                    <td>{source.company_name || "-"}</td>
                    <td>{source.source_type}</td>
                    <td>
                      <SignalPills items={source.detected_features.slice(0, 4)} />
                    </td>
                    <td>
                      <SignalPills items={source.detected_tools.slice(0, 4)} />
                    </td>
                    <td>
                      <span className={`status ${source.status}`}>{source.status}</span>
                    </td>
                    <td>{formatDate(source.scraped_at)}</td>
                    <td>
                      <div className="action-row">
                        <button
                          className="icon-button ghost"
                          title="Re-scrape"
                          onClick={() => refreshSource(source.id)}
                          disabled={pending.sourceRefreshId === source.id}
                        >
                          {pending.sourceRefreshId === source.id ? (
                            <Loader2 size={14} className="spin" />
                          ) : (
                            <RefreshCw size={14} />
                          )}
                        </button>
                        <button
                          className="icon-button danger"
                          title="Delete source"
                          onClick={() => deleteSource(source.id)}
                          disabled={pending.sourceDeleteId === source.id}
                        >
                          {pending.sourceDeleteId === source.id ? (
                            <Loader2 size={14} className="spin" />
                          ) : (
                            <Trash2 size={14} />
                          )}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </section>
      ) : null}

      {activeView === "companies" ? (
        <section className="two-pane">
          <aside className="surface list-pane">
            <h2>Company Entities</h2>
            <div className="company-list">
              {companies.map((company) => (
                <button
                  key={company.id}
                  className={`company-card ${selectedCompanyId === company.id ? "active" : ""}`}
                  onClick={() => setSelectedCompanyId(company.id)}
                >
                  <strong>{company.company_name}</strong>
                  <span>{company.primary_domain || "-"}</span>
                  <span>{company.source_count} sources</span>
                  <span>{company.linkedin_news_count} LinkedIn signals</span>
                </button>
              ))}
            </div>
          </aside>

          <div className="surface detail-pane">
            {!selectedCompany ? (
              <p className="muted">Select a company to view full intelligence.</p>
            ) : (
              <>
                <div className="detail-header">
                  <div>
                    <h2>{selectedCompany.company_name}</h2>
                    <p>{selectedCompany.description || "No company summary yet."}</p>
                    {selectedCompany.linkedin_url ? (
                      <a
                        href={selectedCompany.linkedin_url}
                        target="_blank"
                        rel="noreferrer"
                        className="linkedin-link"
                      >
                        <Linkedin size={14} />
                        LinkedIn Company Page
                      </a>
                    ) : null}
                  </div>
                  <button
                    className="icon-button"
                    onClick={() => refreshCompanyNews(selectedCompany.id)}
                    disabled={pending.companyRefreshId === selectedCompany.id}
                  >
                    {pending.companyRefreshId === selectedCompany.id ? (
                      <Loader2 size={14} className="spin" />
                    ) : (
                      <Newspaper size={14} />
                    )}
                    Refresh News
                  </button>
                </div>

                <div className="signal-columns">
                  <div>
                    <h3>Supported Features</h3>
                    <SignalPills items={selectedCompany.features} />
                  </div>
                  <div>
                    <h3>Observed Tools</h3>
                    <SignalPills items={selectedCompany.tools} />
                  </div>
                </div>

                <h3>Evidence Sources</h3>
                <table className="data-table compact">
                  <thead>
                    <tr>
                      <th>Source</th>
                      <th>Type</th>
                      <th>Confidence</th>
                      <th>Summary</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selectedCompany.sources.length === 0 ? (
                      <tr>
                        <td colSpan={4}>No linked sources yet.</td>
                      </tr>
                    ) : (
                      selectedCompany.sources.map((source) => (
                        <tr key={source.id}>
                          <td>
                            <a href={source.url} target="_blank" rel="noreferrer">
                              {source.domain}
                            </a>
                          </td>
                          <td>{source.source_type}</td>
                          <td>{Math.round(source.confidence * 100)}%</td>
                          <td>{source.summary || "-"}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>

                <h3>Latest News</h3>
                <div className="news-list">
                  {selectedCompany.news.length === 0 ? (
                    <p className="muted">No indexed news yet.</p>
                  ) : (
                    selectedCompany.news.map((item) => (
                      <a
                        key={item.id}
                        href={item.article_url}
                        target="_blank"
                        rel="noreferrer"
                        className="news-row"
                      >
                        <div>
                          <strong>{item.title}</strong>
                          <span>
                            {item.publisher || "Unknown source"} • {formatDate(item.published_at)}
                          </span>
                        </div>
                        <ArrowUpRight size={14} />
                      </a>
                    ))
                  )}
                </div>
              </>
            )}
          </div>
        </section>
      ) : null}

      {activeView === "comparison" && comparison ? (
        <section className="surface">
          <h2>Competitor Gaps vs {comparison.baseline_company_name}</h2>
          <table className="data-table">
            <thead>
              <tr>
                <th>Competitor</th>
                <th>Gap Score</th>
                <th>LinkedIn</th>
                <th>Features Concentric Lacks</th>
                <th>Tools Concentric Lacks</th>
                <th>Latest Market Signals</th>
              </tr>
            </thead>
            <tbody>
              {comparison.competitors.length === 0 ? (
                <tr>
                  <td colSpan={6}>No competitor profiles yet.</td>
                </tr>
              ) : (
                comparison.competitors.map((row) => (
                  <tr key={row.company_id}>
                    <td>{row.company_name}</td>
                    <td>{row.gap_score.toFixed(2)}</td>
                    <td>
                      {row.linkedin_url ? (
                        <a href={row.linkedin_url} target="_blank" rel="noreferrer" className="inline-link">
                          LinkedIn
                        </a>
                      ) : (
                        "-"
                      )}
                    </td>
                    <td>
                      <SignalPills items={row.competitor_only_features.slice(0, 8)} />
                    </td>
                    <td>
                      <SignalPills items={row.competitor_only_tools.slice(0, 8)} />
                    </td>
                    <td>
                      <div className="news-mini">
                        {row.top_news.slice(0, 3).map((news) => (
                          <a
                            key={`${row.company_id}-${news.id}`}
                            href={news.article_url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            {news.title}
                          </a>
                        ))}
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </section>
      ) : null}
    </div>
  );
}

export default App;
