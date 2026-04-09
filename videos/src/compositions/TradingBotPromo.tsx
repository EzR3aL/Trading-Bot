import {
  AbsoluteFill,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
  spring,
  Sequence,
  Easing,
  Audio,
  staticFile,
} from "remotion";
import {
  LayoutDashboard,
  Briefcase,
  Bot,
  TrendingUp,
  ArrowLeftRight,
  Layers,
  Settings as SettingsIcon,
  FileText,
  BookOpen,
  Sun,
  LogOut,
  Play,
  Square,
  MoreVertical,
  ChevronRight,
  Users,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

// ─── EXACT DESIGN TOKENS FROM FRONTEND ───
const C = {
  // Backgrounds
  bg: "#0a0e17",
  bgSecondary: "#111827",
  bgTertiary: "#0f172a",
  sidebarTop: "#0d1321",

  // Primary (Emerald)
  primary50: "#ecfdf5",
  primary400: "#34d399",
  primary500: "#10b981",
  primary600: "#059669",
  primary700: "#047857",

  // Accent (Blue)
  accent400: "#60a5fa",
  accent500: "#3b82f6",

  // Status
  profit: "#00e676",
  loss: "#ff5252",
  amber: "#fbbf24",

  // Text
  white: "#ffffff",
  gray300: "#d1d5db",
  gray400: "#9ca3af",
  gray500: "#6b7280",

  // Glass
  glassBg: "linear-gradient(135deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0.02) 100%)",
  glassBorder: "rgba(255, 255, 255, 0.05)",
  glassBorderHover: "rgba(255, 255, 255, 0.1)",

  // Shadows
  shadowCard: "0 4px 30px rgba(0, 0, 0, 0.3)",
  shadowGlow: "0 0 20px rgba(16, 185, 129, 0.15)",
  shadowGlowSm: "0 0 10px rgba(16, 185, 129, 0.1)",
};

const FONT = "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif";

// ─── NAV ITEMS (exact order from AppLayout.tsx) ───
interface NavItem {
  icon: LucideIcon;
  label: string;
  route: string;
}

const NAV_ITEMS: NavItem[] = [
  { icon: LayoutDashboard, label: "Dashboard", route: "/" },
  { icon: Briefcase, label: "Portfolio", route: "/portfolio" },
  { icon: Bot, label: "Meine Bots", route: "/bots" },
  { icon: TrendingUp, label: "Performance", route: "/performance" },
  { icon: ArrowLeftRight, label: "Trades", route: "/trades" },
  { icon: Layers, label: "Presets", route: "/presets" },
  { icon: SettingsIcon, label: "Einstellungen", route: "/settings" },
  { icon: FileText, label: "Steuerbericht", route: "/tax-report" },
  { icon: BookOpen, label: "Anleitung", route: "/guide" },
  { icon: Users, label: "Admin", route: "/admin/users" },
];

// ─── GLASS CARD (exact .glass-card from index.css) ───
const GlassCard: React.FC<{
  children: React.ReactNode;
  style?: React.CSSProperties;
  hover?: boolean;
}> = ({ children, style = {}, hover = false }) => (
  <div
    style={{
      background: C.glassBg,
      border: `1px solid ${hover ? C.glassBorderHover : C.glassBorder}`,
      borderRadius: 12,
      backdropFilter: "blur(20px)",
      boxShadow: C.shadowCard,
      padding: 20,
      fontFamily: FONT,
      ...style,
    }}
  >
    {children}
  </div>
);

// ─── BADGE (exact from index.css) ───
const Badge: React.FC<{
  text: string;
  variant: "profit" | "loss" | "demo" | "live" | "open" | "neutral";
}> = ({ text, variant }) => {
  const styles: Record<string, { bg: string; text: string; border: string }> = {
    profit: { bg: "rgba(16,185,129,0.1)", text: "#34d399", border: "rgba(16,185,129,0.2)" },
    loss: { bg: "rgba(239,68,68,0.1)", text: "#f87171", border: "rgba(239,68,68,0.2)" },
    demo: { bg: "rgba(245,158,11,0.1)", text: "#fbbf24", border: "rgba(245,158,11,0.2)" },
    live: { bg: "rgba(16,185,129,0.1)", text: "#34d399", border: "rgba(16,185,129,0.2)" },
    open: { bg: "rgba(59,130,246,0.1)", text: "#60a5fa", border: "rgba(59,130,246,0.2)" },
    neutral: { bg: "rgba(255,255,255,0.05)", text: "#9ca3af", border: "rgba(255,255,255,0.1)" },
  };
  const s = styles[variant];
  return (
    <span
      style={{
        display: "inline-block",
        padding: "2px 10px",
        borderRadius: 9999,
        fontSize: 12,
        fontWeight: 500,
        fontFamily: FONT,
        background: s.bg,
        color: s.text,
        border: `1px solid ${s.border}`,
      }}
    >
      {text}
    </span>
  );
};

// ─── PILL BUTTON (exact from index.css .pill-btn) ───
const PillBtn: React.FC<{
  text: string;
  active?: boolean;
}> = ({ text, active = false }) => (
  <span
    style={{
      padding: "6px 12px",
      fontSize: 12,
      fontWeight: 500,
      fontFamily: FONT,
      borderRadius: 8,
      color: active ? C.white : C.gray400,
      background: active
        ? `linear-gradient(135deg, ${C.primary600}, ${C.primary500})`
        : "transparent",
      boxShadow: active ? C.shadowGlowSm : "none",
    }}
  >
    {text}
  </span>
);

// ─── SIDEBAR (exact from AppLayout.tsx) ───
const Sidebar: React.FC<{ activeIndex: number; frame: number }> = ({
  activeIndex,
  frame,
}) => {
  const { fps } = useVideoConfig();

  return (
    <div
      style={{
        width: 240,
        minWidth: 240,
        height: 1080,
        background: `linear-gradient(180deg, ${C.sidebarTop} 0%, ${C.bgSecondary} 50%, ${C.bg} 100%)`,
        borderRight: `1px solid ${C.glassBorder}`,
        display: "flex",
        flexDirection: "column",
        fontFamily: FONT,
        overflow: "hidden",
      }}
    >
      {/* Logo — exact px-5 py-5 border-b border-white/5 */}
      <div
        style={{
          padding: "20px 20px",
          borderBottom: `1px solid ${C.glassBorder}`,
          display: "flex",
          alignItems: "center",
          gap: 12,
        }}
      >
        <div
          style={{
            width: 32,
            height: 32,
            borderRadius: 8,
            background: `linear-gradient(135deg, ${C.primary500}, ${C.primary700})`,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            boxShadow: C.shadowGlowSm,
          }}
        >
          <TrendingUp size={16} color={C.white} strokeWidth={2.5} />
        </div>
        <div>
          <div style={{ color: C.white, fontWeight: 700, fontSize: 16, lineHeight: 1.2 }}>
            Trading Bot
          </div>
          <div style={{ color: C.gray500, fontSize: 10 }}>v2.0</div>
        </div>
      </div>

      {/* Nav Items — exact px-2 py-3 space-y-0.5 */}
      <div style={{ flex: 1, padding: "12px 8px", display: "flex", flexDirection: "column", gap: 2 }}>
        {NAV_ITEMS.map((item, i) => {
          const isActive = i === activeIndex;
          const Icon = item.icon;

          // Animate the active indicator sliding
          const highlightSpring = spring({
            frame: frame - 5,
            fps,
            config: { damping: 15 },
          });

          return (
            <div
              key={item.label}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                padding: "10px 12px",
                borderRadius: 12,
                fontSize: 14,
                fontWeight: isActive ? 500 : 400,
                color: isActive ? C.white : C.gray400,
                background: isActive ? "rgba(255,255,255,0.05)" : "transparent",
                position: "relative",
                transition: "all 0.2s",
              }}
            >
              {/* Active left border — exact 3px gradient */}
              {isActive && (
                <div
                  style={{
                    position: "absolute",
                    left: 0,
                    top: 6,
                    bottom: 6,
                    width: 3,
                    borderRadius: "0 2px 2px 0",
                    background: `linear-gradient(180deg, ${C.primary400}, ${C.primary600})`,
                    opacity: highlightSpring,
                  }}
                />
              )}
              <Icon size={18} strokeWidth={isActive ? 2 : 1.5} />
              <span>{item.label}</span>
            </div>
          );
        })}
      </div>

      {/* User Profile Card — exact p-4 border-t border-white/5 */}
      <div
        style={{
          padding: 16,
          borderTop: `1px solid ${C.glassBorder}`,
          display: "flex",
          flexDirection: "column",
          gap: 12,
        }}
      >
        {/* User row */}
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div
            style={{
              width: 28,
              height: 28,
              borderRadius: "50%",
              background: `linear-gradient(135deg, ${C.primary600}, ${C.primary400})`,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 12,
              fontWeight: 700,
              color: C.white,
            }}
          >
            E
          </div>
          <div>
            <div style={{ color: C.white, fontSize: 14, fontWeight: 500 }}>Edgar</div>
            <div
              style={{
                color: C.gray500,
                fontSize: 10,
                textTransform: "uppercase",
                letterSpacing: 1,
              }}
            >
              Admin
            </div>
          </div>
        </div>

        {/* Demo/Live Toggle — exact pill switch */}
        <div
          style={{
            display: "flex",
            background: "rgba(255,255,255,0.05)",
            borderRadius: 12,
            padding: 2,
            border: `1px solid ${C.glassBorder}`,
          }}
        >
          {["Alle", "Demo", "Live"].map((label, i) => (
            <div
              key={label}
              style={{
                flex: 1,
                padding: "6px 8px",
                textAlign: "center",
                fontSize: 12,
                fontWeight: 500,
                borderRadius: 8,
                color: i === 2 ? C.white : C.gray400,
                background:
                  i === 2
                    ? `linear-gradient(135deg, ${C.primary600}, ${C.primary500})`
                    : "transparent",
                boxShadow: i === 2 ? C.shadowGlowSm : "none",
              }}
            >
              {label}
            </div>
          ))}
        </div>

        {/* Controls row */}
        <div style={{ display: "flex", gap: 8 }}>
          <div
            style={{
              padding: "6px 10px",
              borderRadius: 8,
              background: "rgba(255,255,255,0.05)",
              border: `1px solid ${C.glassBorder}`,
              display: "flex",
              alignItems: "center",
            }}
          >
            <Sun size={14} color={C.gray400} />
          </div>
          <div
            style={{
              padding: "6px 12px",
              borderRadius: 8,
              background: "rgba(255,255,255,0.05)",
              border: `1px solid ${C.glassBorder}`,
              color: C.gray400,
              fontSize: 12,
              fontWeight: 500,
            }}
          >
            DE
          </div>
          <div
            style={{
              flex: 1,
              padding: "6px 12px",
              borderRadius: 8,
              background: "rgba(239,68,68,0.1)",
              color: "#f87171",
              fontSize: 12,
              fontWeight: 500,
              textAlign: "center",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 4,
            }}
          >
            <LogOut size={12} />
            Logout
          </div>
        </div>
      </div>
    </div>
  );
};

// ─── ANIMATED COUNTER (exact count-up class) ───
const CountUp: React.FC<{
  value: number;
  prefix?: string;
  suffix?: string;
  color?: string;
  fontSize?: number;
  frame: number;
  delay?: number;
  decimals?: number;
}> = ({ value, prefix = "", suffix = "", color = C.white, fontSize = 24, frame, delay = 0, decimals = 0 }) => {
  const progress = interpolate(frame - delay, [0, 36], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });
  const translateY = interpolate(frame - delay, [0, 18], [10, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const opacity = interpolate(frame - delay, [0, 18], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const displayValue = decimals > 0
    ? (value * progress).toFixed(decimals)
    : Math.round(value * progress).toLocaleString("de-DE");

  return (
    <span
      style={{
        color,
        fontSize,
        fontWeight: 700,
        fontFamily: FONT,
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        transform: `translateY(${translateY}px)`,
        opacity,
      }}
    >
      {prefix}{displayValue}{suffix}
    </span>
  );
};

// ─── SZENE 1: HERO INTRO (0-3s) ───
const Scene1_Hero: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const logoScale = spring({ frame, fps, config: { damping: 10, mass: 0.8 } });
  const titleSpring = spring({ frame: frame - 15, fps, config: { damping: 12 } });
  const subtitleOpacity = interpolate(frame, [35, 55], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const glowPulse = Math.sin(frame * 0.12) * 0.3 + 0.7;

  return (
    <AbsoluteFill
      style={{
        background: `radial-gradient(ellipse at center, ${C.bgTertiary} 0%, ${C.bg} 70%)`,
        alignItems: "center",
        justifyContent: "center",
        fontFamily: FONT,
      }}
    >
      {/* Scrolling grid */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          backgroundImage: `linear-gradient(rgba(16,185,129,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(16,185,129,0.04) 1px, transparent 1px)`,
          backgroundSize: "60px 60px",
          transform: `translateY(${-frame * 0.4}px)`,
        }}
      />

      <div
        style={{
          transform: `scale(${logoScale})`,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 24,
        }}
      >
        {/* Logo icon — exact from AppLayout */}
        <div
          style={{
            width: 88,
            height: 88,
            borderRadius: 22,
            background: `linear-gradient(135deg, ${C.primary500}, ${C.primary700})`,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            boxShadow: `0 0 ${50 * glowPulse}px rgba(16, 185, 129, 0.4)`,
          }}
        >
          <TrendingUp size={44} color={C.white} strokeWidth={2.5} />
        </div>

        <div
          style={{
            transform: `translateY(${interpolate(titleSpring, [0, 1], [30, 0])}px)`,
            opacity: titleSpring,
          }}
        >
          <h1
            style={{
              fontSize: 68,
              fontWeight: 800,
              color: C.white,
              textAlign: "center",
              letterSpacing: -2,
              margin: 0,
              fontFamily: FONT,
            }}
          >
            Trading Bot
          </h1>
        </div>

        <p
          style={{
            fontSize: 26,
            color: C.primary400,
            opacity: subtitleOpacity,
            fontWeight: 300,
            margin: 0,
            fontFamily: FONT,
          }}
        >
          Automatisierter Krypto-Handel — 24/7
        </p>
      </div>
    </AbsoluteFill>
  );
};

// ─── SZENE 2: DASHBOARD (3-7s) ───
const Scene2_Dashboard: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const kpis = [
    { label: "GESAMT P&L", value: 12847, prefix: "+", suffix: " €", color: C.profit, sub: "↑ 12.3% vs. Vormonat" },
    { label: "WIN RATE", value: 73, suffix: "%", color: C.primary400, sub: "186 / 255 Trades" },
    { label: "BESTER TRADE", value: 1247, prefix: "+", suffix: " €", color: C.profit, sub: "BTCUSDT · 14.02." },
    { label: "SCHLECHTESTER", value: -342, suffix: " €", color: C.loss, sub: "ETHUSDT · 21.02." },
  ];

  // Chart data
  const chartProgress = interpolate(frame, [30, 90], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });

  return (
    <AbsoluteFill style={{ background: C.bg, fontFamily: FONT }}>
      <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 240 }}>
        <Sidebar activeIndex={0} frame={frame} />
      </div>
      <div style={{ position: "absolute", left: 240, top: 0, right: 0, bottom: 0, padding: 24, overflow: "hidden" }}>
        {/* Header row — exact from Dashboard.tsx */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: 24,
            opacity: interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" }),
          }}
        >
          <h1 style={{ fontSize: 24, fontWeight: 700, color: C.white, margin: 0, letterSpacing: -0.5 }}>
            Dashboard
          </h1>
          {/* Period selector — exact pill container */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 2,
              background: "rgba(255,255,255,0.05)",
              borderRadius: 12,
              padding: 2,
              border: `1px solid ${C.glassBorder}`,
            }}
          >
            {["7T", "14T", "30T", "90T"].map((p, i) => (
              <PillBtn key={p} text={p} active={i === 2} />
            ))}
          </div>
        </div>

        {/* KPI Grid — exact grid-cols-4 gap-4 */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 16, marginBottom: 24 }}>
          {kpis.map((kpi, i) => {
            const delay = i * 6;
            const cardSpring = spring({ frame: frame - delay - 5, fps, config: { damping: 12 } });
            return (
              <GlassCard
                key={kpi.label}
                style={{
                  textAlign: "center",
                  transform: `translateY(${interpolate(cardSpring, [0, 1], [20, 0])}px)`,
                  opacity: interpolate(cardSpring, [0, 1], [0, 1]),
                }}
              >
                <div
                  style={{
                    fontSize: 12,
                    fontWeight: 500,
                    color: C.gray400,
                    textTransform: "uppercase",
                    letterSpacing: 1,
                    marginBottom: 8,
                  }}
                >
                  {kpi.label}
                </div>
                <CountUp
                  value={Math.abs(kpi.value)}
                  prefix={kpi.value < 0 ? "-" : kpi.prefix}
                  suffix={kpi.suffix}
                  color={kpi.color}
                  fontSize={24}
                  frame={frame}
                  delay={delay + 8}
                />
                <div style={{ fontSize: 12, color: C.gray500, marginTop: 6 }}>{kpi.sub}</div>
              </GlassCard>
            );
          })}
        </div>

        {/* Charts Row — exact lg:grid-cols-3 */}
        <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 16 }}>
          {/* PnL Chart */}
          <GlassCard>
            <div
              style={{
                fontSize: 12,
                fontWeight: 600,
                color: C.gray400,
                textTransform: "uppercase",
                letterSpacing: 1,
                marginBottom: 16,
              }}
            >
              P&L Verlauf (30 Tage)
            </div>
            <svg viewBox="0 0 600 200" style={{ width: "100%", height: 200 }}>
              <defs>
                <linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={C.primary500} stopOpacity={0.3} />
                  <stop offset="100%" stopColor={C.primary500} stopOpacity={0} />
                </linearGradient>
              </defs>
              {/* Grid lines */}
              {[50, 100, 150].map((y) => (
                <line key={y} x1={0} y1={y} x2={600} y2={y} stroke="rgba(255,255,255,0.05)" strokeWidth={1} />
              ))}
              {/* Chart line */}
              <polyline
                points={Array.from({ length: 30 }, (_, i) => {
                  const x = (i / 29) * 600;
                  const y = 150 - (Math.sin(i * 0.2) * 30 + i * 2.5 + Math.sin(i * 0.5) * 15);
                  return `${x},${y}`;
                }).join(" ")}
                fill="none"
                stroke={C.primary500}
                strokeWidth={2}
                strokeLinecap="round"
                strokeDasharray={900}
                strokeDashoffset={900 * (1 - chartProgress)}
              />
              {/* Area fill */}
              <polyline
                points={`0,200 ${Array.from({ length: 30 }, (_, i) => {
                  const x = (i / 29) * 600;
                  const y = 150 - (Math.sin(i * 0.2) * 30 + i * 2.5 + Math.sin(i * 0.5) * 15);
                  return `${x},${y}`;
                }).join(" ")} 600,200`}
                fill="url(#areaGrad)"
                opacity={chartProgress}
              />
            </svg>
          </GlassCard>

          {/* Win/Loss Donut */}
          <GlassCard>
            <div
              style={{
                fontSize: 12,
                fontWeight: 600,
                color: C.gray400,
                textTransform: "uppercase",
                letterSpacing: 1,
                marginBottom: 16,
              }}
            >
              Win / Loss
            </div>
            <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: 200 }}>
              <svg viewBox="0 0 120 120" style={{ width: 160, height: 160 }}>
                {/* Background ring */}
                <circle cx={60} cy={60} r={45} fill="none" stroke="rgba(255,255,255,0.05)" strokeWidth={12} />
                {/* Win arc */}
                <circle
                  cx={60}
                  cy={60}
                  r={45}
                  fill="none"
                  stroke={C.primary500}
                  strokeWidth={12}
                  strokeDasharray={`${283 * 0.73 * chartProgress} ${283}`}
                  strokeLinecap="round"
                  transform="rotate(-90 60 60)"
                  style={{ filter: `drop-shadow(0 0 6px ${C.primary500}60)` }}
                />
                {/* Loss arc */}
                <circle
                  cx={60}
                  cy={60}
                  r={45}
                  fill="none"
                  stroke={C.loss}
                  strokeWidth={12}
                  strokeDasharray={`${283 * 0.27 * chartProgress} ${283}`}
                  strokeLinecap="round"
                  transform={`rotate(${-90 + 360 * 0.73} 60 60)`}
                  style={{ filter: `drop-shadow(0 0 6px ${C.loss}60)` }}
                />
                <text x={60} y={55} textAnchor="middle" fill={C.white} fontSize={20} fontWeight={700} fontFamily={FONT}>
                  73%
                </text>
                <text x={60} y={72} textAnchor="middle" fill={C.gray400} fontSize={10} fontFamily={FONT}>
                  Win Rate
                </text>
              </svg>
            </div>
          </GlassCard>
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ─── SZENE 3: MEINE BOTS (7-11s) ───
const Scene3_Bots: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const bots = [
    { name: "NR1", strategy: "Edge Indicator", exchange: "Bitget", status: "running" as const, pnl: "+$1.40", trades: 42, open: 0, pairs: "BTCUSDT", mode: "DEMO", color: C.primary500 },
    { name: "Nr2", strategy: "Edge Indicator", exchange: "Bitget", status: "running" as const, pnl: "$-916.23", trades: 12, open: 1, pairs: "BTCUSDT", mode: "DEMO", color: C.accent500 },
    { name: "NR3", strategy: "Liquidation Hunter", exchange: "Bitget", status: "stopped" as const, pnl: "+$1.40", trades: 42, open: 0, pairs: "BTCUSDT", mode: "DEMO", color: C.amber },
    { name: "NR4", strategy: "Sentiment Surfer", exchange: "Hyperliquid", status: "running" as const, pnl: "+$547.80", trades: 28, open: 2, pairs: "ETHUSDT", mode: "LIVE", color: "#a855f7" },
  ];

  const statusStyles = {
    running: { text: C.primary400, dot: C.primary500, label: "Läuft" },
    stopped: { text: C.gray400, dot: C.gray500, label: "Inaktiv" },
  };

  return (
    <AbsoluteFill style={{ background: C.bg, fontFamily: FONT }}>
      <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 240 }}>
        <Sidebar activeIndex={2} frame={frame} />
      </div>
      <div style={{ position: "absolute", left: 240, top: 0, right: 0, bottom: 0, padding: 24, overflow: "hidden" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
          <h1 style={{ fontSize: 24, fontWeight: 700, color: C.white, margin: 0 }}>Meine Bots</h1>
          <div
            style={{
              background: `linear-gradient(135deg, ${C.primary600}, ${C.primary500})`,
              color: C.white,
              padding: "8px 16px",
              borderRadius: 12,
              fontSize: 14,
              fontWeight: 500,
              boxShadow: `0 0 20px rgba(16,185,129,0.3)`,
              display: "flex",
              alignItems: "center",
              gap: 6,
              transform: `scale(${spring({ frame: frame - 8, fps, config: { damping: 12 } })})`,
            }}
          >
            + Neuer Bot
          </div>
        </div>

        {/* Bot Cards Grid */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
          {bots.map((bot, i) => {
            const delay = i * 8;
            const s = spring({ frame: frame - delay - 5, fps, config: { damping: 12 } });
            const st = statusStyles[bot.status];

            return (
              <GlassCard
                key={bot.name}
                hover
                style={{
                  transform: `scale(${interpolate(s, [0, 1], [0.9, 1])})`,
                  opacity: interpolate(s, [0, 1], [0, 1]),
                  position: "relative",
                  overflow: "hidden",
                  borderColor: bot.status === "running" ? "rgba(16,185,129,0.2)" : C.glassBorder,
                }}
              >
                {/* Header: Name + Status */}
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                  <div style={{ color: C.white, fontWeight: 700, fontSize: 18 }}>{bot.name}</div>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, color: st.text, fontSize: 13, fontWeight: 500 }}>
                    <div style={{ width: 8, height: 8, borderRadius: "50%", background: st.dot, boxShadow: bot.status === "running" ? `0 0 8px ${C.primary500}` : "none" }} />
                    {st.label}
                  </div>
                </div>

                {/* Exchange icon + Mode badge + Strategy */}
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
                  <div style={{ width: 28, height: 28, borderRadius: 8, background: "rgba(255,255,255,0.05)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                    <TrendingUp size={14} color={C.primary400} />
                  </div>
                  <Badge text={bot.mode} variant={bot.mode === "DEMO" ? "demo" : "live"} />
                  <span style={{ color: C.gray400, fontSize: 13 }}>{bot.strategy}</span>
                </div>

                {/* Trading pair badge */}
                <div style={{ marginBottom: 14 }}>
                  <span style={{ padding: "4px 10px", borderRadius: 6, background: "rgba(255,255,255,0.05)", border: `1px solid ${C.glassBorder}`, color: C.gray300, fontSize: 12, fontWeight: 500 }}>
                    {bot.pairs}
                  </span>
                </div>

                {/* Stats row: GESAMT-PNL | TRADES | OFFEN */}
                <div style={{ display: "flex", gap: 0, marginBottom: 16 }}>
                  {[
                    { label: "GESAMT-PNL", value: bot.pnl, color: bot.pnl.startsWith("+") ? C.profit : C.loss },
                    { label: "TRADES", value: String(bot.trades), color: C.white },
                    { label: "OFFEN", value: String(bot.open), color: bot.open > 0 ? C.primary400 : C.white },
                  ].map((stat, si) => (
                    <div key={stat.label} style={{ flex: 1, textAlign: si === 0 ? "left" : "center" }}>
                      <div style={{ fontSize: 11, fontWeight: 600, color: C.gray400, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 4 }}>{stat.label}</div>
                      <div style={{ fontSize: 16, fontWeight: 700, color: stat.color, fontFamily: "monospace" }}>{stat.value}</div>
                    </div>
                  ))}
                </div>

                {/* Action buttons: Starten/Stoppen + chart + more */}
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  {bot.status === "running" ? (
                    <div style={{ flex: 1, padding: "8px 16px", borderRadius: 10, background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.2)", color: "#f87171", fontSize: 13, fontWeight: 500, textAlign: "center", display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}>
                      <Square size={13} /> Stoppen
                    </div>
                  ) : (
                    <div style={{ flex: 1, padding: "8px 16px", borderRadius: 10, background: "rgba(16,185,129,0.08)", border: "1px solid rgba(16,185,129,0.2)", color: C.primary400, fontSize: 13, fontWeight: 500, textAlign: "center", display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}>
                      <Play size={13} /> Starten
                    </div>
                  )}
                  <div style={{ padding: 8, borderRadius: 8, background: "rgba(255,255,255,0.03)", border: `1px solid ${C.glassBorder}` }}>
                    <TrendingUp size={15} color={C.gray400} />
                  </div>
                  <div style={{ padding: 8, borderRadius: 8, background: "rgba(255,255,255,0.03)", border: `1px solid ${C.glassBorder}` }}>
                    <MoreVertical size={15} color={C.gray400} />
                  </div>
                </div>
              </GlassCard>
            );
          })}
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ─── SZENE 4: BOT BUILDER (11-15s) ───
const Scene4_BotBuilder: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const steps = ["Grundlagen", "Strategie", "Exchange & Paare", "Risk Mgmt", "Schedule", "Review"];
  const activeStep = Math.min(5, Math.floor(interpolate(frame, [5, 105], [0, 6], { extrapolateLeft: "clamp", extrapolateRight: "clamp" })));

  const exchanges = ["Bitget", "Hyperliquid", "BingX", "Bitunix", "Weex"];
  const strategies = ["Edge Indicator v2", "Liquidation Hunter", "Sentiment Surfer", "Trend Follower", "Mean Reversion"];

  return (
    <AbsoluteFill style={{ background: C.bg, fontFamily: FONT }}>
      <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 240 }}>
        <Sidebar activeIndex={2} frame={frame} />
      </div>
      <div style={{ position: "absolute", left: 240, top: 0, right: 0, bottom: 0, padding: 24, overflow: "hidden" }}>
        <h1 style={{ fontSize: 24, fontWeight: 700, color: C.white, margin: "0 0 20px 0" }}>Bot Builder</h1>

        {/* Step indicator — circles with connector lines */}
        <div style={{ display: "flex", alignItems: "center", marginBottom: 28, gap: 0 }}>
          {steps.map((step, i) => {
            const isDone = i < activeStep;
            const isActive = i === activeStep;
            return (
              <div key={step} style={{ display: "flex", alignItems: "center", flex: i < steps.length - 1 ? 1 : 0 }}>
                <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
                  <div
                    style={{
                      width: 32,
                      height: 32,
                      borderRadius: "50%",
                      background: isDone ? C.primary500 : isActive ? "rgba(16,185,129,0.15)" : "rgba(255,255,255,0.05)",
                      border: `2px solid ${isDone ? C.primary500 : isActive ? C.primary500 : "rgba(255,255,255,0.1)"}`,
                      color: isDone || isActive ? C.white : C.gray500,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontSize: 13,
                      fontWeight: 600,
                      boxShadow: isActive ? `0 0 15px rgba(16,185,129,0.3)` : "none",
                    }}
                  >
                    {isDone ? "✓" : i + 1}
                  </div>
                  <span style={{ fontSize: 10, color: isActive ? C.primary400 : C.gray500, fontWeight: isActive ? 600 : 400, whiteSpace: "nowrap" }}>
                    {step}
                  </span>
                </div>
                {i < steps.length - 1 && (
                  <div
                    style={{
                      flex: 1,
                      height: 2,
                      background: isDone ? C.primary500 : "rgba(255,255,255,0.08)",
                      marginBottom: 20,
                      marginLeft: 4,
                      marginRight: 4,
                      borderRadius: 1,
                    }}
                  />
                )}
              </div>
            );
          })}
        </div>

        {/* Content */}
        <GlassCard style={{ minHeight: 320 }}>
          {activeStep <= 1 && (
            <div>
              <div style={{ fontSize: 16, fontWeight: 600, color: C.white, marginBottom: 16 }}>
                {activeStep === 0 ? "Wähle deine Strategie" : "Strategie-Parameter"}
              </div>
              {activeStep === 0 && (
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
                  {strategies.map((strat, i) => {
                    const s = spring({ frame: frame - 10 - i * 5, fps, config: { damping: 10 } });
                    return (
                      <div
                        key={strat}
                        style={{
                          padding: "16px 20px",
                          borderRadius: 12,
                          background: i === 0 ? "rgba(16,185,129,0.1)" : "rgba(255,255,255,0.03)",
                          border: `1px solid ${i === 0 ? "rgba(16,185,129,0.3)" : C.glassBorder}`,
                          color: i === 0 ? C.primary400 : C.gray400,
                          fontSize: 14,
                          fontWeight: 500,
                          transform: `scale(${interpolate(s, [0, 1], [0.85, 1])})`,
                          opacity: interpolate(s, [0, 1], [0, 1]),
                        }}
                      >
                        {strat}
                      </div>
                    );
                  })}
                </div>
              )}
              {activeStep === 1 && (
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  {["Momentum Threshold: 0.35", "Trailing ATR: 2.5", "Smooth Period: 5", "Min Hold: 4h"].map((param, i) => {
                    const s = spring({ frame: frame - 25 - i * 4, fps, config: { damping: 10 } });
                    return (
                      <div
                        key={param}
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          padding: "12px 16px",
                          borderRadius: 12,
                          background: "rgba(255,255,255,0.03)",
                          border: `1px solid ${C.glassBorder}`,
                          color: C.gray300,
                          fontSize: 14,
                          opacity: interpolate(s, [0, 1], [0, 1]),
                          transform: `translateX(${interpolate(s, [0, 1], [30, 0])}px)`,
                        }}
                      >
                        <span>{param.split(":")[0]}</span>
                        <span style={{ color: C.primary400, fontWeight: 600 }}>{param.split(":")[1]}</span>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}
          {activeStep === 2 && (
            <div>
              <div style={{ fontSize: 16, fontWeight: 600, color: C.white, marginBottom: 16 }}>Exchange & Trading-Paare</div>
              <div style={{ display: "flex", gap: 10, marginBottom: 20 }}>
                {exchanges.map((ex, i) => {
                  const s = spring({ frame: frame - 45 - i * 4, fps, config: { damping: 10 } });
                  return (
                    <div
                      key={ex}
                      style={{
                        padding: "10px 20px",
                        borderRadius: 12,
                        background: i === 0 ? "rgba(16,185,129,0.1)" : "rgba(255,255,255,0.03)",
                        border: `1px solid ${i === 0 ? "rgba(16,185,129,0.3)" : C.glassBorder}`,
                        color: i === 0 ? C.primary400 : C.gray400,
                        fontSize: 13,
                        fontWeight: 500,
                        opacity: interpolate(s, [0, 1], [0, 1]),
                        transform: `scale(${interpolate(s, [0, 1], [0.8, 1])})`,
                      }}
                    >
                      {ex}
                    </div>
                  );
                })}
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                {["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "AVAXUSDT"].map((pair, i) => {
                  const s = spring({ frame: frame - 55 - i * 3, fps, config: { damping: 10 } });
                  return (
                    <div
                      key={pair}
                      style={{
                        padding: "8px 14px",
                        borderRadius: 10,
                        background: "rgba(16,185,129,0.08)",
                        border: `1px solid rgba(16,185,129,0.2)`,
                        color: C.primary400,
                        fontSize: 13,
                        fontWeight: 500,
                        opacity: interpolate(s, [0, 1], [0, 1]),
                        transform: `scale(${interpolate(s, [0, 1], [0.5, 1])})`,
                      }}
                    >
                      {pair}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
          {activeStep >= 3 && activeStep < 5 && (
            <div>
              <div style={{ fontSize: 16, fontWeight: 600, color: C.white, marginBottom: 16 }}>
                {activeStep === 3 ? "Risk Management" : "Schedule"}
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
                {(activeStep === 3
                  ? ["Stop-Loss: 2%", "Take-Profit: 5%", "Max Trades: 3", "Trailing Stop: ATR 2.5x", "Cooldown: 4h"]
                  : ["Mo-Fr: 08:00-22:00", "Sa-So: Aus", "Intervall: 5 Min"]
                ).map((item, i) => {
                  const s = spring({ frame: frame - 75 - i * 4, fps, config: { damping: 10 } });
                  return (
                    <div
                      key={item}
                      style={{
                        padding: "10px 18px",
                        borderRadius: 10,
                        background: "rgba(255,255,255,0.03)",
                        border: `1px solid ${C.glassBorder}`,
                        color: C.gray300,
                        fontSize: 13,
                        opacity: interpolate(s, [0, 1], [0, 1]),
                      }}
                    >
                      {item}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
          {activeStep >= 5 && (
            <div style={{ textAlign: "center", paddingTop: 40 }}>
              <div style={{ fontSize: 48, marginBottom: 12 }}>✓</div>
              <div style={{ fontSize: 20, fontWeight: 700, color: C.primary400, marginBottom: 8 }}>Bot erstellt!</div>
              <div style={{ color: C.gray400, fontSize: 14 }}>BTC Edge Indicator startet auf Bitget...</div>
            </div>
          )}
        </GlassCard>

        {/* Navigation Buttons */}
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 16 }}>
          <div style={{ padding: "8px 16px", borderRadius: 12, background: "rgba(255,255,255,0.05)", border: `1px solid ${C.glassBorder}`, color: C.gray400, fontSize: 14 }}>
            Zurück
          </div>
          <div
            style={{
              padding: "8px 16px",
              borderRadius: 12,
              background: `linear-gradient(135deg, ${C.primary600}, ${C.primary500})`,
              color: C.white,
              fontSize: 14,
              fontWeight: 500,
              display: "flex",
              alignItems: "center",
              gap: 4,
            }}
          >
            Weiter <ChevronRight size={16} />
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ─── SZENE 5: PERFORMANCE (15-19s) ───
const Scene5_Performance: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const stats = [
    { label: "GESAMT-RENDITE", value: "+34.7%", color: C.profit },
    { label: "WIN RATE", value: "73%", color: C.primary400 },
    { label: "SHARPE RATIO", value: "1.42", color: C.accent400 },
    { label: "MAX DRAWDOWN", value: "-8.3%", color: C.loss },
    { label: "TRADES", value: "255", color: C.white },
  ];

  const months = ["Sep", "Okt", "Nov", "Dez", "Jan", "Feb"];
  const profits = [3.2, -1.5, 8.7, 5.4, 12.1, 6.8];

  return (
    <AbsoluteFill style={{ background: C.bg, fontFamily: FONT }}>
      <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 240 }}>
        <Sidebar activeIndex={3} frame={frame} />
      </div>
      <div style={{ position: "absolute", left: 240, top: 0, right: 0, bottom: 0, padding: 24, overflow: "hidden" }}>
        <h1 style={{ fontSize: 24, fontWeight: 700, color: C.white, margin: "0 0 24px 0" }}>Performance</h1>

        {/* Stats — exact grid-cols-5 gap-px */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 1, background: C.glassBorder, borderRadius: 12, overflow: "hidden", marginBottom: 24 }}>
          {stats.map((stat, i) => {
            const s = spring({ frame: frame - i * 5, fps, config: { damping: 12 } });
            return (
              <div
                key={stat.label}
                style={{
                  background: C.bgSecondary,
                  padding: 16,
                  textAlign: "center",
                  opacity: interpolate(s, [0, 1], [0, 1]),
                }}
              >
                <div style={{ fontSize: 11, fontWeight: 600, color: C.gray400, textTransform: "uppercase", letterSpacing: 1, marginBottom: 6 }}>
                  {stat.label}
                </div>
                <div style={{ fontSize: 22, fontWeight: 700, color: stat.color }}>{stat.value}</div>
              </div>
            );
          })}
        </div>

        {/* Bar Chart */}
        <GlassCard style={{ height: 300 }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: C.gray400, textTransform: "uppercase", letterSpacing: 1, marginBottom: 20 }}>
            Monatliche Rendite
          </div>
          <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-around", height: 220, paddingTop: 30 }}>
            {months.map((month, i) => {
              const barProgress = interpolate(frame, [12 + i * 7, 30 + i * 7], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
              const isPositive = profits[i] >= 0;
              const maxProfit = Math.max(...profits.map(Math.abs));
              const barHeight = (Math.abs(profits[i]) / maxProfit) * 150 * barProgress;

              return (
                <div key={month} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 8, width: 80 }}>
                  <span style={{ color: isPositive ? C.profit : C.loss, fontSize: 13, fontWeight: 600, opacity: barProgress }}>
                    {isPositive ? "+" : ""}{profits[i]}%
                  </span>
                  <div
                    style={{
                      width: 44,
                      height: barHeight,
                      borderRadius: "8px 8px 4px 4px",
                      background: isPositive
                        ? `linear-gradient(180deg, ${C.primary500}, ${C.primary700})`
                        : `linear-gradient(180deg, ${C.loss}, #cc3333)`,
                      boxShadow: isPositive ? `0 0 12px rgba(16,185,129,0.25)` : `0 0 12px rgba(255,82,82,0.25)`,
                    }}
                  />
                  <span style={{ color: C.gray500, fontSize: 12 }}>{month}</span>
                </div>
              );
            })}
          </div>
        </GlassCard>
      </div>
    </AbsoluteFill>
  );
};

// ─── SZENE 6: FEATURE FLASH (19-24s) ───
const Scene6_FeatureFlash: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const features = [
    { icon: "📱", title: "WhatsApp Alerts", desc: "Echtzeit-Benachrichtigungen\nbei jedem Trade", color: "#25D366" },
    { icon: "📊", title: "Tax Reports", desc: "Steuer-Export für\ndeine Buchhaltung", color: C.amber },
    { icon: "🌐", title: "5 Exchanges", desc: "Bitget · Hyperliquid\nBingX · Bitunix · Weex", color: C.primary500 },
    { icon: "🛡️", title: "Risk Management", desc: "Trailing Stop · ATR\nSL/TP · Cooldown", color: C.loss },
    { icon: "☁️", title: "24/7 Cloud", desc: "Läuft rund um die Uhr\nauf deinem Server", color: C.accent400 },
  ];

  return (
    <AbsoluteFill
      style={{
        background: `radial-gradient(ellipse at center, ${C.bgTertiary} 0%, ${C.bg} 70%)`,
        alignItems: "center",
        justifyContent: "center",
        fontFamily: FONT,
      }}
    >
      <h2
        style={{
          color: C.white,
          fontSize: 32,
          fontWeight: 700,
          marginBottom: 36,
          textAlign: "center",
          opacity: interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" }),
          letterSpacing: -0.5,
        }}
      >
        Alles was du brauchst
      </h2>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16, maxWidth: 1100, padding: "0 40px" }}>
        {features.map((feat, i) => {
          const delay = 8 + i * 8;
          const s = spring({ frame: frame - delay, fps, config: { damping: 10, mass: 0.6 } });
          return (
            <GlassCard
              key={feat.title}
              style={{
                textAlign: "center",
                padding: 20,
                transform: `scale(${interpolate(s, [0, 1], [0.7, 1])}) translateY(${interpolate(s, [0, 1], [20, 0])}px)`,
                opacity: interpolate(s, [0, 1], [0, 1]),
              }}
            >
              <div style={{ fontSize: 36, marginBottom: 10, filter: `drop-shadow(0 0 8px ${feat.color}50)` }}>
                {feat.icon}
              </div>
              <div style={{ color: C.white, fontSize: 16, fontWeight: 600, marginBottom: 6 }}>{feat.title}</div>
              <div style={{ color: C.gray400, fontSize: 13, lineHeight: 1.5, whiteSpace: "pre-line" }}>{feat.desc}</div>
            </GlassCard>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

// ─── SZENE 7: CTA + AFFILIATE LINKS (24-30s) ───
const Scene7_CTA: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const titleSpring = spring({ frame, fps, config: { damping: 10 } });
  const glowPulse = Math.sin(frame * 0.12) * 0.3 + 0.7;

  const affiliateLinks = [
    { exchange: "Bitget", url: "bitget.com/ref/DEIN_CODE", color: "#00C9A7" },
    { exchange: "Hyperliquid", url: "app.hyperliquid.xyz/join/DEIN_CODE", color: "#6366f1" },
    { exchange: "BingX", url: "bingx.com/invite/DEIN_CODE", color: "#2196F3" },
    { exchange: "Bitunix", url: "bitunix.com/register?ref=DEIN_CODE", color: "#FF9800" },
    { exchange: "Weex", url: "weex.com/register?ref=DEIN_CODE", color: "#E91E63" },
  ];

  return (
    <AbsoluteFill
      style={{
        background: `radial-gradient(ellipse at 50% 30%, rgba(16,185,129,0.08) 0%, ${C.bg} 70%)`,
        alignItems: "center",
        justifyContent: "center",
        fontFamily: FONT,
      }}
    >
      {/* Floating particles */}
      {Array.from({ length: 15 }).map((_, i) => (
        <div
          key={i}
          style={{
            position: "absolute",
            width: 3,
            height: 3,
            borderRadius: "50%",
            background: C.primary500,
            opacity: 0.15 + Math.sin(frame * 0.04 + i) * 0.1,
            left: `${8 + (i * 5.7) % 84}%`,
            top: `${8 + (i * 8.3) % 84}%`,
            transform: `translateY(${Math.sin(frame * 0.025 + i * 0.6) * 15}px)`,
          }}
        />
      ))}

      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 20, transform: `scale(${titleSpring})` }}>
        {/* Logo */}
        <div
          style={{
            width: 64,
            height: 64,
            borderRadius: 16,
            background: `linear-gradient(135deg, ${C.primary500}, ${C.primary700})`,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            boxShadow: `0 0 ${35 * glowPulse}px rgba(16, 185, 129, 0.4)`,
          }}
        >
          <TrendingUp size={32} color={C.white} strokeWidth={2.5} />
        </div>

        <h1 style={{ fontSize: 48, fontWeight: 800, color: C.white, textAlign: "center", margin: 0, letterSpacing: -1 }}>
          Jetzt starten
        </h1>

        <p style={{ color: C.gray400, fontSize: 18, margin: 0 }}>
          Registriere dich über unsere Partner-Links
        </p>

        {/* Affiliate Links */}
        <div style={{ display: "flex", gap: 12, marginTop: 12, flexWrap: "wrap", justifyContent: "center" }}>
          {affiliateLinks.map((link, i) => {
            const delay = 15 + i * 7;
            const s = spring({ frame: frame - delay, fps, config: { damping: 10, mass: 0.5 } });
            return (
              <div
                key={link.exchange}
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  gap: 4,
                  transform: `translateY(${interpolate(s, [0, 1], [25, 0])}px)`,
                  opacity: interpolate(s, [0, 1], [0, 1]),
                }}
              >
                <div
                  style={{
                    padding: "10px 24px",
                    borderRadius: 12,
                    background: `${link.color}12`,
                    border: `1px solid ${link.color}35`,
                    color: link.color,
                    fontSize: 15,
                    fontWeight: 600,
                    boxShadow: `0 0 15px ${link.color}12`,
                  }}
                >
                  {link.exchange}
                </div>
                <span style={{ color: C.gray500, fontSize: 10, fontFamily: "monospace" }}>{link.url}</span>
              </div>
            );
          })}
        </div>

        {/* Bottom CTA */}
        <div style={{ marginTop: 16, opacity: interpolate(frame, [55, 75], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }) }}>
          <span style={{ color: C.primary400, fontSize: 15, fontWeight: 500 }}>▸ Links in der Videobeschreibung</span>
        </div>
      </div>
    </AbsoluteFill>
  );
};

// ─── SZENEN-ÜBERGANG ───
const SceneWrap: React.FC<{ children: React.ReactNode; dur: number }> = ({ children, dur }) => {
  const frame = useCurrentFrame();
  const fadeIn = interpolate(frame, [0, 10], [0, 1], { extrapolateRight: "clamp" });
  const fadeOut = interpolate(frame, [dur - 10, dur], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return <AbsoluteFill style={{ opacity: Math.min(fadeIn, fadeOut) }}>{children}</AbsoluteFill>;
};

// ─── HAUPTKOMPOSITION (30s = 900 Frames @ 30fps) ───
export const TradingBotPromo: React.FC = () => {
  return (
    <AbsoluteFill style={{ fontFamily: FONT }}>
      {/* Background music — uncomment when music.mp3 is in public/ */}
      {/* <Audio src={staticFile("music.mp3")} volume={0.35} /> */}

      <Sequence durationInFrames={90}>
        <SceneWrap dur={90}><Scene1_Hero /></SceneWrap>
      </Sequence>

      <Sequence from={90} durationInFrames={120}>
        <SceneWrap dur={120}><Scene2_Dashboard /></SceneWrap>
      </Sequence>

      <Sequence from={210} durationInFrames={120}>
        <SceneWrap dur={120}><Scene3_Bots /></SceneWrap>
      </Sequence>

      <Sequence from={330} durationInFrames={120}>
        <SceneWrap dur={120}><Scene4_BotBuilder /></SceneWrap>
      </Sequence>

      <Sequence from={450} durationInFrames={120}>
        <SceneWrap dur={120}><Scene5_Performance /></SceneWrap>
      </Sequence>

      <Sequence from={570} durationInFrames={150}>
        <SceneWrap dur={150}><Scene6_FeatureFlash /></SceneWrap>
      </Sequence>

      <Sequence from={720} durationInFrames={180}>
        <SceneWrap dur={180}><Scene7_CTA /></SceneWrap>
      </Sequence>
    </AbsoluteFill>
  );
};
