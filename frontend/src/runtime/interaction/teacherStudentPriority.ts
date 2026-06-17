/**
 * teacherStudentPriority.ts — Priority Conflict Resolution
 *
 * Defines and enforces the rules for resolving priority conflicts
 * between teacher motion and student interaction.
 *
 * Rules (in priority order):
 *   1. Critical narration (locked) — no interruption allowed
 *   2. Teacher drawing a node perimeter — wait for stroke end
 *   3. Teacher at emphasis/pause — student may queue
 *   4. Teacher idle between steps — student may interrupt immediately
 *   5. Practice mode — student has full priority
 */

import {
  interactionArbiter,
  OWNER,
  OWNERSHIP_PRIORITY,
  INTERACTION_MODE,
} from "./interactionArbiter";
import { CONSTRUCTION_PHASE } from "../motion/constructionRuntime";

export enum PRIORITY_RULE {
  LOCKED_NO_INTERRUPT = "locked_no_interrupt",
  WAIT_FOR_STROKE_END = "wait_for_stroke_end",
  QUEUE_FOR_PAUSE = "queue_for_pause",
  IMMEDIATE_INTERRUPT = "immediate_interrupt",
  STUDENT_FULL_CONTROL = "student_full_control",
}

export interface PriorityRuleChange {
  from: PRIORITY_RULE;
  to: PRIORITY_RULE;
  t: number;
}

export interface InterruptionAttemptResult {
  allowed: boolean;
  delay: number;
  reason: string;
}

type RuleCallback = (rule: PRIORITY_RULE) => void;

export class TeacherStudentPriority {
  private _teacherMotor: any;
  private _currentRule: PRIORITY_RULE;
  private _ruleHistory: PriorityRuleChange[];
  private _callbacks: RuleCallback[];

  constructor() {
    this._teacherMotor = null;
    this._currentRule = PRIORITY_RULE.IMMEDIATE_INTERRUPT;
    this._ruleHistory = [];
    this._callbacks = [];
  }

  /**
   * Connect to teacher motor.
   */
  public connect(teacherMotor: any): void {
    this._teacherMotor = teacherMotor;
  }

  /**
   * Evaluate the current priority rule based on teacher state.
   * Called every tick.
   *
   * @returns Current PRIORITY_RULE
   */
  public evaluate(): PRIORITY_RULE {
    const arbiterState = interactionArbiter.getState();

    // Practice mode — student always wins
    if (arbiterState.mode === INTERACTION_MODE.PRACTICE) {
      return this._setRule(PRIORITY_RULE.STUDENT_FULL_CONTROL);
    }

    // Hard locked (critical narration)
    if (arbiterState.isLocked) {
      return this._setRule(PRIORITY_RULE.LOCKED_NO_INTERRUPT);
    }

    // Get teacher construction phase
    const phase = this._teacherMotor?.getPhase?.() || CONSTRUCTION_PHASE.IDLE;

    switch (phase) {
      case CONSTRUCTION_PHASE.EXECUTING:
        // Check if a stroke is actively growing
        const hasStrokes = this._teacherMotor?.runtime?.strokeScheduler?.hasActiveStrokes?.() ?? false;
        if (hasStrokes) {
          return this._setRule(PRIORITY_RULE.WAIT_FOR_STROKE_END);
        }
        return this._setRule(PRIORITY_RULE.QUEUE_FOR_PAUSE);

      case CONSTRUCTION_PHASE.PAUSING:
        return this._setRule(PRIORITY_RULE.QUEUE_FOR_PAUSE);

      case CONSTRUCTION_PHASE.IDLE:
      case CONSTRUCTION_PHASE.COMPLETED:
        return this._setRule(PRIORITY_RULE.IMMEDIATE_INTERRUPT);

      default:
        return this._setRule(PRIORITY_RULE.QUEUE_FOR_PAUSE);
    }
  }

  /**
   * Attempt a student interruption under current rules.
   */
  public async attemptInterruption(context?: any): Promise<InterruptionAttemptResult> {
    const rule = this.evaluate();

    switch (rule) {
      case PRIORITY_RULE.LOCKED_NO_INTERRUPT:
        return { allowed: false, delay: 0, reason: "Canvas is locked during critical narration" };

      case PRIORITY_RULE.WAIT_FOR_STROKE_END:
        // Wait for current stroke to finish (max 500ms)
        await this._waitForStrokeEnd(500);
        return { allowed: true, delay: 0, reason: "Waited for stroke completion" };

      case PRIORITY_RULE.QUEUE_FOR_PAUSE:
        // Wait for teacher to reach a natural pause
        await this._waitForNaturalPause(2000);
        return { allowed: true, delay: 0, reason: "Queued for natural pause" };

      case PRIORITY_RULE.IMMEDIATE_INTERRUPT:
        return { allowed: true, delay: 0, reason: "Teacher idle — immediate" };

      case PRIORITY_RULE.STUDENT_FULL_CONTROL:
        return { allowed: true, delay: 0, reason: "Practice mode" };

      default:
        return { allowed: false, delay: 0, reason: "Unknown rule" };
    }
  }

  /**
   * Get explanation text for UI ("Teacher is drawing — please wait")
   */
  public getStatusText(): string {
    switch (this._currentRule) {
      case PRIORITY_RULE.LOCKED_NO_INTERRUPT:   return "Please wait — critical concept in progress";
      case PRIORITY_RULE.WAIT_FOR_STROKE_END:   return "Finishing this stroke — one moment…";
      case PRIORITY_RULE.QUEUE_FOR_PAUSE:       return "Queueing your question for the next pause…";
      case PRIORITY_RULE.IMMEDIATE_INTERRUPT:   return "Ready for your question";
      case PRIORITY_RULE.STUDENT_FULL_CONTROL:  return "Practice mode — canvas is yours";
      default: return "";
    }
  }

  /**
   * Check if student can draw right now.
   */
  public canStudentDrawNow(): boolean {
    const rule = this.evaluate();
    return rule === PRIORITY_RULE.IMMEDIATE_INTERRUPT || rule === PRIORITY_RULE.STUDENT_FULL_CONTROL;
  }

  public onRuleChange(cb: RuleCallback): void { 
    this._callbacks.push(cb); 
  }

  public reset(): void {
    this._currentRule = PRIORITY_RULE.IMMEDIATE_INTERRUPT;
    this._ruleHistory = [];
  }

  // ── Private Methods ────────────────────────────────────────────

  private _setRule(rule: PRIORITY_RULE): PRIORITY_RULE {
    if (rule !== this._currentRule) {
      this._ruleHistory.push({ from: this._currentRule, to: rule, t: Date.now() });
      if (this._ruleHistory.length > 20) this._ruleHistory.shift();
      this._currentRule = rule;
      this._callbacks.forEach(cb => cb(rule));
    }
    return rule;
  }

  private _waitForStrokeEnd(maxMs: number): Promise<void> {
    return new Promise(resolve => {
      const deadline = Date.now() + maxMs;
      const check = () => {
        const hasStrokes = this._teacherMotor?.runtime?.strokeScheduler?.hasActiveStrokes?.() ?? false;
        if (!hasStrokes || Date.now() >= deadline) resolve();
        else requestAnimationFrame(check);
      };
      requestAnimationFrame(check);
    });
  }

  private _waitForNaturalPause(maxMs: number): Promise<void> {
    return new Promise(resolve => {
      const deadline = Date.now() + maxMs;
      const check = () => {
        const phase = this._teacherMotor?.getPhase?.();
        const isNaturalPause = phase === CONSTRUCTION_PHASE.PAUSING || phase === CONSTRUCTION_PHASE.IDLE;
        if (isNaturalPause || Date.now() >= deadline) resolve();
        else requestAnimationFrame(check);
      };
      requestAnimationFrame(check);
    });
  }
}

// ── Singleton ──────────────────────────────────────────────────
export const teacherStudentPriority = new TeacherStudentPriority();
