import os
import uuid
import json
import shutil
import aio_pika
from fastapi import FastAPI, UploadFile, File, HTTPException
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Upload API - Publisher")
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost/")

# Cria a pasta temporária usando o caminho absoluto para o Windows salvar o arquivo
UPLOAD_DIR = os.path.abspath("temp_uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

async def send_to_rabbitmq(task_id: str, file_name: str):
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    async with connection:
        channel = await connection.channel()
        
        # AJUSTE 1: Declara a fila com as mesmas regras de DLQ do Worker
        await channel.declare_queue(
            "invoice_import_queue", 
            durable=True,
            arguments={
                "x-dead-letter-exchange": "dlx_invoice",
                "x-dead-letter-routing-key": "invoice_import_dlq"
            }
        )
        
        # AJUSTE 2: Monta o caminho relativo (com barra normal) para o Linux/Worker entender
        caminho_relativo = f"temp_uploads/{file_name}"
        
        mensagem = {
            "task_id": task_id,
            "file_path": caminho_relativo,
            "file_type": "PDF",
            "user_id": "api_local" # Para manter o rastreio de auditoria no banco
        }
        
        await channel.default_exchange.publish(
            aio_pika.Message(body=json.dumps(mensagem).encode()),
            routing_key="invoice_import_queue",
        )

@app.post("/upload/pdf")
async def upload_pdf(file: UploadFile = File(...)):
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Envie um arquivo PDF.")
    
    # 1. Gera um ID único para essa importação
    task_id = str(uuid.uuid4())
    file_name = f"{task_id}_{file.filename}"
    
    # 2. Salva o arquivo fisicamente na pasta temporária
    file_path = os.path.join(UPLOAD_DIR, file_name)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    # 3. Manda o aviso para o RabbitMQ (enviando apenas o nome do arquivo para a função montar a rota)
    await send_to_rabbitmq(task_id, file_name)
    
    # 4. Responde na mesma hora para o usuário, sem fazer ele esperar a IA!
    return {
        "message": "Arquivo recebido e enviado para processamento!",
        "task_id": task_id
    }