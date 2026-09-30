from sqlalchemy import Column, String, Integer
from app.database.config import Base

class TaskProgress(Base):
    __tablename__ = "task_progress"
    
    id = Column(String, primary_key=True, index=True) # UUID da tarefa
    status = Column(String, default="PENDING") # PENDING, PROCESSING, COMPLETED, FAILED
    progress = Column(Integer, default=0) # 0 a 100
    message = Column(String, default="Aguardando na fila...")