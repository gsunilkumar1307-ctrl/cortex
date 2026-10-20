export type RiskLevel = "low" | "medium" | "high" | "blocked";
export type TaskStatus =
  | "proposed"
  | "waiting_approval"
  | "running"
  | "completed"
  | "canceled"
  | "failed"
  | "blocked";

export type TaskCommand =
  | "open_app"
  | "close_app"
  | "focus_app"
  | "type_text"
  | "keystroke"
  | "menu_item"
  | "write_note"
  | "send_message"
  | "calculate"
  | "screenshot"
  | "clipboard_read"
  | "clipboard_write"
  | "notification"
  | "reminder"
  | "shutdown"
  | "restart"
  | "unknown";

export interface AuditEvent {
  type: string;
  message: string;
  createdAt: string;
  data: Record<string, unknown>;
}

export interface CortexTask {
  id: string;
  intent: string;
  command: TaskCommand;
  riskLevel: RiskLevel;
  requiresApproval: boolean;
  status: TaskStatus;
  steps: string[];
  result: string | null;
  error: string | null;
  auditTrail: AuditEvent[];
  params: Record<string, unknown>;
}

export interface ChatRequest {
  message: string;
  source?: "text" | "voice";
}

export interface ChatResponse {
  message: string;
  task?: CortexTask;
}
