import os
import sys
import time
import logging
from loguru import logger
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from app.core.config import settings

class InterceptHandler(logging.Handler):
    """
    Redireciona todas as mensagens do módulo logging padrão do Python
    (uvicorn, apscheduler, bleak, requests, etc.) para o Loguru.
    """
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )

def setup_logging():
    """
    Configura o sistema de logs centralizado:
    - Rotação diária à meia-noite (00:00).
    - Retenção configurável (30 ou 90 dias com exclusão automática de arquivos antigos).
    - Formato colunar em linha única para facilitar leitura e monitoramento.
    - Gravação assíncrona (enqueue=True) para evitar overhead de I/O em discos externos/SD Card.
    """
    # 1. Garantir existência do diretório de logs (seja local ou montado em HD externo)
    log_dir = os.path.abspath(settings.LOG_DIR)
    os.makedirs(log_dir, exist_ok=True)
    
    log_file_path = os.path.join(log_dir, settings.LOG_FILENAME)

    # 2. Remover handlers padrão do Loguru
    logger.remove()

    # 3. Formato visual em colunas (com cores para o Console / Terminal)
    console_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line:<4}</cyan> | "
        "<level>{message}</level>"
    )

    # 4. Formato de arquivo em colunas (limpo e legível, sem códigos ANSI)
    file_format = (
        "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
        "{level: <8} | "
        "{name}:{function}:{line:<4} | "
        "{message}"
    )

    # Adicionar saída do Console (Stdout)
    logger.add(
        sys.stdout,
        format=console_format,
        level="INFO",
        colorize=True,
        enqueue=True
    )

    # Adicionar saída em Arquivo com Rotação Diária e Retenção Automática
    logger.add(
        log_file_path,
        format=file_format,
        level="INFO",
        rotation="00:00",  # Rotação diária à meia-noite
        retention=f"{settings.LOG_RETENTION_DAYS} days",  # Retenção automática dos N dias configurados
        encoding="utf-8",
        enqueue=True,  # Gravação assíncrona em thread dedicada
        backtrace=True,
        diagnose=False
    )

    # 5. Interceptar logs do logging padrão do Python e Uvicorn
    logging.root.handlers = [InterceptHandler()]
    logging.root.setLevel(logging.INFO)

    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access", "apscheduler", "bleak"):
        mod_logger = logging.getLogger(logger_name)
        mod_logger.handlers = [InterceptHandler()]
        mod_logger.propagate = False

    logger.info(f"Sistema de Logs inicializado. Gravando em: {log_file_path} (Retenção: {settings.LOG_RETENTION_DAYS} dias)")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware que intercepta todas as requisições HTTP da API FastAPI
    e gera logs em linha única colunada estilo Swagger / Access Log.
    """
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        client_ip = request.client.host if request.client else "unknown"
        method = request.method
        url_path = request.url.path
        if request.url.query:
            url_path += f"?{request.url.query}"

        try:
            response: Response = await call_next(request)
            process_time = (time.time() - start_time) * 1000.0  # em ms
            status_code = response.status_code

            logger.info(
                f"HTTP {status_code} | {method:<6} | {url_path} | {process_time:.2f}ms | Client: {client_ip}"
            )
            return response
        except Exception as exc:
            process_time = (time.time() - start_time) * 1000.0
            logger.error(
                f"HTTP 500 | {method:<6} | {url_path} | {process_time:.2f}ms | Client: {client_ip} | Erro: {exc}"
            )
            raise exc

# Exporta a instância do logger do Loguru para uso em todo o projeto
__all__ = ["logger", "setup_logging", "RequestLoggingMiddleware"]
