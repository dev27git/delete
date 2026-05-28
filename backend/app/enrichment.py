from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote_plus

from .scraper import NewsItem, fetch_news_feed

MAX_ITEMS_PER_CONNECTOR = 6
MIN_CONNECTOR_RELEVANCE_SCORE = 0.55
AUTOMATED_FETCH_METHODS = {"source_scoped_google_news"}

GENERIC_IDENTITY_TERMS = {
    "ai",
    "app",
    "cloud",
    "cyber",
    "data",
    "labs",
    "security",
    "software",
    "tech",
    "technologies",
}


@dataclass(frozen=True, slots=True)
class EnrichmentConnector:
    id: str
    name: str
    category: str
    method: str
    site_domain: str
    query_terms: tuple[str, ...] = ()
    requires_api_key: bool = False
    enabled_by_default: bool = True
    target_url: str = ""
    strategic_value: str = ""


CONNECTORS: tuple[EnrichmentConnector, ...] = (
    EnrichmentConnector(
        id="owasp_genai_security",
        name="OWASP GenAI Security",
        category="Security Framework",
        method="source_scoped_google_news",
        site_domain="genai.owasp.org",
        query_terms=("LLM", "GenAI", "security"),
    ),
    EnrichmentConnector(
        id="nist_ai_security",
        name="NIST AI Security",
        category="Security Framework",
        method="source_scoped_google_news",
        site_domain="nist.gov",
        query_terms=("AI", "risk", "security", "framework"),
    ),
    EnrichmentConnector(
        id="cisa_ai_security",
        name="CISA AI Security",
        category="Security Guidance",
        method="source_scoped_google_news",
        site_domain="cisa.gov",
        query_terms=("AI", "security", "guidance"),
    ),
    EnrichmentConnector(
        id="mit_technology_review_ai",
        name="MIT Technology Review AI",
        category="AI News",
        method="source_scoped_google_news",
        site_domain="technologyreview.com",
        query_terms=("AI", "security"),
    ),
    EnrichmentConnector(
        id="techcrunch_ai",
        name="TechCrunch AI",
        category="AI News",
        method="source_scoped_google_news",
        site_domain="techcrunch.com",
        query_terms=("AI", "security"),
    ),
    EnrichmentConnector(
        id="palo_alto_unit_42",
        name="Palo Alto Unit 42",
        category="Threat Research",
        method="source_scoped_google_news",
        site_domain="unit42.paloaltonetworks.com",
        query_terms=("AI", "security", "threat"),
    ),
    EnrichmentConnector(
        id="google_security_blog",
        name="Google Security Blog",
        category="Security Research",
        method="source_scoped_google_news",
        site_domain="security.googleblog.com",
        query_terms=("AI", "security", "LLM"),
    ),
    EnrichmentConnector(
        id="aws_security_blog",
        name="AWS Security Blog",
        category="Security Research",
        method="source_scoped_google_news",
        site_domain="aws.amazon.com/blogs/security",
        query_terms=("AI", "security", "cloud"),
    ),
    EnrichmentConnector(
        id="cloudflare_blog",
        name="Cloudflare Blog",
        category="Security Research",
        method="source_scoped_google_news",
        site_domain="blog.cloudflare.com",
        query_terms=("AI", "security", "bots"),
    ),
    EnrichmentConnector(
        id="mandiant_threat_intelligence",
        name="Mandiant Threat Intelligence",
        category="Threat Research",
        method="source_scoped_google_news",
        site_domain="cloud.google.com/blog/topics/threat-intelligence",
        query_terms=("AI", "security", "threat"),
    ),
    EnrichmentConnector(
        id="dark_reading_ai_security",
        name="Dark Reading AI Security",
        category="Security News",
        method="source_scoped_google_news",
        site_domain="darkreading.com",
        query_terms=("AI", "security", "LLM"),
    ),
    EnrichmentConnector(
        id="the_hacker_news_ai_security",
        name="The Hacker News AI Security",
        category="Security News",
        method="source_scoped_google_news",
        site_domain="thehackernews.com",
        query_terms=("AI", "security", "LLM"),
    ),
    EnrichmentConnector(
        id="microsoft_security_blog",
        name="Microsoft Security Blog",
        category="Security Research",
        method="source_scoped_google_news",
        site_domain="microsoft.com",
        query_terms=("security", "AI", "blog"),
    ),
    EnrichmentConnector(
        id="github_ai_security",
        name="GitHub AI Security Topics",
        category="Developer Signal",
        method="source_scoped_google_news",
        site_domain="github.com",
        query_terms=('"AI security"', '"LLM security"'),
    ),
    EnrichmentConnector(
        id="snyk_ai_security",
        name="Snyk AI Security",
        category="Developer Security",
        method="source_scoped_google_news",
        site_domain="snyk.io/blog",
        query_terms=("AI", "security", "open source"),
    ),
    EnrichmentConnector(
        id="semgrep_ai_security",
        name="Semgrep AI Security",
        category="Developer Security",
        method="source_scoped_google_news",
        site_domain="semgrep.dev/blog",
        query_terms=("AI", "security", "code"),
    ),
    EnrichmentConnector(
        id="hugging_face",
        name="Hugging Face",
        category="AI Ecosystem",
        method="source_scoped_google_news",
        site_domain="huggingface.co",
        query_terms=("models", "AI", "security"),
    ),
    EnrichmentConnector(
        id="the_rundown_ai",
        name="The Rundown AI",
        category="AI News",
        method="source_scoped_google_news",
        site_domain="therundown.ai",
        query_terms=("AI", "security"),
    ),
    EnrichmentConnector(
        id="venturebeat_ai",
        name="VentureBeat AI",
        category="AI News",
        method="source_scoped_google_news",
        site_domain="venturebeat.com/ai",
        query_terms=("AI", "security", "enterprise"),
    ),
    EnrichmentConnector(
        id="siliconangle_ai",
        name="SiliconANGLE AI",
        category="AI News",
        method="source_scoped_google_news",
        site_domain="siliconangle.com",
        query_terms=("AI", "security", "enterprise"),
    ),
    EnrichmentConnector(
        id="product_hunt_ai",
        name="Product Hunt AI",
        category="Launch Signal",
        method="source_scoped_google_news",
        site_domain="producthunt.com",
        query_terms=("AI", "launch"),
    ),
    EnrichmentConnector(
        id="crunchbase_ai",
        name="Crunchbase AI",
        category="Market Data",
        method="source_scoped_google_news",
        site_domain="crunchbase.com",
        query_terms=("AI", "funding"),
    ),
    EnrichmentConnector(
        id="mitre_atlas",
        name="MITRE ATLAS",
        category="AI Threat & Vulnerability Archive",
        method="source_scoped_google_news",
        site_domain="atlas.mitre.org",
        query_terms=("AI", "adversary", "technique", "mitigation"),
        target_url="https://atlas.mitre.org",
        strategic_value="Tracks adversarial AI techniques and mitigations that can become competitor security controls.",
    ),
    EnrichmentConnector(
        id="ai_incident_database",
        name="AI Incident Database",
        category="AI Threat & Vulnerability Archive",
        method="source_scoped_google_news",
        site_domain="incidentdatabase.ai",
        query_terms=("AI", "incident", "failure", "harm"),
        target_url="https://incidentdatabase.ai",
        strategic_value="Surfaces real-world AI failures that create compliance, safety, and product roadmap pressure.",
    ),
    EnrichmentConnector(
        id="github_advisory_database_ai",
        name="GitHub Advisory Database AI",
        category="AI Threat & Vulnerability Archive",
        method="source_scoped_google_news",
        site_domain="github.com/advisories",
        query_terms=("AI", "LLM", "security", "vulnerability"),
        target_url="https://github.com/advisories",
        strategic_value="Identifies dependency vulnerabilities and advisories affecting AI application stacks.",
    ),
    EnrichmentConnector(
        id="huntr_ai_ml_vulnerabilities",
        name="Huntr AI/ML Vulnerabilities",
        category="AI Threat & Vulnerability Archive",
        method="source_scoped_google_news",
        site_domain="huntr.com",
        query_terms=("AI", "ML", "vulnerability", "security"),
        target_url="https://huntr.com",
        strategic_value="Captures reported vulnerabilities in AI/ML projects before they become mainstream advisories.",
    ),
    EnrichmentConnector(
        id="garak_llm_vulnerability_scanner",
        name="Garak LLM Vulnerability Scanner",
        category="AI Threat & Vulnerability Archive",
        method="source_scoped_google_news",
        site_domain="github.com/leondz/garak",
        query_terms=("LLM", "vulnerability", "jailbreak", "prompt injection"),
        target_url="https://github.com/leondz/garak",
        strategic_value="Monitors emerging LLM probe categories that competitors may package as detection features.",
    ),
    EnrichmentConnector(
        id="github_prompt_injection_topic",
        name="GitHub Prompt Injection Topic",
        category="AI Threat & Vulnerability Archive",
        method="source_scoped_google_news",
        site_domain="github.com/topics/prompt-injection",
        query_terms=("prompt injection", "LLM", "security"),
        target_url="https://github.com/topics/prompt-injection",
        strategic_value="Finds open-source prompt-injection tools, PoCs, and detection libraries.",
    ),
    EnrichmentConnector(
        id="github_jailbreak_topic",
        name="GitHub Jailbreak Topic",
        category="AI Threat & Vulnerability Archive",
        method="source_scoped_google_news",
        site_domain="github.com/topics/jailbreak",
        query_terms=("jailbreak", "LLM", "AI safety"),
        target_url="https://github.com/topics/jailbreak",
        strategic_value="Tracks jailbreak repositories that can indicate new bypass patterns or test harnesses.",
    ),
    EnrichmentConnector(
        id="arxiv_cs_cr_ai_security",
        name="arXiv cs.CR AI Security",
        category="Research & Academic Pipeline",
        method="source_scoped_google_news",
        site_domain="arxiv.org",
        query_terms=("cs.CR", "AI", "security", "LLM"),
        target_url="https://arxiv.org/list/cs.CR/recent",
        strategic_value="Detects early security research that may forecast competitor roadmap features.",
    ),
    EnrichmentConnector(
        id="arxiv_cs_lg_machine_learning",
        name="arXiv cs.LG Machine Learning",
        category="Research & Academic Pipeline",
        method="source_scoped_google_news",
        site_domain="arxiv.org",
        query_terms=("cs.LG", "machine learning", "enterprise", "security"),
        target_url="https://arxiv.org/list/cs.LG/recent",
        strategic_value="Finds ML research signals that can precede new product capabilities.",
    ),
    EnrichmentConnector(
        id="arxiv_cs_ai_artificial_intelligence",
        name="arXiv cs.AI Artificial Intelligence",
        category="Research & Academic Pipeline",
        method="source_scoped_google_news",
        site_domain="arxiv.org",
        query_terms=("cs.AI", "agent", "governance", "security"),
        target_url="https://arxiv.org/list/cs.AI/recent",
        strategic_value="Monitors AI systems research for agent, reasoning, and governance feature signals.",
    ),
    EnrichmentConnector(
        id="hugging_face_papers",
        name="Hugging Face Papers",
        category="Research & Academic Pipeline",
        method="source_scoped_google_news",
        site_domain="huggingface.co/papers",
        query_terms=("paper", "model", "security", "agent"),
        target_url="https://huggingface.co/papers",
        strategic_value="Highlights trending papers and model releases relevant to AI product differentiation.",
    ),
    EnrichmentConnector(
        id="usenix_security",
        name="USENIX Security Symposium",
        category="Research & Academic Pipeline",
        method="source_scoped_google_news",
        site_domain="usenix.org/conference/usenixsecurity",
        query_terms=("AI", "security", "privacy", "LLM"),
        target_url="https://www.usenix.org/conference/usenixsecurity",
        strategic_value="Captures peer-reviewed security research with strong enterprise security relevance.",
    ),
    EnrichmentConnector(
        id="ieee_security_privacy",
        name="IEEE Symposium on Security and Privacy",
        category="Research & Academic Pipeline",
        method="source_scoped_google_news",
        site_domain="ieee-security.org",
        query_terms=("AI", "security", "privacy", "machine learning"),
        target_url="https://www.ieee-security.org/TC/SP-Index.html",
        strategic_value="Tracks top-tier security and privacy research that can influence product requirements.",
    ),
    EnrichmentConnector(
        id="acm_ccs",
        name="ACM CCS",
        category="Research & Academic Pipeline",
        method="source_scoped_google_news",
        site_domain="sigsac.org/ccs",
        query_terms=("AI", "security", "privacy", "LLM"),
        target_url="https://www.sigsac.org/ccs.html",
        strategic_value="Finds early academic security signals before vendor packaging.",
    ),
    EnrichmentConnector(
        id="ndss_symposium",
        name="NDSS Symposium",
        category="Research & Academic Pipeline",
        method="source_scoped_google_news",
        site_domain="ndss-symposium.org",
        query_terms=("AI", "security", "privacy", "machine learning"),
        target_url="https://www.ndss-symposium.org",
        strategic_value="Monitors network and distributed systems security research for technical gap signals.",
    ),
    EnrichmentConnector(
        id="neurips_workshops_ai_security",
        name="NeurIPS Workshops AI Security",
        category="Research & Academic Pipeline",
        method="source_scoped_google_news",
        site_domain="neurips.cc",
        query_terms=("workshop", "security", "privacy", "trustworthy AI"),
        target_url="https://neurips.cc",
        strategic_value="Identifies workshop-level AI safety, governance, and trustworthy AI trends early.",
    ),
    EnrichmentConnector(
        id="eu_ai_act_digital_strategy",
        name="European Commission AI Act",
        category="Regulatory & Compliance Stream",
        method="source_scoped_google_news",
        site_domain="digital-strategy.ec.europa.eu",
        query_terms=("AI Act", "compliance", "risk", "governance"),
        target_url="https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai",
        strategic_value="Flags EU AI Act obligations that can drive competitor governance and compliance features.",
    ),
    EnrichmentConnector(
        id="eu_ai_office",
        name="European AI Office",
        category="Regulatory & Compliance Stream",
        method="source_scoped_google_news",
        site_domain="digital-strategy.ec.europa.eu",
        query_terms=("AI Office", "code of practice", "general purpose AI", "compliance"),
        target_url="https://digital-strategy.ec.europa.eu/en/policies/ai-office",
        strategic_value="Monitors implementation guidance that can create urgent enterprise roadmap needs.",
    ),
    EnrichmentConnector(
        id="iapp_ai_governance",
        name="IAPP AI Governance",
        category="Regulatory & Compliance Stream",
        method="source_scoped_google_news",
        site_domain="iapp.org",
        query_terms=("AI governance", "privacy", "compliance", "risk"),
        target_url="https://iapp.org/resources/topics/artificial-intelligence/",
        strategic_value="Tracks practitioner-facing AI governance updates that influence buyer requirements.",
    ),
    EnrichmentConnector(
        id="ftc_ai_enforcement",
        name="FTC AI Enforcement",
        category="Regulatory & Compliance Stream",
        method="source_scoped_google_news",
        site_domain="ftc.gov/news-events/news/press-releases",
        query_terms=("AI", "enforcement", "deceptive", "privacy"),
        target_url="https://www.ftc.gov/news-events/news/press-releases",
        strategic_value="Surfaces enforcement actions and AI-washing signals that shape compliance messaging.",
    ),
    EnrichmentConnector(
        id="uk_ico_ai_guidance",
        name="UK ICO AI Guidance",
        category="Regulatory & Compliance Stream",
        method="source_scoped_google_news",
        site_domain="ico.org.uk",
        query_terms=("AI", "data protection", "guidance", "privacy"),
        target_url="https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/artificial-intelligence/",
        strategic_value="Captures privacy and AI guidance relevant to enterprise data governance products.",
    ),
    EnrichmentConnector(
        id="edpb_ai_privacy_guidance",
        name="EDPB AI Privacy Guidance",
        category="Regulatory & Compliance Stream",
        method="source_scoped_google_news",
        site_domain="edpb.europa.eu",
        query_terms=("AI", "privacy", "guidelines", "GDPR"),
        target_url="https://www.edpb.europa.eu",
        strategic_value="Tracks EU privacy interpretations that can force governance and audit features.",
    ),
    EnrichmentConnector(
        id="nist_ai_rmf",
        name="NIST AI Risk Management Framework",
        category="Regulatory & Compliance Stream",
        method="source_scoped_google_news",
        site_domain="nist.gov",
        query_terms=("AI RMF", "risk management", "governance"),
        target_url="https://www.nist.gov/itl/ai-risk-management-framework",
        strategic_value="Monitors US AI risk guidance that often becomes buyer checklist language.",
    ),
    EnrichmentConnector(
        id="openssf_ai_supply_chain",
        name="OpenSSF AI Supply Chain",
        category="Developer Ecosystem & Supply Chain",
        method="source_scoped_google_news",
        site_domain="openssf.org",
        query_terms=("AI", "supply chain", "security", "open source"),
        target_url="https://openssf.org",
        strategic_value="Finds open-source supply-chain standards and incidents relevant to AI developer tooling.",
    ),
    EnrichmentConnector(
        id="pypi_security",
        name="PyPI Security",
        category="Developer Ecosystem & Supply Chain",
        method="source_scoped_google_news",
        site_domain="pypi.org",
        query_terms=("security", "malicious package", "AI", "LLM"),
        target_url="https://pypi.org/security/",
        strategic_value="Tracks Python package ecosystem security signals and malicious AI package campaigns.",
    ),
    EnrichmentConnector(
        id="npm_security_advisories",
        name="npm Security Advisories",
        category="Developer Ecosystem & Supply Chain",
        method="source_scoped_google_news",
        site_domain="npmjs.com",
        query_terms=("security", "advisory", "AI", "LLM"),
        target_url="https://www.npmjs.com",
        strategic_value="Detects JavaScript dependency risk and package signals for AI application stacks.",
    ),
    EnrichmentConnector(
        id="github_llmops_topic",
        name="GitHub LLMOps Topic",
        category="Developer Ecosystem & Supply Chain",
        method="source_scoped_google_news",
        site_domain="github.com/topics/llmops",
        query_terms=("LLMOps", "agent", "observability", "deployment"),
        target_url="https://github.com/topics/llmops",
        strategic_value="Surfaces emerging LLMOps projects competitors may integrate or emulate.",
    ),
    EnrichmentConnector(
        id="github_langchain_topic",
        name="GitHub LangChain Topic",
        category="Developer Ecosystem & Supply Chain",
        method="source_scoped_google_news",
        site_domain="github.com/topics/langchain",
        query_terms=("LangChain", "integration", "agent", "security"),
        target_url="https://github.com/topics/langchain",
        strategic_value="Tracks LangChain integrations and agent patterns as early connector signals.",
    ),
    EnrichmentConnector(
        id="github_vector_database_topic",
        name="GitHub Vector Database Topic",
        category="Developer Ecosystem & Supply Chain",
        method="source_scoped_google_news",
        site_domain="github.com/topics/vector-database",
        query_terms=("vector database", "RAG", "embedding", "security"),
        target_url="https://github.com/topics/vector-database",
        strategic_value="Monitors vector database and RAG infrastructure that can indicate ecosystem partnerships.",
    ),
    EnrichmentConnector(
        id="github_mcp_topic",
        name="GitHub Model Context Protocol Topic",
        category="Developer Ecosystem & Supply Chain",
        method="source_scoped_google_news",
        site_domain="github.com/topics/model-context-protocol",
        query_terms=("MCP", "agent", "tool", "connector"),
        target_url="https://github.com/topics/model-context-protocol",
        strategic_value="Finds new agent-tool connector patterns and MCP ecosystem integrations.",
    ),
    EnrichmentConnector(
        id="langchain_blog",
        name="LangChain Blog",
        category="Developer Ecosystem & Supply Chain",
        method="source_scoped_google_news",
        site_domain="blog.langchain.com",
        query_terms=("integration", "agent", "security", "observability"),
        target_url="https://blog.langchain.com",
        strategic_value="Captures agent framework releases that can become competitive integration expectations.",
    ),
    EnrichmentConnector(
        id="llamaindex_blog",
        name="LlamaIndex Blog",
        category="Developer Ecosystem & Supply Chain",
        method="source_scoped_google_news",
        site_domain="llamaindex.ai/blog",
        query_terms=("RAG", "agent", "connector", "security"),
        target_url="https://www.llamaindex.ai/blog",
        strategic_value="Tracks RAG and data-connector patterns relevant to enterprise AI products.",
    ),
    EnrichmentConnector(
        id="salesforce_appexchange",
        name="Salesforce AppExchange",
        category="Enterprise App Marketplace",
        method="source_scoped_google_news",
        site_domain="appexchange.salesforce.com",
        query_terms=("integration", "app", "data", "security"),
        target_url="https://appexchange.salesforce.com",
        strategic_value="Detects competitor CRM and sales workflow integrations becoming commercially packaged.",
    ),
    EnrichmentConnector(
        id="servicenow_store",
        name="ServiceNow Store",
        category="Enterprise App Marketplace",
        method="source_scoped_google_news",
        site_domain="store.servicenow.com",
        query_terms=("integration", "app", "security", "workflow"),
        target_url="https://store.servicenow.com",
        strategic_value="Tracks ITSM, GRC, and SecOps integrations that signal enterprise expansion.",
    ),
    EnrichmentConnector(
        id="sap_store",
        name="SAP Store",
        category="Enterprise App Marketplace",
        method="source_scoped_google_news",
        site_domain="store.sap.com",
        query_terms=("integration", "app", "data", "governance"),
        target_url="https://store.sap.com",
        strategic_value="Identifies competitor integrations into SAP-heavy enterprise environments.",
    ),
    EnrichmentConnector(
        id="aws_marketplace",
        name="AWS Marketplace",
        category="Enterprise App Marketplace",
        method="source_scoped_google_news",
        site_domain="aws.amazon.com/marketplace",
        query_terms=("marketplace", "integration", "security", "AI"),
        target_url="https://aws.amazon.com/marketplace",
        strategic_value="Tracks cloud marketplace listings that signal enterprise procurement readiness.",
    ),
    EnrichmentConnector(
        id="azure_marketplace",
        name="Azure Marketplace",
        category="Enterprise App Marketplace",
        method="source_scoped_google_news",
        site_domain="azuremarketplace.microsoft.com",
        query_terms=("marketplace", "integration", "security", "AI"),
        target_url="https://azuremarketplace.microsoft.com",
        strategic_value="Detects Microsoft ecosystem listings and packaged cloud integrations.",
    ),
    EnrichmentConnector(
        id="google_cloud_marketplace",
        name="Google Cloud Marketplace",
        category="Enterprise App Marketplace",
        method="source_scoped_google_news",
        site_domain="cloud.google.com/marketplace",
        query_terms=("marketplace", "integration", "security", "AI"),
        target_url="https://cloud.google.com/marketplace",
        strategic_value="Monitors GCP marketplace motions and packaged data/security integrations.",
    ),
    EnrichmentConnector(
        id="microsoft_appsource",
        name="Microsoft AppSource",
        category="Enterprise App Marketplace",
        method="source_scoped_google_news",
        site_domain="appsource.microsoft.com",
        query_terms=("integration", "app", "Dynamics", "security"),
        target_url="https://appsource.microsoft.com",
        strategic_value="Finds Microsoft business-app ecosystem integrations and GTM signals.",
    ),
    EnrichmentConnector(
        id="atlassian_marketplace",
        name="Atlassian Marketplace",
        category="Enterprise App Marketplace",
        method="source_scoped_google_news",
        site_domain="marketplace.atlassian.com",
        query_terms=("integration", "app", "workflow", "security"),
        target_url="https://marketplace.atlassian.com",
        strategic_value="Tracks developer and collaboration workflow integrations from competitors.",
    ),
    EnrichmentConnector(
        id="okta_integration_network",
        name="Okta Integration Network",
        category="Enterprise App Marketplace",
        method="source_scoped_google_news",
        site_domain="okta.com/integrations",
        query_terms=("integration", "identity", "SSO", "security"),
        target_url="https://www.okta.com/integrations/",
        strategic_value="Detects identity and SSO packaging signals for enterprise readiness.",
    ),
    EnrichmentConnector(
        id="snowflake_marketplace",
        name="Snowflake Marketplace",
        category="Enterprise App Marketplace",
        method="source_scoped_google_news",
        site_domain="app.snowflake.com/marketplace",
        query_terms=("marketplace", "data", "governance", "integration"),
        target_url="https://app.snowflake.com/marketplace",
        strategic_value="Tracks data product and governance integrations inside Snowflake buyer workflows.",
    ),
    EnrichmentConnector(
        id="databricks_marketplace",
        name="Databricks Marketplace",
        category="Enterprise App Marketplace",
        method="source_scoped_google_news",
        site_domain="databricks.com/product/marketplace",
        query_terms=("marketplace", "data", "AI", "governance"),
        target_url="https://www.databricks.com/product/marketplace",
        strategic_value="Monitors lakehouse marketplace signals and AI/data governance partnerships.",
    ),
    EnrichmentConnector(
        id="hacker_news_algolia",
        name="Hacker News Algolia",
        category="High-Signal Tech Community",
        method="public_api_reference",
        site_domain="hn.algolia.com",
        query_terms=("AI", "security", "startup", "launch"),
        requires_api_key=False,
        enabled_by_default=False,
        target_url="https://hn.algolia.com/api",
        strategic_value="Captures early technical discussion and launch reaction before mainstream coverage.",
    ),
    EnrichmentConnector(
        id="reddit_machinelearning",
        name="Reddit r/MachineLearning",
        category="High-Signal Tech Community",
        method="community_api_reference",
        site_domain="reddit.com/r/MachineLearning",
        query_terms=("AI", "paper", "model", "benchmark"),
        requires_api_key=True,
        enabled_by_default=False,
        target_url="https://www.reddit.com/r/MachineLearning/",
        strategic_value="Tracks practitioner reaction to model and research shifts with API-governed access.",
    ),
    EnrichmentConnector(
        id="reddit_localllama",
        name="Reddit r/LocalLLaMA",
        category="High-Signal Tech Community",
        method="community_api_reference",
        site_domain="reddit.com/r/LocalLLaMA",
        query_terms=("LLM", "agent", "RAG", "inference"),
        requires_api_key=True,
        enabled_by_default=False,
        target_url="https://www.reddit.com/r/LocalLLaMA/",
        strategic_value="Surfaces grassroots model, inference, and tooling adoption signals.",
    ),
    EnrichmentConnector(
        id="reddit_cybersecurity",
        name="Reddit r/cybersecurity",
        category="High-Signal Tech Community",
        method="community_api_reference",
        site_domain="reddit.com/r/cybersecurity",
        query_terms=("AI", "security", "tool", "vendor"),
        requires_api_key=True,
        enabled_by_default=False,
        target_url="https://www.reddit.com/r/cybersecurity/",
        strategic_value="Monitors practitioner discussion around security controls and vendor perception.",
    ),
    EnrichmentConnector(
        id="reddit_netsec",
        name="Reddit r/netsec",
        category="High-Signal Tech Community",
        method="community_api_reference",
        site_domain="reddit.com/r/netsec",
        query_terms=("AI", "exploit", "vulnerability", "research"),
        requires_api_key=True,
        enabled_by_default=False,
        target_url="https://www.reddit.com/r/netsec/",
        strategic_value="Captures technical vulnerability discourse and exploit research signals.",
    ),
    EnrichmentConnector(
        id="lobsters_ai_security",
        name="Lobsters AI/Security",
        category="High-Signal Tech Community",
        method="source_scoped_google_news",
        site_domain="lobste.rs",
        query_terms=("AI", "security", "programming", "privacy"),
        enabled_by_default=False,
        target_url="https://lobste.rs",
        strategic_value="Provides a low-volume technical community signal for developer-facing product gaps.",
    ),
    EnrichmentConnector(
        id="discord_ai_announcements",
        name="AI Discord Announcement Channels",
        category="High-Signal Tech Community",
        method="community_api_reference",
        site_domain="discord.com",
        query_terms=("AI", "announcement", "release", "integration"),
        requires_api_key=True,
        enabled_by_default=False,
        target_url="https://discord.com/developers/docs/resources/channel",
        strategic_value="Supports opt-in monitoring for owned/approved Discord announcement channels.",
    ),
)


def list_enrichment_connectors() -> list[EnrichmentConnector]:
    return list(CONNECTORS)


def _connector_feed_url(connector: EnrichmentConnector, company_name: str, domain: str | None) -> str:
    identity = f'"{company_name}"'
    if domain:
        clean_domain = domain.removeprefix("www.")
        identity = f'("{company_name}" OR "{clean_domain}")'
    terms = [identity, f"site:{connector.site_domain}", *connector.query_terms]
    query = quote_plus(" ".join(terms))
    return f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"


def _normalize_for_match(value: str | None) -> str:
    if not value:
        return ""
    normalized = re.sub(r"[^a-z0-9.]+", " ", value.lower())
    return re.sub(r"\s+", " ", normalized).strip()


def _domain_identity_terms(domain: str | None) -> list[str]:
    if not domain:
        return []
    clean_domain = _normalize_for_match(domain.removeprefix("www."))
    terms = [clean_domain] if clean_domain else []
    domain_root = clean_domain.split(".", 1)[0]
    if len(domain_root) >= 4 and domain_root not in GENERIC_IDENTITY_TERMS:
        terms.append(domain_root)
    return terms


def _company_identity_terms(company_name: str, domain: str | None) -> list[str]:
    normalized_name = _normalize_for_match(company_name)
    terms = [normalized_name] if normalized_name else []
    terms.extend(
        token
        for token in normalized_name.split()
        if len(token) >= 4 and token not in GENERIC_IDENTITY_TERMS
    )
    terms.extend(_domain_identity_terms(domain))
    return list(dict.fromkeys(term for term in terms if term))


def _query_relevance_terms(connector: EnrichmentConnector) -> list[str]:
    terms = [_normalize_for_match(term.strip('"')) for term in connector.query_terms]
    return [term for term in terms if term]


def _connector_source_terms(connector: EnrichmentConnector) -> list[str]:
    site_domain = _normalize_for_match(connector.site_domain.removeprefix("www."))
    terms = [site_domain] if site_domain else []
    source_root = site_domain.split(".", 1)[0]
    if source_root:
        terms.append(source_root)
    normalized_name = _normalize_for_match(connector.name)
    if normalized_name:
        terms.append(normalized_name)
    return list(dict.fromkeys(term for term in terms if term))


def _contains_term(text: str, term: str) -> bool:
    if not text or not term:
        return False
    if " " in term or "." in term:
        return term in text
    return re.search(rf"\b{re.escape(term)}\b", text) is not None


def _connector_item_relevance_score(
    connector: EnrichmentConnector,
    item: NewsItem,
    company_name: str,
    domain: str | None,
) -> float:
    title_summary = _normalize_for_match(f"{item.title} {item.summary or ''}")
    full_text = _normalize_for_match(
        f"{item.title} {item.summary or ''} {item.publisher or ''} {item.article_url}"
    )

    identity_terms = _company_identity_terms(company_name=company_name, domain=domain)
    if not any(_contains_term(full_text, term) for term in identity_terms):
        return 0.0

    identity_score = 0.45
    if any(_contains_term(title_summary, term) for term in identity_terms):
        identity_score = 0.55

    source_score = 0.0
    if any(_contains_term(full_text, term) for term in _connector_source_terms(connector)):
        source_score = 0.25

    topic_score = 0.0
    if any(_contains_term(title_summary, term) for term in _query_relevance_terms(connector)):
        topic_score = 0.2

    summary_score = 0.05 if item.summary else 0.0
    return min(identity_score + source_score + topic_score + summary_score, 1.0)


def _filter_relevant_items(
    connector: EnrichmentConnector,
    items: list[NewsItem],
    company_name: str,
    domain: str | None,
) -> list[NewsItem]:
    scored_items = [
        (_connector_item_relevance_score(connector, item, company_name, domain), item)
        for item in items
    ]
    relevant_items = [
        item
        for score, item in scored_items
        if score >= MIN_CONNECTOR_RELEVANCE_SCORE
    ]
    return relevant_items[:MAX_ITEMS_PER_CONNECTOR]


def fetch_enrichment_news(company_name: str, domain: str | None = None) -> dict[str, list[NewsItem]]:
    results: dict[str, list[NewsItem]] = {}
    for connector in CONNECTORS:
        if (
            not connector.enabled_by_default
            or connector.requires_api_key
            or connector.method not in AUTOMATED_FETCH_METHODS
        ):
            continue
        try:
            feed_url = _connector_feed_url(connector=connector, company_name=company_name, domain=domain)
            items = fetch_news_feed(feed_url=feed_url)
            results[connector.id] = _filter_relevant_items(
                connector=connector,
                items=items,
                company_name=company_name,
                domain=domain,
            )
        except Exception:
            results[connector.id] = []
    return results
