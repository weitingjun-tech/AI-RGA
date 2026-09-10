// RAG 知识库问答系统 - 知识库文档管理页面（仅 Admin）
import { useState, useEffect, useCallback } from 'react';
import {
  Table, Button, Upload, Space, Tag, Popconfirm, message,
  Card, Typography, Badge,
} from 'antd';
import {
  UploadOutlined, DeleteOutlined, ReloadOutlined,
  FilePdfOutlined, FileTextOutlined, FileExcelOutlined,
  FileMarkdownOutlined, CheckCircleOutlined, SyncOutlined,
  CloseCircleOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { knowledgeApi } from '../../services/api';
import type { Document } from '../../types';

const { Title } = Typography;

const fileIcon = (type: string) => {
  const icons: Record<string, React.ReactNode> = {
    '.pdf': <FilePdfOutlined style={{ color: '#ff4d4f' }} />,
    '.txt': <FileTextOutlined style={{ color: '#1677ff' }} />,
    '.md': <FileMarkdownOutlined style={{ color: '#722ed1' }} />,
    '.csv': <FileExcelOutlined style={{ color: '#52c41a' }} />,
    '.docx': <FileTextOutlined style={{ color: '#1677ff' }} />,
    '.epub': <FileTextOutlined style={{ color: '#fa8c16' }} />,
    '.mobi': <FileTextOutlined style={{ color: '#fa8c16' }} />,
  };
  return icons[type] || <FileTextOutlined />;
};

export default function KbManage() {
  const [docs, setDocs] = useState<Document[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);

  const fetchDocs = useCallback(async () => {
    setLoading(true);
    try {
      const res = await knowledgeApi.getDocuments(page);
      setDocs(res.data.documents || []);
      setTotal(res.data.total || 0);
    } catch {
      message.error('获取文档列表失败');
    }
    setLoading(false);
  }, [page]);

  useEffect(() => { fetchDocs(); }, [fetchDocs]);

  // 自动轮询：存在"处理中"的文档时每 3 秒刷新一次状态
  useEffect(() => {
    const hasProcessing = docs.some((d) => d.status === 'processing');
    if (!hasProcessing) return;
    const timer = setInterval(fetchDocs, 3000);
    return () => clearInterval(timer);
  }, [docs, fetchDocs]);

  const handleUpload = async (info: any) => {
    const file = info.file;
    if (!file) return;
    setUploading(true);
    try {
      await knowledgeApi.uploadDocument(file);
      message.success(`${file.name} 上传成功，正在处理中...`);
      fetchDocs();
    } catch (e: any) {
      message.error(e.response?.data?.detail || '上传失败');
    }
    setUploading(false);
  };

  const handleDelete = async (id: number) => {
    try {
      await knowledgeApi.deleteDocument(id);
      message.success('文档已删除');
      fetchDocs();
    } catch {
      message.error('删除失败');
    }
  };

  const handleReindex = async (id: number) => {
    try {
      await knowledgeApi.reindexDocument(id);
      message.success('正在重新索引...');
      setTimeout(fetchDocs, 2000);
    } catch {
      message.error('重新索引失败');
    }
  };

  const columns: ColumnsType<Document> = [
    {
      title: '文件名',
      dataIndex: 'filename',
      key: 'filename',
      render: (name: string, record: Document) => (
        <Space>
          {fileIcon(record.file_type)}
          <span>{name.replace(/^[a-f0-9]+_/, '')}</span>
        </Space>
      ),
    },
    {
      title: '类型',
      dataIndex: 'file_type',
      key: 'file_type',
      width: 80,
      render: (t: string) => <Tag>{t.replace('.', '').toUpperCase()}</Tag>,
    },
    {
      title: '大小',
      dataIndex: 'file_size',
      key: 'file_size',
      width: 100,
      render: (s: number) => {
        if (!s) return '-';
        if (s > 1024 * 1024) return `${(s / (1024 * 1024)).toFixed(1)} MB`;
        return `${(s / 1024).toFixed(0)} KB`;
      },
    },
    {
      title: '分块数',
      dataIndex: 'chunk_count',
      key: 'chunk_count',
      width: 80,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: string) => {
        const config: Record<string, { color: string; icon: React.ReactNode; text: string }> = {
          ready: { color: 'success', icon: <CheckCircleOutlined />, text: '就绪' },
          processing: { color: 'processing', icon: <SyncOutlined spin />, text: '处理中' },
          error: { color: 'error', icon: <CloseCircleOutlined />, text: '失败' },
        };
        const c = config[status] || config.error;
        return <Badge status={c.color as any} text={c.text} />;
      },
    },
    {
      title: '上传时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 170,
      render: (t: string) => new Date(t).toLocaleString(),
    },
    {
      title: '操作',
      key: 'action',
      width: 160,
      render: (_: any, record: Document) => (
        <Space size={4}>
          <Button
            type="link"
            size="small"
            icon={<ReloadOutlined />}
            onClick={() => handleReindex(record.id)}
            disabled={record.status === 'processing'}
          >
            重新索引
          </Button>
          <Popconfirm
            title="确认删除此文档？所有关联的向量数据也将被删除。"
            onConfirm={() => handleDelete(record.id)}
            okText="确认删除"
            cancelText="取消"
          >
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <Card
      title={<Title level={4} style={{ margin: 0 }}>📁 知识库文档管理</Title>}
      extra={
        <Upload
          accept=".pdf,.txt,.md,.csv,.docx,.epub,.mobi"
          showUploadList={false}
          beforeUpload={(file) => { handleUpload({ file }); return false; }}
        >
          <Button type="primary" icon={<UploadOutlined />} loading={uploading}>
            上传文档
          </Button>
        </Upload>
      }
    >
      <Table
        columns={columns}
        dataSource={docs}
        rowKey="id"
        loading={loading}
        pagination={{
          current: page,
          total,
          pageSize: 20,
          onChange: (p) => setPage(p),
          showTotal: (t) => `共 ${t} 份文档`,
        }}
      />
    </Card>
  );
}