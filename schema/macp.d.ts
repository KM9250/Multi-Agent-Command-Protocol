export type Intent = "notify_user" | "handoff_agent" | "report_agent" | "log_only" | "need_review";
export type Status = "queued" | "running" | "done" | "failed" | "blocked" | "need_review";
export type Priority = "low" | "normal" | "high";
export type KnownMood = "good" | "caution" | "bad" | "blocked" | "unknown";
export type Mood = KnownMood | (string & {});
export type KnownTaskType = "portfolio" | "coding" | "avatar_3d" | "research" | "document" | "slides" | "agent_handoff" | "notification_test" | "maintenance";
export type TaskType = KnownTaskType | (string & {});
export type KnownActionType = "open_file" | "open_url" | "copy_prompt" | "retry" | "ack";
export type ActionType = KnownActionType | (string & {});

export interface AgentRef { agent_id: string; agent_role?: string; [key: string]: unknown; }
export interface Destination { type: "user" | "agent" | "broadcast"; target?: string; [key: string]: unknown; }
export interface ResultRef { format?: string; path?: string | null; url?: string | null; [key: string]: unknown; }
export interface Evaluation { confidence?: number; requirement_satisfaction?: number; mood?: Mood; requires_user_action?: boolean; [key: string]: unknown; }
export interface ActionItem { label: string; action_type: ActionType; target?: string; [key: string]: unknown; }
export interface Handoff {
  handoff_id: string; requested_command: string; reason: string; priority?: Priority;
  return_to?: string; return_intent?: string; return_format?: string; hop: number; max_hops: number;
  confidence_gate?: number; must_return_to?: boolean; [key: string]: unknown;
}
export interface MacpPacket {
  protocol: "macp"; version: string; task_id: string; task_type: TaskType; intent: Intent; from: AgentRef;
  to?: Destination; command?: string; command_alias?: string; status: Status; priority?: Priority;
  summary: string; requirement_summary?: string; agent_message?: string; detail?: string;
  result?: ResultRef; evaluation?: Evaluation; actions?: ActionItem[]; handoff?: Handoff; created_at: string;
  event_id?: number; received_at?: string; mood_computed?: KnownMood; [key: string]: unknown;
}
