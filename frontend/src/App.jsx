import { useEffect, useMemo, useState } from "react";
import {
  ArrowUpRight,
  Activity,
  AlertTriangle,
  BarChart3,
  Bot,
  Building2,
  ChevronDown,
  Check,
  CheckCircle2,
  ClipboardList,
  Database,
  Eye,
  Gauge,
  Globe,
  Layers3,
  Link2,
  Linkedin,
  MessageCircle,
  Radar,
  Loader2,
  Moon,
  Droplets,
  Newspaper,
  PlayCircle,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Snowflake,
  Sparkles,
  Sun,
  Target,
  Trash2,
  Wrench,
  X,
} from "lucide-react";

import { API_BASE_URL, api } from "./api";

const VIEWS = [
  { id: "briefing", label: "Briefing", icon: Sparkles },
  { id: "companies", label: "Competitors", icon: Building2 },
  { id: "signals", label: "Signals", icon: Radar },
  { id: "comparison", label: "Gaps", icon: Target },
  { id: "sources", label: "Sources", icon: Link2 },
  { id: "ops", label: "Ops Console", icon: Activity },
];

const THEME_OPTIONS = [
  { id: "light", label: "Light", icon: Sun },
  { id: "dark", label: "Dark", icon: Moon },
  { id: "liquid", label: "Liquid Glass", icon: Droplets },
  { id: "frosted", label: "Frosted Glass", icon: Snowflake },
  { id: "warm-frosted", label: "Warm Frosted", icon: Sun },
  { id: "heritage", label: "Heritage", icon: Sparkles },
];

const METRIC_WIDGETS = [
  { key: "companies", label: "Tracked Companies", icon: Building2 },
  { key: "sources", label: "Source URLs", icon: Link2 },
  { key: "features", label: "Detected Features", icon: ShieldCheck },
  { key: "tools", label: "Detected Tools", icon: Wrench },
  { key: "news", label: "News Articles", icon: Newspaper },
  { key: "enrichment", label: "Market Signals", icon: Radar },
  { key: "highClaims", label: "High-Confidence Claims", icon: Check },
];

const MAX_SOURCE_ROWS = 140;
const MAX_COMPANY_CARDS = 120;
const MAX_EVIDENCE_SOURCES = 80;
const MAX_COMPARISON_ROWS = 80;

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

function isGoogleNewsUrl(value) {
  if (!value) return false;
  try {
    const parsed = new URL(value);
    return parsed.hostname === "news.google.com" || parsed.hostname === "www.news.google.com";
  } catch {
    return false;
  }
}

function articleHref(item) {
  if (item?.id && isGoogleNewsUrl(item.article_url)) {
    return `${API_BASE_URL}/news/${item.id}/resolve`;
  }
  return item?.article_url || "#";
}

function articleLinkTitle(item) {
  if (!isGoogleNewsUrl(item?.article_url)) {
    return "Open article";
  }
  return "Open Google News article";
}

function truncateText(value, maxChars = 180) {
  if (!value) return { text: "-", fullText: "", truncated: false };
  const fullText = String(value).replace(/\s+/g, " ").trim();
  if (!fullText) return { text: "-", fullText: "", truncated: false };
  if (fullText.length <= maxChars) return { text: fullText, fullText, truncated: false };
  return { text: `${fullText.slice(0, maxChars).trimEnd()}...`, fullText, truncated: true };
}

function formatScore(value) {
  const score = Number(value || 0);
  return score.toFixed(2);
}

function scoreBand(score, maxScore) {
  if (!maxScore) return "Low";
  const ratio = score / maxScore;
  if (ratio >= 0.72) return "High";
  if (ratio >= 0.38) return "Medium";
  return "Low";
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

function parseJobResultSummary(value) {
  if (!value) return null;
  if (typeof value === "object") return value;
  if (typeof value !== "string") return { text: String(value) };
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" ? parsed : { text: value };
  } catch {
    return { text: value };
  }
}

function numericEntries(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return [];
  return Object.entries(value)
    .map(([key, count]) => [key, Number(count || 0)])
    .filter(([key, count]) => key && Number.isFinite(count));
}

function countTotal(entries) {
  return entries.reduce((sum, [, count]) => sum + count, 0);
}

function resultSourceLabel(source, connectorNames = {}) {
  return connectorNames[source] || sourceLabel(source, connectorNames);
}

function pluralize(count, singular, plural = `${singular}s`) {
  return `${count} ${count === 1 ? singular : plural}`;
}

function percent(value) {
  return `${Math.round(Number(value || 0) * 100)}%`;
}

function impactLabel(value) {
  if (value === "high") return "High impact";
  if (value === "medium") return "Medium impact";
  return "Low impact";
}

function urgencyLabel(value) {
  if (value === "this_week") return "This week";
  if (value === "low_priority") return "Low priority";
  return "Monitor";
}

function onboardingStatusLabel(value) {
  if (value === "complete") return "Complete";
  if (value === "in_progress") return "In progress";
  return "Pending";
}

function onboardingStatusIcon(value) {
  if (value === "complete") return CheckCircle2;
  if (value === "in_progress") return Loader2;
  return ClipboardList;
}

function coverageStatusLabel(value) {
  if (value === "healthy") return "Healthy";
  if (value === "needs_attention") return "Needs attention";
  return "Thin coverage";
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

function JobResultCell({ job, connectorNames }) {
  if (job.error_message) {
    return (
      <div className="job-result">
        <strong>Failed</strong>
        <span>{compactText(job.error_message, 180)}</span>
      </div>
    );
  }

  const result = parseJobResultSummary(job.result_summary);
  if (!result) {
    return <span className="muted">No result yet</span>;
  }
  if (result.text) {
    return <span>{compactText(result.text, 220)}</span>;
  }

  const newsEntries = numericEntries(result.news);
  const enrichmentEntries = numericEntries(result.enrichment);
  const newsTotal = countTotal(newsEntries);
  const enrichmentTotal = countTotal(enrichmentEntries);
  const visibleBreakdown = [...newsEntries, ...enrichmentEntries]
    .filter(([, count]) => count > 0)
    .slice(0, 6);
  const zeroCheckedCount = [...newsEntries, ...enrichmentEntries].filter(([, count]) => count === 0).length;

  return (
    <div className="job-result">
      <div className="job-result-metrics">
        <span>
          <strong>{newsTotal}</strong>
          News
        </span>
        <span>
          <strong>{enrichmentTotal}</strong>
          Connector items
        </span>
      </div>
      {newsTotal + enrichmentTotal === 0 ? (
        <span className="muted">No new relevant items found.</span>
      ) : (
        <div className="job-result-pills">
          {visibleBreakdown.map(([source, count]) => (
            <span key={source} className="job-result-pill">
              {resultSourceLabel(source, connectorNames)}
              <strong>{count}</strong>
            </span>
          ))}
        </div>
      )}
      {zeroCheckedCount > 0 ? (
        <span className="job-result-note">{pluralize(zeroCheckedCount, "source")} checked with no additions</span>
      ) : null}
    </div>
  );
}

function ExpandableCellText({ text, maxChars = 170 }) {
  const [expanded, setExpanded] = useState(false);
  const snippet = useMemo(() => truncateText(text, maxChars), [text, maxChars]);

  if (!snippet.fullText) {
    return <span className="muted">-</span>;
  }

  if (!snippet.truncated) {
    return <span>{snippet.fullText}</span>;
  }

  return (
    <span className="expandable-text">
      <span>{expanded ? snippet.fullText : snippet.text}</span>
      <button
        type="button"
        className="read-more-link"
        aria-expanded={expanded}
        onClick={() => setExpanded((current) => !current)}
      >
        {expanded ? "Show less" : "Read more"}
      </button>
    </span>
  );
}

function InsightCard({ insight, connectorNames, onOpenCompany }) {
  return (
    <article className={`priority-card impact-${insight.impact || "low"}`}>
      <div className="priority-card-main">
        <div>
          <div className="priority-card-meta">
            <span>{titleCase(insight.insight_type || "signal")}</span>
            <span>{impactLabel(insight.impact)}</span>
            <span>{percent(insight.confidence)} confidence</span>
            <span>{urgencyLabel(insight.urgency)}</span>
          </div>
          <h3>{insight.headline}</h3>
          <p>{insight.summary}</p>
        </div>
        {insight.competitor_id ? (
          <button type="button" className="icon-button compact" onClick={() => onOpenCompany(insight.competitor_id)}>
            <Eye size={14} />
            Evidence
          </button>
        ) : null}
      </div>
      <div className="analyst-note">
        <strong>Recommended action</strong>
        <span>{insight.recommended_action}</span>
      </div>
      {insight.evidence?.length ? (
        <div className="evidence-strip">
          {insight.evidence.slice(0, 3).map((item) => (
            <a key={`${insight.id}-${item.source_type}-${item.id}`} href={item.url} target="_blank" rel="noreferrer">
              <span>{sourceLabel(item.source_type, connectorNames)}</span>
              <strong>{compactText(item.title, 92)}</strong>
            </a>
          ))}
        </div>
      ) : (
        <span className="muted">No direct evidence attached yet.</span>
      )}
    </article>
  );
}

function OnboardingChecklist({ steps }) {
  if (!steps?.length) return null;
  return (
    <section className="surface onboarding-panel">
      <div className="panel-title-row">
        <div>
          <span className="section-kicker">First run setup</span>
          <h2>Progressive Onboarding</h2>
        </div>
        <ClipboardList size={18} />
      </div>
      <div className="onboarding-list">
        {steps.map((step) => {
          const StatusIcon = onboardingStatusIcon(step.status);
          return (
            <div key={step.id} className={`onboarding-step ${step.status}`}>
              <span className="onboarding-step-icon">
                <StatusIcon size={15} className={step.status === "in_progress" ? "spin-soft" : ""} />
              </span>
              <div>
                <strong>{step.label}</strong>
                <span>{step.description}</span>
              </div>
              <em>{onboardingStatusLabel(step.status)}</em>
            </div>
          );
        })}
      </div>
    </section>
  );
}

function QuickStartWizard({
  rows,
  onChange,
  onSubmit,
  pending,
  competitorCount,
}) {
  return (
    <section className="surface quickstart-panel">
      <div className="panel-title-row">
        <div>
          <span className="section-kicker">Quick start</span>
          <h2>Which 3 competitors should Concentric monitor?</h2>
          <p>Add direct company, product, docs, or news URLs. The system will extract entities and generate the first briefing.</p>
        </div>
        <Target size={18} />
      </div>
      <form className="quickstart-form" onSubmit={onSubmit}>
        {rows.map((row, index) => (
          <div key={`quickstart-${index}`} className="quickstart-row">
            <span>{index + 1}</span>
            <input
              value={row.name}
              onChange={(event) => onChange(index, "name", event.target.value)}
              placeholder="Competitor name"
            />
            <input
              value={row.url}
              onChange={(event) => onChange(index, "url", event.target.value)}
              placeholder="https://competitor.com"
            />
          </div>
        ))}
        <div className="quickstart-actions">
          <span>{competitorCount} competitors tracked today</span>
          <button type="submit" disabled={pending}>
            {pending ? <Loader2 size={16} className="spin" /> : <Plus size={16} />}
            Generate Briefing
          </button>
        </div>
      </form>
    </section>
  );
}

function CoverageHealthPanel({ coverage }) {
  if (!coverage?.length) return null;
  return (
    <section className="surface coverage-panel">
      <div className="panel-title-row">
        <div>
          <span className="section-kicker">Trust layer</span>
          <h2>Coverage Health</h2>
        </div>
        <ShieldCheck size={18} />
      </div>
      <div className="coverage-list">
        {coverage.slice(0, 6).map((item) => (
          <article key={item.company_id} className={`coverage-row ${item.status}`}>
            <div>
              <strong>{item.company_name}</strong>
              <span>{item.note}</span>
              {item.missing_sources?.length ? (
                <small>Missing: {item.missing_sources.slice(0, 3).join(", ")}</small>
              ) : null}
            </div>
            <div className="coverage-score">
              <strong>{item.coverage_score}</strong>
              <span>{coverageStatusLabel(item.status)}</span>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function AskConcentricPanel({
  suggestions,
  question,
  answer,
  pending,
  onQuestionChange,
  onAsk,
  onUseSuggestion,
}) {
  return (
    <section className="surface ask-panel">
      <div className="panel-title-row">
        <div>
          <span className="section-kicker">Analyst layer</span>
          <h2>Ask Concentric AI</h2>
        </div>
        <Bot size={18} />
      </div>
      <form className="ask-form" onSubmit={onAsk}>
        <div className="ask-input-shell">
          <MessageCircle size={16} />
          <input
            value={question}
            onChange={(event) => onQuestionChange(event.target.value)}
            placeholder="Ask about competitor moves, gaps, evidence, or source coverage"
          />
        </div>
        <button type="submit" disabled={pending || question.trim().length < 3}>
          {pending ? <Loader2 size={16} className="spin" /> : <Sparkles size={16} />}
          Ask
        </button>
      </form>
      <div className="ask-suggestions">
        {(suggestions || []).slice(0, 4).map((item) => (
          <button key={item} type="button" onClick={() => onUseSuggestion(item)}>
            {item}
          </button>
        ))}
      </div>
      {answer ? (
        <div className="ask-answer">
          <strong>{answer.answer}</strong>
          <span>{answer.why_it_matters}</span>
          <p>{answer.recommended_next_step}</p>
          {answer.evidence?.length ? (
            <div className="evidence-strip">
              {answer.evidence.slice(0, 3).map((item) => (
                <a key={`ask-${item.source_type}-${item.id}`} href={item.url} target="_blank" rel="noreferrer">
                  <span>{titleCase(item.source_type)}</span>
                  <strong>{compactText(item.title, 90)}</strong>
                </a>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function App() {
  const [activeView, setActiveView] = useState("briefing");
  const [urlInput, setUrlInput] = useState("");
  const [sources, setSources] = useState([]);
  const [companies, setCompanies] = useState([]);
  const [connectors, setConnectors] = useState([]);
  const [mergeReviews, setMergeReviews] = useState([]);
  const [ingestionJobs, setIngestionJobs] = useState([]);
  const [comparison, setComparison] = useState(null);
  const [briefing, setBriefing] = useState(null);
  const [selectedCompanyId, setSelectedCompanyId] = useState(null);
  const [selectedCompany, setSelectedCompany] = useState(null);
  const [themeMode, setThemeMode] = useState("dark");
  const [companyQuery, setCompanyQuery] = useState("");
  const [sourceQuery, setSourceQuery] = useState("");
  const [askQuestion, setAskQuestion] = useState("");
  const [askAnswer, setAskAnswer] = useState(null);
  const [quickStartRows, setQuickStartRows] = useState([
    { name: "", url: "" },
    { name: "", url: "" },
    { name: "", url: "" },
  ]);
  const [decisionPolicy, setDecisionPolicy] = useState(null);
  const [autoDiscoverResult, setAutoDiscoverResult] = useState(null);
  const [opsLoaded, setOpsLoaded] = useState(false);
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
    quickStart: false,
    ask: false,
  });

  const resolveSelectedCompanyId = (currentId, nextCompanies) => {
    if (nextCompanies.length === 0) return null;
    if (currentId && nextCompanies.some((company) => company.id === currentId)) {
      return currentId;
    }
    return nextCompanies[0].id;
  };

  const loadOverview = async ({ showLoading = true } = {}) => {
    if (showLoading) {
      setLoading(true);
    }
    setError("");
    try {
      const [nextSources, nextCompanies, nextConnectors, nextDecisionPolicy] = await Promise.all([
        api.listSources(),
        api.listCompanies(),
        api.listEnrichmentConnectors(),
        api.getDecisionPolicy(),
      ]);
      const nextSelectedCompanyId = resolveSelectedCompanyId(selectedCompanyId, nextCompanies);
      setSources(nextSources);
      setCompanies(nextCompanies);
      setConnectors(nextConnectors);
      setDecisionPolicy(nextDecisionPolicy);
      setSelectedCompanyId(nextSelectedCompanyId);
      return { selectedCompanyId: nextSelectedCompanyId };
    } catch (err) {
      setError(err.message || "Failed to load data.");
      return null;
    } finally {
      if (showLoading) {
        setLoading(false);
      }
    }
  };

  const loadBriefing = async ({ showLoading = true } = {}) => {
    if (showLoading) {
      setLoading(true);
    }
    setError("");
    try {
      const nextBriefing = await api.getBriefing();
      setBriefing(nextBriefing);
      return nextBriefing;
    } catch (err) {
      setError(err.message || "Failed to load briefing.");
      return null;
    } finally {
      if (showLoading) {
        setLoading(false);
      }
    }
  };

  const loadComparison = async ({ showLoading = true } = {}) => {
    if (showLoading) {
      setLoading(true);
    }
    setError("");
    try {
      const nextComparison = await api.getComparison();
      setComparison(nextComparison);
      return nextComparison;
    } catch (err) {
      setError(err.message || "Failed to load comparison.");
      return null;
    } finally {
      if (showLoading) {
        setLoading(false);
      }
    }
  };

  const loadOps = async ({ showLoading = true } = {}) => {
    if (showLoading) {
      setLoading(true);
    }
    setError("");
    try {
      const [nextMergeReviews, nextJobs] = await Promise.all([
        api.listMergeReviews("pending"),
        api.listIngestionJobs(50),
      ]);
      setMergeReviews(nextMergeReviews);
      setIngestionJobs(nextJobs);
      setOpsLoaded(true);
      return true;
    } catch (err) {
      setError(err.message || "Failed to load operations.");
      return false;
    } finally {
      if (showLoading) {
        setLoading(false);
      }
    }
  };

  const loadCompanyDetail = async (companyId, { showLoading = false } = {}) => {
    if (!companyId) {
      setSelectedCompany(null);
      return null;
    }
    if (showLoading) {
      setLoading(true);
    }
    try {
      const detail = await api.getCompany(companyId);
      setSelectedCompany(detail);
      return detail;
    } catch (err) {
      setError(err.message || "Failed to load company detail.");
      return null;
    } finally {
      if (showLoading) {
        setLoading(false);
      }
    }
  };

  const refreshActiveViewData = async (companyId = selectedCompanyId, { showLoading = false } = {}) => {
    if (activeView === "briefing" || activeView === "signals") {
      return loadBriefing({ showLoading });
    }
    if (activeView === "companies") {
      return loadCompanyDetail(companyId, { showLoading });
    }
    if (activeView === "comparison") {
      return loadComparison({ showLoading });
    }
    if (activeView === "ops") {
      return loadOps({ showLoading });
    }
    return null;
  };

  const refreshCurrentView = async () => {
    setLoading(true);
    setError("");
    try {
      const [overview] = await Promise.all([
        loadOverview({ showLoading: false }),
        activeView === "briefing" || activeView === "signals"
          ? Promise.resolve(null)
          : loadBriefing({ showLoading: false }),
      ]);
      await refreshActiveViewData(overview?.selectedCompanyId ?? selectedCompanyId, {
        showLoading: false,
      });
    } catch (err) {
      setError(err.message || "Failed to load data.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const stored = window.localStorage.getItem("cci-theme");
    if (THEME_OPTIONS.some((theme) => theme.id === stored)) {
      setThemeMode(stored);
      return;
    }
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    setThemeMode(prefersDark ? "dark" : "light");
  }, []);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", themeMode);
    window.localStorage.setItem("cci-theme", themeMode);
  }, [themeMode]);

  useEffect(() => {
    loadOverview();
    loadBriefing();
  }, []);

  useEffect(() => {
    if (activeView !== "companies") return;
    if (!selectedCompanyId && companies.length > 0) {
      setSelectedCompanyId(companies[0].id);
      return;
    }
    if (selectedCompanyId) {
      loadCompanyDetail(selectedCompanyId, { showLoading: true });
    } else {
      setSelectedCompany(null);
    }
  }, [activeView, selectedCompanyId, companies]);

  useEffect(() => {
    if ((activeView === "briefing" || activeView === "signals") && !briefing) {
      loadBriefing();
    }
    if (activeView === "comparison" && !comparison) {
      loadComparison();
    }
    if (activeView === "ops" && !opsLoaded) {
      loadOps();
    }
  }, [activeView, briefing, comparison, opsLoaded]);

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

  const filteredSources = useMemo(() => {
    const query = sourceQuery.trim().toLowerCase();
    if (!query) {
      return sources;
    }
    return sources.filter((source) => {
      const haystack = [
        source.url,
        source.domain,
        source.company_name,
        source.source_type,
        source.status,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(query);
    });
  }, [sources, sourceQuery]);

  const visibleSources = useMemo(() => filteredSources.slice(0, MAX_SOURCE_ROWS), [filteredSources]);
  const hiddenSourceCount = Math.max(0, filteredSources.length - visibleSources.length);

  const visibleCompanies = useMemo(
    () => filteredCompanies.slice(0, MAX_COMPANY_CARDS),
    [filteredCompanies],
  );
  const hiddenCompanyCount = Math.max(0, filteredCompanies.length - visibleCompanies.length);

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

  const comparisonSummary = useMemo(() => {
    const competitors = comparison?.competitors || [];
    const maxGapScore = competitors.reduce((max, row) => Math.max(max, row.gap_score || 0), 0);
    const totalFeatureGaps = competitors.reduce(
      (sum, row) => sum + (row.competitor_only_features?.length || 0),
      0,
    );
    const totalToolGaps = competitors.reduce(
      (sum, row) => sum + (row.competitor_only_tools?.length || 0),
      0,
    );
    const totalMarketSignals = competitors.reduce(
      (sum, row) => sum + (row.market_signal_count ?? row.top_news?.length ?? 0),
      0,
    );
    const averageGap =
      competitors.length === 0
        ? 0
        : competitors.reduce((sum, row) => sum + (row.gap_score || 0), 0) / competitors.length;
    return {
      averageGap,
      competitors,
      maxGapScore,
      topCompetitor: competitors[0],
      totalFeatureGaps,
      totalMarketSignals,
      totalToolGaps,
    };
  }, [comparison]);

  const visibleComparisonRows = useMemo(
    () => comparisonSummary.competitors.slice(0, MAX_COMPARISON_ROWS),
    [comparisonSummary.competitors],
  );
  const hiddenComparisonCount = Math.max(
    0,
    comparisonSummary.competitors.length - visibleComparisonRows.length,
  );

  const selectedEvidenceSources = useMemo(
    () => (selectedCompany?.sources || []).slice(0, MAX_EVIDENCE_SOURCES),
    [selectedCompany],
  );
  const hiddenEvidenceSourceCount = Math.max(
    0,
    (selectedCompany?.sources?.length || 0) - selectedEvidenceSources.length,
  );
  const selectedTheme = useMemo(
    () => THEME_OPTIONS.find((theme) => theme.id === themeMode) || THEME_OPTIONS[0],
    [themeMode],
  );
  const SelectedThemeIcon = selectedTheme.icon;
  const briefingInsights = briefing?.top_insights || [];
  const urgentSignals = briefing?.urgent_signals || [];
  const shouldShowQuickStart =
    (briefing?.totals?.companies || companies.filter((company) => company.company_name !== "Concentric AI").length) < 3;

  const openCompanyFromInsight = async (companyId) => {
    setSelectedCompanyId(companyId);
    setActiveView("companies");
    await loadCompanyDetail(companyId, { showLoading: true });
  };

  const updateQuickStartRow = (index, field, value) => {
    setQuickStartRows((current) =>
      current.map((row, rowIndex) => (rowIndex === index ? { ...row, [field]: value } : row)),
    );
  };

  const submitQuickStart = async (event) => {
    event.preventDefault();
    const rowsToAdd = quickStartRows
      .map((row) => ({ ...row, url: row.url.trim(), name: row.name.trim() }))
      .filter((row) => row.url);
    if (rowsToAdd.length === 0) {
      setError("Add at least one competitor URL to generate a briefing.");
      return;
    }

    setError("");
    setPending((prev) => ({ ...prev, quickStart: true }));
    try {
      for (const row of rowsToAdd) {
        await api.addSource({ url: row.url });
      }
      setQuickStartRows([
        { name: "", url: "" },
        { name: "", url: "" },
        { name: "", url: "" },
      ]);
      setComparison(null);
      setOpsLoaded(false);
      await refreshCurrentView();
    } catch (err) {
      setError(err.message || "Failed to add competitor sources.");
    } finally {
      setPending((prev) => ({ ...prev, quickStart: false }));
    }
  };

  const askConcentric = async (event) => {
    event.preventDefault();
    if (askQuestion.trim().length < 3) return;
    setError("");
    setPending((prev) => ({ ...prev, ask: true }));
    try {
      const response = await api.askConcentric({ question: askQuestion.trim() });
      setAskAnswer(response);
    } catch (err) {
      setError(err.message || "Failed to ask Concentric AI.");
    } finally {
      setPending((prev) => ({ ...prev, ask: false }));
    }
  };

  const addSource = async (event) => {
    event.preventDefault();
    setError("");
    setPending((prev) => ({ ...prev, adding: true }));
    try {
      await api.addSource({ url: urlInput.trim() });
      setUrlInput("");
      setComparison(null);
      setOpsLoaded(false);
      await refreshCurrentView();
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
      setComparison(null);
      setOpsLoaded(false);
      await refreshCurrentView();
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
      setComparison(null);
      setOpsLoaded(false);
      await refreshCurrentView();
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
      setComparison(null);
      setOpsLoaded(false);
      await refreshCurrentView();
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
      setComparison(null);
      setOpsLoaded(false);
      await loadOverview({ showLoading: false });
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
      setComparison(null);
      setOpsLoaded(false);
      await loadOverview({ showLoading: false });
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
      setComparison(null);
      setOpsLoaded(false);
      await refreshCurrentView();
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
      setOpsLoaded(false);
      await refreshCurrentView();
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
      setComparison(null);
      setOpsLoaded(false);
      await refreshCurrentView();
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
            Start with today's strategic briefing, then drill into competitor evidence only when
            a signal needs validation.
          </p>
        </div>
        <div className="header-actions">
          <div className="theme-switcher">
            <SelectedThemeIcon className="theme-select-icon" size={15} aria-hidden="true" />
            <select
              className="theme-select"
              value={themeMode}
              onChange={(event) => setThemeMode(event.target.value)}
              aria-label="Theme selector"
              title="Theme selector"
            >
              {THEME_OPTIONS.map((theme) => (
                <option key={theme.id} value={theme.id}>
                  {theme.label}
                </option>
              ))}
            </select>
            <ChevronDown className="theme-select-chevron" size={15} aria-hidden="true" />
          </div>
          <button className="icon-button" onClick={refreshCurrentView} title="Refresh current view">
            <RefreshCw size={16} />
            Refresh
          </button>
        </div>
      </header>

      <nav className="tab-bar">
        {VIEWS.map((view) => {
          const ViewIcon = view.icon;
          return (
            <button
              key={view.id}
              className={activeView === view.id ? "active" : ""}
              type="button"
              onClick={() => setActiveView(view.id)}
            >
              <ViewIcon size={15} />
              {view.label}
            </button>
          );
        })}
      </nav>

      {error ? <p className="error-banner">{error}</p> : null}
      {loading ? <p className="loading-banner">Loading intelligence graph...</p> : null}

      {activeView === "briefing" ? (
        <main className="briefing-workspace">
          <section className="surface priority-briefing">
            <div className="briefing-head">
              <div>
                <span className="section-kicker">Daily intelligence briefing</span>
                <h2>What should I focus on today?</h2>
                <p>{briefing?.summary || "Loading today's briefing from your competitor graph."}</p>
              </div>
              <div className="briefing-date">
                <span>{formatDate(briefing?.date)}</span>
                <strong>{urgentSignals.length}</strong>
                <small>priority signals</small>
              </div>
            </div>

            {briefingInsights.length === 0 ? (
              <div className="empty-briefing">
                <Sparkles size={18} />
                <div>
                  <strong>Your first briefing is waiting for competitor evidence.</strong>
                  <span>Add competitor URLs below. Concentric will turn the first scrape into prioritized signals.</span>
                </div>
              </div>
            ) : (
              <div className="priority-list">
                {briefingInsights.slice(0, 3).map((insight, index) => (
                  <div key={insight.id} className={`priority-bullet impact-${insight.impact || "low"}`}>
                    <span>{index + 1}</span>
                    <div>
                      <strong>{insight.headline}</strong>
                      <p>{insight.summary}</p>
                      <small>
                        {impactLabel(insight.impact)} • {percent(insight.confidence)} confidence •{" "}
                        {urgencyLabel(insight.urgency)}
                      </small>
                    </div>
                    {insight.competitor_id ? (
                      <button type="button" className="icon-button ghost text" onClick={() => openCompanyFromInsight(insight.competitor_id)}>
                        <Eye size={14} />
                        Evidence
                      </button>
                    ) : null}
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className={`briefing-action-grid ${shouldShowQuickStart ? "" : "single"}`}>
            {shouldShowQuickStart ? (
              <QuickStartWizard
                rows={quickStartRows}
                onChange={updateQuickStartRow}
                onSubmit={submitQuickStart}
                pending={pending.quickStart}
                competitorCount={briefing?.totals?.companies || 0}
              />
            ) : null}
            <OnboardingChecklist steps={briefing?.onboarding || []} />
          </section>

          <AskConcentricPanel
            suggestions={briefing?.ask_suggestions || []}
            question={askQuestion}
            answer={askAnswer}
            pending={pending.ask}
            onQuestionChange={setAskQuestion}
            onAsk={askConcentric}
            onUseSuggestion={(suggestion) => {
              setAskQuestion(suggestion);
              setAskAnswer(null);
            }}
          />

          <section className="metric-grid briefing-metrics">
            {METRIC_WIDGETS.map((metric) => {
              const MetricIcon = metric.icon;
              return (
                <div className="metric-card" key={metric.key}>
                  <div className="metric-card-head">
                    <span className="metric-icon" aria-hidden="true">
                      <MetricIcon size={14} />
                    </span>
                    <span>{metric.label}</span>
                  </div>
                  <strong>{totals[metric.key]}</strong>
                </div>
              );
            })}
          </section>

          <section className="briefing-action-grid">
            <section className="surface signal-panel">
              <div className="panel-title-row">
                <div>
                  <span className="section-kicker">Priority feed</span>
                  <h2>Analyst Signals</h2>
                </div>
                <AlertTriangle size={18} />
              </div>
              <div className="priority-card-list">
                {briefingInsights.length === 0 ? (
                  <p className="muted">No analyst signals yet.</p>
                ) : (
                  briefingInsights.map((insight) => (
                    <InsightCard
                      key={insight.id}
                      insight={insight}
                      connectorNames={connectorNames}
                      onOpenCompany={openCompanyFromInsight}
                    />
                  ))
                )}
              </div>
            </section>
            <CoverageHealthPanel coverage={briefing?.coverage_health || []} />
          </section>

          {briefing?.recommended_actions?.length ? (
            <section className="surface recommendations-panel">
              <div className="panel-title-row">
                <div>
                  <span className="section-kicker">Next best actions</span>
                  <h2>Recommended Response</h2>
                </div>
                <Check size={18} />
              </div>
              <div className="recommendation-list">
                {briefing.recommended_actions.map((item) => (
                  <article key={item.id} className={`recommendation-row impact-${item.impact}`}>
                    <span>{titleCase(item.recommendation_type)}</span>
                    <strong>{item.action}</strong>
                    <small>
                      {impactLabel(item.impact)} • {urgencyLabel(item.urgency)} • Owner: {titleCase(item.owner_role)}
                    </small>
                  </article>
                ))}
              </div>
            </section>
          ) : null}
        </main>
      ) : null}

      {activeView === "signals" ? (
        <section className="surface signal-panel full">
          <div className="panel-title-row">
            <div>
              <span className="section-kicker">Progressive disclosure</span>
              <h2>Signals and Evidence</h2>
              <p>Start with the analyst interpretation, then inspect the source rows that support it.</p>
            </div>
            <Radar size={18} />
          </div>
          <div className="priority-card-list two-col">
            {briefingInsights.length === 0 ? (
              <p className="muted">No strategic signals yet. Add competitor sources or run enrichment.</p>
            ) : (
              briefingInsights.map((insight) => (
                <InsightCard
                  key={insight.id}
                  insight={insight}
                  connectorNames={connectorNames}
                  onOpenCompany={openCompanyFromInsight}
                />
              ))
            )}
          </div>
        </section>
      ) : null}

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

          <div className="table-filter-bar">
            <input
              className="source-search"
              value={sourceQuery}
              onChange={(event) => setSourceQuery(event.target.value)}
              placeholder="Filter sources by URL, company, type, or status"
            />
            <span className="muted">
              {filteredSources.length} of {sources.length} URLs
            </span>
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
              {filteredSources.length === 0 ? (
                <tr>
                  <td colSpan={8}>{sources.length === 0 ? "No source URLs yet." : "No source URLs match this filter."}</td>
                </tr>
              ) : (
                visibleSources.map((source) => (
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
              {hiddenSourceCount > 0 ? (
                <tr className="table-limit-row">
                  <td colSpan={8}>
                    Showing first {visibleSources.length} of {filteredSources.length} matching URLs. Refine the filter
                    for targeted inspection.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </section>
      ) : null}

      {activeView === "companies" ? (
        <section className="two-pane">
          <aside className="surface list-pane">
            <div className="panel-head">
              <div>
                <h2 className="heading-with-icon">
                  <Building2 size={18} />
                  Company Entities
                </h2>
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
                <>
                  {visibleCompanies.map((company) => (
                    <button
                      key={company.id}
                      type="button"
                      className={`company-card ${selectedCompanyId === company.id ? "active" : ""}`}
                      onClick={() => setSelectedCompanyId(company.id)}
                    >
                      <div className="company-card-head">
                        <div className="company-card-identity">
                          <span className="company-avatar" aria-hidden="true">
                            {(company.company_name || "?").charAt(0).toUpperCase()}
                          </span>
                          <div className="company-card-title">
                            <strong>{company.company_name}</strong>
                            <span>
                              <Globe size={12} />
                              <span className="company-domain-text">{company.primary_domain || "-"}</span>
                            </span>
                          </div>
                        </div>
                        <span className="company-card-score">{company.high_confidence_claim_count || 0}</span>
                      </div>
                      <div className="company-card-metrics">
                        <span>
                          <Link2 size={12} />
                          {company.source_count} sources
                        </span>
                        <span>
                          <Newspaper size={12} />
                          {company.news_count} signals
                        </span>
                        <span>
                          <Linkedin size={12} />
                          {company.linkedin_news_count} LinkedIn
                        </span>
                        <span>
                          <Database size={12} />
                          {company.enrichment_news_count || 0} connectors
                        </span>
                      </div>
                    </button>
                  ))}
                  {hiddenCompanyCount > 0 ? (
                    <p className="list-limit-note muted">
                      Showing first {visibleCompanies.length} matches. Search by name or domain to narrow the list.
                    </p>
                  ) : null}
                </>
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
                    <h2 className="heading-with-icon">
                      <Building2 size={18} />
                      {selectedCompany.company_name}
                    </h2>
                    <p className="company-summary">{cleanSummary(selectedCompany.description)}</p>
                    <div className="company-links">
                      {selectedCompany.website_url ? (
                        <a href={selectedCompany.website_url} target="_blank" rel="noreferrer" className="inline-link">
                          <Globe size={14} />
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
                    <span className="kpi-label">
                      <Globe size={13} />
                      Primary Domain
                    </span>
                    <strong>{selectedCompany.primary_domain || "-"}</strong>
                  </div>
                  <div className="kpi-item">
                    <span className="kpi-label">
                      <Link2 size={13} />
                      Linked Sources
                    </span>
                    <strong>{selectedCompany.source_count}</strong>
                  </div>
                  <div className="kpi-item">
                    <span className="kpi-label">
                      <Newspaper size={13} />
                      Total News
                    </span>
                    <strong>{selectedCompany.news_count}</strong>
                  </div>
                  <div className="kpi-item">
                    <span className="kpi-label">
                      <Database size={13} />
                      Connector Signals
                    </span>
                    <strong>{selectedCompany.enrichment_news_count || 0}</strong>
                  </div>
                  <div className="kpi-item">
                    <span className="kpi-label">
                      <Linkedin size={13} />
                      LinkedIn Signals
                    </span>
                    <strong>{selectedCompany.linkedin_news_count || 0}</strong>
                  </div>
                  <div className="kpi-item">
                    <span className="kpi-label">
                      <Sparkles size={13} />
                      High-Confidence Claims
                    </span>
                    <strong>{selectedCompany.high_confidence_claim_count || 0}</strong>
                  </div>
                </div>

                <div className="signal-columns">
                  <div>
                    <h3 className="heading-with-icon">
                      <ShieldCheck size={15} />
                      Supported Features
                    </h3>
                    <SignalPills items={selectedCompany.features} />
                  </div>
                  <div>
                    <h3 className="heading-with-icon">
                      <Wrench size={15} />
                      Observed Tools
                    </h3>
                    <SignalPills items={selectedCompany.tools} />
                  </div>
                </div>

                <h3 className="heading-with-icon">
                  <Check size={15} />
                  Evidence-Backed Claims
                </h3>
                <table className="data-table compact claims-table">
                  <thead>
                    <tr>
                      <th>Claim</th>
                      <th>Type</th>
                      <th>Confidence</th>
                      <th>Status</th>
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
                        <td colSpan={9}>No evidence-backed claims yet.</td>
                      </tr>
                    ) : (
                      selectedCompany.claims.slice(0, 25).map((claim) => {
                        const isVerified =
                          claim.confidence >= (decisionPolicy?.high_confidence_threshold ?? 0.8);
                        return (
                          <tr key={claim.id}>
                            <td>{claim.claim_value}</td>
                            <td>{titleCase(claim.claim_type)}</td>
                            <td>{Math.round(claim.confidence * 100)}%</td>
                            <td>
                              <span className={`status ${isVerified ? "verified" : "observed"}`}>
                                {isVerified ? "Verified" : "Observed"}
                              </span>
                            </td>
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
                        );
                      })
                    )}
                  </tbody>
                </table>

                <h3 className="heading-with-icon">
                  <Radar size={15} />
                  Market Signal Decisioning
                </h3>
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
                          <td>
                            <ExpandableCellText text={row.basis} maxChars={160} />
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>

                <h3 className="heading-with-icon">
                  <Link2 size={15} />
                  Evidence Sources
                </h3>
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
                      selectedEvidenceSources.map((source) => (
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
                    {hiddenEvidenceSourceCount > 0 ? (
                      <tr className="table-limit-row">
                        <td colSpan={5}>
                          Showing first {selectedEvidenceSources.length} of {selectedCompany.sources.length} evidence
                          sources.
                        </td>
                      </tr>
                    ) : null}
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
                        href={articleHref(item)}
                        target="_blank"
                        rel="noreferrer"
                        title={articleLinkTitle(item)}
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
        <section className="surface comparison-surface">
          <div className="comparison-hero">
            <div>
              <h2 className="heading-with-icon">
                <Target size={18} />
                Competitor Gaps vs {comparison.baseline_company_name}
              </h2>
              <p className="section-subtitle">
                Prioritized by differentiated features, observed tools, and market signal volume so product gaps are
                visible without opening every company profile.
              </p>
            </div>
            <div className="score-formula">
              <Gauge size={16} />
              <span>Gap score</span>
              <strong>features x1.8 + tools x1.2 + signals x0.15</strong>
            </div>
          </div>

          <div className="gap-overview-grid">
            <article className="insight-card">
              <span>
                <Target size={14} />
                Top Gap
              </span>
              <strong>{comparisonSummary.topCompetitor?.company_name || "-"}</strong>
              <small>{formatScore(comparisonSummary.topCompetitor?.gap_score)} score</small>
            </article>
            <article className="insight-card">
              <span>
                <Gauge size={14} />
                Average Gap
              </span>
              <strong>{formatScore(comparisonSummary.averageGap)}</strong>
              <small>{comparisonSummary.competitors.length} competitors ranked</small>
            </article>
            <article className="insight-card">
              <span>
                <Layers3 size={14} />
                Product Gaps
              </span>
              <strong>{comparisonSummary.totalFeatureGaps + comparisonSummary.totalToolGaps}</strong>
              <small>
                {comparisonSummary.totalFeatureGaps} features / {comparisonSummary.totalToolGaps} tools
              </small>
            </article>
            <article className="insight-card">
              <span>
                <Radar size={14} />
                Market Signals
              </span>
              <strong>{comparisonSummary.totalMarketSignals}</strong>
              <small>news and connector evidence</small>
            </article>
          </div>

          <table className="data-table comparison-table">
            <thead>
              <tr>
                <th>Competitor</th>
                <th>Gap Score</th>
                <th>Score Drivers</th>
                <th>Features Concentric Lacks</th>
                <th>Tools Concentric Lacks</th>
                <th>Latest Market Signals</th>
              </tr>
            </thead>
            <tbody>
              {comparisonSummary.competitors.length === 0 ? (
                <tr>
                  <td colSpan={6}>No competitor profiles yet.</td>
                </tr>
              ) : (
                visibleComparisonRows.map((row) => {
                  const scorePercent = comparisonSummary.maxGapScore
                    ? Math.max(4, Math.round((row.gap_score / comparisonSummary.maxGapScore) * 100))
                    : 0;
                  const featureImpact =
                    row.feature_gap_score ?? (row.competitor_only_features?.length || 0) * 1.8;
                  const toolImpact = row.tool_gap_score ?? (row.competitor_only_tools?.length || 0) * 1.2;
                  const signalImpact = row.market_signal_score ?? (row.market_signal_count || 0) * 0.15;
                  return (
                    <tr key={row.company_id}>
                      <td>
                        <div className="competitor-cell">
                          <strong>{row.company_name}</strong>
                          <div className="competitor-meta">
                            {row.linkedin_url ? (
                              <a href={row.linkedin_url} target="_blank" rel="noreferrer" className="inline-link">
                                <Linkedin size={12} />
                                LinkedIn
                              </a>
                            ) : null}
                            <span>{row.shared_feature_count ?? row.shared_features?.length ?? 0} shared features</span>
                            <span>{row.shared_tool_count ?? row.shared_tools?.length ?? 0} shared tools</span>
                          </div>
                        </div>
                      </td>
                      <td>
                        <div className="score-stack">
                          <div className="score-line">
                            <strong>{formatScore(row.gap_score)}</strong>
                            <span>{scoreBand(row.gap_score, comparisonSummary.maxGapScore)} gap</span>
                          </div>
                          <div className="score-bar" aria-hidden="true">
                            <span style={{ width: `${scorePercent}%` }} />
                          </div>
                        </div>
                      </td>
                      <td>
                        <div className="driver-stack">
                          <span>
                            <Layers3 size={12} />
                            Features <strong>{formatScore(featureImpact)}</strong>
                          </span>
                          <span>
                            <Wrench size={12} />
                            Tools <strong>{formatScore(toolImpact)}</strong>
                          </span>
                          <span>
                            <Radar size={12} />
                            Signals <strong>{formatScore(signalImpact)}</strong>
                          </span>
                        </div>
                      </td>
                      <td>
                        <SignalPills items={row.competitor_only_features.slice(0, 8)} />
                      </td>
                      <td>
                        <SignalPills items={row.competitor_only_tools.slice(0, 8)} />
                      </td>
                      <td>
                        <div className="news-mini">
                          {row.top_news.slice(0, 3).map((news) => {
                            const title = truncateText(news.title, 120);
                            return (
                              <a
                                key={`${row.company_id}-${news.id}`}
                                href={articleHref(news)}
                                target="_blank"
                                rel="noreferrer"
                                title={articleLinkTitle(news)}
                                className="news-mini-link"
                              >
                                <span>{title.text}</span>
                                {title.truncated ? <span className="news-mini-more">Read more</span> : null}
                              </a>
                            );
                          })}
                          {row.top_news.length === 0 ? <span className="muted">No recent signals</span> : null}
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
              {hiddenComparisonCount > 0 ? (
                <tr className="table-limit-row">
                  <td colSpan={6}>
                    Showing first {visibleComparisonRows.length} of {comparisonSummary.competitors.length} ranked
                    competitors.
                  </td>
                </tr>
              ) : null}
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
          <table className="data-table compact ops-jobs-table">
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
                    <td>
                      <JobResultCell job={job} connectorNames={connectorNames} />
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
