export interface EmotionState {
  energy: number;
  urgency: number;
  calmness: number;
  confidence: number;
  enthusiasm: number;
}

export interface PhysicsModulators {
  springStiffnessMultiplier: number;
  springDampingMultiplier: number;
  springMassMultiplier: number;
  strokeDurationMultiplier: number;
  moveDurationMultiplier: number;
  hesitationDurationMultiplier: number;
  gestureAmplitudeMultiplier: number;
  wobbleIntensity: number;
}

class EmotionEngine {
  private state: EmotionState;

  constructor() {
    this.state = {
      energy: 0.5,
      urgency: 0.3,
      calmness: 0.6,
      confidence: 0.7,
      enthusiasm: 0.5,
    };
  }

  public setEmotion(profile: Partial<EmotionState>): void {
    this.state = {
      ...this.state,
      ...profile,
    };
  }

  public getModulators(): PhysicsModulators {
    return {
      springStiffnessMultiplier: 1.0,
      springDampingMultiplier: 1.0,
      springMassMultiplier: 1.0,
      strokeDurationMultiplier: 1.0,
      moveDurationMultiplier: 1.0,
      hesitationDurationMultiplier: 1.0,
      gestureAmplitudeMultiplier: 1.0,
      wobbleIntensity: 1.0,
    };
  }
}

export const emotionEngine = new EmotionEngine();

if (typeof window !== "undefined") {
  (window as any).__emotionEngine = emotionEngine;
}