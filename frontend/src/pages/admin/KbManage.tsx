// RAG 知识库问答系统 - 知识库文档管理页面（仅 Admin）
import { useState, useEffect, useCallback } from 'react';
import {
  Table, Button, Upload, Space, Tag, Popconfirm, message,
  Card, Typography, Badge, Select, Modal, Input, Alert,
} from 'antd';
import {
  UploadOutlined, DeleteOutlined, ReloadOutlined,
  FilePdfOutlined, FileTextOutlined, FileExcelOutlined,
  FileMarkdownOutlined, CheckCircleOutlined, SyncOutlined,
  CloseCircleOutlined, PlusOutlined, DatabaseOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { knowledgeApi } from '../../services/api';
import type { Document, KnowledgeBase } from '../../types';

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

  // 多知识库
  const [bases, setBases] = useState<KnowledgeBase[]>([]);
  const [selectedKb, setSelectedKb] = useState<number | undefined>(undefined);
  const [kbModalOpen, setKbModalOpen] = useState(false);
  const [newKbName, setNewKbName] = useState('');
  const [newKbDesc, setNewKbDesc] = useState('');

  const fetchBases = useCallback(async () => {
    try {
      const res = await knowledgeApi.getBases();
      const list: KnowledgeBase[] = res.data.bases || [];
      setBases(list);
      // 默认选中第一个知识库
      if (list.length && selectedKb === undefined) {
        setSelectedKb(list[0].id);
      }
    } catch {
      message.error('获取知识库列表失败');
    }
  }, [selectedKb]);

  const fetchDocs = useCallback(async () => {
    setLoading(true);
    try {
      const res = await knowledgeApi.getDocuments(page, selectedKb);
      setDocs(res.data.documents || []);
      setTotal(res.data.total || 0);
    } catch {
      message.error('获取文档列表失败');
    }
    setLoading(false);
  }, [page, selectedKb]);

  useEffect(() => { fetchBases(); }, [fetchBases]);
  useEffect(() => {
    if (selectedKb !== undefined) fetchDocs();
  }, [fetchDocs, selectedKb]);

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
    if (selectedKb === undefined) {
      message.warning('请先选择要上传到的知识库');
      return;
    }
    setUploading(true);
    try {
      await knowledgeApi.uploadDocument(file, selectedKb);
      message.success(`${file.name} 上传成功，正在处理中...`);
      fetchDocs();
      fetchBases();
    } catch (e: any) {
      message.error(e.response?.data?.detail || '上传失败');
    }
    setUploading(false);
  };

  const handleCreateKb = async () => {
    const name = newKbName.trim();
    if (!name) {
      message.warning('请输入知识库名称');
      return;
    }
    try {
      const res = await knowledgeApi.createBase(name, newKbDesc.trim() || undefined);
      message.success(`知识库「${res.data.name}」已创建`);
      setKbModalOpen(false);
      setNewKbName('');
      setNewKbDesc('');
      await fetchBases();
      setSelectedKb(res.data.id);
    } catch (e: any) {
      message.error(e.response?.data?.detail || '创建失败');
    }
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

  const currentKb = bases.find((b) => b.id === selectedKb);

  return (
    <Card
      title={<Title level={4} style={{ margin: 0 }}>📁 知识库文档管理</Title>}
      extra={
        <Space>
          <Select
            style={{ width: 280 }}
            placeholder="选择知识库"
            value={selectedKb}
            onChange={(v) => { setSelectedKb(v); setPage(1); }}
            suffixIcon={<DatabaseOutlined />}
            options={bases.map((b) => ({
              value: b.id,
              label: `${b.name}（${b.doc_count} 文档 / ${b.chunk_count} 分块）`,
            }))}
          />
          <Button icon={<PlusOutlined />} onClick={() => setKbModalOpen(true)}>
            新建知识库
          </Button>
          <Upload
            accept=".pdf,.txt,.md,.csv,.docx,.epub,.mobi"
            showUploadList={false}
            beforeUpload={(file) => { handleUpload({ file }); return false; }}
          >
            <Button type="primary" icon={<UploadOutlined />} loading={uploading}>
              上传文档
            </Button>
          </Upload>
        </Space>
      }
    >
      {currentKb?.description && (
        <Alert
          style={{ marginBottom: 16 }}
          type="info"
          showIcon
          message={currentKb.description}
        />
      )}
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

      <Modal
        title="新建知识库"
        open={kbModalOpen}
        onOk={handleCreateKb}
        onCancel={() => setKbModalOpen(false)}
        okText="创建"
        cancelText="取消"
      >
        <Space direction="vertical" style={{ width: '100%' }} size="middle">
          <Input
            placeholder="知识库名称（必填，例如：产品技术支持知识库）"
            value={newKbName}
            onChange={(e) => setNewKbName(e.target.value)}
            maxLength={128}
          />
          <Input.TextArea
            placeholder="描述（选填）"
            value={newKbDesc}
            onChange={(e) => setNewKbDesc(e.target.value)}
            maxLength={512}
            rows={3}
          />
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            每个知识库对应一个独立的向量集合，检索时互不干扰。
          </Typography.Text>
        </Space>
      </Modal>
    </Card>
  );
}