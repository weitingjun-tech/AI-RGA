"""分步测试 1: 文档入库 + 向量检索（不含 LLM）"""
import sys, os
os.environ['HF_HOME'] = 'D:/mydo/huggingface_cache'
sys.path.insert(0, '.')

from app.database import SessionLocal
from app.models.document import Document

# 清理旧数据
db = SessionLocal()
db.query(Document).delete()
db.commit()
print("[1/4] 旧数据已清理")

from app.services.kb_service import get_embedding_model, process_document
print("[2/4] 加载 BGE-small-zh 模型...")
model = get_embedding_model()
print(f"      OK, 向量维度: {len(model.embed_query('测试'))}")

file_path = 'uploads/sample_products.md'
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
print(f"[3/4] 文档入库处理中 (id={doc.id})...")
process_document(db, doc.id, file_path, 'sample_products.md')
db.refresh(doc)
print(f"      状态={doc.status}, 分块数={doc.chunk_count}")

print("[4/4] 向量检索测试...")
from app.services.rag_service import search_knowledge
context, sources = search_knowledge('iPhone 15 Pro Max的价格是多少？')
print(f"      检索到 {len(sources)} 个相关片段:")
for s in sources:
    print(f"      - [{s['doc_name']}] score={s['score']}: {s['text_snippet'][:60]}")
db.close()
print("=== 入库+检索测试通过 ===")