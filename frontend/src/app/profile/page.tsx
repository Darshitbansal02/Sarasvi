"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { ArrowLeft, User as UserIcon, Mail, Calendar, GraduationCap, Clock, Brain, Flame, Sparkles, Award } from "lucide-react";
import { useSessionStore } from "@/store/sessionStore";
import { Button } from "@/components/ui/button";

export default function Profile() {
  const router = useRouter();
  const user = useSessionStore((s) => s.user);
  const hasHydrated = useSessionStore((s) => s.hasHydrated);

  useEffect(() => {
    if (hasHydrated && !user) router.push("/welcome");
  }, [user, hasHydrated, router]);

  if (!user) return null;

  const profile = user.learning_profile || {};
  const createdAt = user.created_at ? new Date(user.created_at).toLocaleDateString() : "recently";
  const hobbiesList = Array.isArray(profile.hobbies) ? profile.hobbies : profile.hobby ? [profile.hobby] : [];
  const mastery = user.mastery_scores || {};
  const hasMastery = Object.keys(mastery).length > 0;

  return (
    <div className="min-h-screen bg-[#FAF8F5] font-sans text-[#0B121F] pb-16">
      {/* Header bar */}
      <header className="sticky top-0 z-40 bg-white border-b border-[#E5DEC9] shadow-sm">
        <div className="max-w-[1000px] mx-auto px-6 h-14 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="h-11 w-11 relative overflow-hidden rounded-sm">
              <img src="/logo.png" alt="Sarasvi Logo" className="w-full h-full object-contain" />
            </div>
            <span className="font-display font-bold text-lg text-[#0B121F] tracking-tight">Sarasvi</span>
          </div>
          <div className="text-[11px] font-mono font-semibold text-[#5A6372] uppercase tracking-widest">
            Profile Space
          </div>
        </div>
      </header>

      <div className="max-w-[1000px] mx-auto px-6 pt-10">
        {/* Back Button */}
        <Button
          onClick={() => router.push("/dashboard")}
          variant="ghost"
          size="sm"
          className="h-8 px-3 rounded-sm border border-[#E5DEC9] bg-white text-[#5A6372] hover:text-[#0B121F] hover:bg-[#FAF8F5] hover:border-[#F9A01B]/40 flex items-center gap-1.5 text-xs font-mono mb-8 transition-all shadow-sm"
        >
          <ArrowLeft className="h-3.5 w-3.5" /> Back to Dashboard
        </Button>

        {/* User Hero Section */}
        <div className="flex flex-col md:flex-row items-center gap-6 p-8 border border-[#E5DEC9] rounded-sm bg-white shadow-sm mb-8 relative overflow-hidden">
          <div className="absolute top-0 right-0 h-32 w-32 bg-gradient-to-br from-[#F9A01B]/5 to-transparent rounded-full blur-2xl pointer-events-none" />
          
          <div className="h-20 w-20 rounded-full bg-[#FFF5E6] flex items-center justify-center border border-[#F9A01B]/20 shadow-sm shrink-0">
            <UserIcon className="h-10 w-10 text-[#F9A01B]" strokeWidth={1.5} />
          </div>
          <div className="text-center md:text-left min-w-0 flex-1">
            <h1 className="font-display text-3xl font-bold tracking-tight text-[#0B121F]">{user.name}</h1>
            <p className="text-sm text-[#5A6372] mt-1 flex items-center justify-center md:justify-start gap-2">
              <Mail className="h-3.5 w-3.5 text-[#8B95A5]" /> {user.email}
            </p>
          </div>
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-sm bg-[#FAF8F5] border border-[#E5DEC9] text-xs font-mono text-[#5A6372] shadow-inner shrink-0">
            <Calendar className="h-3.5 w-3.5 text-[#F9A01B]" />
            <span>Joined {createdAt}</span>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
          {/* Left Column: Personal info & Learning preference */}
          <div className="space-y-8">
            {/* Learning Pace Card */}
            <div className="border border-[#E5DEC9] p-6 rounded-sm bg-white shadow-sm">
              <div className="flex items-center gap-2 mb-6 pb-3 border-b border-[#E5DEC9]/60">
                <Clock className="h-4.5 w-4.5 text-[#F9A01B]" />
                <h3 className="font-display font-semibold text-base text-[#0B121F]">Learning Pace</h3>
              </div>
              <div className="space-y-4">
                <div className="flex justify-between items-center py-1.5">
                  <span className="text-sm text-[#5A6372] flex items-center gap-1.5"><Clock className="h-3.5 w-3.5" /> Pace</span>
                  <span className="text-sm font-semibold text-[#0B121F] capitalize">{profile.pace || "Normal"}</span>
                </div>
              </div>
            </div>

            {/* Academic & Interests Card */}
            <div className="border border-[#E5DEC9] p-6 rounded-sm bg-white shadow-sm">
              <div className="flex items-center gap-2 mb-6 pb-3 border-b border-[#E5DEC9]/60">
                <GraduationCap className="h-4.5 w-4.5 text-[#F9A01B]" />
                <h3 className="font-display font-semibold text-base text-[#0B121F]">Academic & Interests</h3>
              </div>
              <div className="space-y-4">
                <div className="flex justify-between items-center py-1.5 border-b border-[#E5DEC9]/40">
                  <span className="text-sm text-[#5A6372]">Age</span>
                  <span className="text-sm font-semibold text-[#0B121F]">{profile.age ? `${profile.age} years old` : "—"}</span>
                </div>
                <div className="flex justify-between items-center py-1.5 border-b border-[#E5DEC9]/40">
                  <span className="text-sm text-[#5A6372]">Grade Level</span>
                  <span className="text-sm font-semibold text-[#0B121F] capitalize">{(profile.grade_level || "college").replace("-", " ")}</span>
                </div>
                <div className="py-1.5">
                  <span className="text-sm text-[#5A6372] block mb-2">Hobbies & Analogy Customization Themes</span>
                  <div className="flex flex-wrap gap-1.5">
                    {hobbiesList.length > 0 ? (
                      hobbiesList.map((h, i) => (
                        <span key={i} className="px-2.5 py-1 text-xs font-medium bg-[#FFF5E6] border border-[#F9A01B]/20 text-[#FFA01A] rounded-full">
                          {h}
                        </span>
                      ))
                    ) : (
                      <span className="text-xs text-[#8B95A5] italic">No custom interests selected</span>
                    )}
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Right Column: Mastery Scores */}
          <div>
            <div className="border border-[#E5DEC9] p-6 rounded-sm bg-white shadow-sm h-full flex flex-col">
              <div className="flex items-center gap-2 mb-6 pb-3 border-b border-[#E5DEC9]/60">
                <Award className="h-4.5 w-4.5 text-[#F9A01B]" />
                <h3 className="font-display font-semibold text-base text-[#0B121F]">Topic Mastery</h3>
              </div>
              
              {hasMastery ? (
                <div className="space-y-5 flex-1">
                  {Object.entries(mastery).map(([topic, score]) => (
                    <div key={topic} className="space-y-1.5">
                      <div className="flex justify-between text-xs font-semibold">
                        <span className="capitalize text-[#0B121F]">{topic.replace("-", " ")}</span>
                        <span className="text-[#F9A01B]">{Math.round(score * 100)}% Mastery</span>
                      </div>
                      <div className="h-2 w-full bg-[#FAF8F5] border border-[#E5DEC9] rounded-full overflow-hidden">
                        <div 
                          className="h-full bg-gradient-to-r from-[#F9A01B] to-[#FFA51E] rounded-full transition-all duration-500" 
                          style={{ width: `${Math.round(score * 100)}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center text-center p-8 flex-1 bg-[#FAF8F5] border border-[#E5DEC9]/40 border-dashed rounded-sm">
                  <Flame className="h-10 w-10 text-[#8B95A5] mb-3 opacity-40 animate-pulse" />
                  <p className="text-xs font-medium text-[#5A6372] max-w-[280px]">
                    No topics mastered yet. Join sessions, ask questions, and test your knowledge to build your mastery profile!
                  </p>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex gap-4 mt-10">
          <Button
            variant="outline"
            className="flex-1 h-12 border-red-200 text-red-500 hover:bg-red-50 hover:border-red-300 rounded-sm font-semibold transition-all active:scale-[0.99]"
            onClick={() => {
              useSessionStore.getState().logout();
              router.push("/welcome");
            }}
          >
            Sign Out Account
          </Button>
        </div>
      </div>
    </div>
  );
}
