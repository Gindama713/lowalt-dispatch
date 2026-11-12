/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_TIANDITU_TOKEN: string
  readonly VITE_CESIUM_ION_TOKEN: string
  readonly VITE_API_BASE: string
  readonly VITE_ANCHOR_LAT: string
  readonly VITE_ANCHOR_LON: string
  readonly VITE_ANCHOR_H: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
