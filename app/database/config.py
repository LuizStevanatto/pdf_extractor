import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Configuração da URL do banco de dados
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://admin:admin123@db:5432/notas_fiscais")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Esta é a função que o rotas.py está tentando importar e não está achando!
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()