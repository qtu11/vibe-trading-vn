import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown, TrendingUp, Globe, Sparkles, Users, UserCircle2, NotebookPen, Landmark, Gem, Search, WalletCards } from "lucide-react";
import { BrandMark } from "@/components/common/BrandMark";

interface Example {
  titleKey: string;
  descKey: string;
  promptKey: string;
}

interface Category {
  labelKey: string;
  icon: React.ReactNode;
  examples: Example[];
}

const CATEGORIES: Category[] = [
  {
    labelKey: "welcome.categories.multiMarketBacktest",
    icon: <TrendingUp className="h-4 w-4" />,
    examples: [
      {
        titleKey: "welcome.examples.adaptStrategy",
        descKey: "welcome.examples.adaptStrategyDesc",
        promptKey: "welcome.examples.adaptStrategyPrompt",
      },
      {
        titleKey: "welcome.examples.crossMarketPortfolio",
        descKey: "welcome.examples.crossMarketPortfolioDesc",
        promptKey: "welcome.examples.crossMarketPortfolioPrompt",
      },
      {
        titleKey: "welcome.examples.btcMacd",
        descKey: "welcome.examples.btcMacdDesc",
        promptKey: "welcome.examples.btcMacdPrompt",
      },
      {
        titleKey: "welcome.examples.usTechMaxDiv",
        descKey: "welcome.examples.usTechMaxDivDesc",
        promptKey: "welcome.examples.usTechMaxDivPrompt",
      },
    ],
  },
  {
    labelKey: "welcome.categories.researchAnalysis",
    icon: <Sparkles className="h-4 w-4" />,
    examples: [
      {
        titleKey: "welcome.examples.multiFactorAlpha",
        descKey: "welcome.examples.multiFactorAlphaDesc",
        promptKey: "welcome.examples.multiFactorAlphaPrompt",
      },
      {
        titleKey: "welcome.examples.optionsGreeks",
        descKey: "welcome.examples.optionsGreeksDesc",
        promptKey: "welcome.examples.optionsGreeksPrompt",
      },
    ],
  },
  {
    labelKey: "welcome.categories.valueInvesting",
    icon: <Gem className="h-4 w-4" />,
    examples: [
      {
        titleKey: "welcome.examples.valueCommittee",
        descKey: "welcome.examples.valueCommitteeDesc",
        promptKey: "welcome.examples.valueCommitteePrompt",
      },
      {
        titleKey: "welcome.examples.bottleneckHunter",
        descKey: "welcome.examples.bottleneckHunterDesc",
        promptKey: "welcome.examples.bottleneckHunterPrompt",
      },
      {
        titleKey: "welcome.examples.thesisTracker",
        descKey: "welcome.examples.thesisTrackerDesc",
        promptKey: "welcome.examples.thesisTrackerPrompt",
      },
      {
        titleKey: "welcome.examples.valuationCheck",
        descKey: "welcome.examples.valuationCheckDesc",
        promptKey: "welcome.examples.valuationCheckPrompt",
      },
    ],
  },
  {
    labelKey: "welcome.categories.swarmTeams",
    icon: <Users className="h-4 w-4" />,
    examples: [
      {
        titleKey: "welcome.examples.investmentCommittee",
        descKey: "welcome.examples.investmentCommitteeDesc",
        promptKey: "welcome.examples.investmentCommitteePrompt",
      },
      {
        titleKey: "welcome.examples.quantStrategyDesk",
        descKey: "welcome.examples.quantStrategyDeskDesc",
        promptKey: "welcome.examples.quantStrategyDeskPrompt",
      },
    ],
  },
  {
    labelKey: "welcome.categories.docWebResearch",
    icon: <Globe className="h-4 w-4" />,
    examples: [
      {
        titleKey: "welcome.examples.earningsReport",
        descKey: "welcome.examples.earningsReportDesc",
        promptKey: "welcome.examples.earningsReportPrompt",
      },
      {
        titleKey: "welcome.examples.macroResearch",
        descKey: "welcome.examples.macroResearchDesc",
        promptKey: "welcome.examples.macroResearchPrompt",
      },
    ],
  },
  {
    labelKey: "welcome.categories.tradeJournal",
    icon: <NotebookPen className="h-4 w-4" />,
    examples: [
      {
        titleKey: "welcome.examples.analyzeBrokerExport",
        descKey: "welcome.examples.analyzeBrokerExportDesc",
        promptKey: "welcome.examples.analyzeBrokerExportPrompt",
      },
      {
        titleKey: "welcome.examples.diagnoseBehavior",
        descKey: "welcome.examples.diagnoseBehaviorDesc",
        promptKey: "welcome.examples.diagnoseBehaviorPrompt",
      },
    ],
  },
  {
    labelKey: "welcome.categories.tradingConnectors",
    icon: <Landmark className="h-4 w-4" />,
    examples: [
      {
        titleKey: "welcome.examples.checkConnector",
        descKey: "welcome.examples.checkConnectorDesc",
        promptKey: "welcome.examples.checkConnectorPrompt",
      },
      {
        titleKey: "welcome.examples.analyzePortfolio",
        descKey: "welcome.examples.analyzePortfolioDesc",
        promptKey: "welcome.examples.analyzePortfolioPrompt",
      },
      {
        titleKey: "welcome.examples.quoteTrend",
        descKey: "welcome.examples.quoteTrendDesc",
        promptKey: "welcome.examples.quoteTrendPrompt",
      },
    ],
  },
  {
    labelKey: "welcome.categories.shadowAccount",
    icon: <UserCircle2 className="h-4 w-4" />,
    examples: [
      {
        titleKey: "welcome.examples.trainShadow",
        descKey: "welcome.examples.trainShadowDesc",
        promptKey: "welcome.examples.trainShadowPrompt",
      },
      {
        titleKey: "welcome.examples.shadowDelta",
        descKey: "welcome.examples.shadowDeltaDesc",
        promptKey: "welcome.examples.shadowDeltaPrompt",
      },
      {
        titleKey: "welcome.examples.shadowReport",
        descKey: "welcome.examples.shadowReportDesc",
        promptKey: "welcome.examples.shadowReportPrompt",
      },
    ],
  },
];

const GREETING_KEYS = {
  morning: [
    "welcome.greetings.morning1",
    "welcome.greetings.morning2",
    "welcome.greetings.morning3",
  ],
  afternoon: [
    "welcome.greetings.afternoon1",
    "welcome.greetings.afternoon2",
    "welcome.greetings.afternoon3",
  ],
  evening: [
    "welcome.greetings.evening1",
    "welcome.greetings.evening2",
    "welcome.greetings.evening3",
  ],
  night: [
    "welcome.greetings.night1",
    "welcome.greetings.night2",
    "welcome.greetings.night3",
  ],
} as const;

const QUICK_ACTIONS = [
  {
    titleKey: "welcome.tasks.research",
    promptKey: "welcome.tasks.researchPrompt",
    icon: <Search className="h-4 w-4" aria-hidden="true" />,
  },
  {
    titleKey: "welcome.tasks.backtest",
    promptKey: "welcome.tasks.backtestPrompt",
    icon: <TrendingUp className="h-4 w-4" aria-hidden="true" />,
  },
  {
    titleKey: "welcome.tasks.portfolio",
    promptKey: "welcome.tasks.portfolioPrompt",
    icon: <WalletCards className="h-4 w-4" aria-hidden="true" />,
  },
] as const;

function pickGreetingKey(): string {
  const hour = new Date().getHours();
  const bucket =
    hour >= 5 && hour < 12
      ? "morning"
      : hour >= 12 && hour < 17
        ? "afternoon"
        : hour >= 17 && hour < 22
          ? "evening"
          : "night";
  const variants = GREETING_KEYS[bucket];
  return variants[Math.floor(Math.random() * variants.length)] ?? variants[0];
}

interface Props {
  onExample: (s: string) => void;
}

export function WelcomeScreen({ onExample }: Props) {
  const { t } = useTranslation();
  const [greetingKey] = useState(() => pickGreetingKey());
  const [isExamplesOpen, setIsExamplesOpen] = useState(false);
  const [activeCategory, setActiveCategory] = useState(0);
  const [activeAction, setActiveAction] = useState<string | null>(null);
  const examplesTriggerRef = useRef<HTMLButtonElement>(null);

  return (
    <div className="relative flex w-full flex-col items-center overflow-hidden px-4 pb-14 text-center">
      {/* Fine grid texture + brand bloom: the hero reads as a designed
          surface rather than an empty panel. */}
      <div aria-hidden="true" className="pointer-events-none absolute inset-x-0 top-0 h-[420px] vt-grid-texture" />
      <div aria-hidden="true" className="pointer-events-none absolute inset-x-0 -top-24 h-[420px] bg-[radial-gradient(60%_60%_at_50%_0%,hsl(var(--accent)/0.16),transparent_70%)]" />

      <div className="relative w-full max-w-3xl">
        <div className="mx-auto max-w-2xl">
          {/* Hero Mascot & Brand Emblem */}
          <div className="mb-6 flex flex-col items-center">
            <div className="mb-4 flex items-center justify-center">
              <BrandMark className="h-20 w-20 transition-transform duration-slow ease-standard hover:scale-105 sm:h-24 sm:w-24" priority />
            </div>
            <div className="inline-flex items-center gap-2 rounded-full border border-accent/25 bg-accent/[0.07] px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-accent-ink backdrop-blur-sm">
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent opacity-75" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-accent" />
              </span>
              VIBE-TRADING AI AGENT
            </div>
          </div>

          <h1 className="text-[30px] font-semibold leading-tight tracking-tight text-ink sm:text-[42px]">
            {t(greetingKey as any)}
          </h1>
          <p className="mx-auto mt-4 max-w-xl text-[15px] leading-relaxed text-ink-muted">
            {t("welcome.taskSubtitle" as any)}
            <span className="mt-2 block text-xs text-ink-faint">{t("welcome.tasks.hint")}</span>
          </p>
        </div>

        <div
          className="mt-8 flex flex-wrap justify-center gap-2"
          role="group"
          aria-label={t("welcome.quickActions" as any)}
        >
          {QUICK_ACTIONS.map((action) => {
            const isActive = action.titleKey === activeAction;
            return (
              <button
                key={action.titleKey}
                type="button"
                aria-pressed={isActive}
                onClick={() => {
                  setActiveAction(action.titleKey);
                  onExample(t(action.promptKey as any));
                }}
                className={
                  isActive
                    ? "inline-flex items-center gap-2 rounded-xl border border-primary/30 bg-primary/[0.08] px-4 py-2.5 text-sm text-primary transition-colors duration-fast hover:border-primary/50 hover:bg-primary/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
                    : "inline-flex items-center gap-2 rounded-xl border border-hairline bg-surface-panel px-4 py-2.5 text-sm text-ink-secondary shadow-panel transition-all duration-fast hover:-translate-y-px hover:border-primary/40 hover:bg-surface-raised hover:text-ink hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
                }
              >
                {action.icon}
                <span>{t(action.titleKey as any)}</span>
              </button>
            );
          })}
        </div>

        <button
          ref={examplesTriggerRef}
          type="button"
          aria-expanded={isExamplesOpen}
          aria-controls="welcome-example-library"
          onClick={() => setIsExamplesOpen((open) => !open)}
          className="vt-focus-visible mt-10 inline-flex items-center gap-1.5 text-sm text-ink-muted transition-colors duration-fast hover:text-ink"
        >
          <span>{t("welcome.browseAllExamples" as any)}</span>
          <ChevronDown
            className={`h-4 w-4 transition-transform duration-slow ease-standard ${isExamplesOpen ? "rotate-180" : ""}`}
            aria-hidden="true"
          />
        </button>

        <div
          id="welcome-example-library"
          aria-hidden={!isExamplesOpen}
          onKeyDown={(event) => {
            if (event.key !== "Escape" || !isExamplesOpen) return;
            event.preventDefault();
            event.stopPropagation();
            setIsExamplesOpen(false);
            examplesTriggerRef.current?.focus();
          }}
          className={`grid text-left transition-[grid-template-rows,opacity] duration-slow ease-standard ${
            isExamplesOpen
              ? "grid-rows-[1fr] opacity-100"
              : "grid-rows-[0fr] opacity-0"
          }`}
        >
          <div className="min-h-0 overflow-hidden">
            {/* One category at a time: a chip tab bar + that category's cards.
                Rendering all 8 categories at once (grid or masonry) reads as
                an unstructured wall — categories have uneven card counts. */}
            <div className="pt-6">
              <div
                className="flex flex-wrap justify-center gap-1.5"
                role="tablist"
                aria-label={t("welcome.browseAllExamples" as any)}
              >
                {CATEGORIES.map((cat, index) => (
                  <button
                    key={cat.labelKey}
                    type="button"
                    role="tab"
                    aria-selected={index === activeCategory}
                    tabIndex={isExamplesOpen ? 0 : -1}
                    onClick={() => setActiveCategory(index)}
                    className={
                      index === activeCategory
                        ? "inline-flex items-center gap-1.5 rounded-lg border border-primary/30 bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary"
                        : "inline-flex items-center gap-1.5 rounded-lg border border-transparent px-3 py-1.5 text-xs text-ink-muted transition-colors duration-fast hover:bg-muted hover:text-ink"
                    }
                  >
                    {cat.icon}
                    <span>{t(cat.labelKey as any)}</span>
                  </button>
                ))}
              </div>
              <div role="tabpanel" className="mt-4 grid gap-2 text-left sm:grid-cols-2">
                {CATEGORIES[activeCategory].examples.map((ex) => (
                  <button
                    key={ex.titleKey}
                    type="button"
                    tabIndex={isExamplesOpen ? 0 : -1}
                    onClick={() => onExample(t(ex.promptKey as any))}
                    className="group block w-full rounded-xl border border-hairline-subtle bg-surface-panel px-3.5 py-3 text-left shadow-panel transition-all duration-fast hover:-translate-y-px hover:border-primary/40 hover:bg-surface-raised hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
                  >
                    <span className="text-sm font-medium leading-snug text-ink">
                      {t(ex.titleKey as any)}
                    </span>
                    <span className="mt-1 block text-xs leading-snug text-ink-muted">
                      {t(ex.descKey as any)}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
