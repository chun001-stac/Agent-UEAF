"""Workflow / multi-agent handoff orchestration (functional module 06).

A ``WorkflowCoordinator`` drives HandoffEnvelope exchanges through the core
HandoffPort; sub-goals are budget-sliced and ownership is explicit. It never
creates Run authority events itself (runs remain owned by RunCoordinator).
"""
