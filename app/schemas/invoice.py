from pydantic import BaseModel, Field, field_validator
from typing import Optional
from decimal import Decimal

class RetencoesSchema(BaseModel):
    iss: Decimal = Field(default=0.0, description="Valor retido de ISS")
    irrf: Decimal = Field(default=0.0, description="Valor retido de Imposto de Renda")
    csll: Decimal = Field(default=0.0, description="Valor retido de CSLL")
    cofins: Decimal = Field(default=0.0, description="Valor retido de COFINS")
    pis: Decimal = Field(default=0.0, description="Valor retido de PIS")
    inss: Decimal = Field(default=0.0, description="Valor retido de INSS")

class InvoiceSchema(BaseModel):
    # Dados do Cabeçalho
    numero_nota: str = Field(..., description="Número oficial da nota fiscal")
    data_emissao: str = Field(..., description="Data de emissão da nota no formato YYYY-MM-DD")
    
    # Dados do Emissor (Fornecedor)
    cnpj_emissor: str = Field(..., description="CNPJ do emissor apenas com números")
    razao_social_emissor: str = Field(..., description="Razão social ou nome fantasia do fornecedor")
    
    # Dados do Tomador (Sua Empresa)
    cnpj_tomador: str = Field(..., description="CNPJ de quem recebeu a nota (Campinas, Guarulhos, etc) apenas com números")
    
    # Valores Financeiros
    valor_bruto: Decimal = Field(..., description="Valor total bruto dos serviços")
    retencoes: RetencoesSchema = Field(default_factory=RetencoesSchema, description="Lista de impostos retidos")
    valor_liquido: Decimal = Field(..., description="Valor líquido a ser pago ao fornecedor")

    # Validação Matemática de Segurança (O Cross-Check Automático)
    @field_validator('valor_liquido')
    @classmethod
    def validar_calculo_impostos(cls, v: Decimal, info) -> Decimal:
        if 'valor_bruto' in info.data and 'retencoes' in info.data:
            bruto = info.data['valor_bruto']
            retencoes = info.data['retencoes']
            
            soma_retencoes = (
                retencoes.iss + retencoes.irrf + retencoes.csll + 
                retencoes.cofins + retencoes.pis + retencoes.inss
            )
            
            liquido_calculado = bruto - soma_retencoes
            
            # Se a diferença for maior que 1 centavo, levanta erro!
            if abs(liquido_calculado - v) > Decimal("0.01"):
                raise ValueError(
                    f"Erro matemático na nota. Bruto ({bruto}) - Retenções ({soma_retencoes}) = {liquido_calculado}. "
                    f"Mas o valor líquido lido foi {v}."
                )
        return v