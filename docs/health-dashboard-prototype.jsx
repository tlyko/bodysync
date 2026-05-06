import { useState, useEffect, useCallback, useRef } from "react";

// ═══════════════════════════════════════════════════════════
// 🏋️ HEALTH & FITNESS DASHBOARD
// Strava · Garmin · Xiaomi Scale · Fitatu · Recipe RAG
// ═══════════════════════════════════════════════════════════

const API_BASE = "http://localhost:8000";

// ─── Color Tokens ───
const C = {
  bg: "#0a0e17",
  surface: "#111827",
  card: "#1a2332",
  cardHover: "#1e2a3d",
  border: "#2a3548",
  borderLight: "#374357",
  text: "#e2e8f0",
  textMuted: "#8b9dc3",
  textDim: "#5a6f8e",
  accent: "#22d3ee",
  accentDim: "rgba(34,211,238,0.12)",
  green: "#10b981",
  greenDim: "rgba(16,185,129,0.12)",
  orange: "#f59e0b",
  orangeDim: "rgba(245,158,11,0.12)",
  red: "#ef4444",
  redDim: "rgba(239,68,68,0.12)",
  purple: "#a78bfa",
  purpleDim: "rgba(167,139,250,0.12)",
  pink: "#f472b6",
  pinkDim: "rgba(244,114,182,0.12)",
};

// ─── Fonts ───
const fontStack = "'JetBrains Mono', 'Fira Code', 'SF Mono', monospace";
const fontBody = "'Inter', -apple-system, BlinkMacSystemFont, sans-serif";

// ─── Shared Styles ───
const cardStyle = {
  background: C.card,
  border: `1px solid ${C.border}`,
  borderRadius: 16,
  padding: 24,
  transition: "all 0.2s ease",
};

const pillStyle = (color, bgColor) => ({
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  padding: "4px 12px",
  borderRadius: 20,
  fontSize: 12,
  fontWeight: 600,
  color,
  background: bgColor,
  fontFamily: fontStack,
});

const btnStyle = (color = C.accent) => ({
  padding: "10px 20px",
  borderRadius: 10,
  border: "none",
  background: color,
  color: C.bg,
  fontWeight: 700,
  fontSize: 13,
  fontFamily: fontStack,
  cursor: "pointer",
  transition: "all 0.15s ease",
  letterSpacing: "0.5px",
});

// ─── Icons (inline SVG) ───
const Icons = {
  strava: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fc4c02" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="5 19 12 5 19 19"/>
      <polyline points="14 15 12 11 10 15"/>
    </svg>
  ),
  garmin: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke={C.accent} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10"/>
      <polyline points="12 6 12 12 16 14"/>
    </svg>
  ),
  scale: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke={C.green} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="7" width="20" height="14" rx="3"/>
      <line x1="12" y1="11" x2="12" y2="17"/>
      <line x1="9" y1="14" x2="15" y2="14"/>
    </svg>
  ),
  food: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke={C.orange} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M18 8h1a4 4 0 010 8h-1"/>
      <path d="M2 8h16v9a4 4 0 01-4 4H6a4 4 0 01-4-4V8z"/>
      <line x1="6" y1="1" x2="6" y2="4"/>
      <line x1="10" y1="1" x2="10" y2="4"/>
      <line x1="14" y1="1" x2="14" y2="4"/>
    </svg>
  ),
  recipe: (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke={C.purple} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 19.5A2.5 2.5 0 016.5 17H20"/>
      <path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z"/>
      <line x1="8" y1="7" x2="16" y2="7"/>
      <line x1="8" y1="11" x2="13" y2="11"/>
    </svg>
  ),
  sync: (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="23 4 23 10 17 10"/>
      <polyline points="1 20 1 14 7 14"/>
      <path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15"/>
    </svg>
  ),
  search: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="8"/>
      <line x1="21" y1="21" x2="16.65" y2="16.65"/>
    </svg>
  ),
  fire: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={C.orange} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 12c2-2.96 0-7-1-8 0 3.038-1.773 4.741-3 6-1.226 1.26-2 3.24-2 5a6 6 0 1012 0c0-1.532-1.056-3.94-2-5-1.786 3-2.791 3-4 2z"/>
    </svg>
  ),
  heart: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={C.red} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20.84 4.61a5.5 5.5 0 00-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 00-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 000-7.78z"/>
    </svg>
  ),
  upload: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="16 16 12 12 8 16"/>
      <line x1="12" y1="12" x2="12" y2="21"/>
      <path d="M20.39 18.39A5 5 0 0018 9h-1.26A8 8 0 103 16.3"/>
    </svg>
  ),
  chart: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="18" y1="20" x2="18" y2="10"/>
      <line x1="12" y1="20" x2="12" y2="4"/>
      <line x1="6" y1="20" x2="6" y2="14"/>
    </svg>
  ),
  settings: (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3"/>
      <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-2 2 2 2 0 01-2-2v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83 0 2 2 0 010-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 01-2-2 2 2 0 012-2h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 010-2.83 2 2 0 012.83 0l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 012-2 2 2 0 012 2v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 0 2 2 0 010 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 012 2 2 2 0 01-2 2h-.09a1.65 1.65 0 00-1.51 1z"/>
    </svg>
  ),
};

// ─── Mini Sparkline Chart ───
function Sparkline({ data, color = C.accent, width = 120, height = 40 }) {
  if (!data || data.length < 2) return null;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const points = data
    .map((v, i) => {
      const x = (i / (data.length - 1)) * width;
      const y = height - ((v - min) / range) * (height - 4) - 2;
      return `${x},${y}`;
    })
    .join(" ");
  return (
    <svg width={width} height={height} style={{ display: "block" }}>
      <defs>
        <linearGradient id={`grad-${color.replace('#','')}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.3"/>
          <stop offset="100%" stopColor={color} stopOpacity="0"/>
        </linearGradient>
      </defs>
      <polygon
        points={`0,${height} ${points} ${width},${height}`}
        fill={`url(#grad-${color.replace('#','')})`}
      />
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

// ─── Stat Card Component ───
function StatCard({ icon, label, value, unit, change, sparkData, sparkColor, accentColor, accentBg }) {
  return (
    <div style={{
      ...cardStyle,
      display: "flex",
      flexDirection: "column",
      gap: 12,
      minWidth: 200,
      position: "relative",
      overflow: "hidden",
    }}>
      <div style={{
        position: "absolute",
        top: -20,
        right: -20,
        width: 80,
        height: 80,
        borderRadius: "50%",
        background: accentBg || C.accentDim,
        opacity: 0.5,
      }}/>
      <div style={{ display: "flex", alignItems: "center", gap: 8, position: "relative" }}>
        {icon}
        <span style={{ fontSize: 12, color: C.textMuted, fontFamily: fontStack, textTransform: "uppercase", letterSpacing: 1 }}>
          {label}
        </span>
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 6, position: "relative" }}>
        <span style={{ fontSize: 32, fontWeight: 800, color: C.text, fontFamily: fontStack, lineHeight: 1 }}>
          {value}
        </span>
        {unit && <span style={{ fontSize: 14, color: C.textMuted, fontFamily: fontStack }}>{unit}</span>}
      </div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        {change !== undefined && (
          <span style={{
            fontSize: 12,
            fontFamily: fontStack,
            color: change >= 0 ? C.green : C.red,
            fontWeight: 600,
          }}>
            {change >= 0 ? "▲" : "▼"} {Math.abs(change)}%
          </span>
        )}
        {sparkData && <Sparkline data={sparkData} color={sparkColor || accentColor || C.accent} />}
      </div>
    </div>
  );
}

// ─── Data Source Status Badge ───
function SourceBadge({ name, icon, status, lastSync }) {
  const statusColors = {
    connected: C.green,
    disconnected: C.textDim,
    syncing: C.orange,
    error: C.red,
  };
  return (
    <div style={{
      display: "flex",
      alignItems: "center",
      gap: 12,
      padding: "12px 16px",
      background: C.card,
      border: `1px solid ${C.border}`,
      borderRadius: 12,
    }}>
      {icon}
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: C.text, fontFamily: fontBody }}>{name}</div>
        <div style={{ fontSize: 11, color: C.textDim, fontFamily: fontStack }}>{lastSync || "Nie zsynchronizowano"}</div>
      </div>
      <div style={{
        width: 8,
        height: 8,
        borderRadius: "50%",
        background: statusColors[status] || C.textDim,
        boxShadow: status === "connected" ? `0 0 8px ${C.green}40` : "none",
      }}/>
    </div>
  );
}

// ─── Activity Row ───
function ActivityRow({ activity }) {
  const typeIcons = {
    run: "🏃",
    ride: "🚴",
    swim: "🏊",
    walk: "🚶",
    hike: "🥾",
    strength: "🏋️",
    other: "⚡",
  };
  const type = (activity.type || "other").toLowerCase();
  const icon = typeIcons[type] || typeIcons.other;
  return (
    <div style={{
      display: "flex",
      alignItems: "center",
      gap: 14,
      padding: "14px 0",
      borderBottom: `1px solid ${C.border}`,
    }}>
      <div style={{
        width: 40,
        height: 40,
        borderRadius: 10,
        background: C.accentDim,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontSize: 20,
      }}>{icon}</div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: C.text, fontFamily: fontBody, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {activity.name || "Aktywność"}
        </div>
        <div style={{ fontSize: 12, color: C.textDim, fontFamily: fontStack }}>
          {activity.date} · {activity.source || "Strava"}
        </div>
      </div>
      <div style={{ textAlign: "right" }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: C.accent, fontFamily: fontStack }}>
          {activity.distance ? `${(activity.distance / 1000).toFixed(1)} km` : activity.duration || "—"}
        </div>
        <div style={{ fontSize: 11, color: C.textMuted, fontFamily: fontStack }}>
          {activity.calories ? `${activity.calories} kcal` : ""}
        </div>
      </div>
    </div>
  );
}

// ─── Weight Chart (simple bars) ───
function WeightChart({ data }) {
  if (!data || data.length === 0) return <div style={{ color: C.textDim, fontSize: 13 }}>Brak danych wagowych</div>;
  const maxW = Math.max(...data.map(d => d.weight));
  const minW = Math.min(...data.map(d => d.weight));
  const range = maxW - minW || 1;
  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap: 3, height: 100, marginTop: 8 }}>
      {data.slice(-30).map((d, i) => {
        const h = ((d.weight - minW) / range) * 80 + 20;
        return (
          <div key={i} style={{ display: "flex", flexDirection: "column", alignItems: "center", flex: 1 }}>
            <div
              style={{
                width: "100%",
                maxWidth: 12,
                height: h,
                borderRadius: 4,
                background: `linear-gradient(to top, ${C.green}40, ${C.green})`,
                transition: "height 0.3s ease",
              }}
              title={`${d.date}: ${d.weight} kg`}
            />
          </div>
        );
      })}
    </div>
  );
}

// ─── Nutrition Donut ───
function NutritionDonut({ protein, carbs, fat, calories }) {
  const total = protein + carbs + fat || 1;
  const segments = [
    { pct: protein / total, color: C.accent, label: "Białko" },
    { pct: carbs / total, color: C.orange, label: "Węgle" },
    { pct: fat / total, color: C.pink, label: "Tłuszcz" },
  ];
  let offset = 0;
  const r = 38, cx = 50, cy = 50, circ = 2 * Math.PI * r;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 24 }}>
      <svg width="100" height="100" viewBox="0 0 100 100">
        {segments.map((seg, i) => {
          const dashLen = seg.pct * circ;
          const dashOffset = -offset * circ;
          offset += seg.pct;
          return (
            <circle
              key={i}
              cx={cx} cy={cy} r={r}
              fill="none"
              stroke={seg.color}
              strokeWidth="8"
              strokeDasharray={`${dashLen} ${circ - dashLen}`}
              strokeDashoffset={dashOffset}
              strokeLinecap="round"
              transform={`rotate(-90 ${cx} ${cy})`}
              style={{ transition: "all 0.5s ease" }}
            />
          );
        })}
        <text x={cx} y={cy - 4} textAnchor="middle" fill={C.text} fontSize="16" fontWeight="800" fontFamily={fontStack}>
          {calories}
        </text>
        <text x={cx} y={cy + 12} textAnchor="middle" fill={C.textMuted} fontSize="9" fontFamily={fontStack}>
          kcal
        </text>
      </svg>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {segments.map((seg, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div style={{ width: 8, height: 8, borderRadius: "50%", background: seg.color }}/>
            <span style={{ fontSize: 12, color: C.textMuted, fontFamily: fontBody, minWidth: 55 }}>{seg.label}</span>
            <span style={{ fontSize: 13, fontWeight: 700, color: C.text, fontFamily: fontStack }}>
              {seg === segments[0] ? protein : seg === segments[1] ? carbs : fat}g
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Recipe Card ───
function RecipeCard({ recipe, onSelect }) {
  return (
    <div
      onClick={() => onSelect && onSelect(recipe)}
      style={{
        ...cardStyle,
        padding: 16,
        cursor: "pointer",
        display: "flex",
        flexDirection: "column",
        gap: 10,
      }}
    >
      <div style={{ fontSize: 15, fontWeight: 700, color: C.text, fontFamily: fontBody }}>{recipe.name}</div>
      <div style={{ fontSize: 12, color: C.textMuted, fontFamily: fontBody, lineHeight: 1.5 }}>
        {(recipe.description || "").slice(0, 100)}...
      </div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {recipe.calories && <span style={pillStyle(C.orange, C.orangeDim)}>{Icons.fire} {recipe.calories} kcal</span>}
        {recipe.protein && <span style={pillStyle(C.accent, C.accentDim)}>B: {recipe.protein}g</span>}
        {recipe.prep_time && <span style={pillStyle(C.textMuted, C.border)}>⏱ {recipe.prep_time} min</span>}
      </div>
      {recipe.tags && (
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {recipe.tags.slice(0, 3).map((tag, i) => (
            <span key={i} style={{
              fontSize: 10,
              padding: "2px 8px",
              borderRadius: 8,
              background: C.purpleDim,
              color: C.purple,
              fontFamily: fontStack,
              textTransform: "uppercase",
              letterSpacing: 0.5,
            }}>{tag}</span>
          ))}
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════
// MAIN APP
// ═══════════════════════════════════════════════════════════
export default function HealthDashboard() {
  const [activeTab, setActiveTab] = useState("dashboard");
  const [stravaActivities, setStravaActivities] = useState([]);
  const [garminData, setGarminData] = useState(null);
  const [weightData, setWeightData] = useState([]);
  const [nutritionData, setNutritionData] = useState({ calories: 0, protein: 0, carbs: 0, fat: 0 });
  const [recipes, setRecipes] = useState([]);
  const [recipeQuery, setRecipeQuery] = useState("");
  const [selectedRecipe, setSelectedRecipe] = useState(null);
  const [sources, setSources] = useState({
    strava: { status: "disconnected", lastSync: null },
    garmin: { status: "disconnected", lastSync: null },
    scale: { status: "disconnected", lastSync: null },
    fitatu: { status: "disconnected", lastSync: null },
  });
  const [syncing, setSyncing] = useState(false);
  const [configModal, setConfigModal] = useState(null);
  const [configForm, setConfigForm] = useState({});
  const [notification, setNotification] = useState(null);
  const fileInputRef = useRef(null);

  // ─── Demo / Mock Data (replaced by real API calls) ───
  useEffect(() => {
    // Populate with demo data initially
    setStravaActivities([
      { name: "Poranny bieg — Łazienki", date: "2026-05-05", type: "run", distance: 8200, calories: 520, source: "Strava" },
      { name: "Rower do pracy", date: "2026-05-04", type: "ride", distance: 12400, calories: 340, source: "Strava" },
      { name: "Siłownia Push Day", date: "2026-05-03", type: "strength", duration: "55 min", calories: 380, source: "Garmin" },
      { name: "Bieg interwałowy", date: "2026-05-02", type: "run", distance: 6000, calories: 470, source: "Strava" },
      { name: "Spacer wieczorny", date: "2026-05-01", type: "walk", distance: 4100, calories: 180, source: "Garmin" },
    ]);
    setWeightData(
      Array.from({ length: 30 }, (_, i) => ({
        date: `2026-04-${String(i + 1).padStart(2, "0")}`,
        weight: 82.5 - Math.sin(i / 5) * 0.8 - i * 0.05 + Math.random() * 0.3,
      }))
    );
    setNutritionData({ calories: 2150, protein: 142, carbs: 245, fat: 72 });
    setGarminData({
      steps: 8742,
      heartRate: 62,
      stress: 28,
      bodyBattery: 72,
      sleep: 7.4,
    });
    setRecipes([
      { name: "Kurczak z ryżem i brokułami", description: "Klasyka meal-prepu — proste, szybkie i bogate w białko. Idealny posiłek potreningowy.", calories: 520, protein: 45, carbs: 52, fat: 12, prep_time: 25, tags: ["high-protein", "meal-prep", "obiad"] },
      { name: "Owsianka proteinowa z jagodami", description: "Pełnowartościowe śniadanie z dużą dawką białka i wolnych węglowodanów na dobry start dnia.", calories: 380, protein: 32, carbs: 48, fat: 8, prep_time: 10, tags: ["śniadanie", "szybkie", "wegetariańskie"] },
      { name: "Bowl z łososiem i awokado", description: "Zdrowe tłuszcze omega-3, świeże warzywa i aromatyczny sos sojowy. Perfekcyjny lunch.", calories: 580, protein: 38, carbs: 42, fat: 28, prep_time: 20, tags: ["omega-3", "lunch", "ryba"] },
      { name: "Shakshuka z jajkami", description: "Bliskowschodnia klasyka — jajka duszone w pomidorowym sosie z przyprawami. Świetna na brunch.", calories: 320, protein: 22, carbs: 18, fat: 18, prep_time: 20, tags: ["brunch", "wegetariańskie", "keto-friendly"] },
    ]);
  }, []);

  const showNotif = (msg, type = "success") => {
    setNotification({ msg, type });
    setTimeout(() => setNotification(null), 3000);
  };

  // ─── API Calls ───
  const syncSource = async (source) => {
    setSyncing(true);
    try {
      const res = await fetch(`${API_BASE}/api/sync/${source}`, { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        setSources(s => ({ ...s, [source]: { status: "connected", lastSync: new Date().toLocaleString("pl-PL") } }));
        showNotif(`${source} zsynchronizowany!`);
        // Refresh data
        if (source === "strava" && data.activities) setStravaActivities(prev => [...data.activities, ...prev]);
        if (source === "garmin" && data.metrics) setGarminData(data.metrics);
        if (source === "scale" && data.weights) setWeightData(data.weights);
        if (source === "fitatu" && data.nutrition) setNutritionData(data.nutrition);
      } else {
        showNotif(`Błąd synchronizacji ${source}`, "error");
      }
    } catch (e) {
      showNotif(`Serwer niedostępny — uruchom backend`, "error");
    }
    setSyncing(false);
  };

  const searchRecipes = async () => {
    if (!recipeQuery.trim()) return;
    try {
      const res = await fetch(`${API_BASE}/api/recipes/search?q=${encodeURIComponent(recipeQuery)}`);
      if (res.ok) {
        const data = await res.json();
        if (data.recipes) setRecipes(data.recipes);
      }
    } catch (e) {
      showNotif("Serwer RAG niedostępny", "error");
    }
  };

  const handleFitatuUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const formData = new FormData();
    formData.append("file", file);
    try {
      const res = await fetch(`${API_BASE}/api/fitatu/upload`, { method: "POST", body: formData });
      if (res.ok) {
        const data = await res.json();
        if (data.nutrition) setNutritionData(data.nutrition);
        showNotif("Dane Fitatu zaimportowane!");
      }
    } catch (e) {
      showNotif("Błąd importu Fitatu", "error");
    }
  };

  const saveConfig = async (source) => {
    try {
      const res = await fetch(`${API_BASE}/api/config/${source}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(configForm),
      });
      if (res.ok) {
        showNotif(`Konfiguracja ${source} zapisana!`);
        setConfigModal(null);
      }
    } catch (e) {
      showNotif("Błąd zapisu konfiguracji", "error");
    }
  };

  // ─── Navigation ───
  const tabs = [
    { id: "dashboard", label: "Dashboard", icon: Icons.chart },
    { id: "activities", label: "Aktywności", icon: Icons.strava },
    { id: "body", label: "Ciało", icon: Icons.scale },
    { id: "nutrition", label: "Odżywianie", icon: Icons.food },
    { id: "recipes", label: "Przepisy AI", icon: Icons.recipe },
    { id: "settings", label: "Ustawienia", icon: Icons.settings },
  ];

  // ─── Render Tab Content ───
  const renderDashboard = () => (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      {/* Stats Grid */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 16 }}>
        <StatCard
          icon={Icons.fire}
          label="Kalorie dzisiaj"
          value={nutritionData.calories}
          unit="kcal"
          change={-3.2}
          sparkData={[2100, 2250, 1980, 2300, 2150, 2080, 2150]}
          sparkColor={C.orange}
          accentBg={C.orangeDim}
        />
        <StatCard
          icon={Icons.strava}
          label="Aktywności (tydzień)"
          value={stravaActivities.length}
          unit="treningów"
          change={12}
          sparkData={[3, 4, 2, 5, 4, 3, 5]}
          sparkColor="#fc4c02"
          accentBg="rgba(252,76,2,0.1)"
        />
        <StatCard
          icon={Icons.scale}
          label="Waga"
          value={weightData.length > 0 ? weightData[weightData.length - 1].weight.toFixed(1) : "—"}
          unit="kg"
          change={weightData.length > 1 ? -((weightData[0].weight - weightData[weightData.length - 1].weight) / weightData[0].weight * 100).toFixed(1) : 0}
          sparkData={weightData.slice(-14).map(d => d.weight)}
          sparkColor={C.green}
          accentBg={C.greenDim}
        />
        <StatCard
          icon={Icons.heart}
          label="Tętno spoczynkowe"
          value={garminData?.heartRate || "—"}
          unit="bpm"
          sparkData={[64, 62, 63, 61, 62, 60, 62]}
          sparkColor={C.red}
          accentBg={C.redDim}
        />
      </div>

      {/* Two Column Layout */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        {/* Recent Activities */}
        <div style={cardStyle}>
          <div style={{ fontSize: 14, fontWeight: 700, color: C.text, fontFamily: fontStack, marginBottom: 8, textTransform: "uppercase", letterSpacing: 1 }}>
            Ostatnie aktywności
          </div>
          {stravaActivities.slice(0, 4).map((a, i) => <ActivityRow key={i} activity={a} />)}
        </div>

        {/* Nutrition + Garmin */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div style={cardStyle}>
            <div style={{ fontSize: 14, fontWeight: 700, color: C.text, fontFamily: fontStack, marginBottom: 12, textTransform: "uppercase", letterSpacing: 1 }}>
              Makroskładniki
            </div>
            <NutritionDonut {...nutritionData} />
          </div>
          <div style={cardStyle}>
            <div style={{ fontSize: 14, fontWeight: 700, color: C.text, fontFamily: fontStack, marginBottom: 12, textTransform: "uppercase", letterSpacing: 1 }}>
              Garmin Connect
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
              {[
                { label: "Kroki", value: garminData?.steps?.toLocaleString() || "—", icon: "👟" },
                { label: "Stres", value: garminData?.stress || "—", icon: "😌" },
                { label: "Body Battery", value: garminData?.bodyBattery || "—", icon: "🔋" },
                { label: "Sen", value: garminData?.sleep ? `${garminData.sleep}h` : "—", icon: "😴" },
              ].map((m, i) => (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, padding: 8, background: C.surface, borderRadius: 8 }}>
                  <span style={{ fontSize: 18 }}>{m.icon}</span>
                  <div>
                    <div style={{ fontSize: 11, color: C.textDim, fontFamily: fontStack }}>{m.label}</div>
                    <div style={{ fontSize: 16, fontWeight: 700, color: C.text, fontFamily: fontStack }}>{m.value}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Data Sources Status */}
      <div style={cardStyle}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
          <span style={{ fontSize: 14, fontWeight: 700, color: C.text, fontFamily: fontStack, textTransform: "uppercase", letterSpacing: 1 }}>
            Źródła danych
          </span>
          <button
            onClick={() => { syncSource("strava"); syncSource("garmin"); syncSource("scale"); }}
            style={{ ...btnStyle(), display: "flex", alignItems: "center", gap: 6, opacity: syncing ? 0.6 : 1 }}
            disabled={syncing}
          >
            {Icons.sync} {syncing ? "Synchronizuję..." : "Synchronizuj wszystko"}
          </button>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 12 }}>
          <SourceBadge name="Strava" icon={Icons.strava} status={sources.strava.status} lastSync={sources.strava.lastSync} />
          <SourceBadge name="Garmin Connect" icon={Icons.garmin} status={sources.garmin.status} lastSync={sources.garmin.lastSync} />
          <SourceBadge name="Xiaomi Scale" icon={Icons.scale} status={sources.scale.status} lastSync={sources.scale.lastSync} />
          <SourceBadge name="Fitatu" icon={Icons.food} status={sources.fitatu.status} lastSync={sources.fitatu.lastSync} />
        </div>
      </div>
    </div>
  );

  const renderActivities = () => (
    <div style={cardStyle}>
      <div style={{ fontSize: 18, fontWeight: 700, color: C.text, fontFamily: fontStack, marginBottom: 16 }}>
        Wszystkie aktywności
      </div>
      {stravaActivities.map((a, i) => <ActivityRow key={i} activity={a} />)}
      {stravaActivities.length === 0 && (
        <div style={{ textAlign: "center", padding: 40, color: C.textDim }}>
          Połącz Stravę lub Garmin aby zobaczyć aktywności
        </div>
      )}
    </div>
  );

  const renderBody = () => (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={cardStyle}>
        <div style={{ fontSize: 18, fontWeight: 700, color: C.text, fontFamily: fontStack, marginBottom: 4 }}>
          Progres wagowy
        </div>
        <div style={{ fontSize: 12, color: C.textDim, fontFamily: fontStack, marginBottom: 16 }}>
          Ostatnie 30 dni · Xiaomi Mi Body Composition Scale
        </div>
        <WeightChart data={weightData} />
        <div style={{ display: "flex", justifyContent: "space-between", marginTop: 8 }}>
          <span style={{ fontSize: 11, color: C.textDim, fontFamily: fontStack }}>
            Min: {weightData.length > 0 ? Math.min(...weightData.map(d => d.weight)).toFixed(1) : "—"} kg
          </span>
          <span style={{ fontSize: 11, color: C.textDim, fontFamily: fontStack }}>
            Max: {weightData.length > 0 ? Math.max(...weightData.map(d => d.weight)).toFixed(1) : "—"} kg
          </span>
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16 }}>
        <StatCard icon={Icons.scale} label="Aktualna waga" value={weightData.length > 0 ? weightData[weightData.length-1].weight.toFixed(1) : "—"} unit="kg" accentBg={C.greenDim}/>
        <StatCard icon={<span style={{fontSize:18}}>📉</span>} label="Zmiana (30d)" value={weightData.length > 1 ? (weightData[weightData.length-1].weight - weightData[0].weight).toFixed(1) : "—"} unit="kg" accentBg={C.accentDim}/>
        <StatCard icon={<span style={{fontSize:18}}>📊</span>} label="Średnia" value={weightData.length > 0 ? (weightData.reduce((s,d) => s+d.weight, 0) / weightData.length).toFixed(1) : "—"} unit="kg" accentBg={C.purpleDim}/>
      </div>
    </div>
  );

  const renderNutrition = () => (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={cardStyle}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
          <div>
            <div style={{ fontSize: 18, fontWeight: 700, color: C.text, fontFamily: fontStack }}>Dzisiejsze odżywianie</div>
            <div style={{ fontSize: 12, color: C.textDim, fontFamily: fontStack }}>Dane z Fitatu</div>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <input type="file" ref={fileInputRef} accept=".csv,.xlsx" style={{ display: "none" }} onChange={handleFitatuUpload} />
            <button onClick={() => fileInputRef.current?.click()} style={{ ...btnStyle(C.orange), display: "flex", alignItems: "center", gap: 6 }}>
              {Icons.upload} Import CSV
            </button>
          </div>
        </div>
        <NutritionDonut {...nutritionData} />
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 16 }}>
        <StatCard icon={Icons.fire} label="Kalorie" value={nutritionData.calories} unit="kcal" accentBg={C.orangeDim}/>
        <StatCard icon={<span style={{fontSize:18}}>🥩</span>} label="Białko" value={nutritionData.protein} unit="g" accentBg={C.accentDim}/>
        <StatCard icon={<span style={{fontSize:18}}>🍞</span>} label="Węglowodany" value={nutritionData.carbs} unit="g" accentBg={C.orangeDim}/>
        <StatCard icon={<span style={{fontSize:18}}>🥑</span>} label="Tłuszcz" value={nutritionData.fat} unit="g" accentBg={C.pinkDim}/>
      </div>
    </div>
  );

  const renderRecipes = () => (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={cardStyle}>
        <div style={{ fontSize: 18, fontWeight: 700, color: C.text, fontFamily: fontStack, marginBottom: 4 }}>
          Wyszukaj przepisy AI
        </div>
        <div style={{ fontSize: 12, color: C.textDim, fontFamily: fontStack, marginBottom: 16 }}>
          RAG z 1000+ dietetycznych przepisów · Wyszukiwanie semantyczne
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <div style={{ flex: 1, position: "relative" }}>
            <input
              value={recipeQuery}
              onChange={e => setRecipeQuery(e.target.value)}
              onKeyDown={e => e.key === "Enter" && searchRecipes()}
              placeholder="np. wysoko-białkowy obiad do 500 kcal..."
              style={{
                width: "100%",
                padding: "12px 16px 12px 42px",
                borderRadius: 10,
                border: `1px solid ${C.border}`,
                background: C.surface,
                color: C.text,
                fontSize: 14,
                fontFamily: fontBody,
                outline: "none",
                boxSizing: "border-box",
              }}
            />
            <div style={{ position: "absolute", left: 14, top: "50%", transform: "translateY(-50%)", color: C.textDim }}>
              {Icons.search}
            </div>
          </div>
          <button onClick={searchRecipes} style={btnStyle(C.purple)}>Szukaj</button>
        </div>
      </div>

      {selectedRecipe && (
        <div style={{ ...cardStyle, border: `1px solid ${C.purple}40` }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
            <div>
              <div style={{ fontSize: 20, fontWeight: 700, color: C.text, fontFamily: fontBody }}>{selectedRecipe.name}</div>
              <div style={{ fontSize: 13, color: C.textMuted, fontFamily: fontBody, marginTop: 4, lineHeight: 1.6 }}>{selectedRecipe.description}</div>
            </div>
            <button onClick={() => setSelectedRecipe(null)} style={{ background: "none", border: "none", color: C.textDim, fontSize: 20, cursor: "pointer" }}>✕</button>
          </div>
          <div style={{ display: "flex", gap: 12, marginTop: 12 }}>
            <span style={pillStyle(C.orange, C.orangeDim)}>{selectedRecipe.calories} kcal</span>
            <span style={pillStyle(C.accent, C.accentDim)}>B: {selectedRecipe.protein}g</span>
            <span style={pillStyle(C.orange, C.orangeDim)}>W: {selectedRecipe.carbs}g</span>
            <span style={pillStyle(C.pink, C.pinkDim)}>T: {selectedRecipe.fat}g</span>
          </div>
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 16 }}>
        {recipes.map((r, i) => <RecipeCard key={i} recipe={r} onSelect={setSelectedRecipe} />)}
      </div>
    </div>
  );

  const renderSettings = () => (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ fontSize: 18, fontWeight: 700, color: C.text, fontFamily: fontStack }}>Konfiguracja źródeł danych</div>

      {/* Strava Config */}
      <div style={cardStyle}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
          {Icons.strava}
          <span style={{ fontSize: 16, fontWeight: 700, color: C.text, fontFamily: fontBody }}>Strava</span>
          <span style={pillStyle("#fc4c02", "rgba(252,76,2,0.15)")}>OAuth2 API</span>
        </div>
        <p style={{ fontSize: 13, color: C.textMuted, fontFamily: fontBody, lineHeight: 1.6, margin: "0 0 12px" }}>
          Strava wymaga rejestracji aplikacji na developers.strava.com. Po utworzeniu aplikacji, wklej Client ID i Client Secret poniżej. Backend automatycznie obsłuży OAuth2 flow i odświeżanie tokenów.
        </p>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <input placeholder="Client ID" style={inputStyle()} onChange={e => setConfigForm(f => ({...f, strava_client_id: e.target.value}))} />
          <input placeholder="Client Secret" type="password" style={inputStyle()} onChange={e => setConfigForm(f => ({...f, strava_client_secret: e.target.value}))} />
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
          <button onClick={() => saveConfig("strava")} style={btnStyle("#fc4c02")}>Zapisz i połącz</button>
          <button onClick={() => window.open(`${API_BASE}/api/strava/auth`, "_blank")} style={{ ...btnStyle(), background: "transparent", border: `1px solid ${C.border}`, color: C.text }}>
            Autoryzuj w Strava
          </button>
        </div>
      </div>

      {/* Garmin Config */}
      <div style={cardStyle}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
          {Icons.garmin}
          <span style={{ fontSize: 16, fontWeight: 700, color: C.text, fontFamily: fontBody }}>Garmin Connect</span>
          <span style={pillStyle(C.accent, C.accentDim)}>Nieoficjalne API</span>
        </div>
        <p style={{ fontSize: 13, color: C.textMuted, fontFamily: fontBody, lineHeight: 1.6, margin: "0 0 12px" }}>
          Używa biblioteki python-garminconnect. Podaj email i hasło do Garmin Connect. Tokeny odświeżają się automatycznie. Może wymagać MFA przy pierwszym logowaniu.
        </p>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <input placeholder="Email Garmin" style={inputStyle()} onChange={e => setConfigForm(f => ({...f, garmin_email: e.target.value}))} />
          <input placeholder="Hasło Garmin" type="password" style={inputStyle()} onChange={e => setConfigForm(f => ({...f, garmin_password: e.target.value}))} />
        </div>
        <button onClick={() => saveConfig("garmin")} style={{ ...btnStyle(C.accent), marginTop: 12 }}>Zapisz i połącz</button>
      </div>

      {/* Xiaomi Scale Config */}
      <div style={cardStyle}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
          {Icons.scale}
          <span style={{ fontSize: 16, fontWeight: 700, color: C.text, fontFamily: fontBody }}>Xiaomi Mi Scale</span>
          <span style={pillStyle(C.green, C.greenDim)}>BLE / Import</span>
        </div>
        <p style={{ fontSize: 13, color: C.textMuted, fontFamily: fontBody, lineHeight: 1.6, margin: "0 0 12px" }}>
          <strong>Opcja 1 (automatyczna):</strong> Raspberry Pi / ESP32 z BLE → MQTT → backend. Podaj adres MQTT brokera i MAC wagi.<br/>
          <strong>Opcja 2 (półautomat):</strong> Eksportuj dane z Mi Fit/Zepp Life jako CSV i importuj tutaj.
        </p>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
          <input placeholder="MQTT Broker (np. 192.168.1.100)" style={inputStyle()} onChange={e => setConfigForm(f => ({...f, mqtt_broker: e.target.value}))} />
          <input placeholder="MQTT Topic" style={inputStyle()} onChange={e => setConfigForm(f => ({...f, mqtt_topic: e.target.value}))} />
          <input placeholder="MAC wagi (AA:BB:CC:...)" style={inputStyle()} onChange={e => setConfigForm(f => ({...f, scale_mac: e.target.value}))} />
        </div>
        <button onClick={() => saveConfig("scale")} style={{ ...btnStyle(C.green), marginTop: 12 }}>Zapisz konfigurację</button>
      </div>

      {/* Fitatu Config */}
      <div style={cardStyle}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
          {Icons.food}
          <span style={{ fontSize: 16, fontWeight: 700, color: C.text, fontFamily: fontBody }}>Fitatu</span>
          <span style={pillStyle(C.orange, C.orangeDim)}>CSV Export</span>
        </div>
        <p style={{ fontSize: 13, color: C.textMuted, fontFamily: fontBody, lineHeight: 1.6, margin: "0 0 12px" }}>
          Fitatu nie ma publicznego API, ale pozwala eksportować dane z ostatnich 30 dni jako CSV. Backend parsuje plik i wyciąga kalorie, makroskładniki i posiłki. Ustaw automatyczny import przez folder watch.
        </p>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <input placeholder="Folder watch (np. ~/Downloads/fitatu)" style={inputStyle()} onChange={e => setConfigForm(f => ({...f, fitatu_watch_dir: e.target.value}))} />
          <input placeholder="Interwał skanowania (sekundy)" style={inputStyle()} defaultValue="300" onChange={e => setConfigForm(f => ({...f, fitatu_interval: e.target.value}))} />
        </div>
        <button onClick={() => saveConfig("fitatu")} style={{ ...btnStyle(C.orange), marginTop: 12 }}>Zapisz konfigurację</button>
      </div>
    </div>
  );

  const inputStyle = () => ({
    padding: "10px 14px",
    borderRadius: 8,
    border: `1px solid ${C.border}`,
    background: C.surface,
    color: C.text,
    fontSize: 13,
    fontFamily: fontStack,
    outline: "none",
    width: "100%",
    boxSizing: "border-box",
  });

  const contentMap = {
    dashboard: renderDashboard,
    activities: renderActivities,
    body: renderBody,
    nutrition: renderNutrition,
    recipes: renderRecipes,
    settings: renderSettings,
  };

  return (
    <div style={{
      minHeight: "100vh",
      background: C.bg,
      color: C.text,
      fontFamily: fontBody,
      display: "flex",
    }}>
      {/* Google Fonts */}
      <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700;800&family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet" />

      {/* Sidebar */}
      <div style={{
        width: 240,
        minHeight: "100vh",
        background: C.surface,
        borderRight: `1px solid ${C.border}`,
        padding: "24px 12px",
        display: "flex",
        flexDirection: "column",
        gap: 4,
        position: "sticky",
        top: 0,
      }}>
        {/* Logo */}
        <div style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "8px 12px",
          marginBottom: 24,
        }}>
          <div style={{
            width: 36,
            height: 36,
            borderRadius: 10,
            background: `linear-gradient(135deg, ${C.accent}, ${C.purple})`,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 18,
            fontWeight: 900,
            color: C.bg,
            fontFamily: fontStack,
          }}>H</div>
          <div>
            <div style={{ fontSize: 15, fontWeight: 800, fontFamily: fontStack, letterSpacing: -0.5, color: C.text }}>
              HealthHub
            </div>
            <div style={{ fontSize: 10, color: C.textDim, fontFamily: fontStack, letterSpacing: 1, textTransform: "uppercase" }}>
              Fitness Tracker
            </div>
          </div>
        </div>

        {tabs.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              padding: "10px 14px",
              borderRadius: 10,
              border: "none",
              background: activeTab === tab.id ? C.accentDim : "transparent",
              color: activeTab === tab.id ? C.accent : C.textMuted,
              cursor: "pointer",
              fontSize: 13,
              fontWeight: activeTab === tab.id ? 700 : 500,
              fontFamily: fontBody,
              transition: "all 0.15s ease",
              width: "100%",
              textAlign: "left",
            }}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>

      {/* Main Content */}
      <div style={{ flex: 1, padding: 32, maxWidth: 1200 }}>
        {/* Header */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 28 }}>
          <div>
            <h1 style={{
              fontSize: 28,
              fontWeight: 800,
              fontFamily: fontStack,
              margin: 0,
              background: `linear-gradient(135deg, ${C.text}, ${C.accent})`,
              WebkitBackgroundClip: "text",
              WebkitTextFillColor: "transparent",
            }}>
              {tabs.find(t => t.id === activeTab)?.label || "Dashboard"}
            </h1>
            <p style={{ fontSize: 13, color: C.textDim, fontFamily: fontStack, margin: "4px 0 0" }}>
              {new Date().toLocaleDateString("pl-PL", { weekday: "long", year: "numeric", month: "long", day: "numeric" })}
            </p>
          </div>
          <button
            onClick={() => { syncSource("strava"); syncSource("garmin"); }}
            style={{ ...btnStyle(), display: "flex", alignItems: "center", gap: 6 }}
          >
            {Icons.sync} Sync
          </button>
        </div>

        {contentMap[activeTab]?.()}
      </div>

      {/* Notification Toast */}
      {notification && (
        <div style={{
          position: "fixed",
          bottom: 24,
          right: 24,
          padding: "14px 24px",
          borderRadius: 12,
          background: notification.type === "error" ? C.red : C.green,
          color: "#fff",
          fontWeight: 600,
          fontSize: 13,
          fontFamily: fontStack,
          boxShadow: "0 8px 32px rgba(0,0,0,0.3)",
          animation: "slideIn 0.3s ease",
          zIndex: 1000,
        }}>
          {notification.msg}
        </div>
      )}

      <style>{`
        @keyframes slideIn { from { transform: translateY(20px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }
        * { box-sizing: border-box; }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: ${C.bg}; }
        ::-webkit-scrollbar-thumb { background: ${C.border}; border-radius: 3px; }
        input:focus { border-color: ${C.accent} !important; box-shadow: 0 0 0 2px ${C.accentDim}; }
        button:hover { filter: brightness(1.1); }
      `}</style>
    </div>
  );
}
