"""
MÓDULO DEPRECADO:
O agendador ativo oficial do MiBandServer está localizado e mantido em:
app.core.scheduler (start_scheduler, reload_scheduler_jobs, execute_sync_workflow)

Este arquivo é mantido apenas como alias de compatibilidade retrógrada.
"""

from app.core.scheduler import scheduler, start_scheduler, run_scheduled_sync

__all__ = ["scheduler", "start_scheduler", "run_scheduled_sync"]
