/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly KAKAO_JS_API_KEY?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
