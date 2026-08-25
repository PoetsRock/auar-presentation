export interface Opening {
  x: number;
  w: number;
  h: number;
}

export type PanelType = 
  | "external_wall" 
  | "internal_wall" 
  | "floor_cassette" 
  | "roof_panel";

export type Zone = 
  | "north" 
  | "east" 
  | "south" 
  | "west" 
  | "internal" 
  | "floor" 
  | "roof";

export type PanelStatus = 
  | "installed" 
  | "planned" 
  | "manufactured" 
  | "in_transit";

export interface Panel {
  panelId: string;
  type: PanelType;
  level: number;
  zone: Zone;
  width: number;
  height: number;
  openings: Opening[];
  span: number | null;
  loadBearing: boolean;
  weightKg: number;
  status: PanelStatus;
}

export interface BuildModel {
  buildId: string;
  projectName: string;
  revision: number;
  supersedes: number | null;
  panels: Panel[];
}

// base properties
type BaseEvent = {
  ts: string;
  cellId: string;
  runId: string;
};

// specific event types
type RunStartedEvent = BaseEvent & {
  event: "run.started";
  buildId: string;
  panelCount: number;
  operator: string;
};

type PanelStartedEvent = BaseEvent & {
  event: "panel.started";
  panelId: string;
  sequence: number;
};

type SawCutCompletedEvent = BaseEvent & {
  event: "saw.cut.completed";
  panelId: string;
  cuts: number;
};

type FrameAssembledEvent = BaseEvent & {
  event: "frame.assembled";
  panelId: string;
};

type NailingStartedEvent = BaseEvent & {
  event: "nailing.started";
  panelId: string;
  pattern: string;
};

type NailingProgressEvent = BaseEvent & {
  event: "nailing.progress";
  panelId: string;
  nailsPlaced: number;
  nailsTotal: number;
};

type NailingCompletedEvent = BaseEvent & {
  event: "nailing.completed";
  panelId: string;
  nailsPlaced: number;
  misfires: number;
};

type PanelCompletedEvent = BaseEvent & {
  event: "panel.completed";
  panelId: string;
  cycleSeconds: number;
};

type StopRequestedEvent = BaseEvent & {
  event: "stop.requested";
  source: string;
  panelId?: string; 
  axisInMotion: boolean;
};

type MotionHaltedEvent = BaseEvent & {
  event: "motion.halted";
  panelId?: string;
  axesStopped: string[];
};

type InterlockEngagedEvent = BaseEvent & {
  event: "interlock.engaged";
  zone: string;
};

type RunPausedEvent = BaseEvent & {
  event: "run.paused";
  reason: string;
};

type InterlockReleasedEvent = BaseEvent & {
  event: "interlock.released";
  zone: string;
  operator: string;
};

type RunResumedEvent = BaseEvent & {
  event: "run.resumed";
  resumeMode?: string; // Optional because the final event in the file omits this
  panelId?: string;    // Optional because the final event in the file omits this
};

export type CellEvent = 
  | RunStartedEvent
  | PanelStartedEvent
  | SawCutCompletedEvent
  | FrameAssembledEvent
  | NailingStartedEvent
  | NailingProgressEvent
  | NailingCompletedEvent
  | PanelCompletedEvent
  | StopRequestedEvent
  | MotionHaltedEvent
  | InterlockEngagedEvent
  | RunPausedEvent
  | InterlockReleasedEvent
  | RunResumedEvent;
