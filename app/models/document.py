from sqlalchemy import Column, Integer, String, Text, Numeric, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.database.config import Base

class Invoice(Base):
    __tablename__ = "invoices"
    
    # ==========================================
    # 1. IDENTIFICAÇÃO INTERNA E ARQUIVO
    # ==========================================
    id = Column(Integer, primary_key=True, index=True)
    
    # A NOVA COLUNA DE SEGURANÇA MULTI-TENANT
    tenant_id = Column(String(50), index=True, nullable=False) 
    
    file_type = Column(String(10)) 
    raw_content = Column(Text)
    
    # ==========================================
    # 2. IDENTIFICAÇÃO DA NOTA (NFS-e Nacional / Municipal)
    # ==========================================
    access_key = Column(String(50), unique=True, index=True, nullable=True) # 50 dígitos no Padrão Nacional
    number = Column(String(20), index=True, nullable=True)
    series = Column(String(10), nullable=True)
    issue_date = Column(DateTime, nullable=True)
    competence_date = Column(DateTime, nullable=True) # Mês/Ano real da prestação do serviço
    verification_code = Column(String(50), nullable=True) # Código alfanumérico legado
    
    # ==========================================
    # 3. ENVOLVIDOS
    # ==========================================
    issuer_cnpj = Column(String(14), index=True, nullable=True)
    issuer_name = Column(String(255), nullable=True)
    issuer_im = Column(String(50), nullable=True) # Inscrição Municipal
    service_municipality = Column(String(255), nullable=True) # Cidade onde o serviço ocorreu
    
    recipient_cnpj = Column(String(14), index=True, nullable=True)
    recipient_name = Column(String(255), nullable=True)
    
    # ==========================================
    # 4. TOTAIS FINANCEIROS E IMPOSTOS (NFS-e)
    # ==========================================
    gross_value = Column(Numeric(15, 2), nullable=True) # Valor Total dos Serviços
    net_value = Column(Numeric(15, 2), nullable=True) # Valor Líquido a Pagar
    calculation_base = Column(Numeric(15, 2), nullable=True) # Base de Cálculo do ISS
    
    # Retenções e ISS
    iss_value = Column(Numeric(15, 2), nullable=True)
    iss_retained = Column(Boolean, default=False) # Define quem paga a guia do ISS
    
    # Impostos Federais
    ir_value = Column(Numeric(15, 2), nullable=True)
    csll_value = Column(Numeric(15, 2), nullable=True)
    inss_value = Column(Numeric(15, 2), nullable=True)
    pis_value = Column(Numeric(15, 2), nullable=True)
    cofins_value = Column(Numeric(15, 2), nullable=True)

    # ==========================================
    # 5. DETALHAMENTO DOS SERVIÇOS
    # ==========================================
    national_tax_code = Column(String(50), nullable=True) # Código Padrão Nacional
    lc116_code = Column(String(20), nullable=True) # Código Lei Complementar (Ex: 14.02)
    service_description = Column(Text, nullable=True) # Texto corrido da nota

    # ==========================================
    # 6. AUDITORIA
    # ==========================================
    imported_by = Column(String(255), nullable=True, default="sistema_automatico")
    imported_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Mantemos os itens caso venham NFS-e com múltiplos serviços discriminados em tabela
    items = relationship("InvoiceItem", back_populates="invoice", cascade="all, delete-orphan")


class InvoiceItem(Base):
    __tablename__ = "invoice_items"
    
    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False)
    
    description = Column(String(500), nullable=True)
    cnae = Column(String(20), nullable=True)
    
    quantity = Column(Numeric(10, 4), nullable=True, default=1.0) 
    unit_price = Column(Numeric(15, 2), nullable=True)
    total_price = Column(Numeric(15, 2), nullable=True)

    invoice = relationship("Invoice", back_populates="items")
    