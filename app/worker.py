import asyncio
import json
import os
import shutil
import signal
import aio_pika
from dotenv import load_dotenv

# Importações da nossa nova camada de resiliência
from tenacity import AsyncRetrying, wait_exponential, stop_after_attempt

load_dotenv()

from app.database.config import SessionLocal
from app.services.extractor_service import extract_and_save_pdf_with_ai
from app.models.document import Invoice
from app.models.task import TaskProgress

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost/")
FINAL_STORAGE_DIR = os.path.abspath("storage_nfs")

# --- 4. GRACEFUL SHUTDOWN (Parte 1): Evento de controle ---
shutdown_event = asyncio.Event()

async def shutdown_gracefully(sig):
    """Função chamada quando o Docker manda o sistema desligar"""
    print(f"\n🛑 Recebido sinal de desligamento ({sig.name}). O Worker não vai pegar notas novas. Finalizando a atual e saindo em breve...")
    shutdown_event.set()

def setup_signal_handlers(loop):
    """Captura os sinais de interrupção (Ctrl+C ou Stop do Docker)"""
    try:
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(shutdown_gracefully(s)))
    except NotImplementedError:
        # Silencia o erro no Windows local, mas funciona perfeitamente no Docker (Linux)
        pass

def update_progress(db, task_id: str, status: str, progress: int, message: str):
    """Função para atualizar o banco de dados com a porcentagem atual"""
    try:
        task = db.query(TaskProgress).filter(TaskProgress.id == task_id).first()
        if not task:
            task = TaskProgress(id=task_id)
            db.add(task)
            
        task.status = status
        task.progress = progress
        task.message = message
        db.commit()
    except Exception as e:
        print(f"⚠️ Erro ao atualizar progresso: {e}")
        db.rollback()

async def process_message(message: aio_pika.IncomingMessage):
    body = json.loads(message.body)
    task_id = body.get("task_id")
    file_path = body.get("file_path")
    file_type = body.get("file_type")
    user_id = body.get("user_id", "sistema_automatico")
    
    db = SessionLocal()
    
    try:
        # --- 1. IDEMPOTÊNCIA: Bloqueio de duplicatas ---
        task_check = db.query(TaskProgress).filter(TaskProgress.id == task_id).first()
        if task_check and task_check.status == "COMPLETED":
            print(f"⏩ [Idempotência] Tarefa {task_id} já concluída anteriormente. Ignorando duplicata da rede.")
            await message.ack()
            return
        
        print(f"\n📥 [Nova Tarefa] {task_id} | Tipo: {file_type} | Usuário: {user_id}")
        update_progress(db, task_id, "PROCESSING", 10, "Lendo documento PDF...")
        
        with open(file_path, "rb") as f:
            content_bytes = f.read()
            
        update_progress(db, task_id, "PROCESSING", 20, "Preparando conexão com a IA...")
        update_progress(db, task_id, "PROCESSING", 30, "Extraindo dados (Pode demorar um pouco)...")
        
        resultado = None
        if file_type == "PDF":
            
            # --- 2. RETENTATIVAS INTELIGENTES (Exponential Backoff) ---
            # Tenta 3 vezes. Se falhar, espera 2s. Se falhar de novo, espera 4s.
            async for attempt in AsyncRetrying(
                wait=wait_exponential(multiplier=2, min=2, max=10),
                stop=stop_after_attempt(3),
                reraise=True
            ):
                with attempt:
                    # --- 3. TIMEOUTS: A guilhotina de tempo ---
                    # Se a IA travar e não responder em 60 segundos, corta a conexão e tenta de novo.
                    resultado = await asyncio.wait_for(
                        extract_and_save_pdf_with_ai(content_bytes, db, user_id),
                        timeout=60.0
                    )
            
        await asyncio.sleep(2) 

        update_progress(db, task_id, "PROCESSING", 70, "Dados extraídos com sucesso! Organizando arquivos...")

        if resultado:
            invoice = db.query(Invoice).filter(Invoice.id == resultado["id"]).first()

            if invoice and invoice.issuer_cnpj:
                update_progress(db, task_id, "PROCESSING", 90, "Salvando arquivo na pasta do emissor...")
                
                cnpj_folder = os.path.join(FINAL_STORAGE_DIR, invoice.issuer_cnpj)
                os.makedirs(cnpj_folder, exist_ok=True)
                
                safe_name = f"{invoice.access_key}.{file_type.lower()}" if invoice.access_key else f"{task_id}.{file_type.lower()}"
                final_path = os.path.join(cnpj_folder, safe_name)
                
                shutil.move(file_path, final_path)
            else:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    
        update_progress(db, task_id, "COMPLETED", 100, "Nota fiscal importada com sucesso!")
        print(f"✅ Tarefa {task_id} finalizada 100%!")
        
        await message.ack()

    except asyncio.TimeoutError:
        # Se esgotar as 3 tentativas e todas derem Timeout
        update_progress(db, task_id, "FAILED", 0, "Erro sistêmico: Timeout crítico com a IA.")
        print(f"❌ Erro na tarefa {task_id}: Tempo esgotado -> Enviando para DLQ.")
        await message.reject(requeue=False)

    except ValueError as e:
        # Erros de Negócio (ex: Documento já existe no banco)
        update_progress(db, task_id, "FAILED", 0, f"Aviso: {str(e)}")
        if os.path.exists(file_path):
            os.remove(file_path)
        await message.ack()
            
    except Exception as e:
        # Erros Sistêmicos (ex: Credencial inválida, arquivo corrompido)
        update_progress(db, task_id, "FAILED", 0, f"Erro sistêmico: {str(e)}")
        print(f"❌ Erro na tarefa {task_id}: {str(e)} -> Enviando para DLQ.")
        await message.reject(requeue=False)
            
    finally:
        db.close()

async def main():
    # Prepara o monitoramento de sinais (Graceful Shutdown)
    loop = asyncio.get_running_loop()
    setup_signal_handlers(loop)

    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    channel = await connection.channel()
    
    await channel.set_qos(prefetch_count=1)
    
    dlx_exchange = await channel.declare_exchange("dlx_invoice", aio_pika.ExchangeType.DIRECT)
    dlq = await channel.declare_queue("invoice_import_dlq", durable=True)
    await dlq.bind(dlx_exchange, routing_key="invoice_import_dlq")
    
    queue = await channel.declare_queue(
        "invoice_import_queue", 
        durable=True,
        arguments={
            "x-dead-letter-exchange": "dlx_invoice",
            "x-dead-letter-routing-key": "invoice_import_dlq"
        }
    )
    
    print("🚀 Worker BLINDADO iniciado! (Idempotência, Retries, Timeout e Shutdown Seguro ativados)")
    
    # Inicia o consumo das mensagens
    consumer_tag = await queue.consume(process_message)
    
    # --- 4. GRACEFUL SHUTDOWN (Parte 2): Esperando a ordem de parada ---
    # Em vez de travar o terminal para sempre, ele trava até a variável shutdown_event ser ativada
    await shutdown_event.wait()
    
    # O código abaixo só é executado quando apertamos Ctrl+C ou o Docker for parado
    print("🛑 Parando de aceitar novas notas na fila...")
    await queue.cancel(consumer_tag)
    
    print("🔌 Encerrando conexão com o RabbitMQ...")
    await channel.close()
    await connection.close()
    print("👋 Worker finalizado com segurança. Nenhuma nota foi partida ao meio!")

if __name__ == "__main__":
    asyncio.run(main())