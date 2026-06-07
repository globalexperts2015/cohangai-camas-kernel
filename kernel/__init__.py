"""CAMAS kernel package.

Exposes the BaseBC contract + 4 typed layers (LLM, Memory, Tool, Storage),
the Scheduler with auto_inject/auto_extract hooks, the Voice + Compliance
gate hooks, and the escalation helper (L1/L2/L3 to Telegram Breakout Ops).
"""
from kernel.base_agent import (
    AgentResult,
    AutonomyLevel,
    BaseBC,
    EscalationTarget,
    ExecutionContext,
)
from kernel.compliance_gate import ComplianceGate, ComplianceVerdict
from kernel.escalation import EscalationService
from kernel.llm_layer import LLMLayer
from kernel.memory_layer import MemoryLayer, MemoryRecord, VoyageEmbedder
from kernel.scheduler import Scheduler
from kernel.tool_layer import ToolLayer, ToolSpec
from kernel.voice_gate import VoiceGate, VoiceVerdict

__all__ = [
    "AgentResult",
    "AutonomyLevel",
    "BaseBC",
    "ComplianceGate",
    "ComplianceVerdict",
    "EscalationService",
    "EscalationTarget",
    "ExecutionContext",
    "LLMLayer",
    "MemoryLayer",
    "MemoryRecord",
    "Scheduler",
    "VoyageEmbedder",
    "ToolLayer",
    "ToolSpec",
    "VoiceGate",
    "VoiceVerdict",
]
