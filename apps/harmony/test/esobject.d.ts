declare type ESObject = any;

declare module 'node:fs' {
  export function readFileSync(path: string, encoding: 'utf8'): string;
}

declare module 'node:path' {
  export function join(...parts: string[]): string;
  export function dirname(path: string): string;
}

declare module 'node:url' {
  export function fileURLToPath(url: string): string;
}

interface ImportMeta {
  url: string;
}

declare var console: {
  log(...args: unknown[]): void;
  error(...args: unknown[]): void;
};
