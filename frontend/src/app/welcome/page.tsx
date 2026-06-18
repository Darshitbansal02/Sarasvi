"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { motion } from "framer-motion";
import { ArrowRight, ArrowLeft, Sparkles, Brain, Eye, Hammer, MessageSquare, Mail, User, GraduationCap, Lock, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useSessionStore } from "@/store/sessionStore";
import { registerUser, loginUser } from "@/lib/api_sessions";
import { toast } from "sonner";

const PACES = [
  { id: "slow", label: "Take it slow", hint: "I want to chew on each idea" },
  { id: "normal", label: "Balanced", hint: "Move with momentum" },
  { id: "fast", label: "Move fast", hint: "Surface tension is fine" },
];

const STYLES = [
  { id: "visual", label: "Visual / diagrams", icon: Eye },
  { id: "analogy", label: "Analogies / stories", icon: MessageSquare },
  { id: "code", label: "Code & formalism", icon: Brain },
  { id: "hands-on", label: "Hands-on examples", icon: Hammer },
];

const GRADE_LEVELS = [
  { id: "middle-school", label: "Middle School", hint: "Grades 6 - 8" },
  { id: "high-school", label: "High School", hint: "Grades 9 - 12" },
  { id: "college", label: "College / University", hint: "Undergraduate / Graduate" },
  { id: "professional", label: "Professional / Adult", hint: "Continuous self-improvement" },
];

export default function Welcome() {
  const router = useRouter();
  const setUser = useSessionStore((s) => s.setUser);

  const [showLanding, setShowLanding] = useState(true);
  const [showTerms, setShowTerms] = useState(false);
  const [agreedToTerms, setAgreedToTerms] = useState(false);
  const [isLogin, setIsLogin] = useState(false);
  const [loginEmail, setLoginEmail] = useState("");
  const [loginPassword, setLoginPassword] = useState("");

  const [step, setStep] = useState(0);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [age, setAge] = useState("");
  const [gradeLevel, setGradeLevel] = useState("");
  const [pace, setPace] = useState("normal");
  const [style, setStyle] = useState("visual");
  const [analogy, setAnalogy] = useState("real-world");
  const [hobby, setHobby] = useState("");
  const [loading, setLoading] = useState(false);

  const [hasLoadedSavedState, setHasLoadedSavedState] = useState(false);

  useEffect(() => {
    try {
      const saved = sessionStorage.getItem("sarasvi_onboarding_state");
      if (saved) {
        const parsed = JSON.parse(saved);
        if (parsed.showLanding !== undefined) setShowLanding(parsed.showLanding);
        if (parsed.showTerms !== undefined) setShowTerms(parsed.showTerms);
        if (parsed.agreedToTerms !== undefined) setAgreedToTerms(parsed.agreedToTerms);
        if (parsed.isLogin !== undefined) setIsLogin(parsed.isLogin);
        if (parsed.loginEmail !== undefined) setLoginEmail(parsed.loginEmail);
        if (parsed.loginPassword !== undefined) setLoginPassword(parsed.loginPassword);
        if (parsed.step !== undefined) setStep(parsed.step);
        if (parsed.email !== undefined) setEmail(parsed.email);
        if (parsed.password !== undefined) setPassword(parsed.password);
        if (parsed.name !== undefined) setName(parsed.name);
        if (parsed.age !== undefined) setAge(parsed.age);
        if (parsed.gradeLevel !== undefined) setGradeLevel(parsed.gradeLevel);
        if (parsed.pace !== undefined) setPace(parsed.pace);
        if (parsed.style !== undefined) setStyle(parsed.style);
        if (parsed.analogy !== undefined) setAnalogy(parsed.analogy);
        if (parsed.hobby !== undefined) setHobby(parsed.hobby);
      }
    } catch (e) {
      console.error("Error reading saved onboarding state", e);
    }
    setHasLoadedSavedState(true);
  }, []);

  useEffect(() => {
    if (!hasLoadedSavedState) return;
    try {
      const stateToSave = {
        showLanding,
        showTerms,
        agreedToTerms,
        isLogin,
        loginEmail,
        loginPassword,
        step,
        email,
        password,
        name,
        age,
        gradeLevel,
        pace,
        style,
        analogy,
        hobby,
      };
      sessionStorage.setItem("sarasvi_onboarding_state", JSON.stringify(stateToSave));
    } catch (e) {
      console.error("Error saving onboarding state", e);
    }
  }, [
    hasLoadedSavedState,
    showLanding,
    showTerms,
    agreedToTerms,
    isLogin,
    loginEmail,
    loginPassword,
    step,
    email,
    password,
    name,
    age,
    gradeLevel,
    pace,
    style,
    analogy,
    hobby,
  ]);

  // Switch modes and transfer typed email context
  const toggleMode = () => {
    if (isLogin) {
      setIsLogin(false);
      setEmail(loginEmail);
      setStep(0);
    } else {
      setIsLogin(true);
      setLoginEmail(email);
    }
  };

  const handleLogin = async () => {
    if (!loginEmail.trim() || !loginPassword) {
      toast.error("Please enter your email and password.");
      return;
    }
    setLoading(true);
    try {
      const user = await loginUser(loginEmail.trim().toLowerCase(), loginPassword);
      setUser(user);
      toast.success(`Welcome back, ${user.name}!`);
      setShowTerms(true);
    } catch (e: any) {
      toast.error(e?.message || "Invalid email or password.");
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  // Validate email + password locally, then advance the wizard. Existing-email
  // detection now happens server-side at registration (409), so we no longer
  // probe the backend (which would leak which emails are registered).
  const handleEmailStepContinue = async () => {
    if (!validateEmail(email)) {
      toast.error("Please enter a valid email address.");
      return;
    }
    if (password.length < 8) {
      toast.error("Password must be at least 8 characters.");
      return;
    }
    setStep(1);
  };

  const submitRegistration = async () => {
    setLoading(true);
    try {
      const parsedAge = parseInt(age) || 18;
      const user = await registerUser(
        email.trim().toLowerCase(),
        name,
        password,
        {
          pace,
          hobbies: [hobby],
          age: parsedAge,
          grade_level: gradeLevel || "college",
        }
      );

      setUser(user);
      toast.success("Profile created successfully!");
      setShowTerms(true);
    } catch (e: any) {
      const msg = e?.message || "Failed to create profile.";
      if (/already registered|409/i.test(msg)) {
        toast.info("This email is already registered. Please log in.");
        setLoginEmail(email);
        setIsLogin(true);
      } else {
        toast.error(msg);
      }
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const validateEmail = (emailStr: string) => {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(emailStr);
  };

  const totalSteps = 3;

  return (
    <div className="min-h-screen w-full flex flex-col lg:flex-row bg-black">
      {/* Decorative branding sidebar (Left Panel - Cream/Light) */}
      <div className="hidden lg:flex lg:w-[50%] relative overflow-hidden bg-[#FAF8F5] border-r border-[#E5DEC9] p-16 flex-col justify-between">
        {/* Subtle grid backdrop */}
        <div className="absolute inset-0 dotgrid-bg opacity-40 pointer-events-none" />
        <div className="absolute inset-0 bg-gradient-to-b from-transparent via-transparent to-[#FAF8F5]/30 pointer-events-none" />

        {/* Hand-drawn math elements (Left Panel - Dark charcoal color with proper visibility) */}
        {/* E = mc² with underlines */}
        <svg viewBox="0 0 150 80" className="absolute top-[8%] right-[10%] w-32 h-auto text-[#0B121F]/75 pointer-events-none" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M 20,15 L 45,13 M 20,15 L 23,45 L 48,43 M 20,29 L 40,28" />
          <path d="M 58,22 L 72,21 M 57,30 L 71,29" />
          <path d="M 82,42 L 82,27 C 82,23 88,23 88,27 L 88,42 C 88,23 96,23 96,27 L 96,42" />
          <path d="M 118,28 C 115,24 106,25 106,33 C 106,41 114,41 117,37" />
          <path d="M 125,18 C 125,13 131,13 131,18 C 131,22 124,24 124,27 L 132,27" />
          <path d="M 15,55 C 50,51 90,56 135,50" />
          <path d="M 18,61 C 55,57 85,62 130,56" />
        </svg>

        {/* Right-angled triangle */}
        <svg viewBox="0 0 120 120" className="absolute right-[8%] top-[38%] w-28 h-auto text-[#0B121F]/75 pointer-events-none" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M 32,20 L 34,90 L 102,88 Z" />
          <path d="M 34,80 L 44,79 L 43,89" />
          {/* Label a - circle + stem */}
          <path d="M 17,58 C 17,55 13,55 13,58 C 13,61 17,61 17,58 Z M 17,55 L 17,61" />
          {/* Label b */}
          <path d="M 60,98 L 60,110 M 60,104 C 64,104 65,110 60,110" />
          {/* Label c */}
          <path d="M 72,40 C 69,37 65,41 68,45 C 70,47 73,45 74,43" />
        </svg>

        {/* Coordinate axis with curve y = f(x) */}
        <svg viewBox="0 0 120 120" className="absolute right-[12%] bottom-[8%] w-32 h-auto text-[#0B121F]/75 pointer-events-none" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M 25,100 L 23,20 L 20,25 M 23,20 L 26,25" />
          <path d="M 20,90 L 100,88 L 95,85 M 100,88 L 95,91" />
          <path d="M 23,10 L 26,15 L 29,10 M 26,15 L 26,19" />
          <path d="M 106,85 L 112,91 M 112,85 L 106,91" />
          <path d="M 23,80 Q 55,82 75,55 T 100,35" strokeWidth="2.2" />
          <path d="M 60,25 C 57,22 53,25 55,28 C 57,30 60,28 61,26 L 59,32" />
          <path d="M 66,26 L 72,26 M 66,29 L 72,29" />
          <path d="M 78,21 L 82,21 M 80,21 L 80,31 M 78,31 L 82,31" />
          <path d="M 85,23 C 83,23 83,29 85,29" />
          <path d="M 88,24 L 92,28 M 92,24 L 88,28" />
          <path d="M 94,23 C 96,23 96,29 94,29" />
        </svg>

        {/* ax² + bx + c = 0 with wavy underline (Positioned to the right of the version label to prevent overlap) */}
        <svg viewBox="0 0 160 60" className="absolute left-[32%] bottom-[4.5%] w-36 h-auto text-[#0B121F]/75 pointer-events-none" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          {/* a - circle + stem */}
          <path d="M 20,26 C 20,23 16,23 16,26 C 16,29 20,29 20,26 Z M 20,23 L 20,31" />
          {/* x */}
          <path d="M 26,23 L 34,31 M 34,23 L 26,31" />
          {/* 2 */}
          <path d="M 37,18 C 37,14 41,14 41,17 C 41,20 37,21 37,23 L 42,23" />
          {/* + */}
          <path d="M 49,27 L 57,27 M 53,23 L 53,31" />
          {/* b */}
          <path d="M 64,15 L 64,31 M 64,25 C 68,25 70,31 64,31" />
          {/* x */}
          <path d="M 75,23 L 83,31 M 83,23 L 75,31" />
          {/* + */}
          <path d="M 90,27 L 98,27 M 94,23 L 94,31" />
          {/* c */}
          <path d="M 110,25 C 107,22 102,23 102,27 C 102,31 107,32 109,29" />
          {/* = */}
          <path d="M 117,24 L 127,24 M 117,29 L 127,29" />
          {/* 0 */}
          <path d="M 134,27 C 134,23 140,23 140,27 C 140,31 134,31 134,27 Z" />
          <path d="M 30,42 Q 40,39 50,42 T 70,42 T 90,42 T 110,42" />
        </svg>

        {/* Brand Logo and Name */}
        <div className="relative z-10 flex items-center gap-4">
          <div className="h-16 w-16 relative overflow-hidden rounded-sm">
            <img src="/logo.png" alt="Sarasvi Logo" className="w-full h-full object-contain" />
          </div>
          <span className="font-display font-bold text-3xl text-[#0B121F] tracking-tight">Sarasvi</span>
        </div>

        {/* Content Showcase */}
        <div className="relative z-10 space-y-6 max-w-lg my-auto">
          <div className="text-xs font-mono font-bold tracking-widest text-[#F9A01B] uppercase">
            Interactive Learning Board
          </div>
          <h1 className="font-display text-4xl lg:text-[46px] font-bold tracking-tight text-[#0B121F] leading-[1.15]">
            A personal tutor that draws lessons on a blackboard and adapts when you ask <span className="text-[#F9A01B]">questions.</span>
          </h1>
          <p className="text-sm text-[#5A6372] leading-relaxed max-w-md">
            Tell us how you learn, and Sarasvi will explain concepts in your style: using diagrams, stories,
            code, or real-world examples. Ask questions at any time, and the board will adapt.
          </p>
        </div>

        {/* Version Details */}
        <div className="relative z-10 flex items-center gap-3">
          <span className="px-2.5 py-1 text-xs font-mono font-bold text-[#F9A01B] bg-[#FFF5E6] border border-[#F9A01B]/20 rounded-sm select-none">
            v0.1
          </span>
          <span className="text-xs text-[#5A6372] font-mono">
            Interactive drawing chalkboard
          </span>
        </div>
      </div>

      {/* Main onboarding container (Right Panel - Navy/Dark) */}
      <div className="dark flex-1 lg:w-[50%] bg-black flex items-center justify-center p-8 lg:p-16 relative min-h-screen">
        {/* Hand-drawn math elements (Right Panel - White color with proper visibility) */}
        {/* Quadratic formula */}
        <svg viewBox="0 0 200 80" className="absolute left-[8%] top-[6%] w-48 h-auto text-white/[0.75] pointer-events-none" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M 15,35 L 25,45 M 25,35 L 15,45" />
          <path d="M 33,37 L 45,37 M 33,43 L 45,43" />
          <path d="M 52,40 L 175,40" strokeWidth="2" />
          <path d="M 58,26 L 68,26" />
          <path d="M 75,14 L 75,30 M 75,24 C 80,24 81,30 75,30" />
          <path d="M 87,25 L 97,25 M 92,20 L 92,30 M 87,31 L 97,31" />
          <path d="M 104,27 L 108,31 L 113,12 L 170,12" strokeWidth="1.8" />
          <path d="M 119,19 L 119,29 M 119,25 C 123,25 124,29 119,29" />
          <path d="M 127,17 C 127,14 130,14 130,16 C 130,18 127,19 127,21 L 131,21" />
          <path d="M 136,24 L 144,24" />
          <path d="M 149,19 L 149,25 L 155,25 M 153,19 L 153,29" />
          {/* a - circle + stem */}
          <path d="M 164,26 C 164,23 160,23 160,26 C 160,29 164,29 164,26 Z M 164,23 L 164,29" />
          <path d="M 172,25 C 170,23 167,24 167,26 C 167,29 170,30 172,28" />
          <path d="M 103,55 C 103,51 108,51 108,54 C 108,57 103,59 103,61 L 109,61" />
          {/* a - circle + stem */}
          <path d="M 118,58 C 118,55 114,55 114,58 C 114,61 118,61 118,58 Z M 118,55 L 118,61" />
        </svg>

        {/* Atom / orbit drawing */}
        <svg viewBox="0 0 100 100" className="absolute right-[8%] top-[8%] w-24 h-auto text-white/[0.75] pointer-events-none" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="50" cy="50" r="4" fill="currentColor" />
          <circle cx="46" cy="48" r="3" fill="currentColor" />
          <circle cx="53" cy="52" r="3" fill="currentColor" />
          <ellipse cx="50" cy="50" rx="40" ry="15" transform="rotate(30 50 50)" />
          <ellipse cx="50" cy="50" rx="40" ry="15" transform="rotate(90 50 50)" />
          <ellipse cx="50" cy="50" rx="40" ry="15" transform="rotate(150 50 50)" />
          <circle cx="20" cy="33" r="2" fill="currentColor" />
          <circle cx="80" cy="67" r="2" fill="currentColor" />
          <circle cx="50" cy="10" r="2" fill="currentColor" />
        </svg>

        {/* Summation summation formula */}
        <svg viewBox="0 0 180 80" className="absolute left-[8%] bottom-[8%] w-44 h-auto text-white/[0.75] pointer-events-none" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M 38,22 L 20,22 L 29,35 L 20,48 L 38,48" strokeWidth="2.2" />
          {/* n at top - fixed to go downward */}
          <path d="M 25,10 L 25,16 M 25,12 C 25,10 29,10 29,12 L 29,16" />
          <path d="M 23,55 L 23,62 M 23,52 L 23,53" />
          <path d="M 27,56 L 33,56 M 27,60 L 33,60" />
          <path d="M 37,54 L 39,52 L 39,62" />
          <path d="M 48,32 L 48,40 M 48,29 L 48,30" />
          <path d="M 57,32 L 67,32 M 57,37 L 67,37" />
          <path d="M 74,35 L 140,35" strokeWidth="2" />
          {/* n - fixed */}
          <path d="M 82,18 L 82,26 M 82,21 C 82,19 86,19 86,21 L 86,26" />
          <path d="M 93,17 C 91,19 91,25 93,27" />
          {/* n - fixed */}
          <path d="M 98,18 L 98,26 M 98,21 C 98,19 102,19 102,21 L 102,26" />
          <path d="M 108,22 L 116,22 M 112,18 L 112,26" />
          <path d="M 121,19 L 123,17 L 123,26" />
          <path d="M 128,17 C 130,19 130,25 128,27" />
          <path d="M 104,52 C 104,48 109,48 109,51 C 109,54 104,56 104,58 L 110,58" />
        </svg>

        {/* Angle circle sector with Theta */}
        <svg viewBox="0 0 100 100" className="absolute right-[8%] bottom-[8%] w-24 h-auto text-white/[0.75] pointer-events-none" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="50" cy="50" r="35" />
          <path d="M 50,50 L 85,50" />
          <path d="M 50,50 L 75,25" />
          <path d="M 57,50 L 54,43" />
          <path d="M 64,50 L 59,39" />
          <path d="M 71,50 L 63,35" />
          <path d="M 78,50 L 68,31" />
          <path d="M 65,50 A 15,15 0 0,0 61,39" />
          <path d="M 68,30 C 65,30 65,36 68,36 C 71,36 71,30 68,30 Z M 65,33 L 71,33" />
        </svg>

        {!showLanding && (
          <div className="absolute top-8 right-8 z-20">
            <Button
              variant="ghost"
              onClick={() => {
                setShowLanding(true);
                setShowTerms(false);
                setAgreedToTerms(false);
              }}
              className="text-xs font-mono text-[#8B95A5] hover:text-white hover:bg-white/5 flex items-center gap-1.5 px-3 py-1.5 rounded-sm transition-all"
            >
              <ArrowLeft className="h-3.5 w-3.5" /> Back to start
            </Button>
          </div>
        )}

        <motion.div
          key={showTerms ? "terms" : showLanding ? "landing" : isLogin ? "login" : "register"}
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="w-full max-w-md space-y-8"
        >
          {showTerms ? (
            /* TERMS / DISCLAIMER SCREEN */
            <div className="space-y-6">
              <div>
                <div className="text-xs font-mono font-semibold tracking-wider text-[#F9A01B] uppercase">Accept Terms & Conditions</div>
                <h2 className="font-display text-3xl font-bold tracking-tight text-white mt-2">
                  Interactive Learning Space
                </h2>
                <p className="text-xs text-[#8B95A5] mt-1">
                  Before you enter the platform, please review our terms of use.
                </p>
              </div>

              {/* Terms and Conditions Box */}
              <div className="border border-white/10 p-5 rounded-sm bg-[#121C2A]/60 text-xs space-y-3 font-sans h-48 overflow-y-auto scrollbar-thin">
                <div className="font-semibold text-white">1. How to Use Sarasvi</div>
                <p className="text-[#8B95A5] leading-relaxed">
                  Type any topic, equation, or question you wish to learn. Sarasvi will dynamically draw explanations, visual nodes, formulas, and narration steps on the interactive chalkboard. You can ask clarifying questions at any point during a lesson by clicking the "Ask a Question" button.
                </p>
                <div className="font-semibold text-white mt-2">2. AI Disclaimer & Limitation of Liability</div>
                <p className="text-[#8B95A5] leading-relaxed">
                  Sarasvi is powered by artificial intelligence. All content, diagrams, code examples, answers, and tutoring responses are generated dynamically by AI. <strong>We are not responsible for any answer, fact, formula, explanation, or calculation provided by the platform.</strong> AI models may generate incorrect or inaccurate information. Users should verify critical calculations and facts independently.
                </p>
              </div>

              {/* Agreement Checkbox */}
              <div className="flex items-start gap-3 pt-2">
                <input
                  type="checkbox"
                  id="agree-checkbox"
                  checked={agreedToTerms}
                  onChange={(e) => setAgreedToTerms(e.target.checked)}
                  className="mt-1 h-4 w-4 rounded border-white/20 text-[#F9A01B] focus:ring-[#F9A01B] cursor-pointer accent-[#F9A01B]"
                />
                <label htmlFor="agree-checkbox" className="text-xs text-[#8B95A5] leading-snug cursor-pointer select-none">
                  I have read and agree to the{" "}
                  <Link href="/terms" className="text-[#F9A01B] hover:underline">
                    Terms of Service &amp; AI Disclaimer
                  </Link>
                  .
                </label>
              </div>

              <div className="pt-4 border-t border-white/5">
                <Button
                  onClick={() => {
                    if (!agreedToTerms) {
                      toast.error("Please agree to the Terms of Service & AI Disclaimer.");
                      return;
                    }
                    toast.success("Welcome to Sarasvi!");
                    router.push("/dashboard");
                  }}
                  disabled={!agreedToTerms}
                  className="w-full h-12 rounded-sm font-semibold bg-[#F9A01B] hover:bg-[#FFA51E] disabled:opacity-50 text-white shadow-sm transition-all active:scale-[0.99]"
                >
                  I Agree & Enter Platform <ArrowRight className="h-4 w-4 ml-2" />
                </Button>
              </div>
            </div>
          ) : showLanding ? (
            /* LANDING / WELCOME SELECTION */
            <div className="space-y-8">
              <div>
                <div className="text-xs font-mono font-semibold tracking-wider text-[#F9A01B] uppercase">Welcome to Sarasvi</div>
                <h2 className="font-display text-4xl font-bold tracking-tight text-white mt-2">
                  Interactive Learning Space
                </h2>
                <p className="text-sm text-[#8B95A5] mt-2 leading-relaxed">
                  A personal tutor that draws lessons on a blackboard and adapts when you ask questions.
                </p>
              </div>

              <div className="space-y-4">
                <button
                  onClick={() => {
                    setIsLogin(true);
                    setShowLanding(false);
                  }}
                  className="w-full h-14 px-5 rounded-sm border border-white/10 bg-white/[0.03] hover:bg-white/[0.06] transition-all flex items-center justify-between text-left text-white shadow-lg group active:scale-[0.99]"
                >
                  <div className="flex items-center gap-3">
                    <div className="h-9 w-9 rounded bg-white/5 flex items-center justify-center text-[#8B95A5] group-hover:text-white transition-colors">
                      <User className="h-4.5 w-4.5" />
                    </div>
                    <span className="text-sm font-medium">
                      Already have an account? <span className="text-[#F9A01B] ml-1 font-semibold group-hover:underline">Log In</span>
                    </span>
                  </div>
                  <ChevronRight className="h-4.5 w-4.5 text-[#8B95A5] group-hover:translate-x-0.5 transition-transform" />
                </button>

                <button
                  onClick={() => {
                    setIsLogin(false);
                    setShowLanding(false);
                    setStep(0);
                  }}
                  className="w-full h-14 px-5 rounded-sm bg-[#F9A01B] hover:bg-[#FFA51E] text-white font-semibold shadow-sm transition-all flex items-center justify-between group active:scale-[0.99]"
                >
                  <div className="flex items-center gap-3">
                    <span className="text-sm font-medium">Create a New Account</span>
                  </div>
                  <ArrowRight className="h-4.5 w-4.5 group-hover:translate-x-0.5 transition-transform" />
                </button>
              </div>
              <p className="text-center text-[10px] text-[#8B95A5]/60 pt-2">
                By signing up you agree to our{" "}
                <Link href="/terms" className="text-[#8B95A5] hover:text-[#F9A01B] underline underline-offset-2 transition-colors">
                  Terms of Service &amp; AI Disclaimer
                </Link>
              </p>
            </div>
          ) : isLogin ? (
            /* LOGIN SCREEN */
            <div className="space-y-6">
              <div>
                <div className="text-xs font-mono font-semibold tracking-wider text-[#F9A01B] uppercase">sign in</div>
                <h2 className="font-display text-3xl font-bold tracking-tight text-white mt-2">
                  Welcome back to Sarasvi
                </h2>
                <p className="text-xs text-[#8B95A5] mt-1">
                  Enter your credentials to access your learning dashboard.
                </p>
              </div>

              <div className="space-y-4">
                <div className="relative">
                  <Mail className="absolute left-4 top-1/2 -translate-y-1/2 h-4.5 w-4.5 text-[#8B95A5]" />
                  <Input
                    data-testid="login-email-input"
                    type="email"
                    placeholder="name@example.com"
                    value={loginEmail}
                    onChange={(e) => setLoginEmail(e.target.value)}
                    className="h-12 pl-12 rounded-sm bg-[#0B131F] border-white/20 text-white font-mono placeholder-[#8B95A5]/70 focus:border-[#F9A01B] focus-visible:ring-[#F9A01B] transition-all"
                  />
                </div>
                <div className="relative">
                  <Lock className="absolute left-4 top-1/2 -translate-y-1/2 h-4.5 w-4.5 text-[#8B95A5]" />
                  <Input
                    data-testid="login-password-input"
                    type="password"
                    placeholder="Password"
                    value={loginPassword}
                    onChange={(e) => setLoginPassword(e.target.value)}
                    className="h-12 pl-12 rounded-sm bg-[#0B131F] border-white/20 text-white placeholder-[#8B95A5]/70 focus:border-[#F9A01B] focus-visible:ring-[#F9A01B] transition-all"
                    onKeyDown={(e) => {
                      if (e.key === "Enter") handleLogin();
                    }}
                  />
                </div>
                <Button
                  data-testid="login-submit"
                  onClick={handleLogin}
                  disabled={loading || !loginEmail.trim() || !loginPassword}
                  className="w-full h-12 rounded-sm font-semibold bg-[#F9A01B] hover:bg-[#FFA51E] disabled:bg-[#1E293B] disabled:text-white/30 disabled:border disabled:border-white/10 text-white shadow-sm transition-all active:scale-[0.99]"
                >
                  {loading ? "Verifying..." : "Enter Sarasvi"} <ArrowRight className="h-4 w-4 ml-2" />
                </Button>
                <p className="text-center text-[10px] text-[#8B95A5]/60 pt-1">
                  <Link href="/terms" className="text-[#8B95A5] hover:text-[#F9A01B] underline underline-offset-2 transition-colors">
                    Terms of Service &amp; AI Disclaimer
                  </Link>
                </p>
              </div>
            </div>
          ) : (
            /* REGISTRATION WIZARD */
            <div className="space-y-6">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-xs font-mono font-semibold tracking-wider text-[#F9A01B] uppercase">step {step + 1} / {totalSteps}</div>
                  <h2 className="font-display text-2xl font-bold tracking-tight text-white mt-2">
                    {step === 0 && "Account Setup"}
                    {step === 1 && "Academic & Pace"}
                    {step === 2 && "Personalize Analogies"}
                  </h2>
                </div>
                {step > 0 && (
                  <Button
                    variant="outline"
                    size="icon"
                    onClick={() => setStep(step - 1)}
                    className="h-9 w-9 rounded-full border-white/10 bg-white/5 hover:bg-white/10 text-[#8B95A5] hover:text-white"
                  >
                    <ArrowLeft className="h-4 w-4" />
                  </Button>
                )}
              </div>               {/* Step 0: Account Info */}
              {step === 0 && (
                <div className="space-y-4">
                  <div className="relative">
                    <User className="absolute left-4 top-1/2 -translate-y-1/2 h-4.5 w-4.5 text-[#8B95A5]" />
                    <Input
                      data-testid="welcome-name-input"
                      placeholder="Your full name"
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      className="h-12 pl-12 rounded-sm bg-[#0B131F] border-white/20 text-white placeholder-[#8B95A5]/70 focus:border-[#F9A01B] focus-visible:ring-[#F9A01B] transition-all"
                    />
                  </div>
                  <div className="relative">
                    <Mail className="absolute left-4 top-1/2 -translate-y-1/2 h-4.5 w-4.5 text-[#8B95A5]" />
                    <Input
                      data-testid="welcome-email-input"
                      type="email"
                      placeholder="Email address (name@example.com)"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      className="h-12 pl-12 rounded-sm bg-[#0B131F] border-white/20 text-white font-mono placeholder-[#8B95A5]/70 focus:border-[#F9A01B] focus-visible:ring-[#F9A01B] transition-all"
                    />
                  </div>
                  <div className="relative">
                    <Lock className="absolute left-4 top-1/2 -translate-y-1/2 h-4.5 w-4.5 text-[#8B95A5]" />
                    <Input
                      data-testid="welcome-password-input"
                      type="password"
                      placeholder="Choose a password (min 8 chars)"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      className="h-12 pl-12 rounded-sm bg-[#0B131F] border-white/20 text-white placeholder-[#8B95A5]/70 focus:border-[#F9A01B] focus-visible:ring-[#F9A01B] transition-all"
                    />
                  </div>
                  <div className="relative">
                    <GraduationCap className="absolute left-4 top-1/2 -translate-y-1/2 h-4.5 w-4.5 text-[#8B95A5]" />
                    <Input
                      data-testid="welcome-age-input"
                      type="number"
                      placeholder="Your age (e.g. 18)"
                      value={age}
                      onChange={(e) => setAge(e.target.value)}
                      className="h-12 pl-12 rounded-sm bg-[#0B131F] border-white/20 text-white placeholder-[#8B95A5]/70 focus:border-[#F9A01B] focus-visible:ring-[#F9A01B] transition-all"
                      min={5}
                      max={100}
                    />
                  </div>
                  <Button
                    data-testid="welcome-next-0"
                    onClick={() => {
                      if (!name.trim()) {
                        toast.error("Please enter your name.");
                        return;
                      }
                      if (!validateEmail(email)) {
                        toast.error("Please enter a valid email address.");
                        return;
                      }
                      if (password.length < 8) {
                        toast.error("Password must be at least 8 characters.");
                        return;
                      }
                      const parsedAge = parseInt(age);
                      if (isNaN(parsedAge) || parsedAge < 5 || parsedAge > 100) {
                        toast.error("Please enter a valid age between 5 and 100.");
                        return;
                      }
                      setStep(1);
                    }}
                    disabled={!name.trim() || !validateEmail(email) || password.length < 8 || !age.trim()}
                    className="w-full h-12 rounded-sm font-semibold bg-[#F9A01B] hover:bg-[#FFA51E] disabled:bg-[#1E293B] disabled:text-white/30 disabled:border disabled:border-white/10 text-white shadow-sm transition-all active:scale-[0.99] flex items-center justify-center gap-2"
                  >
                    Continue <ArrowRight className="h-4.5 w-4.5" />
                  </Button>
                </div>
              )}

              {/* Step 1: Grade & Pace */}
              {step === 1 && (
                <div className="space-y-4">
                  <div>
                    <label className="text-xs font-mono font-bold tracking-wider text-[#8B95A5] uppercase block mb-2">Class or Grade Level</label>
                    <div className="grid grid-cols-2 gap-2 max-h-[180px] overflow-y-auto scrollbar-thin pr-1">
                      {GRADE_LEVELS.map((g) => (
                        <button
                           key={g.id}
                           type="button"
                           data-testid={`welcome-grade-${g.id}`}
                           onClick={() => setGradeLevel(g.id)}
                           className={`text-left border rounded-sm p-3 transition-all duration-200 outline-none ${gradeLevel === g.id
                               ? "border-[#F9A01B] bg-[#F9A01B]/15 text-[#FFA01A]"
                               : "border-white/20 bg-[#0B131F] hover:bg-[#182638] hover:border-white/30 text-[#E2E8F0]"
                            }`}
                        >
                          <div className="font-semibold text-xs">{g.label}</div>
                          <div className="text-[10px] text-[#8B95A5] mt-0.5">{g.hint}</div>
                        </button>
                      ))}
                    </div>
                  </div>

                  <div>
                    <label className="text-xs font-mono font-bold tracking-wider text-[#8B95A5] uppercase block mb-2">Learning Pace</label>
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                      {PACES.map((p) => (
                        <button
                           key={p.id}
                           type="button"
                           data-testid={`welcome-pace-${p.id}`}
                           onClick={() => setPace(p.id)}
                           className={`text-left border rounded-sm p-3 transition-all duration-200 outline-none ${pace === p.id
                               ? "border-[#F9A01B] bg-[#F9A01B]/15 text-[#FFA01A]"
                               : "border-white/20 bg-[#0B131F] hover:bg-[#182638] hover:border-white/30 text-[#E2E8F0]"
                            }`}
                        >
                          <div className="font-semibold text-xs">{p.label}</div>
                          <div className="text-[10px] text-[#8B95A5] mt-0.5 truncate">{p.hint}</div>
                        </button>
                      ))}
                    </div>
                  </div>

                  <Button
                    data-testid="welcome-next-1"
                    onClick={() => {
                      if (!gradeLevel) {
                        toast.error("Please select your grade level.");
                        return;
                      }
                      setStep(2);
                    }}
                    disabled={!gradeLevel}
                    className="w-full h-12 rounded-sm font-semibold bg-[#F9A01B] hover:bg-[#FFA51E] disabled:bg-[#1E293B] disabled:text-white/30 disabled:border disabled:border-white/10 text-white shadow-sm transition-all active:scale-[0.99] mt-2"
                  >
                    Continue <ArrowRight className="h-4 w-4 ml-2" />
                  </Button>
                </div>
              )}

              {/* Step 2: Hobbies / Metaphors */}
              {step === 2 && (
                <div className="space-y-4">
                  <div>
                    <label className="text-xs font-mono font-bold tracking-wider text-[#8B95A5] uppercase block mb-2">Select a theme for custom analogies</label>
                    <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                      {["Minecraft", "Sports", "Music", "Cooking", "Space", "History"].map((h) => (
                        <button
                           key={h}
                           type="button"
                           data-testid={`welcome-hobby-${h.toLowerCase()}`}
                           onClick={() => setHobby(h)}
                           className={`text-left border rounded-sm p-3 transition-all duration-200 outline-none ${hobby === h
                               ? "border-[#F9A01B] bg-[#F9A01B]/15 text-[#FFA01A]"
                               : "border-white/20 bg-[#0B131F] hover:bg-[#182638] hover:border-white/30 text-[#E2E8F0]"
                            }`}
                        >
                          <div className="font-semibold text-xs">{h}</div>
                        </button>
                      ))}
                    </div>
                  </div>

                  <div className="relative">
                    <User className="absolute left-4 top-1/2 -translate-y-1/2 h-4.5 w-4.5 text-[#8B95A5]" />
                    <Input
                      placeholder="Or type another custom interest..."
                      value={hobby}
                      onChange={(e) => setHobby(e.target.value)}
                      className="h-12 pl-12 rounded-sm bg-[#0B131F] border-white/20 text-white placeholder-[#8B95A5]/70 focus:border-[#F9A01B] focus-visible:ring-[#F9A01B] transition-all"
                    />
                  </div>

                  <Button
                    data-testid="welcome-finish"
                    onClick={submitRegistration}
                    disabled={loading || !hobby.trim()}
                    className="w-full h-12 rounded-sm font-semibold bg-[#F9A01B] hover:bg-[#FFA51E] disabled:bg-[#1E293B] disabled:text-white/30 disabled:border disabled:border-white/10 text-white shadow-sm transition-all active:scale-[0.99] mt-2"
                  >
                    {loading ? "Creating profile..." : "Enter Sarasvi"} <ArrowRight className="h-4 w-4 ml-2" />
                  </Button>
                </div>
              )}

              {/* Bottom progress steps bar */}
              <div className="flex gap-2.5 mt-6">
                {Array.from({ length: totalSteps }).map((_, i) => (
                  <div key={i} className={`h-1 flex-1 rounded-full transition-all duration-300 ${i <= step ? "bg-[#F9A01B]" : "bg-white/10"}`} />
                ))}
              </div>
            </div>
          )}
        </motion.div>
      </div>
    </div>
  );
}
