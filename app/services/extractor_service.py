import os
import json
import xmltodict  # Necessário para ler XML sem usar IA (pip install xmltodict)
from google import genai
from google.genai import types
from dotenv import load_dotenv
from sqlalchemy.orm import Session
from tenacity import retry, stop_after_attempt, wait_exponential

# Nossos modelos externos
from app.models.document import Invoice, InvoiceItem
from app.schemas.invoice import InvoiceSchema 

load_dotenv()
client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# ========================================================
# 1. ROTEADOR HÍBRIDO (A Porta de Entrada)
# ========================================================
async def process_document(filename: str, content_bytes: bytes, db: Session, tenant_id: str) -> dict:
    """Decide se usa o parseador nativo (XML) ou Inteligência Artificial (PDF/Imagem)"""
    
    ext = filename.lower().split('.')[-1]
    
    if ext == 'xml':
        return await process_xml_native(content_bytes, db, tenant_id)
    elif ext in ['pdf', 'jpg', 'jpeg', 'png']:
        return await extract_and_save_pdf_with_ai(content_bytes, db, tenant_id)
    else:
        raise ValueError(f"Extensão .{ext} não suportada pelo OmniHub Extractor.")

# ========================================================
# 2. PARSER COM IA (Para PDFs)
# ========================================================
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10), reraise=True)
async def extract_and_save_pdf_with_ai(content_bytes: bytes, db: Session, tenant_id: str) -> dict:
    try:
        document_part = types.Part.from_bytes(
            data=content_bytes,
            mime_type='application/pdf'
        )

        prompt = "Analise esta nota fiscal de serviços em PDF e extraia os dados solicitados de acordo com o schema."
        
        response = client.models.generate_content(
            model='gemini-3.5-flash-lite',
            contents=[prompt, document_part],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=InvoiceSchema, # Usa o schema importado
                temperature=0.0 
            )
        )
        
        # O PULO DO GATO: O Pydantic valida a matemática e a tipagem AQUI
        dados_nf = InvoiceSchema.model_validate_json(response.text)
        
    except ValueError as ve:
        # Captura o erro matemático do Pydantic (Cross-check falhou)
        raise ValueError(f"Divergência matemática ou de formato identificada na NF: {str(ve)}")
    except Exception as e:
        raise ValueError(f"Falha ao ler o documento com IA: {str(e)}")

    # Chama a função de salvamento genérica
    return save_to_database(dados_nf, db, tenant_id, "PDF-AI")

# ========================================================
# 3. PARSER NATIVO (Para XML - Custo Zero)
# ========================================================
async def process_xml_native(content_bytes: bytes, db: Session, tenant_id: str) -> dict:
    try:
        xml_dict = xmltodict.parse(content_bytes)
        
        # Aqui você mapeia os campos do XML da prefeitura para o seu formato
        # Exemplo super simplificado:
        # dict_formatado = { "numero_nota": xml_dict['CompNfse']['Nfse']['InfNfse']['Numero'], ... }
        
        # Como é um mock para o exemplo, vamos assumir que extraiu:
        dict_formatado = {} # Implementar de acordo com o padrão ABRASF da prefeitura
        
        # Valida pelo Pydantic para garantir que o XML também segue a regra matemática
        dados_nf = InvoiceSchema.model_validate(dict_formatado)
        
        return save_to_database(dados_nf, db, tenant_id, "XML-NATIVO")
        
    except Exception as e:
        raise ValueError(f"Falha ao processar o arquivo XML: {str(e)}")

# ========================================================
# 4. FUNÇÃO DE SALVAMENTO NO BANCO
# ========================================================
def save_to_database(dados_nf: InvoiceSchema, db: Session, tenant_id: str, file_type: str) -> dict:
    # Acesso seguro usando a notação de objeto do Pydantic (dados_nf.atributo)
    
    if dados_nf.access_key:
        existing_invoice = db.query(Invoice).filter(
            Invoice.access_key == dados_nf.access_key,
            Invoice.tenant_id == tenant_id # Bloqueio de segurança Multi-tenant
        ).first()
        
        if existing_invoice:
            raise ValueError(f"A Nota Fiscal já foi importada para esta empresa (ID: {existing_invoice.id}).")

    try:
        new_invoice = Invoice(
            tenant_id=tenant_id, # Vínculo com a empresa (Campinas, Guarulhos, etc)
            file_type=file_type,
            access_key=dados_nf.access_key,
            number=dados_nf.numero_nota,
            issuer_cnpj=dados_nf.cnpj_emissor,
            issuer_name=dados_nf.razao_social_emissor,
            total_value=dados_nf.valor_bruto
        )

        # Se houver itens na nota (opcional para algumas NFS-e)
        if hasattr(dados_nf, 'items') and dados_nf.items:
            for item in dados_nf.items:
                new_item = InvoiceItem(
                    product_code=item.product_code,
                    description=item.description,
                    total_price=item.total_price
                )
                new_invoice.items.append(new_item)

        db.add(new_invoice)
        db.commit()
        db.refresh(new_invoice)
        
        return {"mensagem": f"Documento processado via {file_type} e salvo com sucesso!", "id": new_invoice.id}

    except Exception as e:
        db.rollback()
        raise ValueError(f"Erro ao salvar dados no banco: {str(e)}")