import os
import uuid
import json
import shutil
import aio_pika
from fastapi import APIRouter, UploadFile, File, HTTPException
from dotenv import load_dotenv

# Carrega as variáveis de ambiente (para achar a URL do RabbitMQ)
load_dotenv()

router = APIRouter()
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost/")

# Cria a pasta temporária para o Worker poder pegar o arquivo depois
UPLOAD_DIR = os.path.abspath("temp_uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

async def send_to_rabbitmq(task_id: str, file_path: str, file_type: str):
    """Função auxiliar para conectar e enviar a mensagem para a fila"""
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    async with connection:
        channel = await connection.channel()
        # Garante que a fila existe
        await channel.declare_queue("invoice_import_queue", durable=True)
        
        # Monta o "bilhete" que o Worker vai ler
        mensagem = {
            "task_id": task_id,
            "file_path": file_path,
            "file_type": file_type
        }
        
        # Publica na fila
        await channel.default_exchange.publish(
            aio_pika.Message(body=json.dumps(mensagem).encode()),
            routing_key="invoice_import_queue",
        )

@router.post("/upload/xml")
async def upload_xml(file: UploadFile = File(...)):
    if not file.filename.endswith('.xml'):
        raise HTTPException(status_code=400, detail="Arquivo inválido. Envie um XML.")
    
    task_id = str(uuid.uuid4())
    file_path = os.path.join(UPLOAD_DIR, f"{task_id}_{file.filename}")
    
    # Salva o arquivo fisicamente no disco
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    # Envia para a fila em vez de processar na hora
    await send_to_rabbitmq(task_id, file_path, "XML")
    
    return {"message": "XML adicionado à fila de processamento!", "task_id": task_id}


@router.post("/upload/pdf")
async def upload_pdf(file: UploadFile = File(...)):
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Arquivo inválido. Envie um PDF.")
    
    task_id = str(uuid.uuid4())
    file_path = os.path.join(UPLOAD_DIR, f"{task_id}_{file.filename}")
    
    # Salva o arquivo fisicamente no disco
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    # Envia para a fila em vez de processar na hora
    await send_to_rabbitmq(task_id, file_path, "PDF")
    
    return {"message": "PDF adicionado à fila de processamento!", "task_id": task_id}