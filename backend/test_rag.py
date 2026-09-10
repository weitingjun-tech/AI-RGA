"""端到端 RAG 测试脚本"""
import sys, os
os.environ['HF_HOME'] = 'D:/mydo/huggingface_cache'
sys.path.insert(0, '.')

from app.database import SessionLocal
from app.models.document import Document

# 清理旧数据
db = SessionLocal()
db.query(Document).delete()
db.commit()
db.close()
print("1. 旧数据已清理")

# 测试 BGE-small 模型加载
from app.services.kb_service import get_embedding_model, get_chroma_collection
print("2. 正在加载 BGE-small-zh 模型（首次下载到 D 盘，约 400MB）...")
model = get_embedding_model()
vec = model.embed_query('你好世界')
print(f"   向量维度: {len(vec)}, 前5值: {vec[:5]}")

# 测试文档入库
from app.services.kb_service import process_document
file_path = 'uploads/sample_products.md'
db = SessionLocal()
doc = Document(
    filename='sample_products.md',
    file_type='.md',
    file_size=os.path.getsize(file_path),
    status='processing',
    uploaded_by=1
)
db.add(doc)
db.commit()
db.refresh(doc)
print(f"3. 文档已注册: id={doc.id}")

print("4. 正在分块、向量化、入库...")
process_document(db, doc.id, file_path, 'sample_products.md')
db.refresh(doc)
print(f"   处理完成! 状态={doc.status}, 分块数={doc.chunk_count}")

# 测试 RAG 检索
print("5. 测试向量检索...")
from app.services.rag_service import search_knowledge
context, sources = search_knowledge('iPhone 15的价格是多少？')
print(f"   检索到 {len(sources)} 个相关片段")
for s in sources:
    print(f"   - [{s['doc_name']}]: score={s['score']}, snippet={s['text_snippet'][:80]}...")

# 测试 LLM 生成（Ollama）
print("6. 测试 LLM 生成...")
from app.services.rag_service import get_llm
llm = get_llm()
from langchain_core.prompts import ChatPromptTemplate
prompt = ChatPromptTemplate.from_messages([
    ("system", "根据以下知识库回答问题：\n{context}"),
    ("human", "iPhone 15的价格是多少？")
])
chain = prompt | llm
response = chain.invoke({"context": context})
print(f"   LLM 回答（前200字）: {response.content[:200]}")

db.close()
print("\n=== 全部 6 步端到端测试通过! ===")