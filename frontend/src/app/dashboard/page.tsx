"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import {
  Clock,
  ChevronRight,
  Play,
  GitBranch,
  Repeat,
  Network,
  Layers,
  Sparkles,
  BookOpen,
  Search,
  Globe,
  ChevronDown,
  Loader2,
  User as UserIcon,
  LogOut,
  BarChart3,
  CheckCircle2,
  Timer,
  Brain,
  ArrowRight,
  Upload,
  Zap,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useSessionStore } from "@/store/sessionStore";
import {
  getSessions,
  createSession as apiCreateSession,
  getUser,
  extractImageText,
} from "@/lib/api_sessions";
import { toast } from "sonner";
import { CleanPreview } from "@/components/ui/CleanPreview";

interface Session {
  id: string;
  topic: string;
  duration_ms?: number;
  started_at?: string;
  status: string;
}

const STATUS_META: Record<string, { label: string; cls: string }> = {
  CREATED: { label: "Created", cls: "bg-[#FAF8F5] text-[#5A6372] border border-[#E5DEC9]" },
  ACTIVE: { label: "Active", cls: "bg-green-50 text-green-700 border border-green-200" },
  PAUSED: { label: "Paused", cls: "bg-[#FFF5E6] text-[#B36B00] border border-[#F9A01B]/30" },
  COMPLETED: { label: "Completed", cls: "bg-blue-50 text-blue-700 border border-blue-200" },
  INTERRUPTED: { label: "Interrupted", cls: "bg-red-50 text-red-600 border border-red-200" },
};

function StatusBadge({ status }: { status: string }) {
  const meta = STATUS_META[status] || STATUS_META.CREATED;
  return (
    <span
      data-testid={`status-${status.toLowerCase()}`}
      className={`inline-flex items-center text-[10px] font-bold font-mono tracking-wide px-2 py-0.5 rounded-full ${meta.cls}`}
    >
      {meta.label}
    </span>
  );
}

function fmtDuration(ms: number): string {
  if (!ms) return "—";
  const m = Math.floor(ms / 60000);
  const s = Math.floor((ms % 60000) / 1000);
  return `${m}m ${s}s`;
}

function fmtDate(iso: string): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const now = new Date();
  return d.toDateString() === now.toDateString()
    ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString([], { month: "short", day: "numeric" });
}

export default function Dashboard() {
  const router = useRouter();
  const user = useSessionStore((s) => s.user);
  const logout = useSessionStore((s) => s.logout);
  const hasHydrated = useSessionStore((s) => s.hasHydrated);
  const [showProfileMenu, setShowProfileMenu] = useState(false);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [mastery, setMastery] = useState<Record<string, number>>({});
  const [customTopic, setCustomTopic] = useState("");
  const [selectedLanguage, setSelectedLanguage] = useState("en-US");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [isStarting, setIsStarting] = useState(false);
  const [isExtracting, setIsExtracting] = useState(false);
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const [imageFileName, setImageFileName] = useState<string | null>(null);
  const [imageDimensions, setImageDimensions] = useState<{ w: number; h: number } | null>(null);
  const [showImageLightbox, setShowImageLightbox] = useState(false);
  const [imageContext, setImageContext] = useState<{
    diagramDescription: string;
    mathEntities: string[];
    containsDiagram: boolean;
    learningGoal: string;
  } | null>(null);

  // Compose the full API topic string at lesson-start time (not stored in input).
  // Budget: 2800 chars (backend limit is 3000; leave room for safety).
  const composeApiTopic = (questionText: string, ctx: typeof imageContext): string => {
    if (!ctx) return questionText;
    const BUDGET = 2800;
    const parts: string[] = [];
    if (questionText.trim()) parts.push(questionText.trim());
    if (ctx.diagramDescription?.trim()) parts.push(`[Diagram: ${ctx.diagramDescription.trim()}]`);
    const base = parts.join("\n");
    const keyExpr = ctx.mathEntities?.length
      ? `Key expressions: ${ctx.mathEntities.join(", ")}`
      : "";
    if (keyExpr && base.length + keyExpr.length + 1 <= BUDGET) parts.push(keyExpr);
    if (!parts.length && ctx.learningGoal?.trim()) parts.push(ctx.learningGoal.trim());
    return (parts.join("\n") || questionText).slice(0, BUDGET);
  };

  const MAX_IMAGE_BYTES = 10 * 1024 * 1024; // 10 MB

  const applyExtractionResult = (result: Awaited<ReturnType<typeof extractImageText>>, toastId: string | number) => {
    const questionText = result.question_text?.trim() || result.learning_goal?.trim() || "";
    const hasDiagram = result.contains_diagram || !!result.diagram_description;
    if (!questionText && !hasDiagram && !result.math_entities?.length) {
      toast.error("Could not extract content from image.", { id: toastId });
      return;
    }
    // Keep the input field clean — only the human-readable question text
    setCustomTopic(questionText);
    setImageContext({
      diagramDescription: result.diagram_description || "",
      mathEntities: result.math_entities || [],
      containsDiagram: hasDiagram,
      learningGoal: result.learning_goal || "",
    });
    toast.success(hasDiagram ? "Diagram analyzed." : "Question extracted!", { id: toastId });
    if (result.needs_user_review) {
      toast.warning("OCR confidence is low — please verify the extracted text before starting.");
    }
  };

  const loadImageDimensions = (url: string) => {
    const img = new window.Image();
    img.onload = () => setImageDimensions({ w: img.naturalWidth, h: img.naturalHeight });
    img.src = url;
  };

  const removeImage = () => {
    if (imagePreview) URL.revokeObjectURL(imagePreview);
    setImagePreview(null);
    setImageFileName(null);
    setImageDimensions(null);
    setImageContext(null);
    setCustomTopic("");
    setShowImageLightbox(false);
  };

  const handleDashboardImageUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > MAX_IMAGE_BYTES) {
      toast.error("Image is too large. Please upload an image under 10 MB.");
      e.target.value = "";
      return;
    }
    if (imagePreview) URL.revokeObjectURL(imagePreview);
    setImageFileName(file.name);
    setImageDimensions(null);
    const objUrl = URL.createObjectURL(file);
    setImagePreview(objUrl);
    loadImageDimensions(objUrl);
    setIsExtracting(true);
    const toastId = toast.loading("Analyzing question from image...");
    try {
      const result = await extractImageText(file);
      applyExtractionResult(result, toastId);
    } catch { toast.error("Failed to extract text.", { id: toastId }); }
    finally { setIsExtracting(false); e.target.value = ""; }
  };

  const handleDashboardPaste = async (e: React.ClipboardEvent<HTMLInputElement>) => {
    for (const item of Array.from(e.clipboardData.items)) {
      if (item.type.startsWith("image/")) {
        const file = item.getAsFile();
        if (file) {
          e.preventDefault();
          if (file.size > MAX_IMAGE_BYTES) {
            toast.error("Pasted image is too large (max 10 MB).");
            break;
          }
          if (imagePreview) URL.revokeObjectURL(imagePreview);
          setImageFileName(file.name || "pasted-image.png");
          setImageDimensions(null);
          const objUrl = URL.createObjectURL(file);
          setImagePreview(objUrl);
          loadImageDimensions(objUrl);
          setIsExtracting(true);
          const toastId = toast.loading("Analyzing pasted image...");
          try {
            const result = await extractImageText(file);
            applyExtractionResult(result, toastId);
          } catch { toast.error("Extraction failed.", { id: toastId }); }
          finally { setIsExtracting(false); }
          break;
        }
      }
    }
  };

  useEffect(() => {
    const current = imagePreview;
    return () => { if (current) URL.revokeObjectURL(current); };
  }, [imagePreview]);

  useEffect(() => {
    if (!hasHydrated) return;
    if (!user) { router.push("/welcome"); return; }
    let mounted = true;
    getUser(user.id).catch((err) => {
      if (err instanceof Error && (err.message.includes("401") || err.message.includes("403") || err.message.includes("404"))) {
        logout();
        router.push("/welcome");
      } else {
        console.warn("Transient error checking user session:", err);
      }
    });
    getSessions(user.id).then((resp) => {
      if (mounted) {
        setSessions((resp.sessions || []).map((s: any) => ({ ...s, status: String(s.status || "CREATED").toUpperCase() })));
        setLoading(false);
      }
    }).catch(() => { if (mounted) setLoading(false); });
    if (user.mastery_scores) setMastery(user.mastery_scores);
    return () => { mounted = false; };
  }, [user, hasHydrated, router, logout]);

  const filtered = sessions.filter((s) => s.topic.toLowerCase().includes(search.toLowerCase()));
  const totalMs = sessions.reduce((a, s) => a + (s.duration_ms || 0), 0);
  const completed = sessions.filter((s) => s.status === "COMPLETED").length;
  const masteryAvg = Math.round(
    (Object.values(mastery).reduce((a, b) => a + b, 0) / Math.max(1, Object.keys(mastery).length)) * 100
  );

  const startNew = async (topicName: string) => {
    const baseText = topicName.trim();
    if (!baseText && !imageContext) { toast.error("Please enter a topic or question."); return; }
    if (isStarting) return;
    setIsStarting(true);
    // Compose the full topic (clean text + diagram/math context for the backend)
    const fullTopic = composeApiTopic(baseText, imageContext);
    try {
      const sess = await apiCreateSession(fullTopic, { user_id: user!.id, language: selectedLanguage });
      toast.success("Preparing your blackboard...");
      router.push(`/session/${sess.id}?topic=${encodeURIComponent(fullTopic)}&lang=${selectedLanguage}`);
    } catch { toast.error("Failed to create session."); setIsStarting(false); }
  };

  if (!user) return null;

  return (
    <div className="min-h-screen bg-[#FAF8F5] font-sans">

      {/* ── Top Nav — matches welcome page left panel feel ──────── */}
      <header className="sticky top-0 z-40 bg-white border-b border-[#E5DEC9] shadow-sm">
        <div className="max-w-[1300px] mx-auto px-6 h-14 flex items-center justify-between gap-4">
          {/* Brand — exact welcome page style */}
          <div className="flex items-center gap-2.5">
            <div className="h-11 w-11 relative overflow-hidden rounded-sm">
              <img src="/logo.png" alt="Sarasvi Logo" className="w-full h-full object-contain" />
            </div>
            <span className="font-display font-bold text-lg text-[#0B121F] tracking-tight">Sarasvi</span>
          </div>

          {/* Center label */}
          <div className="hidden md:flex items-center gap-1.5 text-[11px] font-mono font-semibold text-[#5A6372] uppercase tracking-widest">
            <BookOpen className="h-3.5 w-3.5" />
            Learning Space
          </div>

          {/* Profile */}
          <div className="relative">
            <button
              onClick={() => setShowProfileMenu(!showProfileMenu)}
              className="flex items-center gap-2 px-3 py-1.5 rounded-sm border border-[#E5DEC9] bg-white hover:bg-[#FAF8F5] hover:border-[#F9A01B]/40 transition-all text-sm font-medium text-[#0B121F] shadow-sm"
            >
              <div className="w-6 h-6 rounded-full bg-[#FFF5E6] border border-[#F9A01B]/30 flex items-center justify-center">
                <UserIcon className="h-3.5 w-3.5 text-[#F9A01B]" />
              </div>
              <span className="hidden sm:block max-w-[120px] truncate text-[#0B121F]">{user.name?.split(" ")[0]}</span>
              <ChevronDown className="h-3.5 w-3.5 text-[#5A6372]" />
            </button>

            {showProfileMenu && (
              <>
                <div className="fixed inset-0 z-40" onClick={() => setShowProfileMenu(false)} />
                <div className="absolute right-0 mt-2 w-64 bg-white border border-[#E5DEC9] rounded-sm p-4 shadow-xl z-50">
                  <div className="flex items-center gap-3 pb-3 mb-3 border-b border-[#E5DEC9]">
                    <div className="w-9 h-9 rounded-full bg-[#FFF5E6] border border-[#F9A01B]/20 flex items-center justify-center shrink-0">
                      <UserIcon className="h-4 w-4 text-[#F9A01B]" />
                    </div>
                    <div className="min-w-0">
                      <div className="font-semibold text-[#0B121F] text-sm truncate">{user.name}</div>
                      <div className="text-[10px] text-[#5A6372] font-mono truncate">{user.email}</div>
                    </div>
                  </div>
                  {user.learning_profile?.grade_level && (
                    <div className="flex justify-between text-xs py-1.5 mb-2 border-b border-[#E5DEC9]/40">
                      <span className="text-[#5A6372]">Grade</span>
                      <span className="text-[#0B121F] font-medium capitalize">{user.learning_profile.grade_level.replace("-", " ")}</span>
                    </div>
                  )}
                  <Button
                    variant="ghost"
                    onClick={() => { setShowProfileMenu(false); router.push("/profile"); }}
                    className="w-full h-8 text-xs justify-start px-2 text-[#0B121F] hover:bg-[#FAF8F5] hover:text-[#F9A01B] rounded-sm flex items-center gap-2 mb-1.5 font-medium border border-transparent hover:border-[#E5DEC9]"
                  >
                    <UserIcon className="h-3.5 w-3.5 text-[#F9A01B]" /> View Full Profile
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => { logout(); router.push("/welcome"); }}
                    className="w-full h-8 text-xs text-red-500 border-red-200 hover:bg-red-50 hover:border-red-300 rounded-sm"
                  >
                    <LogOut className="h-3.5 w-3.5 mr-1.5" /> Sign Out
                  </Button>
                </div>
              </>
            )}
          </div>
        </div>
      </header>

      {/* ── Main Content ─────────────────────────────────────────── */}
      <main className="max-w-[1300px] mx-auto px-6 py-8 space-y-6">

        {/* Greeting */}
        <div>
          <div className="text-xs font-mono font-bold tracking-widest text-[#F9A01B] uppercase mb-1">
            Learning Space
          </div>
          <h1 className="font-display text-[2rem] font-bold text-[#0B121F] tracking-tight leading-tight">
            Welcome back, {user?.name?.split(" ")[0] || "Learner"}.
          </h1>
          <p className="text-sm text-[#5A6372] mt-1 leading-relaxed">
            Choose a topic or type any question. Sarasvi will write out the explanation step-by-step on the blackboard.
          </p>
        </div>

        {/* ── Prompt Input Card ─────────────────────────────────── */}
        <div className="bg-white rounded-sm border border-[#E5DEC9] shadow-sm overflow-hidden">
          {/* Orange top accent stripe — same as welcome page feel */}
          <div className="h-[2px] w-full bg-gradient-to-r from-transparent via-[#F9A01B]/60 to-transparent" />

          <div className="p-6">
            <div className="flex items-center gap-2 mb-1">
              <Zap className="h-3.5 w-3.5 text-[#F9A01B]" />
              <span className="text-[10px] font-mono font-bold text-[#F9A01B] uppercase tracking-widest">Start a Lesson</span>
            </div>
            <h2 className="font-display text-xl font-semibold text-[#0B121F] tracking-tight mb-1">
              What would you like to learn today?
            </h2>
            <p className="text-xs text-[#5A6372] mb-5 leading-relaxed">
              Type any topic, equation, or coding problem. Your AI tutor will explain step-by-step on the blackboard.
            </p>

            {/* Input row */}
            <div className="flex flex-col sm:flex-row gap-3">
              <div className="relative flex-1">
                <Input
                  data-testid="custom-prompt-input"
                  value={customTopic}
                  onChange={(e) => setCustomTopic(e.target.value)}
                  onPaste={handleDashboardPaste}
                  placeholder="E.g. Solve (2x + 4)/2 = 5, explain Dijkstra, teach recursion..."
                  className="w-full h-12 pl-4 pr-24 bg-[#FAF8F5] border-[#E5DEC9] text-sm text-[#0B121F] placeholder:text-[#5A6372]/50 focus:border-[#F9A01B]/60 focus:ring-2 focus:ring-[#F9A01B]/10 rounded-sm transition-all"
                  onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); startNew(customTopic); } }}
                />
                <div className="absolute right-3 top-1/2 -translate-y-1/2 flex items-center gap-1.5">
                  <label className="cursor-pointer p-1.5 rounded text-[#5A6372] hover:text-[#F9A01B] hover:bg-[#FFF5E6] transition-all" title="Upload image">
                    <input type="file" accept="image/*" className="hidden" onChange={handleDashboardImageUpload} disabled={isExtracting} />
                    {isExtracting ? <Loader2 className="h-4 w-4 animate-spin text-[#F9A01B]" /> : <Upload className="h-4 w-4" />}
                  </label>
                  <kbd className="text-[10px] font-mono text-[#5A6372]/50 bg-[#FAF8F5] border border-[#E5DEC9] px-1.5 py-0.5 rounded-sm select-none">↵</kbd>
                </div>
              </div>

              {/* Language */}
              <div className="relative flex items-center w-full sm:w-44 h-12 shrink-0">
                <Globe className="absolute left-3 h-4 w-4 text-[#5A6372] pointer-events-none z-10" />
                <select
                  value={selectedLanguage}
                  onChange={(e) => setSelectedLanguage(e.target.value)}
                  className="w-full h-full pl-9 pr-8 border border-[#E5DEC9] bg-[#FAF8F5] hover:border-[#F9A01B]/40 rounded-sm text-[#0B121F] focus:border-[#F9A01B]/60 focus:ring-2 focus:ring-[#F9A01B]/10 outline-none cursor-pointer appearance-none text-xs font-semibold uppercase tracking-wide transition-all"
                >
                  <option value="en-US">English</option>
                  <option value="hinglish">Hinglish</option>
                  <option value="hi-IN">Hindi</option>
                </select>
                <ChevronDown className="absolute right-3 h-3.5 w-3.5 text-[#5A6372] pointer-events-none z-10" />
              </div>

              {/* CTA — exact welcome page button style */}
              <Button
                data-testid="spark-session-btn"
                onClick={() => startNew(customTopic)}
                disabled={isStarting}
                className="h-12 px-6 bg-[#F9A01B] hover:bg-[#FFA51E] active:scale-[0.98] text-white font-semibold text-sm rounded-sm transition-all shadow-sm shrink-0"
              >
                {isStarting ? (
                  <><Loader2 className="h-4 w-4 mr-2 animate-spin" /> Starting…</>
                ) : (
                  <><Sparkles className="h-4 w-4 mr-2" /> Start Lesson</>
                )}
              </Button>
            </div>

            {/* Compact attachment chip — click thumbnail to open lightbox */}
            {imagePreview && (
              <div className="mt-2 inline-flex items-center gap-2 bg-[#F0EDE8] border border-[#DDD8CC] rounded px-2 py-1.5 max-w-full">
                <button
                  onClick={() => setShowImageLightbox(true)}
                  className="shrink-0 rounded-sm overflow-hidden border border-[#DDD8CC] hover:border-[#F9A01B]/60 hover:opacity-90 transition-all"
                  title="Click to view full image"
                >
                  <img
                    src={imagePreview}
                    alt=""
                    className="h-8 w-14 object-cover block"
                  />
                </button>
                <div className="min-w-0 flex-1">
                  <div className="text-[11px] font-medium text-[#1A2433] truncate max-w-[220px]">
                    {imageFileName || "image"}
                  </div>
                  {imageDimensions && (
                    <div className="text-[9px] text-[#5A6372]">
                      {imageDimensions.w}×{imageDimensions.h}
                    </div>
                  )}
                </div>
                <button
                  onClick={removeImage}
                  className="shrink-0 h-4 w-4 rounded-full bg-[#D4CFC9] hover:bg-red-100 text-[#5A6372] hover:text-red-500 text-[10px] font-bold flex items-center justify-center transition-colors"
                  title="Remove image"
                >×</button>
              </div>
            )}

            {/* Image lightbox */}
            {showImageLightbox && imagePreview && (
              <div
                className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
                onClick={() => setShowImageLightbox(false)}
              >
                <div
                  className="relative max-w-[90vw] max-h-[90vh]"
                  onClick={(e) => e.stopPropagation()}
                >
                  <img
                    src={imagePreview}
                    alt={imageFileName || "Uploaded image"}
                    className="max-w-full max-h-[85vh] object-contain rounded shadow-2xl"
                  />
                  <button
                    onClick={() => setShowImageLightbox(false)}
                    className="absolute -top-3 -right-3 h-7 w-7 rounded-full bg-white text-[#1A2433] text-sm font-bold flex items-center justify-center shadow-lg hover:bg-red-50 hover:text-red-500 transition-colors"
                    title="Close"
                  >×</button>
                </div>
              </div>
            )}

            {/* Question preview — extracted text only, no image */}
            {customTopic.trim() && (
              <div className="mt-3 border border-[#F9A01B]/20 rounded-sm overflow-hidden bg-[#FFFDF9]">
                <div className="px-3 pt-2.5 pb-1 flex items-center gap-1.5 border-b border-[#F9A01B]/10">
                  <span className="text-[9px] font-bold text-[#F9A01B] uppercase tracking-widest">Question Preview</span>
                  {imageContext?.containsDiagram && (
                    <span className="text-[8px] font-semibold bg-amber-100 text-amber-700 border border-amber-200 px-1.5 py-0.5 rounded-full">
                      Diagram detected
                    </span>
                  )}
                </div>
                <div className="p-3">
                  <CleanPreview text={customTopic} plain />
                </div>
              </div>
            )}


          </div>
        </div>

        {/* ── Stats Row ─────────────────────────────────────────── */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-px bg-[#E5DEC9] border border-[#E5DEC9] rounded-sm shadow-sm overflow-hidden">
          {[
            { icon: BarChart3, label: "Total Sessions", value: sessions.length },
            { icon: CheckCircle2, label: "Completed", value: completed },
            { icon: Timer, label: "Total Learning Time", value: fmtDuration(totalMs) },
            { icon: Brain, label: "Avg Mastery", value: `${masteryAvg}%` },
          ].map((stat) => (
            <div key={stat.label} className="px-6 py-5 flex items-start gap-3 bg-white group hover:bg-[#FAF8F5] transition-colors">
              <stat.icon className="h-4 w-4 text-[#F9A01B] mt-1 shrink-0" strokeWidth={1.8} />
              <div>
                <div className="text-[9px] font-mono font-bold text-[#5A6372] uppercase tracking-widest">{stat.label}</div>
                <div className="font-display text-2xl font-bold text-[#0B121F] tracking-tight mt-1">{stat.value}</div>
              </div>
            </div>
          ))}
        </div>



        {/* ── Past Sessions ─────────────────────────────────────── */}
        <div className="bg-white rounded-sm border border-[#E5DEC9] shadow-sm overflow-hidden">
          <div className="flex items-center justify-between px-5 py-4 border-b border-[#E5DEC9]">
            <div>
              <div className="text-[9px] font-mono font-bold text-[#5A6372] uppercase tracking-widest">Past Sessions</div>
              <div className="text-[10px] text-[#5A6372]/60 font-mono mt-0.5">{sessions.length} total · {completed} completed</div>
            </div>
            <div className="relative w-56">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-[#5A6372]/60" />
              <Input
                data-testid="search-sessions-input"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search sessions..."
                className="w-full h-9 pl-9 pr-3 bg-[#FAF8F5] border-[#E5DEC9] text-xs rounded-sm focus:border-[#F9A01B]/50 focus:ring-1 focus:ring-[#F9A01B]/20 placeholder:text-[#5A6372]/40"
              />
            </div>
          </div>

          {loading ? (
            <div className="py-16 text-center">
              <Loader2 className="h-5 w-5 animate-spin mx-auto mb-2 text-[#E5DEC9]" />
              <p className="text-sm text-[#5A6372] font-mono">Loading past sessions…</p>
            </div>
          ) : filtered.length === 0 ? (
            <div className="py-16 text-center">
              <BookOpen className="h-8 w-8 mx-auto text-[#E5DEC9] mb-3" />
              <p className="text-sm text-[#5A6372]">No sessions yet.</p>
              <p className="text-xs text-[#5A6372]/60 mt-1">Type a question above to start your first lesson.</p>
            </div>
          ) : (
            <div className="divide-y divide-[#E5DEC9]">
              {filtered.map((s) => (
                <div
                  key={s.id}
                  data-testid={`session-row-${s.id}`}
                  className="flex items-center justify-between px-5 py-3.5 hover:bg-[#FAF8F5] transition-colors group"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2.5">
                      <span className="font-medium text-sm text-[#0B121F] group-hover:text-[#0B121F] max-w-xl block truncate">
                        <CleanPreview text={s.topic} plain />
                      </span>
                      <StatusBadge status={s.status} />
                    </div>
                    <div className="flex items-center gap-3 mt-0.5">
                      <span className="text-[10px] text-[#5A6372] font-mono flex items-center gap-1">
                        <Clock className="h-3 w-3" /> {fmtDuration(s.duration_ms || 0)}
                      </span>
                      <span className="text-[10px] text-[#5A6372]/50 font-mono">{fmtDate(s.started_at || "")}</span>
                    </div>
                  </div>

                  {s.status === "COMPLETED" ? (
                    <Button
                      variant="outline"
                      size="sm"
                      data-testid={`replay-${s.id}`}
                      onClick={() => router.push(`/session/${s.id}/replay?topic=${encodeURIComponent(s.topic)}`)}
                      className="rounded-sm h-8 text-xs border-[#E5DEC9] bg-white hover:border-[#F9A01B]/50 hover:bg-[#FFF5E6] hover:text-[#B36B00] transition-all shrink-0 ml-4 font-medium"
                    >
                      <Play className="h-3 w-3 mr-1.5 fill-current" /> Replay
                    </Button>
                  ) : (
                    <Button
                      variant="outline"
                      size="sm"
                      data-testid={`resume-${s.id}`}
                      onClick={() => router.push(`/session/${s.id}?topic=${encodeURIComponent(s.topic)}`)}
                      className="rounded-sm h-8 text-xs border-[#F9A01B]/40 bg-[#FFF5E6] text-[#B36B00] hover:bg-[#FFF0D9] hover:border-[#F9A01B]/60 transition-all shrink-0 ml-4 font-medium"
                    >
                      <Play className="h-3 w-3 mr-1.5 fill-current" /> Open
                    </Button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
