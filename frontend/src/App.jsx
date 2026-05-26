import { useEffect, useMemo, useState } from "react";
import {
  ArrowUpRight,
  BarChart3,
  Check,
  Database,
  Linkedin,
  Radar,
  Loader2,
  Newspaper,
  PlayCircle,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Trash2,
  X,
} from "lucide-react";

import { api } from "./api";

const VIEWS = [
  { id: "sources", label: "Source Intake" },
  { id: "companies", label: "Company Intelligence" },
  { id: "comparison", label: "Concentric Gap View" },
  { id: "ops", label: "Ops Console" },
];

function formatDate(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleDateString();
}

function titleCase(value) {
  return value
    .replace(/[_:]/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
    .trim();
}

function sourceLabel(source, connectorNames = {}) {
  if (!source) return "Unknown";
  if (source === "google_news_rss") return "Google News";
  if (source === "linkedin_news_rss") return "LinkedIn";
  if (source.startsWith("enrichment:")) {
    const connectorId = source.replace("enrichment:", "");
    return connectorNames[connectorId] || titleCase(connectorId);
  }
  return titleCase(source);
}

function compactText(value, maxChars = 260) {
  if (!value) return "-";
  const text = String(value).replace(/\s+/g, " ").trim();
  if (!text) return "-";
  if (text.length <= maxChars) return text;
  return `${text.slice(0, maxChars).trimEnd()}...`;
}

function looksLikeBlockedText(value) {
  if (!value) return false;
  const lowered = value.toLowerCase();
  return [
    "access denied",
    "attention required",
    "just a moment",
    "errors.edgesuite.net",
    "verify you are human",
    "request blocked",
    "security check",
  ].some((marker) => lowered.includes(marker));
}

function cleanSummary(value) {
  if (!value) return "-";
  if (looksLikeBlockedText(value)) {
    return "Source page appears blocked by anti-bot/CDN checks. Add product/docs/news URLs for stronger evidence quality.";
  }
  return compactText(value, 340);
}

function sourceTierFromType(sourceType) {
  if (sourceType === "product" || sourceType === "docs") return 0.95;
  if (sourceType === "website") return 0.88;
  if (sourceType === "linkedin") return 0.7;
  if (sourceType === "news") return 0.58;
  return 0.6;
}

function sourceSelectionBasis(source) {
  const featureCount = source.detected_features?.length || 0;
  const toolCount = source.detected_tools?.length || 0;
  const signalCount = featureCount + toolCount;
  const sourceTier = sourceTierFromType(source.source_type);
  const extractionScore = Math.round((source.confidence || 0) * 100);
  return `${titleCase(source.source_type)} tier ${sourceTier.toFixed(2)} • extraction ${extractionScore}% • ${signalCount} detected signals`;
}

function marketSignalBasis(sourceKey, connectorsById = {}) {
  if (sourceKey === "google_news_rss") {
    return "Broad monitoring via Google News RSS query using company name and domain.";
  }
  if (sourceKey === "linkedin_news_rss") {
    return "LinkedIn-targeted Google News query using company name and LinkedIn company slug.";
  }
  if (sourceKey.startsWith("enrichment:")) {
    const connectorId = sourceKey.replace("enrichment:", "");
    const connector = connectorsById[connectorId];
    if (!connector) return "Connector-scoped source enrichment signal.";
    return `Connector-scoped signal from ${connector.name} (${connector.site_domain}) for targeted market context.`;
  }
  return "External signal channel used for company market intelligence.";
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
  const [connectors, setConnectors] = useState([]);
  const [mergeReviews, setMergeReviews] = useState([]);
  const [ingestionJobs, setIngestionJobs] = useState([]);
  const [comparison, setComparison] = useState(null);
  const [selectedCompanyId, setSelectedCompanyId] = useState(null);
  const [selectedCompany, setSelectedCompany] = useState(null);
  const [companyQuery, setCompanyQuery] = useState("");
  const [decisionPolicy, setDecisionPolicy] = useState(null);
  const [autoDiscoverResult, setAutoDiscoverResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [pending, setPending] = useState({
    adding: false,
    autoDiscover: false,
    sourceRefreshId: null,
    sourceDeleteId: null,
    companyRefreshId: null,
    companyEnrichmentId: null,
    mergeReviewId: null,
    runCycle: false,
  });

  const loadOverview = async () => {
    setLoading(true);
    setError("");
    try {
      const [
        nextSources,
        nextCompanies,
        nextComparison,
        nextConnectors,
        nextMergeReviews,
        nextJobs,
        nextDecisionPolicy,
      ] =
        await Promise.all([
        api.listSources(),
        api.listCompanies(),
        api.getComparison(),
        api.listEnrichmentConnectors(),
        api.listMergeReviews("pending"),
        api.listIngestionJobs(50),
        api.getDecisionPolicy(),
      ]);
      setSources(nextSources);
      setCompanies(nextCompanies);
      setComparison(nextComparison);
      setConnectors(nextConnectors);
      setMergeReviews(nextMergeReviews);
      setIngestionJobs(nextJobs);
      setDecisionPolicy(nextDecisionPolicy);
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
    const enrichmentTotal = companies.reduce(
      (sum, company) => sum + (company.enrichment_news_count || 0),
      0,
    );
    const highConfidenceClaims = companies.reduce(
      (sum, company) => sum + (company.high_confidence_claim_count || 0),
      0,
    );
    return {
      companies: companies.length,
      sources: sources.length,
      features: featureTotal,
      tools: toolTotal,
      news: newsTotal,
      enrichment: enrichmentTotal,
      highClaims: highConfidenceClaims,
    };
  }, [companies, sources]);

  const connectorNames = useMemo(
    () => Object.fromEntries(connectors.map((connector) => [connector.id, connector.name])),
    [connectors],
  );
  const connectorsById = useMemo(
    () => Object.fromEntries(connectors.map((connector) => [connector.id, connector])),
    [connectors],
  );

  const filteredCompanies = useMemo(() => {
    const query = companyQuery.trim().toLowerCase();
    if (!query) {
      return companies;
    }
    return companies.filter((company) => {
      const companyName = (company.company_name || "").toLowerCase();
      const domain = (company.primary_domain || "").toLowerCase();
      return companyName.includes(query) || domain.includes(query);
    });
  }, [companies, companyQuery]);

  const selectedSourceTypeCounts = useMemo(() => {
    const counts = {};
    if (!selectedCompany?.sources) return counts;
    for (const source of selectedCompany.sources) {
      counts[source.source_type] = (counts[source.source_type] || 0) + 1;
    }
    return counts;
  }, [selectedCompany]);

  const selectedMarketSignalRows = useMemo(() => {
    if (!selectedCompany) return [];
    return Object.entries(selectedCompany.news_source_counts || {}).map(([source, count]) => ({
      source,
      count,
      label: sourceLabel(source, connectorNames),
      basis: marketSignalBasis(source, connectorsById),
    }));
  }, [selectedCompany, connectorNames, connectorsById]);

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

  const autoDiscoverCompetitors = async () => {
    setError("");
    setPending((prev) => ({ ...prev, autoDiscover: true }));
    try {
      const result = await api.autoDiscoverCompetitors({
        maxCandidates: 60,
        includeNews: true,
        refreshMarketSignals: false,
      });
      setAutoDiscoverResult(result);
      await loadOverview();
      if (selectedCompanyId) {
        await loadCompanyDetail(selectedCompanyId);
      }
    } catch (err) {
      setError(err.message || "Failed to auto-discover competitors.");
    } finally {
      setPending((prev) => ({ ...prev, autoDiscover: false }));
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

  const refreshCompanyEnrichment = async (companyId) => {
    setPending((prev) => ({ ...prev, companyEnrichmentId: companyId }));
    setError("");
    try {
      const detail = await api.refreshCompanyEnrichment(companyId);
      setSelectedCompany(detail);
      await loadOverview();
    } catch (err) {
      setError(err.message || "Failed to refresh source enrichment.");
    } finally {
      setPending((prev) => ({ ...prev, companyEnrichmentId: null }));
    }
  };

  const approveMergeReview = async (reviewId) => {
    setPending((prev) => ({ ...prev, mergeReviewId: reviewId }));
    setError("");
    try {
      await api.approveMergeReview(reviewId, {});
      await loadOverview();
      if (selectedCompanyId) {
        await loadCompanyDetail(selectedCompanyId);
      }
    } catch (err) {
      setError(err.message || "Failed to approve merge review.");
    } finally {
      setPending((prev) => ({ ...prev, mergeReviewId: null }));
    }
  };

  const rejectMergeReview = async (reviewId) => {
    setPending((prev) => ({ ...prev, mergeReviewId: reviewId }));
    setError("");
    try {
      await api.rejectMergeReview(reviewId, {});
      await loadOverview();
    } catch (err) {
      setError(err.message || "Failed to reject merge review.");
    } finally {
      setPending((prev) => ({ ...prev, mergeReviewId: null }));
    }
  };

  const runIngestionCycle = async () => {
    setPending((prev) => ({ ...prev, runCycle: true }));
    setError("");
    try {
      await api.runIngestionCycle();
      await loadOverview();
      if (selectedCompanyId) {
        await loadCompanyDetail(selectedCompanyId);
      }
    } catch (err) {
      setError(err.message || "Failed to run ingestion cycle.");
    } finally {
      setPending((prev) => ({ ...prev, runCycle: false }));
    }
  };

  return (
    <div className="app-shell">
      <header className="header">
        <div>
          <span className="hero-kicker">Concentric AI</span>
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
        <div className="metric-card">
          <span>Tracked Companies</span>
          <strong>{totals.companies}</strong>
        </div>
        <div className="metric-card">
          <span>Source URLs</span>
          <strong>{totals.sources}</strong>
        </div>
        <div className="metric-card">
          <span>Detected Features</span>
          <strong>{totals.features}</strong>
        </div>
        <div className="metric-card">
          <span>Detected Tools</span>
          <strong>{totals.tools}</strong>
        </div>
        <div className="metric-card">
          <span>News Articles</span>
          <strong>{totals.news}</strong>
        </div>
        <div className="metric-card">
          <span>Connector Signals</span>
          <strong>{totals.enrichment}</strong>
        </div>
        <div className="metric-card">
          <span>High-Confidence Claims</span>
          <strong>{totals.highClaims}</strong>
        </div>
      </section>

      <nav className="tab-bar">
        {VIEWS.map((view) => (
          <button
            key={view.id}
            className={activeView === view.id ? "active" : ""}
            type="button"
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
            <div className="url-form-actions">
              <button type="submit" disabled={pending.adding}>
                {pending.adding ? <Loader2 size={16} className="spin" /> : <Plus size={16} />}
                Add and Analyze
              </button>
              <button type="button" onClick={autoDiscoverCompetitors} disabled={pending.autoDiscover}>
                {pending.autoDiscover ? <Loader2 size={16} className="spin" /> : <Search size={16} />}
                Auto Discover Competitors
              </button>
            </div>
          </form>

          {autoDiscoverResult ? (
            <div className="discovery-summary">
              <span>
                Added {autoDiscoverResult.added_sources} • Skipped {autoDiscoverResult.skipped_existing} • Failed{" "}
                {autoDiscoverResult.failed_sources}
              </span>
              <span>Candidates scanned: {autoDiscoverResult.candidates_considered}</span>
              <span>Run ingestion cycle to enrich discovered companies with external market signals.</span>
            </div>
          ) : null}

          <div className="connector-strip" aria-label="Enrichment sources">
            {connectors.map((connector) => (
              <div key={connector.id} className="connector-card">
                <span>{connector.category}</span>
                <strong>{connector.name}</strong>
                <small>{connector.site_domain}</small>
              </div>
            ))}
          </div>

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
            <div className="panel-head">
              <div>
                <h2>Company Entities</h2>
                <p>
                  {filteredCompanies.length} of {companies.length} companies
                </p>
              </div>
              <input
                className="company-search"
                value={companyQuery}
                onChange={(event) => setCompanyQuery(event.target.value)}
                placeholder="Search company or domain"
              />
            </div>
            <div className="company-list">
              {filteredCompanies.length === 0 ? (
                <p className="muted">No companies match this filter.</p>
              ) : (
                filteredCompanies.map((company) => (
                  <button
                    key={company.id}
                    className={`company-card ${selectedCompanyId === company.id ? "active" : ""}`}
                    onClick={() => setSelectedCompanyId(company.id)}
                  >
                    <div className="company-card-top">
                      <strong>{company.company_name}</strong>
                      <span>{company.primary_domain || "-"}</span>
                    </div>
                    <div className="company-card-metrics">
                      <span>{company.source_count} sources</span>
                      <span>{company.linkedin_news_count} LinkedIn</span>
                      <span>{company.enrichment_news_count || 0} connector</span>
                      <span>{company.high_confidence_claim_count || 0} high-confidence</span>
                    </div>
                  </button>
                ))
              )}
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
                    <p className="company-summary">{cleanSummary(selectedCompany.description)}</p>
                    <div className="company-links">
                      {selectedCompany.website_url ? (
                        <a href={selectedCompany.website_url} target="_blank" rel="noreferrer" className="inline-link">
                          Website
                        </a>
                      ) : null}
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
                  </div>
                  <div className="detail-actions">
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
                    <button
                      className="icon-button"
                      onClick={() => refreshCompanyEnrichment(selectedCompany.id)}
                      disabled={pending.companyEnrichmentId === selectedCompany.id}
                    >
                      {pending.companyEnrichmentId === selectedCompany.id ? (
                        <Loader2 size={14} className="spin" />
                      ) : (
                        <Database size={14} />
                      )}
                      Refresh Enrichment
                    </button>
                  </div>
                </div>

                <div className="decision-grid">
                  <article className="decision-card">
                    <h4>
                      <ShieldCheck size={14} />
                      Why This Company Is Grouped
                    </h4>
                    <p>
                      Entity grouping uses canonical domain + normalized company key. Near-duplicate names are queued
                      into merge review before final consolidation.
                    </p>
                    <div className="decision-chip-row">
                      {Object.entries(selectedSourceTypeCounts).map(([sourceType, count]) => (
                        <span key={sourceType}>
                          {titleCase(sourceType)} <strong>{count}</strong>
                        </span>
                      ))}
                    </div>
                  </article>
                  <article className="decision-card">
                    <h4>
                      <BarChart3 size={14} />
                      Claim Confidence Decision
                    </h4>
                    <p>
                      Confidence = extraction signal + source tier + freshness + corroboration bonus from repeated
                      evidence across distinct sources.
                    </p>
                    <div className="decision-chip-row">
                      <span>
                        Extraction <strong>{Math.round((decisionPolicy?.claim_confidence_weights?.extraction ?? 0.45) * 100)}%</strong>
                      </span>
                      <span>
                        Source Tier <strong>{Math.round((decisionPolicy?.claim_confidence_weights?.source_tier ?? 0.4) * 100)}%</strong>
                      </span>
                      <span>
                        Freshness <strong>{Math.round((decisionPolicy?.claim_confidence_weights?.freshness ?? 0.15) * 100)}%</strong>
                      </span>
                      <span>
                        High Confidence <strong>&gt;= {Math.round((decisionPolicy?.high_confidence_threshold ?? 0.8) * 100)}%</strong>
                      </span>
                    </div>
                  </article>
                  <article className="decision-card">
                    <h4>
                      <Radar size={14} />
                      Market Signal Selection
                    </h4>
                    <p>
                      Signals appear only when retrieved from approved channels (Google News, LinkedIn-targeted
                      search, and enrichment connectors).
                    </p>
                    <div className="decision-chip-row">
                      {selectedMarketSignalRows.length === 0 ? (
                        <span>
                          Active Channels <strong>0</strong>
                        </span>
                      ) : (
                        selectedMarketSignalRows.map((row) => (
                          <span key={row.source}>
                            {row.label} <strong>{row.count}</strong>
                          </span>
                        ))
                      )}
                    </div>
                  </article>
                </div>

                <div className="company-kpi-grid">
                  <div className="kpi-item">
                    <span>Primary Domain</span>
                    <strong>{selectedCompany.primary_domain || "-"}</strong>
                  </div>
                  <div className="kpi-item">
                    <span>Linked Sources</span>
                    <strong>{selectedCompany.source_count}</strong>
                  </div>
                  <div className="kpi-item">
                    <span>Total News</span>
                    <strong>{selectedCompany.news_count}</strong>
                  </div>
                  <div className="kpi-item">
                    <span>Connector Signals</span>
                    <strong>{selectedCompany.enrichment_news_count || 0}</strong>
                  </div>
                  <div className="kpi-item">
                    <span>LinkedIn Signals</span>
                    <strong>{selectedCompany.linkedin_news_count || 0}</strong>
                  </div>
                  <div className="kpi-item">
                    <span>High-Confidence Claims</span>
                    <strong>{selectedCompany.high_confidence_claim_count || 0}</strong>
                  </div>
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

                <h3>Evidence-Backed Claims</h3>
                <table className="data-table compact claims-table">
                  <thead>
                    <tr>
                      <th>Claim</th>
                      <th>Type</th>
                      <th>Confidence</th>
                      <th>Tier</th>
                      <th>Corroboration</th>
                      <th>Last Verified</th>
                      <th>Decision Basis</th>
                      <th>Evidence</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(selectedCompany.claims || []).length === 0 ? (
                      <tr>
                        <td colSpan={8}>No evidence-backed claims yet.</td>
                      </tr>
                    ) : (
                      selectedCompany.claims.slice(0, 25).map((claim) => (
                        <tr key={claim.id}>
                          <td>{claim.claim_value}</td>
                          <td>{titleCase(claim.claim_type)}</td>
                          <td>{Math.round(claim.confidence * 100)}%</td>
                          <td>{claim.source_tier.toFixed(2)}</td>
                          <td>{claim.source_count} sources</td>
                          <td>{formatDate(claim.last_verified_at)}</td>
                          <td>{titleCase(claim.source_type)} + freshness + corroboration</td>
                          <td>
                            <a href={claim.source_url} target="_blank" rel="noreferrer">
                              {compactText(claim.evidence_snippet || "Open source evidence", 120)}
                            </a>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>

                <h3>Market Signal Decisioning</h3>
                <table className="data-table compact market-signal-table">
                  <thead>
                    <tr>
                      <th>Channel</th>
                      <th>Signals</th>
                      <th>Selection Basis</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selectedMarketSignalRows.length === 0 ? (
                      <tr>
                        <td colSpan={3}>No market signal channels with evidence yet.</td>
                      </tr>
                    ) : (
                      selectedMarketSignalRows.map((row) => (
                        <tr key={row.source}>
                          <td>{row.label}</td>
                          <td>{row.count}</td>
                          <td>{row.basis}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>

                <h3>Evidence Sources</h3>
                <table className="data-table compact evidence-source-table">
                  <thead>
                    <tr>
                      <th>Source</th>
                      <th>Type</th>
                      <th>Confidence</th>
                      <th>Selection Basis</th>
                      <th>Summary</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selectedCompany.sources.length === 0 ? (
                      <tr>
                        <td colSpan={5}>No linked sources yet.</td>
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
                          <td>{sourceSelectionBasis(source)}</td>
                          <td>{cleanSummary(source.summary || source.meta_description)}</td>
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
                            <em>{sourceLabel(item.source, connectorNames)}</em>
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

      {activeView === "ops" ? (
        <section className="surface">
          <div className="ops-header">
            <h2>Ingestion and Merge Operations</h2>
            <button className="icon-button" onClick={runIngestionCycle} disabled={pending.runCycle}>
              {pending.runCycle ? <Loader2 size={14} className="spin" /> : <PlayCircle size={14} />}
              Run Refresh Cycle
            </button>
          </div>

          <h3>Pending Merge Reviews</h3>
          <table className="data-table compact">
            <thead>
              <tr>
                <th>Detected</th>
                <th>Candidate</th>
                <th>Score</th>
                <th>Source</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {mergeReviews.length === 0 ? (
                <tr>
                  <td colSpan={5}>No pending merge reviews.</td>
                </tr>
              ) : (
                mergeReviews.map((review) => (
                  <tr key={review.id}>
                    <td>{review.detected_company_name}</td>
                    <td>{review.candidate_company_name}</td>
                    <td>{(review.similarity_score * 100).toFixed(1)}%</td>
                    <td>
                      <a href={review.source_url} target="_blank" rel="noreferrer">
                        {review.source_domain}
                      </a>
                    </td>
                    <td>
                      <div className="action-row">
                        <button
                          className="icon-button ghost"
                          onClick={() => approveMergeReview(review.id)}
                          disabled={pending.mergeReviewId === review.id}
                          title="Approve merge"
                        >
                          {pending.mergeReviewId === review.id ? (
                            <Loader2 size={14} className="spin" />
                          ) : (
                            <Check size={14} />
                          )}
                        </button>
                        <button
                          className="icon-button danger"
                          onClick={() => rejectMergeReview(review.id)}
                          disabled={pending.mergeReviewId === review.id}
                          title="Reject merge"
                        >
                          {pending.mergeReviewId === review.id ? (
                            <Loader2 size={14} className="spin" />
                          ) : (
                            <X size={14} />
                          )}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>

          <h3>Recent Ingestion Jobs</h3>
          <table className="data-table compact">
            <thead>
              <tr>
                <th>Time</th>
                <th>Company</th>
                <th>Type</th>
                <th>Mode</th>
                <th>Status</th>
                <th>Result</th>
              </tr>
            </thead>
            <tbody>
              {ingestionJobs.length === 0 ? (
                <tr>
                  <td colSpan={6}>No ingestion jobs yet.</td>
                </tr>
              ) : (
                ingestionJobs.map((job) => (
                  <tr key={job.id}>
                    <td>{formatDate(job.created_at)}</td>
                    <td>{job.company_name || "-"}</td>
                    <td>{titleCase(job.job_type)}</td>
                    <td>{titleCase(job.run_mode)}</td>
                    <td>
                      <span className={`status ${job.status}`}>{job.status}</span>
                    </td>
                    <td>{job.error_message || job.result_summary || "-"}</td>
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
