/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 后端 API 根地址，构建时注入；未设置时回退到 http://localhost:8000 */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
