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
                    className="h-12 pl-12 rounded-sm bg-[#121C2A] border-white/10 text-white font-mono placeholder-[#8B95A5]/40 focus:border-[#F9A01B]/50 focus-visible:ring-[#F9A01B] transition-all"
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
                    className="h-12 pl-12 rounded-sm bg-[#121C2A] border-white/10 text-white placeholder-[#8B95A5]/40 focus:border-[#F9A01B]/50 focus-visible:ring-[#F9A01B] transition-all"
                    onKeyDown={(e) => {
                      if (e.key === "Enter") handleLogin();
                    }}
                  />
                </div>
                <Button
                  data-testid="login-submit"
                  onClick={handleLogin}
                  disabled={loading || !loginEmail.trim() || !loginPassword}
                  className="w-full h-12 rounded-sm font-semibold bg-[#F9A01B] hover:bg-[#FFA51E] disabled:opacity-50 text-white shadow-sm transition-all active:scale-[0.99]"
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
              </div>

              {/* Step 0: Account Info */}
              {step === 0 && (
                <div className="space-y-4">
                  <div className="relative">
                    <User className="absolute left-4 top-1/2 -translate-y-1/2 h-4.5 w-4.5 text-[#8B95A5]" />
                    <Input
                      data-testid="welcome-name-input"
                      placeholder="Your full name"
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      className="h-12 pl-12 rounded-sm bg-[#121C2A] border-white/10 text-white placeholder-[#8B95A5]/40 focus:border-[#F9A01B]/50 focus-visible:ring-[#F9A01B] transition-all"
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
                      className="h-12 pl-12 rounded-sm bg-[#121C2A] border-white/10 text-white font-mono placeholder-[#8B95A5]/40 focus:border-[#F9A01B]/50 focus-visible:ring-[#F9A01B] transition-all"
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
                      className="h-12 pl-12 rounded-sm bg-[#121C2A] border-white/10 text-white placeholder-[#8B95A5]/40 focus:border-[#F9A01B]/50 focus-visible:ring-[#F9A01B] transition-all"
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
                      className="h-12 pl-12 rounded-sm bg-[#121C2A] border-white/10 text-white placeholder-[#8B95A5]/40 focus:border-[#F9A01B]/50 focus-visible:ring-[#F9A01B] transition-all"
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
                    className="w-full h-12 rounded-sm font-semibold bg-[#F9A01B] hover:bg-[#FFA51E] disabled:opacity-50 text-white shadow-sm transition-all active:scale-[0.99] flex items-center justify-center gap-2"
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
                              : "border-white/10 bg-[#121C2A] hover:bg-[#182638] hover:border-white/20 text-[#E2E8F0]"
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
                              : "border-white/10 bg-[#121C2A] hover:bg-[#182638] hover:border-white/20 text-[#E2E8F0]"
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
                    className="w-full h-12 rounded-sm font-semibold bg-[#F9A01B] hover:bg-[#FFA51E] disabled:opacity-50 text-white shadow-sm transition-all active:scale-[0.99] mt-2"
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
                              : "border-white/10 bg-[#121C2A] hover:bg-[#182638] hover:border-white/20 text-[#E2E8F0]"
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
                      className="h-12 pl-12 rounded-sm bg-[#121C2A] border-white/10 text-white placeholder-[#8B95A5]/40 focus:border-[#F9A01B]/50 focus-visible:ring-[#F9A01B] transition-all"
                    />
                  </div>

                  <Button
                    data-testid="welcome-finish"
                    onClick={submitRegistration}
                    disabled={loading || !hobby.trim()}
                    className="w-full h-12 rounded-sm font-semibold bg-[#F9A01B] hover:bg-[#FFA51E] disabled:opacity-50 text-white shadow-sm transition-all active:scale-[0.99] mt-2"
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
