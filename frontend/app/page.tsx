"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useSyncExternalStore } from "react";

import { Icon, type IconName } from "@/components/Icon";
import { ApiError, apiFetch } from "@/lib/api";
import {
  hasAnyRole,
  readStoredToken,
  sessionFromToken,
  subscribeToSession,
} from "@/lib/auth";

type LearningObject = {
  id: string;
  title: string;
  status: string;
  created_at: string;
};

type ContentPage = {
  items: LearningObject[];
  total: number;
};

type Facet = { value: string; count: number };
type SearchResponse = {
  total: number;
  facets: { subject: Facet[]; format: Facet[] };
};

type DashboardData = {
  token: string;
  content: ContentPage;
  search: SearchResponse;
  metrics: { total: number; downloads: number; storage_bytes: number; by_status: Record<string, number> };
};

type DashboardLink = {
  href: string;
  label: string;
  description: string;
  icon: IconName;
  roles?: string[];
};

const TASK_LINKS: DashboardLink[] = [
  {
    href: "/contribute",
    label: "Create learning object",
    description: "Add new content to the repository",
    icon: "plus",
    roles: ["Contributor"],
  },
  {
    href: "/review",
    label: "Review submissions",
    description: "Check content awaiting review",
    icon: "check",
    roles: ["Reviewer"],
  },
  {
    href: "/reports",
    label: "View repository reports",
    description: "Explore completion activity",
    icon: "chart",
    roles: ["Admin"],
  },
];

const QUICK_LINKS: DashboardLink[] = [
  {
    href: "/search",
    label: "Browse the content library",
    description: "Find published learning objects",
    icon: "library",
    roles: ["Learner", "Contributor", "Reviewer"],
  },
  {
    href: "/contribute",
    label: "Contribute content",
    description: "Upload and describe a package",
    icon: "upload",
    roles: ["Contributor"],
  },
  {
    href: "/review",
    label: "Review & publish",
    description: "Manage the review workflow",
    icon: "workflow",
    roles: ["Reviewer"],
  },
  {
    href: "/reports",
    label: "Reports & analytics",
    description: "See learning completion reports",
    icon: "chart",
    roles: ["Admin"],
  },
];

const ACTIONS: (DashboardLink & { title: string; subtitle: string })[] = [
  {
    href: "/contribute",
    title: "Create",
    subtitle: "Learning Object",
    label: "Create learning object",
    description: "Add new content",
    icon: "plus",
    roles: ["Contributor"],
  },
  {
    href: "/contribute",
    title: "Upload",
    subtitle: "Content",
    label: "Upload content",
    description: "Upload a learning package",
    icon: "upload",
    roles: ["Contributor"],
  },
  {
    href: "/search",
    title: "Browse",
    subtitle: "Library",
    label: "Browse library",
    description: "Find learning objects",
    icon: "layers",
    roles: ["Learner", "Contributor", "Reviewer"],
  },
  {
    href: "/#categories",
    title: "Explore",
    subtitle: "Categories",
    label: "Explore categories",
    description: "Browse published subjects",
    icon: "folder",
    roles: ["Learner", "Contributor", "Reviewer"],
  },
  {
    href: "/review",
    title: "Review &",
    subtitle: "Publish",
    label: "Review and publish",
    description: "Review submitted content",
    icon: "workflow",
    roles: ["Reviewer"],
  },
  {
    href: "/reports",
    title: "View",
    subtitle: "Analytics",
    label: "View analytics",
    description: "Explore repository reports",
    icon: "chart",
    roles: ["Admin"],
  },
];

export default function Home() {
  const token = useSyncExternalStore(subscribeToSession, readStoredToken, () => null);
  const session = useMemo(() => (token ? sessionFromToken(token) : null), [token]);
  const canBrowse = hasAnyRole(session, ["Learner", "Contributor", "Reviewer"]);
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!canBrowse || !token) return;

    let cancelled = false;
    Promise.all([
      apiFetch<ContentPage>("/v1/content?page_size=5"),
      apiFetch<SearchResponse>("/v1/search?page_size=1"),
      apiFetch<DashboardData["metrics"]>("/v1/dashboard"),
    ])
      .then(([content, search, metrics]) => {
        if (!cancelled) {
          setData({ token, content, search, metrics });
          setError(null);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : "Could not load repository overview.");
          setData(null);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [canBrowse, token]);

  const currentData = data?.token === token ? data : null;
  const visibleTasks = TASK_LINKS.filter(
    (item) => !item.roles || hasAnyRole(session, item.roles),
  );
  const visibleQuickLinks = QUICK_LINKS.filter(
    (item) => !item.roles || hasAnyRole(session, item.roles),
  );
  const visibleActions = ACTIONS.filter(
    (item) => !item.roles || hasAnyRole(session, item.roles),
  );

  return (
    <div className="dashboard">
      <div className="dashboard-primary">
        <section className="hero-panel" aria-labelledby="welcome-heading">
          <div className="hero-content">
            <span className="hero-kicker">Your learning workspace</span>
            <h1 id="welcome-heading">Enterprise Learning Object Repository</h1>
            <p>Create <span>•</span> Organize <span>•</span> Reuse <span>•</span> Publish <span>•</span> Govern</p>
          </div>
          <div className="hero-art" aria-hidden="true">
            <div className="hero-orbit orbit-one" />
            <div className="hero-orbit orbit-two" />
            <div className="hero-book book-back" />
            <div className="hero-book book-middle" />
            <div className="hero-book book-front" />
            <div className="hero-screen">
              <span />
              <span />
              <span />
              <i />
            </div>
          </div>
        </section>

        <form action="/search" method="get" className="dashboard-search">
          <label className="search-field">
            <Icon name="search" size={20} />
            <input
              type="search"
              name="q"
              placeholder="Search learning objects by keyword, title, tag, or metadata..."
              aria-label="Search learning objects"
            />
          </label>
          <button type="submit">Search</button>
          <Link href="/search" className="advanced-search">
            Advanced Search
          </Link>
        </form>

        <section className="action-grid" aria-label="Quick actions">
          {visibleActions.length > 0 ? (
            visibleActions.map((action) => (
              <ActionCard
                key={action.label}
                href={action.href}
                title={action.title}
                subtitle={action.subtitle}
                icon={action.icon}
              />
            ))
          ) : (
            <div className="action-sign-in">
              <p>Sign in to see actions for your repository role.</p>
              <Link href="/login">Sign in <Icon name="arrow" size={15} /></Link>
            </div>
          )}
        </section>

        <section className="dashboard-section recent-section" aria-labelledby="recent-heading">
          <SectionHeading
            id="recent-heading"
            title="Recently Added"
            href="/search"
            linkLabel="Browse Library"
          />
          {!canBrowse ? (
            <div className="dashboard-message">
              <p>Sign in with a repository account to see recent learning objects.</p>
              <Link href="/login">Sign in</Link>
            </div>
          ) : error ? (
            <div className="dashboard-message error-message" role="alert">
              {error}
            </div>
          ) : !currentData ? (
            <div className="loading-cards" aria-label="Loading recent learning objects">
              {[0, 1, 2, 3, 4].map((item) => (
                <div className="loading-card" key={item} />
              ))}
            </div>
          ) : currentData.content.items.length === 0 ? (
            <div className="dashboard-message empty-message">
              <p>No learning objects are available in your library yet.</p>
              {hasAnyRole(session, ["Contributor"]) && (
                <Link href="/contribute">Create the first learning object <Icon name="arrow" size={16} /></Link>
              )}
            </div>
          ) : (
            <div className="object-grid">
              {currentData.content.items.map((item, index) => (
                <article className="object-card" key={item.id}>
                  <div className={`object-cover cover-${index % 5}`} aria-hidden="true">
                    <span className="cover-glow" />
                    <Icon name={index % 2 === 0 ? "book" : "layers"} size={39} />
                    <span className="cover-lines" />
                  </div>
                  <div className="object-card-body">
                    <span className={`object-status status-${item.status.toLowerCase()}`}>
                      {item.status.replaceAll("_", " ")}
                    </span>
                    <h3 title={item.title}><Link href={`/objects?id=${encodeURIComponent(item.id)}`}>{item.title}</Link></h3>
                    <p>Added {formatDate(item.created_at)}</p>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>

        <section
          id="categories"
          className="dashboard-section category-section"
          aria-labelledby="category-heading"
        >
          <SectionHeading id="category-heading" title="Explore by Category" href="/search" />
          {currentData?.search.facets.subject.length ? (
            <div className="category-grid">
              {currentData.search.facets.subject.slice(0, 6).map((facet, index) => (
                <Link
                  key={facet.value}
                  href={`/search?subject=${encodeURIComponent(facet.value)}`}
                  className={`category-card category-${index % 6}`}
                >
                  <Icon name={categoryIcon(index)} size={26} />
                  <span>{facet.value}</span>
                  <small>{facet.count} object{facet.count === 1 ? "" : "s"}</small>
                </Link>
              ))}
            </div>
          ) : (
            <p className="category-empty">
              Published subject areas will appear here as your library grows.
            </p>
          )}
        </section>
      </div>

      <aside className="dashboard-aside" aria-label="Repository overview">
        <section className="overview-card tasks-card">
          <SectionHeading
            title="My Tasks"
            href={
              hasAnyRole(session, ["Reviewer"])
                ? "/review"
                : hasAnyRole(session, ["Contributor"])
                  ? "/contribute"
                  : hasAnyRole(session, ["Admin"])
                    ? "/reports"
                    : "/login"
            }
          />
          {visibleTasks.length > 0 ? (
            <div className="task-list">
              {visibleTasks.map((task) => (
                <DashboardRow key={task.label} item={task} />
              ))}
            </div>
          ) : (
            <div className="task-empty">
              <p>Sign in to see actions available for your role.</p>
              <Link href="/login">Sign in <Icon name="arrow" size={15} /></Link>
            </div>
          )}
        </section>

        <section className="overview-card insights-card">
          <div className="insights-heading">
            <h2>Repository Insights</h2>
            <span>Current</span>
          </div>
          {canBrowse && currentData ? (
            <div className="insight-grid">
              <Insight icon="layers" value={currentData.content.total.toLocaleString()} label="Objects you can access" />
              <Insight icon="check" value={currentData.search.total.toLocaleString()} label="Published objects" />
              <Insight icon="clock" value={(currentData.metrics.by_status.draft || 0).toLocaleString()} label="Draft objects" />
              <Insight icon="chart" value={currentData.metrics.downloads.toLocaleString()} label="Repository downloads" />
              <Insight icon="workflow" value={(currentData.metrics.by_status.submitted || 0).toLocaleString()} label="Pending reviews" />
              <Insight icon="layers" value={`${(currentData.metrics.storage_bytes / 1048576).toFixed(1)} MB`} label="Stored content" />
            </div>
          ) : (
            <div className="insights-locked">
              <Icon name="users" size={25} />
              <p>Sign in to view repository activity and object counts.</p>
            </div>
          )}
          {error && canBrowse && <p className="insights-error">{error}</p>}
        </section>

        <section className="overview-card quick-card">
          <h2>Quick Links</h2>
          {visibleQuickLinks.length > 0 ? (
            <div className="quick-list">
              {visibleQuickLinks.map((item) => (
                <DashboardRow key={item.label} item={item} compact />
              ))}
            </div>
          ) : (
            <div className="task-empty">
              <p>Sign in to access your repository tools.</p>
              <Link href="/login">Sign in <Icon name="arrow" size={15} /></Link>
            </div>
          )}
        </section>
      </aside>
    </div>
  );
}

function ActionCard({
  href,
  title,
  subtitle,
  icon,
}: {
  href: string;
  title: string;
  subtitle: string;
  icon: IconName;
}) {
  return (
    <Link href={href} className={`action-card action-${icon}`}>
      <Icon name={icon} size={31} />
      <span>{title}</span>
      <strong>{subtitle}</strong>
    </Link>
  );
}

function SectionHeading({
  id,
  title,
  href,
  linkLabel = "View All",
}: {
  id?: string;
  title: string;
  href: string;
  linkLabel?: string;
}) {
  return (
    <div className="section-heading">
      <h2 id={id}>{title}</h2>
      <Link href={href}>
        {linkLabel} <Icon name="arrow" size={15} />
      </Link>
    </div>
  );
}

function DashboardRow({ item, compact = false }: { item: DashboardLink; compact?: boolean }) {
  return (
    <Link href={item.href} className={`dashboard-row${compact ? " compact" : ""}`}>
      <Icon name={item.icon} size={20} />
      <span className="dashboard-row-copy">
        <strong>{item.label}</strong>
        {!compact && <small>{item.description}</small>}
      </span>
      <Icon name="chevron" size={17} />
    </Link>
  );
}

function Insight({ icon, value, label }: { icon: IconName; value: string; label: string }) {
  return (
    <div className="insight-tile">
      <Icon name={icon} size={24} />
      <span className="insight-value">{value}</span>
      <small>{label}</small>
    </div>
  );
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "recently"
    : new Intl.DateTimeFormat("en", { month: "short", day: "numeric", year: "numeric" }).format(date);
}

function categoryIcon(index: number): IconName {
  const icons: IconName[] = ["shield", "workflow", "users", "tag", "layers", "book"];
  return icons[index % icons.length];
}
