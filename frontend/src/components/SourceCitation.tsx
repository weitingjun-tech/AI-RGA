// RAG 知识库问答系统 - 引用来源卡片（现代样式）
import { FileTextOutlined } from '@ant-design/icons';
import type { SourceCitation as SourceType } from '../types';

export function SourceCitation({ sources }: { sources: SourceType[] }) {
  if (!sources || sources.length === 0) return null;

  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ fontSize: 12.5, color: '#94a3b8', marginBottom: 8, fontWeight: 600, letterSpacing: 0.3 }}>
        📚 引用来源
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {sources.map((s, i) => (
          <div key={i} className="source-card" style={{ padding: '10px 14px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
                <FileTextOutlined style={{ color: '#6366f1', fontSize: 13 }} />
                <span style={{ fontWeight: 600, fontSize: 12.5, color: '#1e293b', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {s.doc_name}
                </span>
                <span style={{ fontSize: 11, color: '#94a3b8' }}>
                  #第 {parseInt(String(s.chunk_id), 10) + 1} 段
                </span>
              </div>
              <span className="score-chip" style={{ flexShrink: 0, marginLeft: 8 }}>
                相关度 {(s.score * 100).toFixed(0)}%
              </span>
            </div>
            <div style={{ fontSize: 12, color: '#64748b', lineHeight: 1.6 }}>
              {s.text_snippet}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}